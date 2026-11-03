"""General, pre-registered handling of provider HTTP 429 stops in Experiment C.

Governed by ``specs/journal-extension-sep14/experiment-c-provider-429-procedure-2026-09-25.md``.

A provider "heavy load" 429 is a ``call_failed`` event with ``RateLimitError``
and null cost/usage/completion. The frozen runner correctly stops on it because
its cost is unknown. This module provides, without changing any frozen module:

* ``PinnedFailure`` and ``check_pinned`` -- exact byte/identity checks for one
  such event at a fixed line of an immutable parent ledger;
* ``normalized`` -- an in-memory view in which only pinned events cost zero;
* ``settlement_proof`` -- the account-level proof that a pinned 429 was not
  charged: every signed-in monthly quota change from the reading before the
  failed run to at least 30 minutes after the failure is exactly explained by
  the audited raw costs of the serial runs in between;
* ``build_source`` -- the resume source: the frozen C builder's output with the
  same three anchors the Qwen s02/Gemini s06 repairs replaced, generalised to
  any pinned set;
* ``check_resumed_suffix`` -- replay rules for a resumed run whose novel suffix
  either completes or ends in one new, unsettled 429 (then the shard stays
  partial and the new event can only be settled by a later proof).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import build_experiment_c_cell_v1 as frozen
import build_experiment_c_gemini_s06_resume_v1 as anchors
import experiment_c_selection_v1 as selection_rules


ROOT = Path(__file__).resolve().parent.parent
QUOTA_ENDPOINT = "/api/i/models.ModelProxyService/GetModelProxyQuotas"
QUOTA_TRANSPORT = "signed-in Kaggle browser CDP Network.getResponseBody"
SETTLEMENT_MINUTES = 30
TRANSPORT_BUG = "ValueError('24-order decisions/vote inputs changed')"


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class PinnedFailure:
    line_index: int
    line_sha256: str
    job_id: str
    attempt: int
    step: int

    def as_dict(self) -> dict:
        return {"line_index": self.line_index, "line_sha256": self.line_sha256,
                "job_id": self.job_id, "attempt": self.attempt, "step": self.step}


def is_null_cost_429(event: dict) -> bool:
    return (event.get("event") == "call_failed"
            and event.get("error_type") == "RateLimitError"
            and event.get("cost_usd") is None
            and event.get("raw_completion") is None
            and isinstance(event.get("usage"), dict)
            and all(value is None for value in event["usage"].values()))


def check_pinned(lines: list[bytes], pin: PinnedFailure, model: str) -> dict:
    if len(lines) <= pin.line_index or sha256(lines[pin.line_index]) != pin.line_sha256:
        raise ValueError("pinned 429 line changed")
    event = json.loads(lines[pin.line_index])
    if (not is_null_cost_429(event) or event.get("model") != model
            or event.get("job_id") != pin.job_id or event.get("attempt") != pin.attempt
            or event.get("step") != pin.step):
        raise ValueError("pinned 429 identity changed")
    return event


def normalized(raw: bytes, parent: bytes, parent_sha256: str,
               pins: tuple[PinnedFailure, ...], model: str) -> list[dict]:
    """Events of ``raw`` with only the pinned parent 429s costed at zero, in memory."""
    if (sha256(parent) != parent_sha256 or not raw.startswith(parent)
            or not parent.endswith(b"\n") or not raw.endswith(b"\n")):
        raise ValueError("resume parent prefix or newline differs")
    lines = raw.splitlines(keepends=True)
    for pin in pins:
        check_pinned(lines, pin, model)
    events = [json.loads(line) for line in lines]
    pinned = {pin.line_index for pin in pins}
    if any(event.get("event") in ("call_complete", "call_failed") and event.get("cost_usd") is None
           for index, event in enumerate(events) if index not in pinned):
        raise ValueError("another unknown-cost call remains")
    result = copy.deepcopy(events)
    for index in pinned:
        result[index]["cost_usd"] = 0.0
        result[index]["usage"]["input_tokens_cost_nanodollars"] = 0
        result[index]["usage"]["output_tokens_cost_nanodollars"] = 0
    return result


# ---------------------------------------------------------------- settlement

def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp lacks timezone")
    return parsed


def read_observation(path: Path) -> dict:
    outer = json.loads(path.read_bytes())
    if (outer.get("schema") != "chronos.kaggle-browser-quota-observation.v1"
            or outer.get("endpoint") != QUOTA_ENDPOINT
            or outer.get("transport") != QUOTA_TRANSPORT):
        raise ValueError("quota observation provenance differs")
    rows = {row["refillPeriod"]: row for row in
            json.loads(outer["response_raw"], parse_float=Decimal)["quotaBalances"]}
    monthly = rows.get("MONTHLY") or {}
    if monthly.get("totalQuotaAllowed") != Decimal(100) or monthly.get("quotaUsed") is None:
        raise ValueError("quota observation lacks the monthly balance")
    return {"start": _time(outer["queried_at_start_utc"]), "end": _time(outer["queried_at_end_utc"]),
            "monthly": monthly["quotaUsed"], "monthly_reset": monthly["refillTime"][:16],
            "sha256": sha256(path.read_bytes()), "path": str(path.relative_to(ROOT))}


def raw_known_cost(raw: bytes) -> Decimal:
    return sum((Decimal(str(event["cost_usd"])) for event in map(json.loads, raw.splitlines())
                if event.get("event") in ("call_complete", "call_failed")
                and event.get("cost_usd") is not None), Decimal(0))


def _event_times(raw: bytes) -> tuple[datetime, datetime]:
    stamps = [_time(event["timestamp"]) for event in map(json.loads, raw.splitlines())
              if event.get("timestamp")]
    return min(stamps), max(stamps)


def settlement_proof(*, failure_raw: Path, failure_parent: Path | None, pin: PinnedFailure,
                     model: str, windows: list[dict]) -> dict:
    """Prove zero account charge for one pinned 429.

    ``windows`` are the consecutive serial runs starting with the one containing
    the failure: ``{"prebuild": obs, "after": obs, "raw": path, "parent": path|None}``.
    Each window's monthly delta must equal its novel raw known cost; consecutive
    windows must join without an unexplained monthly change; the last reading
    must be at least 30 minutes after the failure within one monthly window.
    """
    raw = failure_raw.read_bytes()
    failure = check_pinned(raw.splitlines(keepends=True), pin, model)
    failure_time = _time(failure["timestamp"])
    if not windows or windows[0]["raw"] != failure_raw:
        raise ValueError("settlement must start with the failed run")
    checked, previous_after, monthly_reset = [], None, None
    for window in windows:
        pre, post = read_observation(window["prebuild"]), read_observation(window["after"])
        run_raw = window["raw"].read_bytes()
        parent = window["parent"].read_bytes() if window["parent"] else b""
        if parent and not run_raw.startswith(parent):
            raise ValueError("settlement window parent is not a byte prefix")
        novel = run_raw[len(parent):]
        first, last = _event_times(novel)
        cost = raw_known_cost(novel)
        if not (pre["end"] < first and last < post["start"] and post["end"] - post["start"] < timedelta(seconds=10)):
            raise ValueError("settlement window readings do not bracket the run")
        if post["monthly"] - pre["monthly"] != cost:
            raise ValueError("settlement window monthly delta differs from raw cost")
        if previous_after is not None and (pre["monthly"] != previous_after["monthly"]
                                           or pre["start"] <= previous_after["end"]):
            raise ValueError("unexplained monthly change between serial runs")
        for reading in (pre, post):
            if monthly_reset is None:
                monthly_reset = reading["monthly_reset"]
            elif reading["monthly_reset"] != monthly_reset:
                raise ValueError("settlement crosses a monthly reset")
        checked.append({"raw_sha256": sha256(run_raw), "novel_known_cost_usd": str(cost),
                        "prebuild": pre["path"], "prebuild_sha256": pre["sha256"],
                        "after": post["path"], "after_sha256": post["sha256"],
                        "monthly_before": str(pre["monthly"]), "monthly_after": str(post["monthly"])})
        previous_after = post
    if previous_after["start"] - failure_time < timedelta(minutes=SETTLEMENT_MINUTES):
        raise ValueError("settlement readings end less than 30 minutes after the failure")
    return {
        "schema": "chronos.experiment-c-provider-429-settlement.v1",
        "finding": "account_level_zero_increment_for_pinned_429",
        "failed_raw_sha256": sha256(raw),
        "failed_parent_sha256": sha256(failure_parent.read_bytes()) if failure_parent else None,
        "pin": pin.as_dict(),
        "failure_timestamp_utc": failure["timestamp"],
        "last_reading_utc": previous_after["end"].isoformat(),
        "windows": checked,
    }


# ---------------------------------------------------------------- source

def _validation_source(pins: tuple[PinnedFailure, ...]) -> str:
    table = {pin.line_index: (pin.line_sha256, pin.attempt, pin.step, pin.job_id) for pin in pins}
    return f"""_PINNED_429 = {table!r}

