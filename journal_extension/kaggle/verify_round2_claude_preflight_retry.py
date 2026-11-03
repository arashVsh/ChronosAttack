"""Freeze and verify the one-shot Claude minimal replacement preflight."""

from __future__ import annotations

import argparse
import ast
import copy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

from build_hosted_cell_v2 import build_source, plan_cell
from capture_benchmark_quota_v1 import verify_attestation
import verify_round2_generated


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GENERATED = HERE / "round2_generated"
MANIFEST = GENERATED / "claude_preflight_retry_v1.json"
AMENDMENT = (
    ROOT
    / "specs/journal-extension-sep14/"
    "round2-claude-preflight-retry-amendment-2026-09-20.md"
)
SOURCE = GENERATED / "claude_reasoning_preflight_minimal_retry_v1.py"
MODEL = "anthropic/claude-sonnet-4-6@default"
REASONING = "minimal"
ORIGINAL_STUDY_ID = "chronos_round2_claude_reasoning_preflight_minimal_v1"
STUDY_ID = "chronos_round2_claude_reasoning_preflight_minimal_retry_v1"
TASK = "chronos-r2-claude-preflight-minimal-retry-v1"
OUTPUT_FOLDER = "round2_claude_reasoning_preflight_minimal_retry_v1"
FROZEN_AT = "2026-09-20T21:08:22+03:30"
CEILING_USD = 0.25
PRIOR_DAILY_COST_USD = 8.555856
DAILY_LIMIT_USD = 10.0

ORIGINAL_ROOT = (
    HERE
    / "round2_runs_20260920/claude_minimal"
    / "chronos-r2-claude-preflight-minimal-v1/1"
    / "claude-sonnet-4-6-default/2647262"
    / "round2_claude_reasoning_preflight_minimal_v1"
)
ORIGINAL_ARTIFACTS = {
    "evidence": ORIGINAL_ROOT / "anthropic_claude-sonnet-4-6@default.jsonl",
    "terminal": ORIGINAL_ROOT / "reasoning_terminal.json",
    "intended_manifest": ORIGINAL_ROOT / "intended_manifest.json",
    "audit": ORIGINAL_ROOT / "audit.json",
    "quota_attestation": ORIGINAL_ROOT / "quota_attestation_1.json",
}
EXPECTED_ORIGINAL_HASHES = {
    "evidence": "8cb0b2cecd7cb0ba2b22b3f84fdd4dca6e11a3199b975405362431c48b10da1d",
    "terminal": "84fd465308adb45169b01d098a775fbae661ee2f4a1802d47a0554ff410d0ae9",
    "intended_manifest": "dcc166fea1788d40da8972c26ce87c0352481cb6a04769afa89d8b184aa6141f",
    "audit": "380db9b455723c63bbe7f6c498ff0db12cc23603eb4e2497a822108b98894026",
    "quota_attestation": "cbdd09dbac13e5c6ae1838c0531d0761784e8562b15a484f1a809d57f4d15aed",
}
AMENDMENT_SHA256 = (
    "de72d61ca3bcfc05b22699326c6dc03e48913b6309b876b75374730f908fc0e2"
)

TOP_LEVEL_KEYS = {
    "schema",
    "retry_manifest_sha256",
    "frozen_at",
    "status",
    "amendment",
    "trigger",
    "retry",
    "budget",
}
FILE_RECORD_KEYS = {"path", "sha256", "bytes"}


def _arguments() -> dict:
    return {
        "kind": "preflight",
        "model": MODEL,
        "reasoning": REASONING,
        "study_id": STUDY_ID,
        "ceiling_usd": CEILING_USD,
        "task_name": TASK,
        "output_folder": OUTPUT_FOLDER,
    }


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_hash(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return _sha256(raw)


def _manifest_hash(manifest: dict) -> str:
    body = {
        key: value
        for key, value in manifest.items()
        if key != "retry_manifest_sha256"
    }
    return _canonical_hash(body)


def _repo_relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve()))


def _file_record(path: Path) -> dict:
    raw = path.read_bytes()
    return {
        "path": _repo_relative(path),
        "sha256": _sha256(raw),
        "bytes": len(raw),
    }


def _read_pinned(record: dict, expected: Path, label: str) -> bytes:
    if set(record) != FILE_RECORD_KEYS:
        raise ValueError(f"invalid pinned file record: {label}")
    path = (ROOT / record["path"]).resolve()
    if path != expected.resolve():
        raise ValueError(f"pinned path changed: {label}")
    if path != ROOT.resolve() and ROOT.resolve() not in path.parents:
        raise ValueError(f"pinned path escapes repository: {label}")
    raw = path.read_bytes()
    if len(raw) != record["bytes"] or _sha256(raw) != record["sha256"]:
        raise ValueError(f"pinned hash/size mismatch: {label}")
    return raw


