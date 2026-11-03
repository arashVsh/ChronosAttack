"""Issue an outcome-independent B pilot receipt from downloaded raw artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import audit_experiment_b as auditor
import build_experiment_b_hosted_v1 as builder
import experiment_b_protocol as protocol
from round2_hosted import parse_jsonl_bytes, validate_resume_ledger


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _hash_body(value: dict) -> str:
    return _sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def issue_receipt(*, evidence: bytes, terminal: bytes, intended: bytes, model: str) -> dict:
    if not evidence or not evidence.endswith(b"\n"):
        raise ValueError("B pilot raw evidence must be nonempty newline-terminated JSONL")
    terminal_value = json.loads(terminal)
    intended_value = json.loads(intended)
    plan = builder.plan_cell(model=model, phase="pilot")
    cell = protocol.cell(model, "pilot")
    _, source_hashes = builder._sources()
    contract = intended_value.get("resume_ledger")
    if (
        intended_value.get("jobs") != plan["jobs"]
        or {key: value for key, value in intended_value.items() if key != "jobs"}
        != {
            **{key: value for key, value in plan.items() if key != "jobs"},
            **{
                key: intended_value[key]
                for key in ("source_sha256", "incremental_ceiling_usd", "effective_ceiling_usd", "parent_ledger_sha256", "pilot_receipt_sha256", "sdk_max_retries")
            },
        }
        or contract != plan["resume_ledger"]
        or intended_value.get("pilot_receipt_sha256") is not None
        or intended_value.get("parent_ledger_sha256") is not None
        or intended_value.get("sdk_max_retries") != 0
        or intended_value.get("source_sha256") != source_hashes
        or intended_value.get("incremental_ceiling_usd") != builder.PILOT_CEILING_USD
        or intended_value.get("effective_ceiling_usd") != builder.PILOT_CEILING_USD
    ):
        raise ValueError("B pilot intended manifest differs from frozen plan")
    expected_terminal = {
        "schema": "chronos.experiment-b-terminal.v1",
        "model": model,
        "reasoning": cell["reasoning"],
        "role": cell["role"],
        "phase": "pilot",
        "study_id": cell["study_id"],
        "identity": plan["identity"],
        "fixture_manifest_sha256": plan["fixture_manifest_sha256"],
        "jobs_sha256": plan["jobs_sha256"],
        "job_ids": [job["id"] for job in plan["jobs"]],
        "planned_calls": 10,
        "call_settings": {**protocol.call_settings(model), "sdk_max_retries": 0},
        "source_sha256": intended_value["source_sha256"],
        "evidence_sha256": _sha256(evidence),
        "parent_ledger_sha256": None,
        "pilot_receipt_sha256": None,
        "error": None,
    }
    if terminal_value != expected_terminal:
        raise ValueError("B pilot terminal differs from raw planned cell")
    events = parse_jsonl_bytes(evidence, label="B pilot evidence")
    structural = auditor.audit(events, model, "pilot")
    ledger = validate_resume_ledger(
        events,
        model=model,
        identity=plan["identity"],
        expected_jobs={job["id"]: job for job in plan["jobs"]},
        structural_audit=lambda rows: auditor.audit(rows, model, "pilot", require_complete=False),
    )
    if (
        not structural["pilot_passed"]
        or ledger["completed_jobs"] != 2
        or ledger["observed_invocations"] != 10
        or ledger["known_cost_usd"] != structural["known_cost_usd"]
    ):
        raise ValueError("B pilot did not pass raw structural and cost checks")
    body = {
        "schema": "chronos.experiment-b-pilot-receipt.v1",
        **cell,
        "identity": plan["identity"],
        "fixture_manifest_sha256": plan["fixture_manifest_sha256"],
        "jobs_sha256": plan["jobs_sha256"],
        "passed": True,
        "completed_jobs": 2,
        "observed_invocations": 10,
        "failed_calls": 0,
        "unknown_cost_calls": 0,
        "known_cost_usd": structural["known_cost_usd"],
        "outcomes_examined_for_authorization": False,
        "pilot_excluded_from_study": True,
        "evidence_sha256": _sha256(evidence),
        "terminal_sha256": _sha256(terminal),
        "intended_manifest_sha256": _sha256(intended),
    }
    return {**body, "receipt_sha256": _hash_body(body)}


def validate_receipt(receipt: dict, *, evidence: bytes, terminal: bytes, intended: bytes) -> None:
    rebuilt = issue_receipt(
        evidence=evidence,
        terminal=terminal,
        intended=intended,
        model=receipt["model"],
    )
    if rebuilt != receipt:
        raise ValueError("B pilot receipt differs from revalidated raw evidence")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--terminal", required=True, type=Path)
    parser.add_argument("--intended", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    receipt = issue_receipt(
        evidence=args.evidence.read_bytes(),
        terminal=args.terminal.read_bytes(),
        intended=args.intended.read_bytes(),
        model=args.model,
    )
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(receipt["receipt_sha256"])


if __name__ == "__main__":
    main()