def _reconciled_events(raw):
    if not raw.startswith(RESUME_SEED) or not raw.endswith(b'\\n'):
        raise ValueError('resume raw prefix changed')
    lines = raw.splitlines(keepends=True)
    rows = parse_jsonl_bytes(raw)
    for index, (line_sha, attempt, step, job_id) in _PINNED_429.items():
        if len(lines) <= index or hashlib.sha256(lines[index]).hexdigest() != line_sha:
            raise ValueError('pinned 429 line changed')
        failure = rows[index]
        if (failure.get('event') != 'call_failed' or failure.get('error_type') != 'RateLimitError'
                or failure.get('cost_usd') is not None or failure.get('raw_completion') is not None
                or failure.get('step') != step or failure.get('attempt') != attempt
                or failure.get('job_id') != job_id or failure.get('model') != MODEL
                or not isinstance(failure.get('usage'), dict)
                or any(value is not None for value in failure['usage'].values())):
            raise ValueError('pinned 429 identity changed')
    if any(row.get('event') in ('call_complete', 'call_failed') and row.get('cost_usd') is None
           for index, row in enumerate(rows) if index not in _PINNED_429):
        raise ValueError('another unknown-cost call remains')
    checked = copy.deepcopy(rows)
    for index in _PINNED_429:
        checked[index]['cost_usd'] = 0.0
        checked[index]['usage']['input_tokens_cost_nanodollars'] = 0
        checked[index]['usage']['output_tokens_cost_nanodollars'] = 0
    return checked

