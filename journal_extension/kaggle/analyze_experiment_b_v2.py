"""Frozen Experiment B analysis applied to the v2 collection (adds Gemini-minimal and Qwen-low).

``analyze_experiment_b_v1.build_analysis`` runs unchanged; only its collection verifier
is the v2 one. The result discloses the two amendments the new cells ran under.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest import mock

import analyze_experiment_b_v1 as frozen
import verify_experiment_b_collection_v2 as collection

DEFAULT_OUTPUT = frozen.HERE / "round2_analysis/experiment_b_analysis_v2.json"


def build_analysis(collection_path: Path = collection.OUTPUT) -> dict:
    verifier = type("V2", (), {"verify_collection_manifest": staticmethod(collection.verify)})
    with mock.patch.object(frozen, "collection_verifier", verifier):
        result = frozen.build_analysis(collection_path)
    body = {key: value for key, value in result.items() if key != "analysis_sha256"}
    body["schema"] = "chronos.experiment-b-analysis.v2"
    body["amendments"] = {
        "cells": [model for model, _ in collection.study.SETTINGS.values()],
        "procedures": list(collection.AMENDMENTS),
        "disclosure": ("Gemini-minimal and Qwen-low ran after Terra-low and Claude-none, from replacement "
                       "pilots, with provider HTTP 429s waited out below the evidence layer. Qwen-low "
                       "shard 25 failed once on a truncated provider answer and was rerun from scratch "
                       "under a written note; the failed run is excluded from outcomes, and its cost, "
                       "including one call priced only by the quota meter, is listed below."),
        "replaced_runs": [run for cell in collection.verify(collection_path)["cells"]
                          for run in cell.get("replaced_runs", [])],
    }
    return {**body, "analysis_sha256": frozen._canonical_hash(body)}


def verify_analysis_file(path: Path = DEFAULT_OUTPUT) -> dict:
    saved = json.loads(Path(path).read_text())
    if saved != build_analysis():
        raise ValueError("Experiment B v2 analysis differs from fresh sealed raw regeneration")
    return saved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", type=Path, default=collection.OUTPUT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.verify:
        result = verify_analysis_file(args.verify)
    else:
        result = build_analysis(args.collection)
        if args.output:
            args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result["status"], result["analysis_sha256"])


if __name__ == "__main__":
    main()
