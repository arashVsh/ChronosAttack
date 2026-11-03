"""Build isolated, identity-aware round-two Kaggle task files.

Generation is offline and makes no model call. The generated task writes an
intended-manifest record before calling a provider, validates any resume seed
against the exact model/reasoning/study/subset identity, and exits gracefully so
paid evidence remains downloadable after a stop.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime
from pathlib import Path
import re

import audit_four_observation as study_audit
import audit_round2_defense as defense_audit
from capture_benchmark_quota_v1 import verify_attestation
import four_observation_defenses as defenses
import four_observation_protocol as protocol
import reasoning_preflight_v1 as preflight
from round2_hosted import (
    manifest_digest,
    parse_jsonl_bytes,
    raw_event_summary,
    select_shard,
    validate_resume_ledger,
)


HERE = Path(__file__).resolve().parent
SOURCE_FILES = (
    "completion_protocol.py",
    "four_observation_protocol.py",
    "four_observation_defenses.py",
    "audit_four_observation.py",
    "audit_round2_defense.py",
    "round2_hosted.py",
    "reasoning_preflight_v1.py",
    "round2_manifest_v1.json",
)
ROUND2_MANIFEST = json.loads((HERE / "round2_manifest_v1.json").read_text())
ALIGNMENT_MODELS = frozenset(ROUND2_MANIFEST["reasoning_alignment"]["models"])
RESOLUTION = {
    row["model"]: tuple(row["resolution"])
    for row in ROUND2_MANIFEST["primary_matrix"]
    if row["model"] in ALIGNMENT_MODELS
}
HISTORICAL_STUDY_IDS = {
    "chronos_independent_tree4_20260909_v1",
    "chronos_tree4_defenses_20260914",
}
STUDY_ID_PATTERN = re.compile(r"^chronos_round2_[a-z0-9_]+_v[0-9]+$")
TASK_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
FOLDER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{2,79}$")


def _validate_study_id(kind: str, study_id: str) -> None:
    if not STUDY_ID_PATTERN.fullmatch(study_id) or study_id in HISTORICAL_STUDY_IDS:
        raise ValueError("study_id must be a new versioned round-two identifier")
    if f"_{kind}_" not in study_id:
        raise ValueError(f"study_id must be kind-tagged with _{kind}_")


def _validate_parameters(
    *,
    kind: str,
    model: str,
    reasoning: str,
    study_id: str,
    ceiling_usd: float,
    task_name: str,
    output_folder: str,
    arm: str | None,
    shard_index: int,
    shard_count: int,
) -> None:
    if kind not in {"preflight", "study", "defense"}:
        raise ValueError("kind must be preflight, study, or defense")
    if model not in ALIGNMENT_MODELS:
        raise ValueError("model is outside the frozen reasoning-alignment roster")
    if reasoning not in {"minimal", "low"}:
        raise ValueError("round-two cells require an explicit non-off reasoning setting")
    _validate_study_id(kind, study_id)
    if not 0 < ceiling_usd <= 10:
        raise ValueError("cell ceiling must fit the authorized $10 daily limit")
    if not TASK_PATTERN.fullmatch(task_name):
        raise ValueError("invalid hosted task name")
    if not FOLDER_PATTERN.fullmatch(output_folder):
        raise ValueError("invalid explicit output folder")
    if arm is not None and (kind != "defense" or arm not in defenses.MODES):
        raise ValueError("arm shards are valid only for a named defense arm")
    if kind == "preflight" and (arm is not None or shard_index != 0 or shard_count != 1):
        raise ValueError("preflight is the exact unsharded ten-call path")
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("invalid deterministic shard")


def _events(seed: bytes) -> list[dict]:
    return parse_jsonl_bytes(seed, label="resume seed")


def _identity(engine, study_id: str, model: str, fixtures: dict) -> str:
    return engine.digest(
        json.dumps(
            {
                "study": study_id,
                "model": model,
                "fixtures": fixtures,
                "settings": engine.CALL_SETTINGS,
            },
            sort_keys=True,
        )
    )


def plan_cell(
    *,
    kind: str,
    model: str,
    reasoning: str,
    study_id: str,
    arm: str | None = None,
    shard_index: int = 0,
    shard_count: int = 1,
    resume_seed: bytes = b"",
) -> dict:
    """Resolve the intended manifest and validate a seed without making calls."""
    if kind not in {"preflight", "study", "defense"}:
        raise ValueError("kind must be preflight, study, or defense")
    if model not in ALIGNMENT_MODELS:
        raise ValueError("model is outside the frozen reasoning-alignment roster")
    if reasoning not in RESOLUTION[model]:
        raise ValueError("reasoning is outside the frozen compatibility sequence")
    _validate_study_id(kind, study_id)
    if resume_seed and not resume_seed.endswith(b"\n"):
        raise ValueError("resume ledger must end with a newline before append")
    if kind in {"preflight", "study"}:
        old_models = protocol.engine.MODELS
        old_study_id = protocol.engine.STUDY_ID
        old_settings = protocol.engine.CALL_SETTINGS
        try:
            protocol.engine.MODELS = tuple(dict.fromkeys((*old_models, model)))
            protocol.engine.STUDY_ID = study_id
            protocol.engine.CALL_SETTINGS = dict(old_settings, reasoning=reasoning)
            full_jobs = protocol.jobs_for(model, "study")
            jobs = preflight.jobs(full_jobs) if kind == "preflight" else select_shard(
                full_jobs, shard_index=shard_index, shard_count=shard_count
            )
            fixtures = protocol.fixtures()
            identity = _identity(protocol.engine, study_id, model, fixtures)
            seed_events = _events(resume_seed)
            seed_summary = validate_resume_ledger(
                seed_events,
                model=model,
                identity=identity,
                expected_jobs={job["id"]: job for job in jobs},
                structural_audit=lambda events: study_audit.audit(
                    events, model, "study", require_complete=False
                ),
            )
            if kind == "preflight" and seed_summary["incomplete_jobs"]:
                raise ValueError("a stopped preflight cannot be resumed")
            protocol_hash = fixtures["tree4"]["extension_sha256"]
        finally:
            protocol.engine.MODELS = old_models
            protocol.engine.STUDY_ID = old_study_id
            protocol.engine.CALL_SETTINGS = old_settings
    else:
        old_models = defenses.engine.MODELS
        old_study_id = defenses.STUDY_ID
        old_engine_study_id = defenses.engine.STUDY_ID
        old_settings = defenses.engine.CALL_SETTINGS
        try:
            defenses.engine.MODELS = tuple(dict.fromkeys((*old_models, model)))
            defenses.STUDY_ID = study_id
            defenses.engine.STUDY_ID = study_id
            defenses.engine.CALL_SETTINGS = dict(old_settings, reasoning=reasoning)
            full_jobs = defenses.jobs_for(model, "defense")
            if arm:
                full_jobs = [job for job in full_jobs if job["mode"] == arm]
            jobs = select_shard(
                full_jobs, shard_index=shard_index, shard_count=shard_count
            )
            fixtures = defenses.fixtures()
            identity = _identity(defenses.engine, study_id, model, fixtures)
            seed_events = _events(resume_seed)
            seed_summary = validate_resume_ledger(
                seed_events,
                model=model,
                identity=identity,
                expected_jobs={job["id"]: job for job in jobs},
                structural_audit=lambda events: defense_audit.audit(
                    events,
                    model,
                    expected_jobs=jobs,
                    require_complete=False,
                ),
            )
            protocol_hash = fixtures["tree4"]["extension_sha256"]
        finally:
            defenses.engine.MODELS = old_models
            defenses.STUDY_ID = old_study_id
            defenses.engine.STUDY_ID = old_engine_study_id
            defenses.engine.CALL_SETTINGS = old_settings

    return {
        "kind": kind,
        "study_id": study_id,
        "model": model,
        "reasoning": reasoning,
        "jobs": jobs,
        "job_count": len(jobs),
        "planned_calls": sum(job["calls"] for job in jobs),
        "manifest_sha256": manifest_digest(jobs),
        "identity": identity,
        "protocol_extension_sha256": protocol_hash,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "arm": arm,
        "resume_ledger": seed_summary,
    }


def _source_payload() -> tuple[dict[str, str], dict[str, str]]:
    sources = {name: (HERE / name).read_text() for name in SOURCE_FILES}
    hashes = {
        name: hashlib.sha256(content.encode("utf-8")).hexdigest()
        for name, content in sources.items()
    }
    for name, expected in ROUND2_MANIFEST["historical_source_sha256"].items():
        if hashes.get(name) != expected:
            raise ValueError(f"frozen historical source hash mismatch: {name}")
    return sources, hashes


def _strict_preflight_audit(
    events: list[dict], *, model: str, reasoning: str, study_id: str
) -> tuple[dict, dict]:
    contract = plan_cell(
        kind="preflight",
        model=model,
        reasoning=reasoning,
        study_id=study_id,
    )
    expected_ids = {job["id"] for job in contract["jobs"]}
    if any(
        (event.get("job_id") or event.get("job", {}).get("id")) not in expected_ids
        for event in events
    ):
        raise ValueError("preflight evidence contains an extra job")
    old_models = protocol.engine.MODELS
    old_study_id = protocol.engine.STUDY_ID
    old_settings = protocol.engine.CALL_SETTINGS
    try:
        protocol.engine.MODELS = tuple(dict.fromkeys((*old_models, model)))
        protocol.engine.STUDY_ID = study_id
        protocol.engine.CALL_SETTINGS = dict(old_settings, reasoning=reasoning)
        checked = study_audit.audit(events, model, "study", require_complete=False)
    finally:
        protocol.engine.MODELS = old_models
        protocol.engine.STUDY_ID = old_study_id
        protocol.engine.CALL_SETTINGS = old_settings
    return contract, checked


def _terminal_error_metadata(error) -> dict:
    response = getattr(error, "response", None)
    body = getattr(error, "body", None)
    if not isinstance(body, dict):
        body = {}
    return {
        "type": type(error).__name__,
        "status_code": getattr(error, "status_code", None)
        or getattr(response, "status_code", None),
        "code": getattr(error, "code", None) or body.get("code"),
        "param": getattr(error, "param", None) or body.get("param"),
        "message": str(error)[:2000],
    }


def _receipt_hash(body: dict) -> str:
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _provider_error_fields(error: dict) -> tuple[str, str]:
    """Recover provider parameter/code, including Kaggle's nested error body."""
    param = str(error.get("param") or "").lower()
    code = str(error.get("code") or "").lower()
    if param and code:
        return param, code
    message = str(error.get("message") or "")
    try:
        outer = ast.literal_eval(message.split(" - ", 1)[1])
        nested = json.loads(outer["message"])["error"]
    except (IndexError, KeyError, TypeError, ValueError, SyntaxError, json.JSONDecodeError):
        return param, code
    if not isinstance(nested, dict):
        return param, code
    return (
        param or str(nested.get("param") or "").lower(),
        code or str(nested.get("code") or "").lower(),
    )


