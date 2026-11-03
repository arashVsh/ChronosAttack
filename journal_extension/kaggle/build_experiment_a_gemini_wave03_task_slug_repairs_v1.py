"""Build the one-line task-slug repairs for Gemini Experiment A wave 03."""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from pathlib import Path


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"


@dataclass(frozen=True)
class Repair:
    shard: int
    original_sha256: str
    repair_sha256: str

    @property
    def original_task(self) -> str:
        return f"chronos-r2-water4-study-gemini-minimal-s{self.shard}-v1"

    @property
    def repair_task(self) -> str:
        return f"chronos-r2-water4-study-gemini-minimal-s{self.shard}-repair-v1"

    @property
    def original_path(self) -> Path:
        return GENERATED / f"water4_study_gemini_minimal_s{self.shard}_v1.py"

    @property
    def repair_path(self) -> Path:
        return GENERATED / f"water4_study_gemini_minimal_s{self.shard}_repair_v1.py"


REPAIRS = (
    Repair(
        shard=26,
        original_sha256="eb887e0e45c5c2f00842ffd538183c62ceada4bf97ad5247c9acdf870c393806",
        repair_sha256="7f5389a61936386d50d2463e1dcad6f63bb96d4b2a5ed7a560db5f288d8eaa5d",
    ),
    Repair(
        shard=27,
        original_sha256="3c25329b5e091d93239d259ae5177f44a7588d2c43ddf73ac3813369d738ad17",
        repair_sha256="9a3fb38eaa26f6f3d5fead7e14aaea02545ff632de1c95b4212e0d003bfba7a1",
    ),
    Repair(
        shard=28,
        original_sha256="8b5e1bbd7abbd57e23f165c497478799ccb0f3e833b31720fa6b86edf69f93ce",
        repair_sha256="0d9b0a5a5d6d2a29b6b7d6d2eeb39e6010c175635c10d6fa1c06fb7ef1442004",
    ),
    Repair(
        shard=29,
        original_sha256="7bca40299a725afcb1114bd52a31972fa0679397c3a7bea27008a36a54f9e854",
        repair_sha256="f41facd8358a27133602de79296e59f7d3183de034365e11d06b3684d4c882b9",
    ),
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def build(repair: Repair) -> bytes:
    original = repair.original_path.read_bytes()
    if _sha256(original) != repair.original_sha256:
        raise ValueError(f"canonical shard-{repair.shard} source hash changed")
    old = f"@kbench.task(name={repair.original_task!r})".encode()
    new = f"@kbench.task(name={repair.repair_task!r})".encode()
    if original.count(old) != 1 or new in original:
        raise ValueError(f"canonical shard-{repair.shard} task decorator is not unique")
    repaired = original.replace(old, new)
    if repaired.replace(new, old) != original:
        raise ValueError(f"shard-{repair.shard} repair is not exactly reversible")
    if _sha256(repaired) != repair.repair_sha256:
        raise ValueError(f"shard-{repair.shard} repair source hash changed")
    return repaired


def verify(repair: Repair) -> bytes:
    expected = build(repair)
    observed = repair.repair_path.read_bytes()
    if observed != expected:
        raise ValueError(
            f"written shard-{repair.shard} repair differs from deterministic build"
        )
    return observed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    for repair in REPAIRS:
        expected = build(repair)
        if args.write:
            if repair.repair_path.exists() and repair.repair_path.read_bytes() != expected:
                raise ValueError(
                    f"refusing to overwrite a different shard-{repair.shard} repair source"
                )
            repair.repair_path.write_bytes(expected)
            action = "WROTE"
        else:
            verify(repair)
            action = "PASS"
        print(f"{action} {repair.repair_path} {_sha256(expected)}")


if __name__ == "__main__":
    main()