if (CONTRACT['cost_reconciliation']['raw_sha256'] != hashlib.sha256(RESUME_SEED).hexdigest()
        or CONTRACT['cost_reconciliation']['failed_event_line_sha256']
        != [hashlib.sha256(RESUME_SEED.splitlines(keepends=True)[i]).hexdigest() for i in sorted(_PINNED_429)]):
    raise ValueError('account reconciliation changed')

validate_resume_ledger(_reconciled_events(RESUME_SEED), model=MODEL, identity=IDENTITY,
    expected_jobs={{job['id']:job for job in JOBS}},
    structural_audit=lambda values: auditor.audit(values, MODEL, SELECTION, require_complete=False, expected_job_ids=set(CONTRACT['expected_job_ids'])))

_parent_failed_events = [parse_jsonl_bytes(RESUME_SEED)[i] for i in sorted(_PINNED_429)]
_original_accept = protocol.engine.Evidence._accept
def _reconciled_accept(self, event):
    if event in _parent_failed_events:
        adjusted = copy.deepcopy(event)
        adjusted['cost_usd'] = 0.0
        return _original_accept(self, adjusted)
    return _original_accept(self, event)
protocol.engine.Evidence._accept = _reconciled_accept"""


def reconciliation_record(parent: bytes, pins: tuple[PinnedFailure, ...], proofs: list[dict]) -> dict:
    if len(proofs) != len(pins) or not pins:
        raise ValueError("every pinned 429 needs exactly one settlement proof")
    return {
        "schema": "chronos.experiment-c-provider-429-reconciliation.v1",
        "raw_sha256": sha256(parent),
        "failed_event_line_sha256": [pin.line_sha256 for pin in sorted(pins, key=lambda p: p.line_index)],
        "raw_null_cost_calls": len(pins),
        "pins": [pin.as_dict() for pin in sorted(pins, key=lambda p: p.line_index)],
        "proofs": proofs,
    }


def augment_contract(contract: dict, record: dict, *, model: str, parent_sha256: str) -> dict:
    if (contract.get("model") != model or contract.get("parent_ledger_sha256") != parent_sha256
            or record.get("raw_sha256") != parent_sha256 or "cost_reconciliation" in contract):
        raise ValueError("contract is not the exact reconciled resume")
    body = copy.deepcopy({key: value for key, value in contract.items() if key != "contract_sha256"})
    body["cost_reconciliation"] = copy.deepcopy(record)
    return {**body, "contract_sha256": selection_rules.canonical_hash(body)}


TRANSPORT_POLICY = {
    "schema": "chronos.experiment-c-transport-wait.v1",
    "procedure": "specs/journal-extension-sep14/experiment-c-transport-wait-amendment-2026-09-25.md",
    "wait_on": ["RateLimitError"],
    "initial_delay_seconds": 20,
    "max_delay_seconds": 300,
    "max_wait_seconds_per_call": 1800,
    "sdk_max_retries": 0,
}

_CLIENT_ANCHOR = "    llm.client = llm.client.with_options(max_retries=0)\n"
_WAIT_WRAPPER = """    llm.client = llm.client.with_options(max_retries=0)
    _policy = CONTRACT['transport_policy']
    _waits = dict(schema=_policy['schema'], count=0, seconds=0)
    _waits_path = OUTPUT / 'transient_waits.json'
    _waits_path.write_text(json.dumps(_waits, sort_keys=True) + '\\n')
    _original_respond = llm.respond
    def _respond(**kwargs):
        waited, delay = 0, _policy['initial_delay_seconds']
        while True:
            try:
                return _original_respond(**kwargs)
            except Exception as error:
                if type(error).__name__ not in _policy['wait_on']:
                    raise
                remaining = _policy['max_wait_seconds_per_call'] - waited
                if remaining <= 0:
                    raise
                pause = min(delay, remaining)
                print('TRANSIENT', type(error).__name__, 'waiting', pause, 's', flush=True)
                time.sleep(pause)
                waited += pause
                _waits['count'] += 1
                _waits['seconds'] += pause
                _waits_path.write_text(json.dumps(_waits, sort_keys=True) + '\\n')
                delay = min(delay * 2, _policy['max_delay_seconds'])
    llm.respond = _respond