def _zero_cost_resolution(
    *,
    call: dict,
    evidence: bytes,
    events: list[dict],
    terminal_raw: bytes | None,
    quota_attestation: dict | None,
) -> dict | None:
    usage = call.get("usage") if isinstance(call.get("usage"), dict) else {}
    token_counts_zero = (
        usage.get("input_tokens") in (0, None)
        and usage.get("output_tokens") in (0, None)
    )
    raw_cost_zero = (
        call.get("cost_usd") == 0
        and usage.get("input_tokens_cost_nanodollars") == 0
        and usage.get("output_tokens_cost_nanodollars") == 0
    )
    if token_counts_zero and raw_cost_zero:
        if quota_attestation is not None:
            raise ValueError("quota attestation is unnecessary for known raw zero cost")
        return {
            "source": "raw_call_telemetry",
            "raw_call_cost_usd": 0.0,
        }
    null_cost_telemetry = (
        call.get("cost_usd") is None
        and token_counts_zero
        and usage.get("input_tokens_cost_nanodollars") in (0, None)
        and usage.get("output_tokens_cost_nanodollars") in (0, None)
    )
    if not null_cost_telemetry or quota_attestation is None or terminal_raw is None:
        return None
    verify_attestation(quota_attestation, evidence, terminal_raw)
    response = quota_attestation["response"]
    if response["daily_quota_used_usd"] != 0.0:
        return None
    query_time = datetime.fromisoformat(quota_attestation["queried_at_start_utc"])
    last_event = max(datetime.fromisoformat(event["timestamp"]) for event in events)
    settlement_lag = (query_time - last_event).total_seconds()
    if settlement_lag < 300:
        raise ValueError("zero-quota attestation was captured before the settlement window")
    return {
        "source": "kaggle_daily_quota_attestation",
        "raw_call_cost_usd": None,
        "daily_quota_used_usd": 0.0,
        "total_daily_quota_allowed_usd": response[
            "total_daily_quota_allowed_usd"
        ],
        "queried_at_start_utc": quota_attestation["queried_at_start_utc"],
        "settlement_lag_seconds": settlement_lag,
        "attestation_sha256": quota_attestation["attestation_sha256"],
        "task": quota_attestation["run_context"]["task"],
        "run_id": quota_attestation["run_context"]["run_id"],
    }


