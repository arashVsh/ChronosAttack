"""Verify signed-in Kaggle browser quota captures without changing frozen SDK code."""

from __future__ import annotations

import json

import capture_benchmark_quota_v1 as base


BROWSER_SCHEMA = "chronos.kaggle-browser-quota-attestation.v1"
BROWSER_OBSERVATION_SCHEMA = "chronos.kaggle-browser-quota-observation.v1"
BROWSER_ENDPOINT = "/api/i/models.ModelProxyService/GetModelProxyQuotas"
BROWSER_TRANSPORT = "signed-in Kaggle browser CDP Network.getResponseBody"


def build_browser_attestation(
    *, observation: dict, task: str, evidence: bytes, terminal: bytes,
) -> dict:
    """Bind the exact signed-in page API quota body to a completed raw run."""
    if (
        observation.get("schema") != BROWSER_OBSERVATION_SCHEMA
        or observation.get("endpoint") != BROWSER_ENDPOINT
        or observation.get("transport") != BROWSER_TRANSPORT
        or not isinstance(observation.get("response_raw"), str)
    ):
        raise ValueError("unexpected browser quota observation")
    try:
        raw = json.loads(observation["response_raw"])
        daily = [balance for balance in raw["quotaBalances"]
                 if balance["refillPeriod"] == "DAILY"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid browser quota response") from exc
    if len(daily) != 1:
        raise ValueError("browser quota response must have one daily balance")
    used = daily[0].get("quotaUsed")
    allowed = daily[0].get("totalQuotaAllowed")
    if (
        type(used) not in (int, float) or type(allowed) not in (int, float)
        or not 0 <= used <= allowed or allowed <= 0
    ):
        raise ValueError("invalid browser quota values")
    start = base._parse_time(observation["queried_at_start_utc"])
    end = base._parse_time(observation["queried_at_end_utc"])
    last_event = base._parse_time(base._last_event_time(evidence))
    if end < start or start < last_event:
        raise ValueError("browser quota was queried before the pinned run ended")
    terminal_value = json.loads(terminal)
    if not isinstance(terminal_value, dict):
        raise ValueError("terminal artifact must be a JSON object")
    body = {
        "schema": BROWSER_SCHEMA,
        "endpoint": BROWSER_ENDPOINT,
        "transport": BROWSER_TRANSPORT,
        "queried_at_start_utc": start.isoformat(),
        "queried_at_end_utc": end.isoformat(),
        "response_raw": observation["response_raw"],
        "response": {
            "daily_quota_used_usd": float(used),
            "total_daily_quota_allowed_usd": float(allowed),
        },
        "run_context": {
            "task": task,
            "model": terminal_value.get("model"),
            "reasoning": terminal_value.get("reasoning"),
            "study_id": terminal_value.get("study_id"),
            "last_evidence_event_utc": last_event.isoformat(),
            "evidence_sha256": base._sha256(evidence),
            "terminal_sha256": base._sha256(terminal),
        },
    }
    return {**body, "attestation_sha256": base._sha256(base._canonical(body))}


def verify_attestation(attestation: dict, evidence: bytes, terminal: bytes) -> None:
    if attestation.get("schema") != BROWSER_SCHEMA:
        base.verify_attestation(attestation, evidence, terminal)
        return
    digest = attestation.get("attestation_sha256")
    body = {key: value for key, value in attestation.items() if key != "attestation_sha256"}
    if digest != base._sha256(base._canonical(body)):
        raise ValueError("quota attestation self-hash mismatch")
    rebuilt = build_browser_attestation(
        observation={
            "schema": BROWSER_OBSERVATION_SCHEMA,
            "endpoint": attestation.get("endpoint"),
            "transport": attestation.get("transport"),
            "queried_at_start_utc": attestation["queried_at_start_utc"],
            "queried_at_end_utc": attestation["queried_at_end_utc"],
            "response_raw": attestation.get("response_raw"),
        },
        task=attestation["run_context"]["task"],
        evidence=evidence, terminal=terminal,
    )
    if rebuilt != attestation:
        raise ValueError("browser quota attestation differs from rebuilt evidence")
