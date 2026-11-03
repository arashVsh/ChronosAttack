"""Build the one-line task-slug repair for Gemini Experiment A shard 11."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
ORIGINAL = GENERATED / "water4_study_gemini_minimal_s11_v1.py"
REPAIR = GENERATED / "water4_study_gemini_minimal_s11_repair_v1.py"

ORIGINAL_TASK = "chronos-r2-water4-study-gemini-minimal-s11-v1"
REPAIR_TASK = "chronos-r2-water4-study-gemini-minimal-s11-repair-v1"
ORIGINAL_SHA256 = (
    "fa564ba2bc8d3ce20cfd2e68dadaa612ff487cbe5e3f15f7651d14478d473cdd"
)
REPAIR_SHA256 = (
    "22b513ecd26c0f1e1e0c4f7fe51d02986ace2e22e2b75295e9e8f145f3934448"
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def build() -> bytes:
    original = ORIGINAL.read_bytes()
    if _sha256(original) != ORIGINAL_SHA256:
        raise ValueError("canonical shard-11 source hash changed")
    old = f"@kbench.task(name={ORIGINAL_TASK!r})".encode()
    new = f"@kbench.task(name={REPAIR_TASK!r})".encode()
    if original.count(old) != 1 or new in original:
        raise ValueError("canonical shard-11 task decorator is not unique")
    repaired = original.replace(old, new)
    if repaired.replace(new, old) != original:
        raise ValueError("repair is not exactly reversible")
    if _sha256(repaired) != REPAIR_SHA256:
        raise ValueError("repair source hash changed")
    return repaired


def verify() -> bytes:
    expected = build()
    observed = REPAIR.read_bytes()
    if observed != expected:
        raise ValueError("written repair source differs from deterministic build")
    return observed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    expected = build()
    if args.write:
        if REPAIR.exists() and REPAIR.read_bytes() != expected:
            raise ValueError("refusing to overwrite a different repair source")
        REPAIR.write_bytes(expected)
        print(f"WROTE {REPAIR} {_sha256(expected)}")
    else:
        verify()
        print(f"PASS {REPAIR} {_sha256(expected)}")


if __name__ == "__main__":
    main()