def build_preflight_receipt(
    evidence: bytes,
    terminal: dict,
    quota_attestation: dict | None = None,
    terminal_raw: bytes | None = None,
) -> dict:
    """Revalidate raw preflight artifacts and return a self-hashed receipt."""
    if evidence and not evidence.endswith(b"\n"):
        raise ValueError("preflight evidence must be newline terminated")
    required_terminal = {
        "schema",
        "model",
        "reasoning",
        "study_id",
        "identity",
        "manifest_sha256",
        "protocol_extension_sha256",
        "call_settings",
        "source_sha256",
        "job_ids",
        "planned_calls",
        "evidence_sha256",
        "error",
        "transient_waits",
        "minimal_unsupported_receipt_sha256",
    }
    if set(terminal) != required_terminal or terminal["schema"] != "chronos.reasoning-terminal.v1":
        raise ValueError("invalid reasoning terminal artifact schema")
    model = terminal["model"]
    reasoning = terminal["reasoning"]
    study_id = terminal["study_id"]
    contract, strict = _strict_preflight_audit(
        parse_jsonl_bytes(evidence, label="preflight evidence"),
        model=model,
        reasoning=reasoning,
        study_id=study_id,
    )
    _, source_hashes = _source_payload()
    expected_settings = {
        "temperature": 1,
        "reasoning": reasoning,
        "max_completion_tokens": 256,
        "timeout": 30,
        "sdk_max_retries": 0,
    }
    expected_terminal = {
        **terminal,
        "identity": contract["identity"],
        "manifest_sha256": contract["manifest_sha256"],
        "protocol_extension_sha256": contract["protocol_extension_sha256"],
        "call_settings": expected_settings,
        "source_sha256": source_hashes,
        "job_ids": [job["id"] for job in contract["jobs"]],
        "planned_calls": 10,
        "evidence_sha256": hashlib.sha256(evidence).hexdigest(),
        "transient_waits": {"count": 0, "seconds": 0},
    }
    if terminal != expected_terminal:
        raise ValueError("reasoning terminal artifact differs from raw contract")
    events = parse_jsonl_bytes(evidence, label="preflight evidence")
    accounting = raw_event_summary(events)
    gate = preflight.pass_gate(events, contract["jobs"])
    error = terminal["error"]
    cost_resolution = None
    if gate["passed"]:
        if (
            error is not None
            or strict["completed_jobs"] != 2
            or quota_attestation is not None
        ):
            raise ValueError("passed preflight has terminal error or incomplete jobs")
        disposition = "passed"
    else:
        expected_kinds = ["job_started", "call_failed", "job_error"]
        call = events[1] if len(events) == 3 else {}
        if terminal_raw is not None:
            try:
                parsed_terminal = json.loads(terminal_raw)
            except json.JSONDecodeError as exc:
                raise ValueError("raw terminal artifact is not valid JSON") from exc
            if parsed_terminal != terminal:
                raise ValueError("raw terminal artifact differs from parsed terminal")
        cost_resolution = _zero_cost_resolution(
            call=call,
            evidence=evidence,
            events=events,
            terminal_raw=terminal_raw,
            quota_attestation=quota_attestation,
        )
        error_param, error_code = _provider_error_fields(error or {})
        if not (
            reasoning == "minimal"
            and [event.get("event") for event in events] == expected_kinds
            and all(event.get("attempt") == 1 for event in events)
            and call.get("step") == 1
            and call.get("raw_completion") is None
            and cost_resolution is not None
            and accounting["complete_calls"] == 0
            and accounting["failed_calls"] == 1
            and accounting["unknown_cost_calls"]
            == (1 if call.get("cost_usd") is None else 0)
            and strict["completed_jobs"] == 0
            and isinstance(error, dict)
            and error.get("type") == call.get("error_type")
            and events[2].get("error_type") == call.get("error_type")
            and error.get("status_code") in (400, 422)
            and error_param in {"reasoning", "reasoning_effort"}
            and error_code in {"unsupported_value", "unsupported_parameter", ""}
            and preflight.unsupported_reasoning(error.get("type"), error.get("message"))
        ):
            raise ValueError("failed preflight is not a verified minimal-setting rejection")
        disposition = "minimal_unsupported"
    body = {
        "schema": "chronos.reasoning-preflight-receipt.v1",
        "disposition": disposition,
        "model": model,
        "reasoning": reasoning,
        "study_id": study_id,
        "identity": contract["identity"],
        "manifest_sha256": contract["manifest_sha256"],
        "protocol_extension_sha256": contract["protocol_extension_sha256"],
        "call_settings": expected_settings,
        "source_sha256": source_hashes,
        "job_ids": [job["id"] for job in contract["jobs"]],
        "planned_calls": 10,
        "evidence": {
            "raw_sha256": hashlib.sha256(evidence).hexdigest(),
            **accounting,
        },
        "terminal_failure": error,
        "cost_resolution": cost_resolution,
        "minimal_unsupported_receipt_sha256": terminal[
            "minimal_unsupported_receipt_sha256"
        ],
    }
    return {**body, "receipt_sha256": _receipt_hash(body)}


