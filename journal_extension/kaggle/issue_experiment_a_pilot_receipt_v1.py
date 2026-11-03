"""Issue an Experiment A pilot receipt only after raw-evidence revalidation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import audit_water_supply as water_audit
import build_experiment_a_pilot_v1 as pilot_builder
import reasoning_preflight_v1 as pilot_gate
import round2_hosted as hosted
import water_supply_protocol as protocol


RECEIPT_SCHEMA = "chronos.experiment-a-pilot-receipt.v1"
PILOT_CEILING_USD = 0.25


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_hash(value: dict) -> str:
    return _sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )


def _receipt_hash(receipt: dict) -> str:
    return _canonical_hash(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )


def _load_object(raw: bytes, label: str) -> dict:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return value


def _expected_intended(
    *, model: str, reasoning: str, study_id: str
) -> tuple[dict, dict]:
    contract = pilot_builder.plan_pilot(
        model=model,
        reasoning=reasoning,
        study_id=study_id,
    )
    _, source_hashes = pilot_builder._source_payload()
    public = {key: value for key, value in contract.items() if key != "jobs"}
    public.update(
        {
            "source_sha256": source_hashes,
            "incremental_ceiling_usd": PILOT_CEILING_USD,
            "effective_ceiling_usd": PILOT_CEILING_USD,
            "parent_ledger_sha256": None,
            "call_settings": {
                "temperature": 1,
                "reasoning": reasoning,
                "max_completion_tokens": 256,
                "timeout": 30,
                "sdk_max_retries": 0,
            },
        }
    )
    return (
        dict(public, jobs=contract["jobs"], seed_audit=contract["resume_ledger"]),
        contract,
    )


def _raw_revalidation(
    evidence_raw: bytes,
    *,
    model: str,
    reasoning: str,
    study_id: str,
    expected_jobs: list[dict],
    identity: str,
) -> dict:
    events, failures = hosted.parse_jsonl_best_effort(evidence_raw)
    if failures:
        raise ValueError("pilot evidence contains invalid JSON lines")
    old = pilot_builder._with_runtime(model, reasoning, study_id)
    try:
        runtime_jobs = pilot_gate.jobs(protocol.jobs_for(model, "study"))
        if runtime_jobs != expected_jobs:
            raise ValueError("runtime pilot jobs differ from the frozen contract")
        structural_audit = lambda values: water_audit.audit(
            values, model, "study", require_complete=False
        )
        ledger = hosted.validate_resume_ledger(
            events,
            model=model,
            identity=identity,
            expected_jobs={job["id"]: job for job in expected_jobs},
            structural_audit=structural_audit,
        )
        structural = structural_audit(events)
        gate = pilot_gate.pass_gate(events, expected_jobs)
    finally:
        pilot_builder._restore_runtime(old)

    accounting = hosted.raw_event_summary(events)
    expected_accounting = {
        "events": 14,
        "invalid_json_lines": 0,
        "accounting_complete": True,
        "started_attempts": 2,
        "completed_jobs": 2,
        "observed_invocations": 10,
        "complete_calls": 10,
        "failed_calls": 0,
        "unknown_cost_calls": 0,
    }
    if any(accounting.get(key) != value for key, value in expected_accounting.items()):
        raise ValueError("pilot raw accounting does not pass the frozen gate")
    cost = accounting.get("known_cost_usd")
    if not (
        isinstance(cost, (int, float))
        and not isinstance(cost, bool)
        and math.isfinite(cost)
        and 0 <= cost <= PILOT_CEILING_USD
    ):
        raise ValueError("pilot cost is invalid or exceeds its frozen ceiling")
    if (
        not gate.get("passed")
        or gate.get("outcomes_ignored_for_pass") is not True
        or ledger.get("completed_jobs") != 2
        or ledger.get("observed_invocations") != 10
        or ledger.get("failed_calls") != 0
        or ledger.get("incomplete_jobs") != []
        or set(ledger.get("max_attempt_by_job", {}).values()) != {1}
        or structural.get("completed_jobs") != 2
        or structural.get("attempted_calls") != 10
        or structural.get("failed_calls") != 0
        or structural.get("unknown_cost_calls") != 0
    ):
        raise ValueError("pilot raw evidence fails independent structural validation")
    return {
        "accounting": accounting,
        "ledger": ledger,
        "structural": structural,
        "pilot_gate": gate,
    }


def build_pilot_receipt(
    *,
    evidence_raw: bytes,
    terminal_raw: bytes,
    intended_raw: bytes,
    expected_model: str,
    expected_reasoning: str,
    expected_role: str,
    expected_study_id: str,
) -> dict:
    """Rebuild a receipt without consulting the hosted audit or its PASS badge."""
    intended = _load_object(intended_raw, "intended manifest")
    terminal = _load_object(terminal_raw, "pilot terminal")
    expected_intended, contract = _expected_intended(
        model=expected_model,
        reasoning=expected_reasoning,
        study_id=expected_study_id,
    )
    cell = pilot_builder._cell(expected_model, expected_reasoning)
    if expected_role != cell["role"]:
        raise ValueError("expected pilot role differs from the frozen availability role")
    if intended != expected_intended:
        raise ValueError("intended pilot manifest differs from offline regeneration")

    terminal_keys = {
        "schema",
        "model",
        "reasoning",
        "role",
        "study_id",
        "identity",
        "manifest_sha256",
        "protocol_extension_sha256",
        "availability_manifest_sha256",
        "call_settings",
        "source_sha256",
        "job_ids",
        "planned_calls",
        "evidence_sha256",
        "error",
        "transient_waits",
    }
    if set(terminal) != terminal_keys:
        raise ValueError("pilot terminal schema changed")
    expected_terminal = {
        "schema": "chronos.experiment-a-pilot-terminal.v1",
        "model": expected_model,
        "reasoning": expected_reasoning,
        "role": expected_role,
        "study_id": expected_study_id,
        "identity": contract["identity"],
        "manifest_sha256": contract["manifest_sha256"],
        "protocol_extension_sha256": contract["protocol_extension_sha256"],
        "availability_manifest_sha256": contract["availability_manifest_sha256"],
        "call_settings": expected_intended["call_settings"],
        "source_sha256": expected_intended["source_sha256"],
        "job_ids": [job["id"] for job in contract["jobs"]],
        "planned_calls": 10,
        "evidence_sha256": _sha256(evidence_raw),
        "error": None,
        "transient_waits": {"count": 0, "seconds": 0},
    }
    if terminal != expected_terminal:
        raise ValueError("pilot terminal does not bind the exact successful run")

    checked = _raw_revalidation(
        evidence_raw,
        model=expected_model,
        reasoning=expected_reasoning,
        study_id=expected_study_id,
        expected_jobs=contract["jobs"],
        identity=contract["identity"],
    )
    authorization = (
        "matched_non_off_primary_full_cell"
        if expected_role == "matched_non_off_primary"
        else "reasoning_off_sensitivity_full_cell"
    )
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "receipt_sha256": None,
        "disposition": "passed",
        "authorization": authorization,
        "model": expected_model,
        "reasoning": expected_reasoning,
        "role": expected_role,
        "study_id": expected_study_id,
        "identity": contract["identity"],
        "jobs_sha256": contract["manifest_sha256"],
        "availability_manifest_sha256": contract[
            "availability_manifest_sha256"
        ],
        "protocol_extension_sha256": contract["protocol_extension_sha256"],
        "evidence": {
            "sha256": _sha256(evidence_raw),
            "bytes": len(evidence_raw),
            **checked["accounting"],
        },
        "terminal": {
            "sha256": _sha256(terminal_raw),
            "bytes": len(terminal_raw),
        },
        "intended_manifest": {
            "sha256": _sha256(intended_raw),
            "bytes": len(intended_raw),
        },
        "raw_revalidation": {
            "ledger": checked["ledger"],
            "structural": checked["structural"],
            "pilot_gate": checked["pilot_gate"],
        },
        "pilot_excluded_from_confirmation": True,
        "outcomes_examined_for_authorization": False,
    }
    receipt["receipt_sha256"] = _receipt_hash(receipt)
    return receipt


def validate_pilot_receipt(
    *,
    receipt_raw: bytes,
    evidence_raw: bytes,
    terminal_raw: bytes,
    intended_raw: bytes,
    expected_model: str,
    expected_reasoning: str,
    expected_role: str,
    expected_study_id: str,
) -> dict:
    receipt = _load_object(receipt_raw, "pilot receipt")
    if receipt.get("receipt_sha256") != _receipt_hash(receipt):
        raise ValueError("pilot receipt self-hash mismatch")
    rebuilt = build_pilot_receipt(
        evidence_raw=evidence_raw,
        terminal_raw=terminal_raw,
        intended_raw=intended_raw,
        expected_model=expected_model,
        expected_reasoning=expected_reasoning,
        expected_role=expected_role,
        expected_study_id=expected_study_id,
    )
    if receipt != rebuilt:
        raise ValueError("pilot receipt differs from raw-evidence revalidation")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--terminal", type=Path, required=True)
    parser.add_argument("--intended", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning", choices=("none", "minimal", "low"), required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--study-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite receipt: {args.output}")
    receipt = build_pilot_receipt(
        evidence_raw=args.evidence.read_bytes(),
        terminal_raw=args.terminal.read_bytes(),
        intended_raw=args.intended.read_bytes(),
        expected_model=args.model,
        expected_reasoning=args.reasoning,
        expected_role=args.role,
        expected_study_id=args.study_id,
    )
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(f"ISSUED {args.output} {receipt['receipt_sha256']}")


if __name__ == "__main__":
    main()