"""


def add_transport_policy(contract: dict) -> dict:
    if "transport_policy" in contract:
        raise ValueError("contract already carries a transport policy")
    body = copy.deepcopy({key: value for key, value in contract.items() if key != "contract_sha256"})
    body["transport_policy"] = copy.deepcopy(TRANSPORT_POLICY)
    return {**body, "contract_sha256": selection_rules.canonical_hash(body)}


def build_source(contract: dict, selection: dict, parent: bytes, pins: tuple[PinnedFailure, ...], *,
                 task_name: str, output_folder: str, standard_builder=None) -> str:
    """Frozen C builder output plus (a) reconciled-resume anchors when ``pins`` is
    non-empty and (b) the transport wait wrapper when the contract carries a policy."""
    record = contract.get("cost_reconciliation")
    if pins:
        if (record is None or record.get("raw_sha256") != sha256(parent)
                or record.get("failed_event_line_sha256")
                != [pin.line_sha256 for pin in sorted(pins, key=lambda p: p.line_index)]):
            raise ValueError("resume source lacks the exact parent and account proofs")
    elif parent or record is not None:
        raise ValueError("fresh source must have no parent and no reconciliation")
    policy = contract.get("transport_policy")
    if policy is not None and policy != TRANSPORT_POLICY:
        raise ValueError("transport policy differs from the amendment")
    if not pins and policy is None:
        raise ValueError("nothing distinguishes this source from the frozen builder")
    builder = standard_builder or frozen.build_source
    source = builder(contract=contract, selection=selection, task_name=task_name,
                     output_folder=output_folder, resume_seed=parent)
    if pins:
        source = anchors._replace_once(source, "import hashlib\n", "import hashlib\nimport copy\n")
        source = anchors._replace_once(source, anchors.VALIDATION, _validation_source(pins))
        source = anchors._replace_once(source, anchors.ORIGINAL_AUDIT, anchors.RECONCILED_AUDIT)
        source = anchors._replace_once(source, anchors.ORIGINAL_TERMINAL_END, anchors.RECONCILED_TERMINAL_END)
    if policy is not None:
        source = anchors._replace_once(source, "import sys\n", "import sys\nimport time\n")
        source = anchors._replace_once(source, _CLIENT_ANCHOR, _WAIT_WRAPPER)
    compile(source, "provider_429_source.py", "exec")
    return source


# ---------------------------------------------------------------- replay

def check_resumed_suffix(raw: bytes, parent: bytes, model: str) -> dict:
    """Classify the novel suffix: clean, or ending in exactly one new unsettled 429."""
    if not raw.startswith(parent):
        raise ValueError("resumed raw does not keep the parent prefix")
    suffix = [json.loads(line) for line in raw[len(parent):].splitlines()]
    unknown = [i for i, event in enumerate(suffix)
               if event.get("event") in ("call_complete", "call_failed") and event.get("cost_usd") is None]
    if not unknown:
        return {"new_429": None, "novel_events": len(suffix)}
    if (len(unknown) != 1 or len(suffix) < 2 or unknown[0] != len(suffix) - 2
            or not is_null_cost_429(suffix[-2]) or suffix[-2].get("model") != model
            or suffix[-1].get("event") != "job_error"
            or suffix[-1].get("error_type") != "RateLimitError"):
        raise ValueError("resumed suffix has an unknown cost other than one terminal 429")
    lines = raw.splitlines(keepends=True)
    index = len(parent.splitlines()) + unknown[0]
    event = suffix[-2]
    return {"new_429": PinnedFailure(index, sha256(lines[index]), event["job_id"],
                                     event["attempt"], event["step"]),
            "novel_events": len(suffix)}


# ---------------------------------------------------------------- registry

REGISTRY = ROOT / "kaggle/experiment_c_provider_429_settlements_v1.json"


def _proof(entry: dict, model: str) -> dict:
    pin = PinnedFailure(**entry["pin"])
    spec = entry["proof"]
    if spec["kind"] == "legacy":
        import importlib
        result = importlib.import_module(spec["module"]).verify()
        line_keys = [key for key in result if key.endswith("failed_event_line_sha256")]
        if (len(line_keys) != 1 or result[line_keys[0]] != pin.line_sha256
                or result.get("resume_authorized") is not False):
            raise ValueError("legacy settlement proof is not for this pinned 429")
        return {"kind": "legacy", "module": spec["module"],
                **{key: value for key, value in result.items() if key != "resume_authorized"}}
    if spec["kind"] == "continuity":
        windows = [{"prebuild": ROOT / w["prebuild"], "after": ROOT / w["after"], "raw": ROOT / w["raw"],
                    "parent": ROOT / w["parent"] if w.get("parent") else None} for w in spec["windows"]]
        return {"kind": "continuity", **settlement_proof(
            failure_raw=ROOT / entry["raw"], failure_parent=ROOT / entry["parent"] if entry.get("parent") else None,
            pin=pin, model=model, windows=windows)}
    raise ValueError("unknown settlement proof kind")


def settled_pins(parent: bytes, model: str) -> tuple[tuple[PinnedFailure, ...], list[dict]]:
    """Every null-cost 429 in ``parent`` must be a registered, provably settled pin."""
    registry = json.loads(REGISTRY.read_text())
    if registry.get("schema") != "chronos.experiment-c-provider-429-settlements.v1":
        raise ValueError("settlement registry schema differs")
    lines = parent.splitlines(keepends=True)
    unknown = [index for index, line in enumerate(lines)
               if (event := json.loads(line)).get("event") in ("call_complete", "call_failed")
               and event.get("cost_usd") is None]
    pins, proofs = [], []
    for index in unknown:
        matches = [entry for entry in registry["entries"]
                   if entry["pin"]["line_index"] == index and entry["pin"]["line_sha256"] == sha256(lines[index])
                   and parent.startswith((ROOT / entry["raw"]).read_bytes()[:len(b"".join(lines[:index + 1]))])]
        if len(matches) != 1:
            raise ValueError(f"null-cost call at line {index} has no unique settlement entry")
        pin = PinnedFailure(**matches[0]["pin"])
        check_pinned(lines, pin, model)
        pins.append(pin)
        proofs.append(_proof(matches[0], model))
    if not pins:
        raise ValueError("parent has no null-cost 429 to reconcile")
    return tuple(pins), proofs