def validate_preflight_receipt(
    receipt: dict,
    evidence: bytes,
    terminal: dict,
    *,
    model: str,
    reasoning: str,
    disposition: str,
    quota_attestation: dict | None = None,
    terminal_raw: bytes | None = None,
) -> dict:
    rebuilt = build_preflight_receipt(
        evidence,
        terminal,
        quota_attestation=quota_attestation,
        terminal_raw=terminal_raw,
    )
    if receipt != rebuilt:
        raise ValueError("preflight receipt does not match revalidated raw artifacts")
    if (
        rebuilt["model"] != model
        or rebuilt["reasoning"] != reasoning
        or rebuilt["disposition"] != disposition
    ):
        raise ValueError("preflight receipt does not authorize this cell")
    return rebuilt


def _load_json_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _load_receipt_bundle(
    *,
    receipt_path: Path | None,
    evidence_path: Path | None,
    terminal_path: Path | None,
    model: str,
    reasoning: str,
    disposition: str,
    label: str,
    quota_attestation_path: Path | None = None,
) -> dict:
    if not all((receipt_path, evidence_path, terminal_path)):
        raise ValueError(f"{label} receipt, evidence and terminal artifact are required")
    terminal_raw = terminal_path.read_bytes()
    return validate_preflight_receipt(
        _load_json_object(receipt_path, f"{label} receipt"),
        evidence_path.read_bytes(),
        json.loads(terminal_raw),
        model=model,
        reasoning=reasoning,
        disposition=disposition,
        quota_attestation=(
            _load_json_object(quota_attestation_path, f"{label} quota attestation")
            if quota_attestation_path
            else None
        ),
        terminal_raw=terminal_raw,
    )


