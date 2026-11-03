"""Derived cost view for only the byte-pinned Gemini s06 HTTP 429.

The hosted and downloaded JSONL stays null-cost. The zero-cost value exists
only in memory after the separate official-quota settlement proof succeeds.
"""

from __future__ import annotations

import copy
import hashlib
import json


PARENT_SHA256 = "c9c9115e3d36a23f3a10e03af182b961273d29cd6160d4751b7774d280f72154"
FAILED_LINE_SHA256 = "3eb040116d27899e8a9e4391f3b91b278ff2abb83a76d13483db7776aed9783f"
FAILED_LINE_INDEX = 1
MODEL = "google/gemini-3.6-flash"
JOB_ID = "chronos_round2_tree4_experiment_c_v1|defense|google/gemini-3.6-flash|tree4|undefended_natural|0|7"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _failed_event(event: dict) -> None:
    if (event.get("event") != "call_failed"
            or event.get("error_type") != "RateLimitError"
            or event.get("job_id") != JOB_ID
            or event.get("model") != MODEL
            or event.get("step") != 1
            or event.get("attempt") != 1
            or event.get("cost_usd") is not None
            or event.get("raw_completion") is not None
            or not isinstance(event.get("usage"), dict)
            or any(value is not None for value in event["usage"].values())):
        raise ValueError("Gemini s06 reconciled event differs from the pinned 429")


def normalized_cumulative(raw: bytes, parent: bytes) -> list[dict]:
    if (_sha256(parent) != PARENT_SHA256 or not raw.startswith(parent)
            or not parent.endswith(b"\n") or not raw.endswith(b"\n")):
        raise ValueError("Gemini s06 raw prefix or newline differs")
    lines = raw.splitlines(keepends=True)
    if (len(lines) <= FAILED_LINE_INDEX
            or _sha256(lines[FAILED_LINE_INDEX]) != FAILED_LINE_SHA256):
        raise ValueError("Gemini s06 failed event line changed")
    events = [json.loads(line) for line in lines]
    _failed_event(events[FAILED_LINE_INDEX])
    if any(event.get("event") in ("call_complete", "call_failed")
           and event.get("cost_usd") is None for i, event in enumerate(events)
           if i != FAILED_LINE_INDEX):
        raise ValueError("Gemini s06 has another unknown-cost call")
    normalized = copy.deepcopy(events)
    replacement = normalized[FAILED_LINE_INDEX]
    replacement["cost_usd"] = 0.0
    replacement["usage"]["input_tokens_cost_nanodollars"] = 0
    replacement["usage"]["output_tokens_cost_nanodollars"] = 0
    return normalized


def original_failure(parent: bytes) -> dict:
    normalized_cumulative(parent, parent)
    return json.loads(parent.splitlines(keepends=True)[FAILED_LINE_INDEX])
