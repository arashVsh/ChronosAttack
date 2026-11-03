"""Read-only settlement proof for Gemini s06's second, post-reset HTTP 429.

Kaggle omits the daily-used field after reset. This verifier checks monthly
usage across all observations and leaves daily used as missing; a separate
quota-transport gate is required for any later launch. Both raw failed calls
remain null-cost in evidence.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import verify_experiment_c_gemini_s06_resume_collection_v1 as collection


ROOT = collection.bridge.ROOT
GENERATED = ROOT / "kaggle/round2_generated"
SNAPSHOT = GENERATED / "experiment_c_collection_gemini_s06_v2_repeated429_platform_bridge_snapshot_v1.json"
RAW = (ROOT / collection.CANONICAL /
       "round2_tree4_c_gemini_minimal_s06_v1/google_gemini-3.6-flash.jsonl")
OBSERVATIONS = (
    GENERATED / "experiment_c_quota_gemini_s06_v2_immediate_prelaunch_observation_20260924_v1.json",
    GENERATED / "experiment_c_quota_after_gemini_s06_v2_429_postreset_browser_observation_20260924_v1.json",
    GENERATED / "experiment_c_quota_gemini_s06_v2_429_settlement_observation_20260924_v1.json",
)
COLLECTION_SHA256 = "40423c972ab727055365546bde33e72666cabfa0ce864a2fd7e227f5507a5962"
FAILED_LINE_SHA256 = "73b02bd99aa8c265fd1f49dd63b6bf264b580fd1dc1c3600bde9cfb3158f6566"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("s06 v2 observation timestamp lacks timezone")
    return parsed


def parse_observation(raw: bytes, *, allow_missing_daily: bool = False) -> dict:
    outer = json.loads(raw)
    if (outer.get("schema") != "chronos.kaggle-browser-quota-observation.v1"
            or outer.get("endpoint") !=
            "/api/i/models.ModelProxyService/GetModelProxyQuotas"
            or outer.get("transport") !=
            "signed-in Kaggle browser CDP Network.getResponseBody"):
        raise ValueError("s06 v2 quota observation provenance differs")
    response = json.loads(outer["response_raw"], parse_float=Decimal)
    balances = response.get("quotaBalances")
    if (not isinstance(balances, list) or len(balances) != 2
            or {row.get("refillPeriod") for row in balances}
            != {"DAILY", "MONTHLY"}):
        raise ValueError("s06 v2 quota response lacks both windows")
    rows = {row["refillPeriod"]: row for row in balances}
    daily, monthly = rows["DAILY"], rows["MONTHLY"]
    start = _time(outer["queried_at_start_utc"])
    end = _time(outer["queried_at_end_utc"])
    if not start <= end or end - start > timedelta(seconds=10):
        raise ValueError("s06 v2 quota query timing differs")
    used_daily = daily.get("quotaUsed")
    used_monthly = monthly.get("quotaUsed")
    if (daily.get("totalQuotaAllowed") != Decimal(10)
            or monthly.get("totalQuotaAllowed") != Decimal(100)
            or used_monthly is None or not 0 <= used_monthly <= 100
            or used_daily is None and not allow_missing_daily
            or used_daily is not None and not 0 <= used_daily <= 10
            or not isinstance(monthly.get("refillTime"), str)
            or used_daily is not None
            and not isinstance(daily.get("refillTime"), str)):
        raise ValueError("s06 v2 quota balance fields differ")
    return {
        "start": start, "end": end,
        "daily": used_daily, "monthly": used_monthly,
        "daily_reset": daily.get("refillTime"),
        "monthly_reset": monthly["refillTime"],
    }


def reconcile(observations: list[dict], events: list[dict]) -> dict:
    if (len(observations) != 3
            or any(left["end"] >= right["start"]
                   for left, right in zip(observations, observations[1:]))):
        raise ValueError("s06 v2 quota observations are not ordered")
    before, immediate, late = observations
    if (len(events) != 6
            or [event.get("event") for event in events[3:]]
            != ["job_started", "call_failed", "job_error"]):
        raise ValueError("s06 v2 raw suffix differs")
    failed = events[4]
    if (failed.get("error_type") != "RateLimitError"
            or failed.get("model") != collection.view.MODEL
            or failed.get("job_id") != collection.view.JOB_ID
            or failed.get("step") != 1 or failed.get("attempt") != 2
            or failed.get("cost_usd") is not None
            or failed.get("raw_completion") is not None
            or not isinstance(failed.get("usage"), dict)
            or any(value is not None for value in failed["usage"].values())):
        raise ValueError("s06 v2 failure differs from the second null-cost 429")
    failure_time = _time(failed["timestamp"])
    if (not before["end"] < failure_time < immediate["start"] < late["start"]
            or late["start"] - failure_time < timedelta(minutes=30)
            or not before["end"] < _time(before["daily_reset"]) < immediate["start"]
            or late["daily"] is not None and late["daily"] != Decimal(0)
            or late["daily_reset"] is not None
            and _time(late["daily_reset"]) <= late["end"]):
        raise ValueError("s06 v2 settlement did not span the daily reset")
    if (before["monthly"] != immediate["monthly"]
            or before["monthly"] != late["monthly"]
            or any(abs((_time(row["monthly_reset"])
                        - _time(before["monthly_reset"])).total_seconds()) > 1
                   for row in (immediate, late))):
        raise ValueError("s06 v2 monthly quota moved after the 429")
    return {
        "schema": "chronos.experiment-c-gemini-s06-v2-quota-reconciliation.v1",
        "finding": "account_level_zero_increment_for_second_429_across_daily_reset",
        "raw_null_cost_calls_in_s06": 2,
        "failure_timestamp_utc": failed["timestamp"],
        "last_observation_utc": late["end"].isoformat(),
        "monthly_used_usd": str(late["monthly"]),
        "daily_used_usd_after_reset": (None if late["daily"] is None
                                       else str(late["daily"])),
        "daily_usage_field_status": ("omitted" if late["daily"] is None
                                     else "explicit"),
    }


def verify() -> dict:
    checked = collection.verify(SNAPSHOT)
    if checked["collection_sha256"] != COLLECTION_SHA256:
        raise ValueError("s06 v2 partial collection seal changed")
    raw = RAW.read_bytes()
    if digest(raw) != collection.RAW_SHA256 or not raw.endswith(b"\n"):
        raise ValueError("s06 v2 raw ledger bytes changed")
    lines = raw.splitlines(keepends=True)
    if len(lines) != 6 or digest(lines[4]) != FAILED_LINE_SHA256:
        raise ValueError("s06 v2 second failure line changed")
    events = [json.loads(line) for line in lines]
    observations = [parse_observation(path.read_bytes(),
                                      allow_missing_daily=index in (1, 2))
                    for index, path in enumerate(OBSERVATIONS)]
    result = reconcile(observations, events)
    return {
        **result,
        "raw_sha256": digest(raw),
        "failed_event_line_sha256": digest(lines[4]),
        "observation_sha256": [digest(path.read_bytes()) for path in OBSERVATIONS],
        "collection_sha256": checked["collection_sha256"],
        "resume_authorized": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
