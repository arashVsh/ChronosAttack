"""Account-level settlement proof for the Gemini s06 zero-job HTTP 429.

The raw failed call remains null-cost. This read-only proof does not authorize
a resume, change the frozen runner, or imply that Kaggle's PASS means complete.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path

import verify_experiment_c_gemini_s03_platform_bridge_v1 as bridge
from verify_experiment_c_qwen_s02_reconciliation_v1 import parse_observation


ROOT = bridge.ROOT
GENERATED = ROOT / "kaggle/round2_generated"
TASK = "chronos-r2-tree4-c-gemini-minimal-s06-v1"
RUN_ID = 2938768
RUN_ROOT = (ROOT / "kaggle/round2_runs_20260920/experiment_c_study/"
            f"gemini-minimal/{TASK}/1")
ORIGINAL = RUN_ROOT / TASK / "1" / "gemini-3.6-flash" / str(RUN_ID)
RAW = RUN_ROOT / "round2_tree4_c_gemini_minimal_s06_v1/google_gemini-3.6-flash.jsonl"
SNAPSHOT = GENERATED / "experiment_c_collection_gemini_s06_partial_platform_bridge_snapshot_v1.json"
OBSERVATIONS = (
    GENERATED / "experiment_c_quota_after_gemini_s05_browser_observation_20260924_v1.json",
    GENERATED / "experiment_c_quota_after_gemini_s06_429_browser_observation_20260924_v1.json",
    GENERATED / "experiment_c_quota_gemini_s06_429_settlement_observation_20260924_v1.json",
)
RAW_SHA256 = "c9c9115e3d36a23f3a10e03af182b961273d29cd6160d4751b7774d280f72154"
FAILED_LINE_SHA256 = "3eb040116d27899e8a9e4391f3b91b278ff2abb83a76d13483db7776aed9783f"
COLLECTION_SHA256 = "fa1314c70615297a41ade5032bcc0f8bf0957ba7cc54470073599d0cd6773add"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("429 timestamp lacks timezone")
    return parsed


def _original_copy() -> None:
    originals = sorted(path for path in ORIGINAL.rglob("*") if path.is_file())
    if len(originals) < 10:
        raise ValueError("s06 run-ID download is incomplete")
    for path in originals:
        copied = RUN_ROOT / path.relative_to(ORIGINAL)
        if not copied.is_file() or copied.read_bytes() != path.read_bytes():
            raise ValueError("s06 canonical run differs from original download")


def reconcile(observations: list[dict], events: list[dict]) -> dict:
    if len(observations) != 3 or any(
        left["end"] >= right["start"]
        for left, right in zip(observations, observations[1:])
    ):
        raise ValueError("s06 quota observations are not strictly ordered")
    before, after, late = observations
    if (len(events) != 3
            or [event.get("event") for event in events]
            != ["job_started", "call_failed", "job_error"]):
        raise ValueError("s06 raw 429 event sequence differs")
    failed = events[1]
    if (failed.get("error_type") != "RateLimitError"
            or failed.get("model") != bridge.MODEL
            or failed.get("job_id") !=
            "chronos_round2_tree4_experiment_c_v1|defense|google/gemini-3.6-flash|tree4|undefended_natural|0|7"
            or failed.get("step") != 1
            or failed.get("attempt") != 1
            or failed.get("cost_usd") is not None
            or failed.get("raw_completion") is not None
            or not isinstance(failed.get("usage"), dict)
            or any(value is not None for value in failed["usage"].values())):
        raise ValueError("s06 failed event is not the pinned null-cost 429")
    failure_time = _time(failed["timestamp"])
    if (not before["end"] < failure_time < after["start"] < late["start"]
            or late["start"] - failure_time < timedelta(minutes=30)
            or not late["end"] < _time(before["daily_reset"])):
        raise ValueError("s06 settlement observation is outside the pre-reset interval")
    for field in ("daily", "monthly"):
        if not before[field] == after[field] == late[field]:
            raise ValueError("s06 quota moved after the 429")
    for field in ("daily_reset", "monthly_reset"):
        reference = _time(before[field])
        if any(abs((_time(row[field]) - reference).total_seconds()) > 1
               for row in (after, late)):
            raise ValueError("s06 quota reset identity changed")
    return {
        "schema": "chronos.experiment-c-gemini-s06-quota-reconciliation.v1",
        "finding": "account_level_zero_increment_for_one_429",
        "raw_null_cost_calls": 1,
        "failure_timestamp_utc": failed["timestamp"],
        "last_observation_utc": late["end"].isoformat(),
    }


def verify() -> dict:
    checked = bridge.verify(SNAPSHOT)
    if checked["collection_sha256"] != COLLECTION_SHA256:
        raise ValueError("s06 partial collection seal changed")
    _original_copy()
    raw = RAW.read_bytes()
    if digest(raw) != RAW_SHA256 or not raw.endswith(b"\n"):
        raise ValueError("s06 raw ledger bytes changed")
    lines = raw.splitlines(keepends=True)
    if len(lines) != 3 or digest(lines[1]) != FAILED_LINE_SHA256:
        raise ValueError("s06 failed line changed")
    events = [json.loads(line) for line in lines]
    observations = [parse_observation(path.read_bytes()) for path in OBSERVATIONS]
    result = reconcile(observations, events)
    return {
        **result,
        "raw_sha256": digest(raw),
        "failed_event_line_sha256": digest(lines[1]),
        "observation_sha256": [digest(path.read_bytes()) for path in OBSERVATIONS],
        "collection_sha256": checked["collection_sha256"],
        "resume_authorized": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
