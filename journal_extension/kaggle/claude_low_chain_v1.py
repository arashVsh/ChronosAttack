"""Claude `minimal` disposition from deterministic HTTP 500s, and `low` builds that use it.

See specs/journal-extension-sep14/round2-claude-low-reinstatement-2026-09-27.md. The frozen
gate recognises only a 400/422 rejection; Kaggle answers Claude `minimal` with a generic 500
every time. This module pins that evidence and supplies it where the frozen builder asks for
the minimal-unsupported receipt; nothing else in the builder changes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest import mock

import build_hosted_cell_v2 as builder

HERE = Path(__file__).resolve().parent
MODEL = "anthropic/claude-sonnet-4-6@default"
NOTE = "specs/journal-extension-sep14/round2-claude-low-reinstatement-2026-09-27.md"
_R = "round2_runs_20260920/"
_G = "round2_generated/claude_preflight_minimal_r2_task_download/masihmaafi/chronos-r2-claude-preflight-minimal-r2-v1/1/claude-sonnet-4-6-default/3242886/round2_claude_reasoning_preflight_minimal_r2_v1/"
PREFLIGHTS = (  # (raw ledger, sha256), each: one step-1 call_failed, InternalServerError 500, then job_error
    (_R + "claude_minimal/chronos-r2-claude-preflight-minimal-v1/1/claude-sonnet-4-6-default/2647262/round2_claude_reasoning_preflight_minimal_v1/anthropic_claude-sonnet-4-6@default.jsonl",
     "8cb0b2cecd7cb0ba2b22b3f84fdd4dca6e11a3199b975405362431c48b10da1d"),
    (_R + "claude_minimal_retry/chronos-r2-claude-preflight-minimal-retry-v1/1/claude-sonnet-4-6-default/2671436/round2_claude_reasoning_preflight_minimal_retry_v1/anthropic_claude-sonnet-4-6@default.jsonl",
     "d2316f8f14a6e010b3693ab196361bbdced9af9f1b74a3df5480673755ee2a20"),
    (_G + "anthropic_claude-sonnet-4-6@default.jsonl",
     "0b79da0455e51c3b870855f44340b326a5f45f53a3b6a3ae389428781f1a6f6e"),
)
DIAGNOSTICS = (
    "reasoning_probe_20260927/download_v2/masihmaafi/chronos-claude-reasoning-diag-20260927/2/claude-sonnet-4-6-default/3243304/claude_reasoning_diag.json",
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _terminal(ledger: Path) -> dict:
    (path,) = [p for p in ledger.parent.glob("*terminal*.json")]
    return json.loads(path.read_text())


def disposition() -> dict:
    """Re-check the pinned evidence and return the minimal-unsupported disposition."""
    pins = []
    for relative, expected in PREFLIGHTS:
        path = HERE / relative
        raw = path.read_bytes()
        events = [json.loads(line) for line in raw.splitlines()]
        error = _terminal(path).get("error") or {}
        if (_sha(raw) != expected or [e.get("event") for e in events] != ["job_started", "call_failed", "job_error"]
                or events[1].get("step") != 1 or events[1].get("raw_completion") is not None
                or events[1].get("error_type") != "InternalServerError" or error.get("status_code") != 500):
            raise ValueError(f"pinned Claude minimal preflight changed: {relative}")
        pins.append({"path": relative, "sha256": expected})
    for relative in DIAGNOSTICS:
        rows = json.loads((HERE / relative).read_text())
        minimal = [r for r in rows if r["reasoning"] == "minimal"]
        low = [r for r in rows if r["reasoning"] == "low"]
        if not minimal or any(r["ok"] or r.get("status") != 500 for r in minimal) or not low or not all(r["ok"] for r in low):
            raise ValueError("diagnostic no longer shows minimal failing and low passing")
        pins.append({"path": relative, "sha256": _sha((HERE / relative).read_bytes())})
    body = {"schema": "chronos.claude-minimal-disposition.v1", "disposition": "minimal_unsupported",
            "basis": "deterministic_http_500", "model": MODEL, "reasoning": "minimal",
            "note": NOTE, "evidence": pins}
    return {**body, "receipt_sha256": _sha(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())}


def build_low_source(**kwargs) -> str:
    """Frozen builder output for a Claude `low` cell, with the pinned disposition as predecessor."""
    original = builder._load_receipt_bundle

    def load(**bundle):
        if bundle.get("label") == "minimal-unsupported":
            return disposition()
        return original(**bundle)

    with mock.patch.object(builder, "_load_receipt_bundle", load):
        return builder.build_source(model=MODEL, reasoning="low", **kwargs)


if __name__ == "__main__":
    print(json.dumps(disposition(), indent=2))
