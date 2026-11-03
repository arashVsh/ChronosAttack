"""Account-level, byte-pinned reconciliation for the Qwen s02 HTTP 429.

This verifier never rewrites the raw null-cost event or authorizes a resume.
It proves only that signed-in Kaggle quota movements equal independently
recorded non-null call costs through a later, serial Claude run.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import verify_experiment_c_collection_v1 as collection


ROOT = Path(__file__).resolve().parent.parent
GENERATED = ROOT / "kaggle/round2_generated"
QWEN_ROOT = ROOT / "kaggle/round2_runs_20260920/experiment_c_study/qwen-low/chronos-r2-tree4-c-qwen-low-s02-v1/1"
CLAUDE_ROOT = ROOT / "kaggle/round2_runs_20260920/experiment_c_study/claude-none/chronos-r2-tree4-c-claude-none-s02-v1/1"
QWEN_RAW = QWEN_ROOT / "round2_tree4_c_qwen_low_s02_v1/qwen_qwen3-235b-a22b-instruct-2507.jsonl"
CLAUDE_RAW = CLAUDE_ROOT / "round2_tree4_c_claude_none_s02_v1/anthropic_claude-sonnet-4-6@default.jsonl"
OBSERVATIONS = (
    GENERATED / "experiment_c_quota_before_qwen_s02_browser_observation_20260924_v1.json",
    GENERATED / "experiment_c_quota_after_qwen_s02_browser_observation_20260924_v1.json",
    GENERATED / "experiment_c_quota_qwen_s02_reconciliation_observation_20260924_v1.json",
    GENERATED / "experiment_c_quota_after_claude_s02_browser_observation_20260924_v1.json",
)
SPECS = GENERATED / "experiment_c_run_specs_claude_s02_snapshot_v1.json"
SNAPSHOT = GENERATED / "experiment_c_collection_claude_s02_snapshot_v1.json"
QWEN_SHA256 = "cd6e6cc30cc8497a55d3768438cd54d2faa95d5a036137e837bfa4f746745499"
COLLECTION_SHA256 = "41f8b703946d3ea4246575417c7b3bbbbdbca080adeb7201e0d242b081b33cd6"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("quota or event timestamp has no timezone")
    return parsed


def parse_observation(raw: bytes) -> dict:
    outer = json.loads(raw)
    if (outer.get("schema") != "chronos.kaggle-browser-quota-observation.v1"
            or outer.get("endpoint") != "/api/i/models.ModelProxyService/GetModelProxyQuotas"
            or outer.get("transport") != "signed-in Kaggle browser CDP Network.getResponseBody"):
        raise ValueError("quota observation provenance differs")
    balances = json.loads(outer["response_raw"], parse_float=Decimal)["quotaBalances"]
    if len(balances) != 2 or {item["refillPeriod"] for item in balances} != {"DAILY", "MONTHLY"}:
        raise ValueError("quota response lacks daily and monthly balances")
    rows = {item["refillPeriod"]: item for item in balances}
    start, end = _time(outer["queried_at_start_utc"]), _time(outer["queried_at_end_utc"])
    if not start <= end or (end - start).total_seconds() > 10:
        raise ValueError("quota observation timing differs")
    for row, allowed in ((rows["DAILY"], Decimal(10)), (rows["MONTHLY"], Decimal(100))):
        if row["totalQuotaAllowed"] != allowed or not 0 <= row["quotaUsed"] <= allowed:
            raise ValueError("quota allowance or usage differs")
    return {
        "start": start,
        "end": end,
        "daily": rows["DAILY"]["quotaUsed"],
        "monthly": rows["MONTHLY"]["quotaUsed"],
        "daily_reset": rows["DAILY"]["refillTime"],
        "monthly_reset": rows["MONTHLY"]["refillTime"],
    }


def parse_ledger(raw: bytes) -> tuple[list[dict], list[bytes]]:
    if not raw.endswith(b"\n"):
        raise ValueError("raw ledger is not newline terminated")
    lines = raw.splitlines(keepends=True)
    return [json.loads(line) for line in lines], lines


def reconcile(observations: list[dict], qwen_events: list[dict],
              claude_events: list[dict]) -> dict:
    if len(observations) != 4 or any(
        left["end"] >= right["start"] for left, right in zip(observations, observations[1:])
    ):
        raise ValueError("quota observations are not strictly ordered")
    before, post, late, after_claude = observations
    if (abs((_time(before["daily_reset"]) - _time(post["daily_reset"])).total_seconds()) > 1
            or abs((_time(before["monthly_reset"]) - _time(post["monthly_reset"])).total_seconds()) > 1
            or post["daily"] != late["daily"]
            or post["monthly"] != late["monthly"]):
        raise ValueError("quota changed during the Qwen settlement interval")
    q_calls = [event for event in qwen_events if event.get("event") in ("call_complete", "call_failed")]
    c_calls = [event for event in claude_events if event.get("event") in ("call_complete", "call_failed")]
    failed = [event for event in q_calls if event["event"] == "call_failed"]
    if (len(q_calls) != 7 or len(failed) != 1 or len(c_calls) != 45
            or any(event["event"] != "call_complete" for event in c_calls)):
        raise ValueError("the two run call rosters differ")
    failure = failed[0]
    if (failure.get("error_type") != "RateLimitError"
            or failure.get("cost_usd") is not None
            or failure.get("raw_completion") is not None
            or any(value is not None for value in (failure.get("usage") or {}).values())
            or not before["end"] < _time(failure["timestamp"]) < post["start"]):
        raise ValueError("the pinned Qwen 429 is not the sole null-cost failure")
    if any(event.get("cost_usd") is None for event in q_calls if event is not failure):
        raise ValueError("another Qwen call has unknown cost")
    q_cost = sum((Decimal(str(event["cost_usd"])) for event in q_calls if event is not failure), Decimal(0))
    c_cost = sum((Decimal(str(event["cost_usd"])) for event in c_calls), Decimal(0))
    if (q_cost != Decimal("0.00135960") or c_cost != Decimal("0.195744")
            or post["daily"] - before["daily"] != q_cost
            or post["monthly"] - before["monthly"] != q_cost
            or after_claude["daily"] - late["daily"] != c_cost
            or after_claude["monthly"] - late["monthly"] != c_cost
            or _time(c_calls[-1]["timestamp"]) >= after_claude["start"]):
        raise ValueError("official quota movement does not equal the raw known costs")
    return {
        "schema": "chronos.experiment-c-qwen-s02-quota-reconciliation.v1",
        "finding": "account_level_zero_increment_for_one_429",
        "qwen_known_cost_usd": str(q_cost),
        "claude_known_cost_usd": str(c_cost),
        "raw_null_cost_calls": 1,
        "qwen_failure_timestamp_utc": failure["timestamp"],
        "last_observation_utc": after_claude["end"].isoformat(),
    }


def verify() -> dict:
    checked = collection.verify_collection_manifest(SNAPSHOT)
    rebuilt = collection.build_manifest_from_runs(json.loads(SPECS.read_text()))
    if checked["collection_sha256"] != COLLECTION_SHA256 or rebuilt["collection_sha256"] != COLLECTION_SHA256:
        raise ValueError("C collection no longer matches the strict raw replay")
    qraw, craw = QWEN_RAW.read_bytes(), CLAUDE_RAW.read_bytes()
    if digest(qraw) != QWEN_SHA256:
        raise ValueError("Qwen raw bytes changed")
    qevents, qlines = parse_ledger(qraw)
    cevents, _ = parse_ledger(craw)
    observations = [parse_observation(path.read_bytes()) for path in OBSERVATIONS]
    result = reconcile(observations, qevents, cevents)
    failures = [line for event, line in zip(qevents, qlines) if event.get("event") == "call_failed"]
    if len(failures) != 1:
        raise ValueError("Qwen failure line is not unique")
    return {
        **result,
        "qwen_raw_sha256": digest(qraw),
        "qwen_failed_event_line_sha256": digest(failures[0]),
        "claude_raw_sha256": digest(craw),
        "observation_sha256": [digest(path.read_bytes()) for path in OBSERVATIONS],
        "collection_sha256": checked["collection_sha256"],
        "resume_authorized": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
