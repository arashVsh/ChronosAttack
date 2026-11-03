"""Offline, read-only verification of an extracted round-two packet."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "MANIFEST.json"


def _safe(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        isinstance(name, str) and name == path.as_posix()
        and not path.is_absolute() and len(path.parts) > 0
        and all(part not in ("", ".", "..") for part in path.parts)
    )


def verify_manifest() -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError("manifest is empty or malformed")
    if any(not _safe(name) or name == "MANIFEST.json" for name in manifest):
        raise ValueError("manifest contains an unsafe path")
    expected = set(manifest) | {"MANIFEST.json"}
    actual = set()
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT).as_posix()
        if path.is_symlink():
            raise ValueError(f"symlink payload: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"non-file payload: {relative}")
        actual.add(relative)
    if actual != expected:
        raise ValueError(f"payload path mismatch: missing={sorted(expected-actual)} extra={sorted(actual-expected)}")
    for name, digest in manifest.items():
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError(f"invalid digest for {name}")
        actual_hash = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        if actual_hash != digest:
            raise ValueError(f"checksum mismatch: {name}")
    return manifest


def commands():
    config = json.loads((ROOT / "PACKAGE.json").read_text(encoding="utf-8"))
    c_collection = config["c_collection"]
    c_report = config["c_report"]
    return [
        ["kaggle/verify_reproduction.py"],
        ["kaggle/verify_round2.py"],
        ["kaggle/analyze_experiment_a.py", "--verify", "kaggle/round2_analysis/experiment_a_analysis_v1.json"],
        ["kaggle/analyze_experiment_b_v1.py", "--verify", "kaggle/round2_analysis/experiment_b_analysis_v1.json"],
        ["kaggle/analyze_experiment_b_v2.py", "--verify", "kaggle/round2_analysis/experiment_b_analysis_v2.json"],
        ["kaggle/analyze_experiment_e_v1.py", "--verify"],
        ["kaggle/verify_experiment_c_collection_v4.py", "--output", c_collection],
        ["kaggle/report_experiment_c_collection_v1.py", "--collection", c_collection, "--verify", c_report],
    ]


def verify_replay() -> None:
    env = dict(os.environ, PYTHONPATH=str(ROOT / "kaggle"), PYTHONDONTWRITEBYTECODE="1")
    for arguments in commands():
        subprocess.run([sys.executable, *arguments], cwd=ROOT, env=env, check=True)


def main() -> None:
    try:
        manifest = verify_manifest()
        verify_replay()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"PACKET VERIFICATION FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"PACKET VERIFIED: {len(manifest)} payload hashes and all offline raw replay gates")


if __name__ == "__main__":
    main()
