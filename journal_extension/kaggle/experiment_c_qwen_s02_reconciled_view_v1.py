"""One-event, in-memory cost view for the byte-preserved Qwen s02 ledger.

Only the pinned, account-reconciled HTTP 429 is represented as zero cost in
this derived view. The downloaded raw JSONL remains unchanged and null-cost.
This module does not authorize a launch or change any frozen scientific input.
"""

from __future__ import annotations

import copy
import hashlib
import json


PARENT_SHA256 = "cd6e6cc30cc8497a55d3768438cd54d2faa95d5a036137e837bfa4f746745499"
FAILED_LINE_SHA256 = "844cc962acb7869864fd636700f0e3a14d712f43cf85f4292d520b9a39d67081"
FAILED_LINE_INDEX = 9
MODEL = "qwen/qwen3-235b-a22b-instruct-2507"
JOB_ID = "chronos_round2_tree4_experiment_c_v1|defense|qwen/qwen3-235b-a22b-instruct-2507|tree4|undefended_selected_order|0|3"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _failed_event(event: dict) -> None:
    if (event.get("event") != "call_failed"
            or event.get("error_type") != "RateLimitError"
            or event.get("job_id") != JOB_ID
            or event.get("model") != MODEL
            or event.get("step") != 2
            or event.get("attempt") != 1
            or event.get("cost_usd") is not None
            or event.get("raw_completion") is not None
            or not isinstance(event.get("usage"), dict)
            or any(value is not None for value in event["usage"].values())):
        raise ValueError("Qwen s02 reconciled event differs from the pinned 429")


def normalized_cumulative(raw: bytes, parent: bytes) -> list[dict]:
    """Return a deep-copied cost view; require the exact parent raw prefix."""
    if (_sha256(parent) != PARENT_SHA256 or not raw.startswith(parent)
            or not parent.endswith(b"\n") or not raw.endswith(b"\n")):
        raise ValueError("Qwen s02 raw prefix or newline differs")
    lines = raw.splitlines(keepends=True)
    if len(lines) <= FAILED_LINE_INDEX or _sha256(lines[FAILED_LINE_INDEX]) != FAILED_LINE_SHA256:
        raise ValueError("Qwen s02 failed event line changed")
    events = [json.loads(line) for line in lines]
    failed = events[FAILED_LINE_INDEX]
    _failed_event(failed)
    if any(event.get("event") in ("call_complete", "call_failed")
           and event.get("cost_usd") is None for i, event in enumerate(events)
           if i != FAILED_LINE_INDEX):
        raise ValueError("Qwen s02 has another unknown-cost call")
    normalized = copy.deepcopy(events)
    replacement = normalized[FAILED_LINE_INDEX]
    replacement["cost_usd"] = 0.0
    replacement["usage"]["input_tokens_cost_nanodollars"] = 0
    replacement["usage"]["output_tokens_cost_nanodollars"] = 0
    return normalized


def original_failure(parent: bytes) -> dict:
    """Return only the exact original event for a guarded runtime loader."""
    normalized_cumulative(parent, parent)
    return json.loads(parent.splitlines(keepends=True)[FAILED_LINE_INDEX])
