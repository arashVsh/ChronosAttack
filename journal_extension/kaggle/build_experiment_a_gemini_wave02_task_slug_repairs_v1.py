"""Build the one-line task-slug repairs for Gemini Experiment A wave 02."""

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
        shard=18,
        original_sha256="ba975c8b240af6375c508c8241c30813a697e593688651c4f94de38863e3d543",
        repair_sha256="3df89124f03ae978e83a5c1b2790ac7b226011582ba36e2a8a85d34aae29ee3c",
    ),
    Repair(
        shard=20,
        original_sha256="d6eb200c54bc0152f471e699312814e3d9e900281f99c7c839c4a73313c5ccbb",
        repair_sha256="544273ce2d6b676ab489473da792876e1ac0031c0a6542a821adfa3bc7e4249a",
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