def build_source(
    *,
    kind: str,
    model: str,
    reasoning: str,
    study_id: str,
    ceiling_usd: float,
    task_name: str,
    output_folder: str,
    arm: str | None = None,
    shard_index: int = 0,
    shard_count: int = 1,
    resume_from: Path | None = None,
    wait_budget: int | None = None,
    preflight_receipt: Path | None = None,
    preflight_evidence: Path | None = None,
    preflight_terminal: Path | None = None,
    minimal_unsupported_receipt: Path | None = None,
    minimal_unsupported_evidence: Path | None = None,
    minimal_unsupported_terminal: Path | None = None,
    minimal_unsupported_quota_attestation: Path | None = None,
) -> str:
    _validate_parameters(
        kind=kind,
        model=model,
        reasoning=reasoning,
        study_id=study_id,
        ceiling_usd=ceiling_usd,
        task_name=task_name,
        output_folder=output_folder,
        arm=arm,
        shard_index=shard_index,
        shard_count=shard_count,
    )
    wait_budget = (0 if kind == "preflight" else 7200) if wait_budget is None else wait_budget
    if wait_budget < 0:
        raise ValueError("wait budget cannot be negative")
    if kind == "preflight" and wait_budget != 0:
        raise ValueError("preflight wait budget must be zero")
    seed = Path(resume_from).read_bytes() if resume_from else b""
    if kind == "preflight" and resume_from is not None:
        raise ValueError("preflight cannot resume or replay a compatibility outcome")
    contract = plan_cell(
        kind=kind,
        model=model,
        reasoning=reasoning,
        study_id=study_id,
        arm=arm,
        shard_index=shard_index,
        shard_count=shard_count,
        resume_seed=seed,
    )
    passed_bundle_supplied = any(
        (preflight_receipt, preflight_evidence, preflight_terminal)
    )
    minimal_bundle_supplied = any(
        (
            minimal_unsupported_receipt,
            minimal_unsupported_evidence,
            minimal_unsupported_terminal,
            minimal_unsupported_quota_attestation,
        )
    )
    if kind == "preflight" and passed_bundle_supplied:
        raise ValueError("a preflight cannot consume a passed-preflight receipt")
    if reasoning == "minimal" and minimal_bundle_supplied:
        raise ValueError("minimal is the first compatibility setting and has no predecessor")
    minimal_receipt = None
    if reasoning == "low":
        minimal_receipt = _load_receipt_bundle(
            receipt_path=minimal_unsupported_receipt,
            evidence_path=minimal_unsupported_evidence,
            terminal_path=minimal_unsupported_terminal,
            model=model,
            reasoning="minimal",
            disposition="minimal_unsupported",
            label="minimal-unsupported",
            quota_attestation_path=minimal_unsupported_quota_attestation,
        )
    accepted_receipt = None
    if kind != "preflight":
        accepted_receipt = _load_receipt_bundle(
            receipt_path=preflight_receipt,
            evidence_path=preflight_evidence,
            terminal_path=preflight_terminal,
            model=model,
            reasoning=reasoning,
            disposition="passed",
            label="passed preflight",
        )
        predecessor = accepted_receipt["minimal_unsupported_receipt_sha256"]
        expected_predecessor = (
            minimal_receipt["receipt_sha256"] if minimal_receipt else None
        )
        if predecessor != expected_predecessor:
            raise ValueError("passed preflight does not carry the required compatibility chain")
    sources, source_hashes = _source_payload()
    public_contract = {key: value for key, value in contract.items() if key != "jobs"}
    public_contract["source_sha256"] = source_hashes
    public_contract["incremental_ceiling_usd"] = ceiling_usd
    public_contract["effective_ceiling_usd"] = (
        ceiling_usd + contract["resume_ledger"]["known_cost_usd"]
    )
    public_contract["parent_ledger_sha256"] = (
        hashlib.sha256(seed).hexdigest() if seed else None
    )
    public_contract["accepted_preflight_receipt_sha256"] = (
        accepted_receipt["receipt_sha256"] if accepted_receipt else None
    )
    public_contract["minimal_unsupported_receipt_sha256"] = (
        minimal_receipt["receipt_sha256"] if minimal_receipt else None
    )
    public_contract["call_settings"] = {
        "temperature": 1,
        "reasoning": reasoning,
        "max_completion_tokens": 256,
        "timeout": 30,
        "sdk_max_retries": 0,
    }
    return f'''# Generated offline by build_hosted_cell_v2.py; private synthetic research.
import hashlib
import json
import sys
import time
from pathlib import Path
import kaggle_benchmarks as kbench

SOURCES = {sources!r}
SOURCE_SHA256 = {source_hashes!r}
RESUME_LEDGER = {seed!r}
CONTRACT = {public_contract!r}
EXPECTED_JOBS = {contract["jobs"]!r}
MODEL = {model!r}
REASONING = {reasoning!r}
STUDY_ID = {study_id!r}
KIND = {kind!r}
OUTPUT_FOLDER = {output_folder!r}
INCREMENTAL_CEILING_USD = {ceiling_usd!r}
MAX_WAIT_SECONDS = {wait_budget!r}

source_root = Path('/kaggle/working') / (OUTPUT_FOLDER + '_source')
source_root.mkdir(parents=True, exist_ok=False)
for name, content in SOURCES.items():
    if hashlib.sha256(content.encode('utf-8')).hexdigest() != SOURCE_SHA256[name]:
        raise ValueError('Embedded source hash mismatch: ' + name)
    path = source_root / name
    path.write_text(content)
sys.path.insert(0, str(source_root))

round2_manifest = json.loads(SOURCES['round2_manifest_v1.json'])
if MODEL not in round2_manifest['reasoning_alignment']['models']:
    raise ValueError('Runtime model is outside the frozen alignment manifest')
for name, expected in round2_manifest['historical_source_sha256'].items():
    if SOURCE_SHA256.get(name) != expected:
        raise ValueError('Frozen historical source hash mismatch: ' + name)

import round2_hosted as hosted
import reasoning_preflight_v1 as reasoning_preflight

if KIND in ('preflight', 'study'):
    import four_observation_protocol as cell
    import audit_four_observation as cell_auditor
    cell.engine.MODELS = tuple(dict.fromkeys((*cell.engine.MODELS, MODEL)))
    cell.engine.STUDY_ID = STUDY_ID
    cell.engine.CALL_SETTINGS = dict(cell.engine.CALL_SETTINGS, reasoning=REASONING)
    full_jobs = cell.jobs_for(MODEL, 'study')
    jobs = reasoning_preflight.jobs(full_jobs) if KIND == 'preflight' else hosted.select_shard(
        full_jobs, shard_index=CONTRACT['shard_index'], shard_count=CONTRACT['shard_count'])
    fixtures = cell.fixtures()
    structural_audit = lambda events: cell_auditor.audit(
        events, MODEL, 'study', require_complete=False)
else:
    import four_observation_defenses as cell
    import audit_round2_defense as cell_auditor
    cell.engine.MODELS = tuple(dict.fromkeys((*cell.engine.MODELS, MODEL)))
    cell.STUDY_ID = STUDY_ID
    cell.engine.STUDY_ID = STUDY_ID
    cell.engine.CALL_SETTINGS = dict(cell.engine.CALL_SETTINGS, reasoning=REASONING)
    full_jobs = cell.jobs_for(MODEL, 'defense')
    if CONTRACT['arm']:
        full_jobs = [job for job in full_jobs if job['mode'] == CONTRACT['arm']]
    jobs = hosted.select_shard(
        full_jobs, shard_index=CONTRACT['shard_index'], shard_count=CONTRACT['shard_count'])
    fixtures = cell.fixtures()
    structural_audit = lambda events: cell_auditor.audit(
        events, MODEL, expected_jobs=jobs, require_complete=False)

expected_engine_settings = {{key: value for key, value in CONTRACT['call_settings'].items()
                            if key != 'sdk_max_retries'}}
if cell.engine.CALL_SETTINGS != expected_engine_settings:
    raise ValueError('Runtime call settings differ from the intended settings')
if jobs != EXPECTED_JOBS or hosted.manifest_digest(jobs) != CONTRACT['manifest_sha256']:
    raise ValueError('Runtime manifest differs from the pre-audited intended manifest')
identity = cell.engine.digest(json.dumps(dict(
    study=STUDY_ID, model=MODEL, fixtures=fixtures,
    settings=cell.engine.CALL_SETTINGS), sort_keys=True))
if identity != CONTRACT['identity']:
    raise ValueError('Runtime identity differs from the pre-audited identity')

if RESUME_LEDGER and not RESUME_LEDGER.endswith(b'\\n'):
    raise ValueError('Resume ledger is not append safe')
seed_events = hosted.parse_jsonl_bytes(RESUME_LEDGER, label='resume ledger')
seed_audit = hosted.validate_resume_ledger(
    seed_events, model=MODEL, identity=identity,
    expected_jobs={{job['id']: job for job in jobs}},
    structural_audit=structural_audit)
if KIND == 'preflight' and seed_events:
    raise ValueError('Preflight cannot resume or replay a compatibility outcome')
if CONTRACT['effective_ceiling_usd'] != INCREMENTAL_CEILING_USD + seed_audit['known_cost_usd']:
    raise ValueError('Effective ceiling does not include the exact prior spend')

output = Path('/kaggle/working') / OUTPUT_FOLDER
output.mkdir(parents=True, exist_ok=False)
manifest = dict(CONTRACT, jobs=jobs, seed_audit=seed_audit)
(output / 'intended_manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True))
evidence_path = output / (MODEL.replace('/', '_') + '.jsonl')
if RESUME_LEDGER:
    with evidence_path.open('xb') as stream:
        stream.write(RESUME_LEDGER)

TRANSIENT = ('RateLimitError', 'InternalServerError', 'APIConnectionError', 'APITimeoutError')
WAITS = dict(count=0, seconds=0)


@kbench.task(name={task_name!r})
def hosted_cell(llm):
    if llm.model != MODEL:
        raise ValueError('Unexpected selected model')
    llm.client = llm.client.with_options(max_retries=0)
    if KIND != 'preflight':
        original_respond = llm.respond

        def respond(**kwargs):
            waited, delay = 0, 20
            while True:
                try:
                    return original_respond(**kwargs)
                except Exception as error:
                    if type(error).__name__ not in TRANSIENT:
                        raise
                    remaining = MAX_WAIT_SECONDS - waited
                    if remaining <= 0:
                        raise
                    pause = min(delay, remaining)
                    print('TRANSIENT', type(error).__name__, 'waiting', pause,
                          's (total', waited, 's)', flush=True)
                    time.sleep(pause)
                    waited += pause
                    WAITS['count'] += 1
                    WAITS['seconds'] += pause
                    delay = min(delay * 2, 300)

        llm.respond = respond

    def error_metadata(error):
        response = getattr(error, 'response', None)
        body = getattr(error, 'body', None)
        if not isinstance(body, dict):
            body = {{}}
        return dict(
            type=type(error).__name__,
            status_code=getattr(error, 'status_code', None)
            or getattr(response, 'status_code', None),
            code=getattr(error, 'code', None) or body.get('code'),
            param=getattr(error, 'param', None) or body.get('param'),
            message=str(error)[:2000],
        )

    exhausted, stopped, terminal_error = False, None, None
    try:
        if KIND == 'preflight':
            reasoning_preflight.run_once(
                cell.engine, cell.execute_job, kbench, llm, fixtures, jobs,
                output, CONTRACT['effective_ceiling_usd'])
        else:
            cell.engine.run_jobs(
                kbench, llm, fixtures, jobs, output,
                CONTRACT['effective_ceiling_usd'])
    except RuntimeError as error:
        terminal_error = error_metadata(error)
        if str(error) == 'Cost ceiling reached; checkpoint retained':
            exhausted = True
        else:
            stopped = repr(error)
    except Exception as error:
        terminal_error = error_metadata(error)
        stopped = repr(error)

    raw_bytes = evidence_path.read_bytes() if evidence_path.exists() else b''
    prefix_ok = raw_bytes.startswith(RESUME_LEDGER)
    suffix = raw_bytes[len(RESUME_LEDGER):] if prefix_ok else b''
    events, parse_failures = hosted.parse_jsonl_best_effort(raw_bytes)
    suffix_events, suffix_parse_failures = hosted.parse_jsonl_best_effort(suffix)
    raw_accounting = hosted.raw_event_summary(
        events, invalid_json_lines=len(parse_failures))
    new_accounting = hosted.raw_event_summary(
        suffix_events, invalid_json_lines=len(suffix_parse_failures))
    evidence_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if KIND == 'preflight':
        terminal = dict(
            schema='chronos.reasoning-terminal.v1',
            model=MODEL,
            reasoning=REASONING,
            study_id=STUDY_ID,
            identity=CONTRACT['identity'],
            manifest_sha256=CONTRACT['manifest_sha256'],
            protocol_extension_sha256=CONTRACT['protocol_extension_sha256'],
            call_settings=CONTRACT['call_settings'],
            source_sha256=CONTRACT['source_sha256'],
            job_ids=[job['id'] for job in jobs],
            planned_calls=10,
            evidence_sha256=evidence_sha256,
            error=terminal_error,
            transient_waits=dict(WAITS),
            minimal_unsupported_receipt_sha256=
                CONTRACT['minimal_unsupported_receipt_sha256'],
        )
        (output / 'reasoning_terminal.json').write_text(
            json.dumps(terminal, indent=2, sort_keys=True))

    audit_error, checked = None, None
    try:
        if not prefix_ok:
            raise ValueError('Final ledger does not preserve the parent byte prefix')
        if parse_failures:
            raise ValueError('Final ledger contains invalid JSON lines')
        ledger = hosted.validate_resume_ledger(
            events, model=MODEL, identity=identity,
            expected_jobs={{job['id']: job for job in jobs}},
            structural_audit=structural_audit)
        structural = structural_audit(events)
        subset = hosted.subset_summary(events, {{job['id'] for job in jobs}})
        checked = dict(CONTRACT, ledger_audit=ledger,
                       structural_audit=structural, subset=subset,
                       allocation_exhausted=exhausted, stopped_early=stopped,
                       terminal_error=terminal_error,
                       transient_waits=dict(WAITS),
                       evidence_sha256=evidence_sha256,
                       raw_accounting=raw_accounting,
                       new_suffix_accounting=new_accounting,
                       parent_prefix_preserved=prefix_ok)
        checked['passed'] = bool(subset['complete'] and not exhausted and not stopped)
        if KIND == 'preflight':
            checked['preflight'] = reasoning_preflight.pass_gate(events, jobs)
            checked['passed'] = checked['passed'] and checked['preflight']['passed']
    except Exception as error:
        audit_error = repr(error)
        checked = dict(CONTRACT, passed=False, audit_failed=audit_error,
                       allocation_exhausted=exhausted, stopped_early=stopped,
                       terminal_error=terminal_error,
                       transient_waits=dict(WAITS),
                       evidence_sha256=evidence_sha256,
                       raw_accounting=raw_accounting,
                       new_suffix_accounting=new_accounting,
                       parse_failures=parse_failures,
                       parent_prefix_preserved=prefix_ok)
    (output / 'audit.json').write_text(json.dumps(checked, indent=2, sort_keys=True))
    print('ROUND2_AUDIT', json.dumps(checked, sort_keys=True), flush=True)
    if stopped:
        print('STOPPED_EARLY', stopped, flush=True)


hosted_cell.run(kbench.llms[MODEL])
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("preflight", "study", "defense"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning", choices=("minimal", "low"), required=True)
    parser.add_argument("--study-id", required=True)
    parser.add_argument("--ceiling", type=float, required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--output-folder", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--arm", choices=defenses.MODES)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--resume-from", type=Path)
    parser.add_argument("--wait-budget", type=int)
    parser.add_argument("--preflight-receipt", type=Path)
    parser.add_argument("--preflight-evidence", type=Path)
    parser.add_argument("--preflight-terminal", type=Path)
    parser.add_argument("--minimal-unsupported-receipt", type=Path)
    parser.add_argument("--minimal-unsupported-evidence", type=Path)
    parser.add_argument("--minimal-unsupported-terminal", type=Path)
    parser.add_argument("--minimal-unsupported-quota-attestation", type=Path)
    args = parser.parse_args()
    code = build_source(
        kind=args.kind,
        model=args.model,
        reasoning=args.reasoning,
        study_id=args.study_id,
        ceiling_usd=args.ceiling,
        task_name=args.task,
        output_folder=args.output_folder,
        arm=args.arm,
        shard_index=args.shard_index,
        shard_count=args.shard_count,
        resume_from=args.resume_from,
        wait_budget=args.wait_budget,
        preflight_receipt=args.preflight_receipt,
        preflight_evidence=args.preflight_evidence,
        preflight_terminal=args.preflight_terminal,
        minimal_unsupported_receipt=args.minimal_unsupported_receipt,
        minimal_unsupported_evidence=args.minimal_unsupported_evidence,
        minimal_unsupported_terminal=args.minimal_unsupported_terminal,
        minimal_unsupported_quota_attestation=(
            args.minimal_unsupported_quota_attestation
        ),
    )
    compile(code, str(args.output), "exec")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(code)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
