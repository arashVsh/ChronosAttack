"""Offline gate for the frozen Terra shard-00 attempt-extension task."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import build_attempt_extension_v1 as builder


GENERATED = (
    Path(__file__).resolve().parent
    / "round2_generated/terra_attempt_extension_s00_v1.py"
)


def verify(generated: bytes | None = None) -> dict:
    planned = builder.plan_repair()
    expected = builder.build_source().encode("utf-8")
    actual = GENERATED.read_bytes() if generated is None else generated
    if actual != expected:
        raise ValueError("generated repair task is not the exact builder output")
    compile(actual.decode("utf-8"), str(GENERATED), "exec")
    contract = planned["contract"]
    return {
        "schema": "chronos.attempt-extension-verification.v1",
        "generated_path": str(GENERATED.relative_to(builder.ROOT)),
        "generated_bytes": len(actual),
        "generated_sha256": hashlib.sha256(actual).hexdigest(),
        "manifest_sha256": contract["attempt_extension_manifest_sha256"],
        "parent_sha256": contract["parent_ledger_sha256"],
        "parent_bytes": contract["parent_ledger_bytes"],
        "completed_jobs": contract["parent_ledger_audit"]["completed_jobs"],
        "authorized_next_attempt": contract["parent_ledger_audit"][
            "authorized_next_attempt"
        ],
        "job_count": contract["job_count"],
        "planned_calls": contract["planned_calls"],
        "incremental_ceiling_usd": contract["incremental_ceiling_usd"],
        "effective_ceiling_usd": contract["effective_ceiling_usd"],
        "receipts_revalidated": True,
        "byte_regeneration_passed": True,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