def _json(raw: bytes, label: str) -> dict:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return value


def _assignments(source: str) -> dict:
    values = {}
    for node in ast.parse(source, str(SOURCE)).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    values[target.id] = ast.literal_eval(node.value)
                except (TypeError, ValueError):
                    pass
    return values


def build_manifest() -> dict:
    source_values = _assignments(SOURCE.read_text())
    terminal = json.loads(ORIGINAL_ARTIFACTS["terminal"].read_text())
    manifest = {
        "schema": "chronos.round2.claude-preflight-retry.v1",
        "retry_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "status": "authorized_not_launched",
        "amendment": _file_record(AMENDMENT),
        "trigger": {
            "task": "chronos-r2-claude-preflight-minimal-v1",
            "task_version": 1,
            "run_id": 2647262,
            "model": MODEL,
            "reasoning": REASONING,
            "study_id": ORIGINAL_STUDY_ID,
            "identity": terminal["identity"],
            "status": "generic_http_500_zero_completion_zero_increment",
            "observed_invocations": 1,
            "raw_unknown_cost_invocations": 1,
            "resolved_incremental_cost_usd": 0.0,
            "receipt_issued": False,
            "artifacts": {
                label: _file_record(path)
                for label, path in ORIGINAL_ARTIFACTS.items()
            },
        },
        "retry": {
            "task": TASK,
            "model": MODEL,
            "reasoning": REASONING,
            "study_id": STUDY_ID,
            "identity": source_values["CONTRACT"]["identity"],
            "output_folder": OUTPUT_FOLDER,
            "source": _file_record(SOURCE),
            "job_count": 2,
            "planned_calls": 10,
            "incremental_ceiling_usd": CEILING_USD,
            "sdk_max_retries": 0,
            "transport_wait_budget_seconds": 0,
            "replacement_limit": 1,
        },
        "budget": {
            "prior_known_daily_cost_usd": PRIOR_DAILY_COST_USD,
            "minimal_retry_ceiling_usd": CEILING_USD,
            "conditional_low_preflight_ceiling_usd": CEILING_USD,
            "maximum_after_minimal_retry_usd": (
                PRIOR_DAILY_COST_USD + CEILING_USD
            ),
            "maximum_if_low_is_authorized_usd": (
                PRIOR_DAILY_COST_USD + 2 * CEILING_USD
            ),
            "daily_limit_usd": DAILY_LIMIT_USD,
        },
    }
    manifest["retry_manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _load_manifest(value: dict | None) -> dict:
    manifest = (
        json.loads(MANIFEST.read_text()) if value is None else copy.deepcopy(value)
    )
    if set(manifest) != TOP_LEVEL_KEYS:
        raise ValueError("invalid Claude retry manifest schema")
    if _manifest_hash(manifest) != manifest["retry_manifest_sha256"]:
        raise ValueError("Claude retry manifest self-hash mismatch")
    if (
        manifest["schema"] != "chronos.round2.claude-preflight-retry.v1"
        or manifest["frozen_at"] != FROZEN_AT
        or manifest["status"] != "authorized_not_launched"
    ):
        raise ValueError("Claude retry top-level contract changed")
    return manifest


def _verify_trigger(trigger: dict) -> str:
    expected_keys = {
        "task",
        "task_version",
        "run_id",
        "model",
        "reasoning",
        "study_id",
        "identity",
        "status",
        "observed_invocations",
        "raw_unknown_cost_invocations",
        "resolved_incremental_cost_usd",
        "receipt_issued",
        "artifacts",
    }
    if set(trigger) != expected_keys or (
        trigger["task"] != "chronos-r2-claude-preflight-minimal-v1"
        or trigger["task_version"] != 1
        or trigger["run_id"] != 2647262
        or trigger["model"] != MODEL
        or trigger["reasoning"] != REASONING
        or trigger["study_id"] != ORIGINAL_STUDY_ID
        or trigger["status"]
        != "generic_http_500_zero_completion_zero_increment"
        or trigger["observed_invocations"] != 1
        or trigger["raw_unknown_cost_invocations"] != 1
        or trigger["resolved_incremental_cost_usd"] != 0.0
        or trigger["receipt_issued"] is not False
    ):
        raise ValueError("Claude retry trigger contract changed")
    if set(trigger["artifacts"]) != set(ORIGINAL_ARTIFACTS):
        raise ValueError("Claude retry trigger artifact set changed")
    blobs = {
        label: _read_pinned(
            trigger["artifacts"][label], path, f"Claude trigger {label}"
        )
        for label, path in ORIGINAL_ARTIFACTS.items()
    }
    for label, expected_hash in EXPECTED_ORIGINAL_HASHES.items():
        if _sha256(blobs[label]) != expected_hash:
            raise ValueError(f"Claude trigger canonical hash changed: {label}")

    evidence = blobs["evidence"]
    if not evidence.endswith(b"\n"):
        raise ValueError("Claude trigger evidence is not newline terminated")
    events = [json.loads(line) for line in evidence.splitlines()]
    kinds = [event.get("event") for event in events]
    failed = events[1] if len(events) == 3 else {}
    if (
        kinds != ["job_started", "call_failed", "job_error"]
        or any(event.get("attempt") != 1 for event in events)
        or failed.get("step") != 1
        or failed.get("error_type") != "InternalServerError"
        or failed.get("raw_completion") is not None
        or failed.get("cost_usd") is not None
        or any(failed.get("usage", {}).get(key) is not None for key in (
            "input_tokens",
            "input_tokens_cost_nanodollars",
            "output_tokens",
            "output_tokens_cost_nanodollars",
            "total_backend_latency_ms",
        ))
    ):
        raise ValueError("Claude trigger is not the exact zero-completion stop")

    terminal = _json(blobs["terminal"], "Claude trigger terminal")
    intended = _json(blobs["intended_manifest"], "Claude trigger manifest")
    audit = _json(blobs["audit"], "Claude trigger audit")
    quota = _json(blobs["quota_attestation"], "Claude trigger quota")
    error = terminal.get("error") or {}
    if (
        trigger["identity"] != terminal.get("identity")
        or terminal.get("model") != MODEL
        or terminal.get("reasoning") != REASONING
        or terminal.get("study_id") != ORIGINAL_STUDY_ID
        or terminal.get("evidence_sha256") != _sha256(evidence)
        or error.get("type") != "InternalServerError"
        or error.get("status_code") != 500
        or "internal server error" not in str(error.get("message") or "").lower()
        or terminal.get("transient_waits") != {"count": 0, "seconds": 0}
        or intended.get("job_count") != 2
        or intended.get("planned_calls") != 10
        or intended.get("incremental_ceiling_usd") != CEILING_USD
        or intended.get("effective_ceiling_usd") != CEILING_USD
        or audit.get("passed") is not False
        or (audit.get("raw_accounting") or {}).get("observed_invocations") != 1
        or (audit.get("raw_accounting") or {}).get("unknown_cost_calls") != 1
    ):
        raise ValueError("Claude trigger terminal or audit changed")
    verify_attestation(quota, evidence, blobs["terminal"])
    query_time = datetime.fromisoformat(quota["queried_at_start_utc"])
    last_event = max(datetime.fromisoformat(event["timestamp"]) for event in events)
    observed_quota = quota["response"]["daily_quota_used_usd"]
    if (
        (query_time - last_event).total_seconds() < 300
        or not math.isclose(observed_quota, 0.030434, rel_tol=0.0, abs_tol=1e-12)
    ):
        raise ValueError("Claude trigger cost was not independently settled")
    return terminal["identity"]


def _verify_retry(retry: dict, original_identity: str) -> dict:
    expected_keys = {
        "task",
        "model",
        "reasoning",
        "study_id",
        "identity",
        "output_folder",
        "source",
        "job_count",
        "planned_calls",
        "incremental_ceiling_usd",
        "sdk_max_retries",
        "transport_wait_budget_seconds",
        "replacement_limit",
    }
    if set(retry) != expected_keys or (
        retry["task"] != TASK
        or retry["model"] != MODEL
        or retry["reasoning"] != REASONING
        or retry["study_id"] != STUDY_ID
        or retry["output_folder"] != OUTPUT_FOLDER
        or (retry["job_count"], retry["planned_calls"]) != (2, 10)
        or retry["incremental_ceiling_usd"] != CEILING_USD
        or retry["sdk_max_retries"] != 0
        or retry["transport_wait_budget_seconds"] != 0
        or retry["replacement_limit"] != 1
        or retry["identity"] == original_identity
    ):
        raise ValueError("Claude retry execution contract changed")
    source_raw = _read_pinned(retry["source"], SOURCE, "Claude retry source")
    source = source_raw.decode("utf-8")
    if source != build_source(**_arguments()):
        raise ValueError("Claude retry source is not byte-exact regeneration")
    compile(source, str(SOURCE), "exec")
    values = _assignments(source)
    contract = values["CONTRACT"]
    jobs = values["EXPECTED_JOBS"]
    planned = plan_cell(
        kind="preflight",
        model=MODEL,
        reasoning=REASONING,
        study_id=STUDY_ID,
    )
    if (
        values["MODEL"] != MODEL
        or values["REASONING"] != REASONING
        or values["STUDY_ID"] != STUDY_ID
        or values["KIND"] != "preflight"
        or values["OUTPUT_FOLDER"] != OUTPUT_FOLDER
        or values["INCREMENTAL_CEILING_USD"] != CEILING_USD
        or values["MAX_WAIT_SECONDS"] != 0
        or values["RESUME_LEDGER"] != b""
        or jobs != planned["jobs"]
        or len(jobs) != 2
        or sum(job["calls"] for job in jobs) != 10
        or any(job["rep"] != 1 for job in jobs)
        or {job["condition"] for job in jobs} != {"natural", "attack"}
        or contract["identity"] != retry["identity"]
        or contract["manifest_sha256"] != planned["manifest_sha256"]
        or contract["job_count"] != 2
        or contract["planned_calls"] != 10
        or contract["incremental_ceiling_usd"] != CEILING_USD
        or contract["effective_ceiling_usd"] != CEILING_USD
        or contract["accepted_preflight_receipt_sha256"] is not None
        or contract["minimal_unsupported_receipt_sha256"] is not None
        or contract["call_settings"].get("sdk_max_retries") != 0
        or f"@kbench.task(name={TASK!r})" not in source
    ):
        raise ValueError("Claude retry generated contract changed")
    return {
        "source_sha256": _sha256(source_raw),
        "identity": retry["identity"],
        "jobs": len(jobs),
        "calls": sum(job["calls"] for job in jobs),
    }


def _verify_budget(budget: dict) -> None:
    expected = {
        "prior_known_daily_cost_usd": PRIOR_DAILY_COST_USD,
        "minimal_retry_ceiling_usd": CEILING_USD,
        "conditional_low_preflight_ceiling_usd": CEILING_USD,
        "maximum_after_minimal_retry_usd": PRIOR_DAILY_COST_USD + CEILING_USD,
        "maximum_if_low_is_authorized_usd": PRIOR_DAILY_COST_USD + 2 * CEILING_USD,
        "daily_limit_usd": DAILY_LIMIT_USD,
    }
    if budget != expected or (
        budget["maximum_after_minimal_retry_usd"] > DAILY_LIMIT_USD
        or budget["maximum_if_low_is_authorized_usd"] > DAILY_LIMIT_USD
    ):
        raise ValueError("Claude retry budget changed or exceeds daily credit")


def verify(value: dict | None = None) -> dict:
    manifest = _load_manifest(value)
    generated = verify_round2_generated.verify()
    claude = next(item for item in generated if item["model"] == MODEL)
    if claude["execution_status"] != "transient_error_stopped":
        raise ValueError("original Claude stop no longer independently verifies")
    amendment = _read_pinned(manifest["amendment"], AMENDMENT, "Claude amendment")
    if _sha256(amendment) != AMENDMENT_SHA256:
        raise ValueError("Claude amendment canonical hash changed")
    original_identity = _verify_trigger(manifest["trigger"])
    retry = _verify_retry(manifest["retry"], original_identity)
    _verify_budget(manifest["budget"])
    return {
        "schema": "chronos.round2.claude-preflight-retry-verification.v1",
        "retry_manifest_sha256": manifest["retry_manifest_sha256"],
        "status": manifest["status"],
        "task": TASK,
        "model": MODEL,
        "reasoning": REASONING,
        "jobs": retry["jobs"],
        "calls": retry["calls"],
        "source_sha256": retry["source_sha256"],
        "maximum_after_minimal_retry_usd": manifest["budget"][
            "maximum_after_minimal_retry_usd"
        ],
        "maximum_if_low_is_authorized_usd": manifest["budget"][
            "maximum_if_low_is_authorized_usd"
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    if args.write_manifest:
        manifest = build_manifest()
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"WROTE {MANIFEST}")
    checked = verify()
    print(
        "CLAUDE MINIMAL REPLACEMENT AUTHORIZED: {task}; {jobs} jobs / {calls} "
        "calls; source {source_sha256}; maximum ${maximum_after_minimal_retry_usd:.6f} "
        "today (${maximum_if_low_is_authorized_usd:.6f} only if explicit "
        "minimal-unsupported evidence authorizes low)".format(**checked)
    )


if __name__ == "__main__":
    main()
