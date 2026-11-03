"""Build the reversible Claude-none shard-24 task-slug repair."""

from __future__ import annotations

import argparse
import ast
import base64
from pathlib import Path
import zlib


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
ORIGINAL = GENERATED / "water4_study_claude_none_s24_v1.py"
REPAIR = GENERATED / "water4_study_claude_none_s24_repair_v1.py"
WRAPPER = GENERATED / "water4_study_claude_none_s24_repair_transport_v1.py"

ORIGINAL_TASK = "chronos-r2-water4-study-claude-none-s24-v1"
REPAIR_TASK = "chronos-r2-water4-study-claude-none-s24-repair-v1"
ORIGINAL_SHA256 = (
    "125071d068bdadd9ea8949af81a85dc3dd29b9867507a00fd5798e7c76a912e6"
)
REPAIR_SHA256 = (
    "54dc20f1acd4ab61ee206c33ffd68b16598541b0cb88610af2be409d5c03987c"
)


def _sha256(raw: bytes) -> str:
    import hashlib

    return hashlib.sha256(raw).hexdigest()


def build_repair() -> bytes:
    original = ORIGINAL.read_bytes()
    if _sha256(original) != ORIGINAL_SHA256:
        raise ValueError("canonical Claude shard-24 source hash changed")
    old = f"@kbench.task(name={ORIGINAL_TASK!r})".encode()
    new = f"@kbench.task(name={REPAIR_TASK!r})".encode()
    if original.count(old) != 1 or new in original:
        raise ValueError("Claude shard-24 task decorator is not unique")
    repaired = original.replace(old, new)
    if repaired.replace(new, old) != original:
        raise ValueError("Claude shard-24 repair is not exactly reversible")
    if _sha256(repaired) != REPAIR_SHA256:
        raise ValueError("Claude shard-24 repair source hash changed")
    return repaired


def build_source() -> str:
    """Expose the repaired source through the collection recovery interface."""
    return build_repair().decode()


def build_wrapper() -> str:
    repaired = build_repair()
    encoded = base64.b85encode(zlib.compress(repaired, level=9))
    return f'''# Deterministic transport wrapper for the shard-24 task-slug repair.
import base64 as _transport_base64
import hashlib as _transport_hashlib
import zlib as _transport_zlib

if False:
    @task(name={REPAIR_TASK!r})
    def _transport_task_marker(llm):
        pass

_TRANSPORT_PAYLOAD_B85 = {encoded!r}
_TRANSPORT_PAYLOAD_SHA256 = {REPAIR_SHA256!r}
_transport_payload = _transport_zlib.decompress(
    _transport_base64.b85decode(_TRANSPORT_PAYLOAD_B85)
)
if _transport_hashlib.sha256(_transport_payload).hexdigest() != (
    _TRANSPORT_PAYLOAD_SHA256
):
    raise ValueError("Repaired Experiment A payload hash mismatch")
exec(
    compile(_transport_payload, {REPAIR.name!r}, "exec"),
    globals(),
    globals(),
)
'''


def _literal_assignments(source: str) -> dict:
    values = {}
    for node in ast.parse(source, str(WRAPPER)).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    values[target.id] = ast.literal_eval(node.value)
                except (TypeError, ValueError):
                    pass
    return values


def verify_sources() -> tuple[bytes, bytes]:
    repaired = build_repair()
    if REPAIR.read_bytes() != repaired:
        raise ValueError("written Claude shard-24 repair source changed")
    wrapper = WRAPPER.read_bytes()
    expected_wrapper = build_wrapper().encode()
    if wrapper != expected_wrapper:
        raise ValueError("written Claude shard-24 repair wrapper changed")
    values = _literal_assignments(wrapper.decode())
    decoded = zlib.decompress(
        base64.b85decode(values["_TRANSPORT_PAYLOAD_B85"])
    )
    if (
        decoded != repaired
        or values["_TRANSPORT_PAYLOAD_SHA256"] != REPAIR_SHA256
    ):
        raise ValueError("Claude shard-24 wrapper payload changed")
    compile(repaired.decode(), str(REPAIR), "exec")
    compile(wrapper.decode(), str(WRAPPER), "exec")
    return repaired, wrapper


def verify() -> dict:
    repaired, wrapper = verify_sources()
    return {
        "source_sha256": _sha256(repaired),
        "wrapper_sha256": _sha256(wrapper),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    repaired = build_repair()
    wrapper = build_wrapper().encode()
    if args.write:
        for path, raw in ((REPAIR, repaired), (WRAPPER, wrapper)):
            if path.exists() and path.read_bytes() != raw:
                raise ValueError(f"refusing to overwrite different source: {path}")
            path.write_bytes(raw)
            print(f"WROTE {path} {_sha256(raw)}")
    verify_sources()
    print(
        "PASS Claude s24 repair sources: one reversible task-slug change, "
        f"payload {REPAIR_SHA256}"
    )


if __name__ == "__main__":
    main()
