"""C collection replay composing the Gemini s06 chain with the Qwen s02 resume.

The Gemini s03 platform bridge and the Gemini s06 reconciled resume keep their
exact scopes. The only addition is routing the pinned Qwen s02 task-v2 resume
to its separately tested reconciled replay (``verify_experiment_c_collection_v2``).
Every other run still goes through the ordinary strict verifier.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest import mock

import verify_experiment_c_collection_v1 as v1
import verify_experiment_c_collection_v2 as qwen_layer
import verify_experiment_c_gemini_s03_platform_bridge_v1 as bridge
import verify_experiment_c_gemini_s06_resume_collection_v1 as gemini_layer


SCHEMA = "chronos.experiment-c-collection-gemini-s06-qwen-s02-reconciled.v1"
_ORDINARY_VERIFY = gemini_layer._ORDINARY_VERIFY


def _ordinary_or_qwen(run: dict, task: dict, staged: dict,
                      *, require_claims: bool = True) -> dict:
    if qwen_layer._special(run, task):
        return qwen_layer._verify_reconciled_run(
            run, task, staged, require_claims=require_claims)
    return _ORDINARY_VERIFY(run, task, staged, require_claims=require_claims)


def build(run_specs_path: Path) -> dict:
    with mock.patch.object(gemini_layer, "_ORDINARY_VERIFY",
                           side_effect=_ordinary_or_qwen):
        composed = gemini_layer.build(run_specs_path)
    body = {key: value for key, value in composed.items()
            if key != "collection_sha256"}
    body["schema"] = SCHEMA
    body["qwen_s02_reconciled_resume"] = {
        "schema": "chronos.experiment-c-qwen-s02-reconciled-resume.v1",
        "task": qwen_layer.repair.TASK,
        "parent_raw_sha256": qwen_layer.view.PARENT_SHA256,
    }
    return {**body, "collection_sha256": v1._digest(body)}


def verify(path: Path) -> dict:
    saved = json.loads(path.read_text())
    provenance = saved.get("provenance_bridge") or {}
    specs_path = bridge.ROOT / provenance.get("run_specs_path", "")
    if not specs_path.is_file():
        raise ValueError("C composed collection run specs are missing")
    rebuilt = build(specs_path)
    if saved != rebuilt:
        raise ValueError("C composed collection differs from raw replay")
    return rebuilt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-specs", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.run_specs is None:
        result = verify(args.output)
    else:
        result = build(args.run_specs)
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
            handle.write("\n")
    print(args.output, result["collection_sha256"])


if __name__ == "__main__":
    main()
