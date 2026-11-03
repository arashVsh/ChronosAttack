"""Narrow no-call bridge for Kaggle's Gemini s03 v2 metadata version lag.

The downloaded run/task/ATIF artifacts say task version 1, although the
signed-in ListBenchmarkTaskRuns response binds this exact run to task version
2. Nothing on disk is rewritten. This verifier preserves every original
artifact hash and changes only the in-memory version claim after checking the
full browser response, the original run-ID download path, and all metadata.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from unittest import mock

import verify_experiment_c_collection_v1 as base


ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "chronos.experiment-c-collection-platform-bridge.v1"
TASK = "chronos-r2-tree4-c-gemini-minimal-s03-v1"
MODEL = "google/gemini-3.6-flash"
RUN_ID = 2920589
CANONICAL = ("kaggle/round2_runs_20260920/experiment_c_study/gemini-minimal/"
             f"{TASK}/2")
SOURCE = "kaggle/round2_generated/tree4_c_gemini_minimal_s03_v1_resume_e8d53ac3d3b16956.py"
SOURCE_SHA = "81f0743046d3c6d2cccb636873287bd836d59064ba55fb0fe94beee2d01bd18c"
API_PATH = "kaggle/round2_generated/experiment_c_gemini_s03_v2_browser_list_runs_raw_20260924_v1.json"
API_SHA = "52733f7b11143ac1fad2271157f2b965147851a4fac45020e639cf55707dba3a"
ORIGINAL_DOWNLOAD = f"{CANONICAL}/{TASK}/2/gemini-3.6-flash/{RUN_ID}"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _browser_run(raw: bytes) -> dict:
    if raw.endswith(b"\n"):
        raw = raw[:-1]
    if _sha(raw) != API_SHA:
        raise ValueError("C browser run response hash changed")
    response = json.loads(raw)
    if (set(response) != {"benchmarkTaskRuns", "totalResults"}
            or response["totalResults"] != 1
            or len(response["benchmarkTaskRuns"]) != 1):
        raise ValueError("C browser run response roster changed")
    run = response["benchmarkTaskRuns"][0]
    version = run.get("taskVersion") or {}
    model = run.get("modelVersion") or {}
    source = (ROOT / SOURCE).read_bytes()
    if (_sha(source) != SOURCE_SHA
            or run.get("id") != RUN_ID
            or version.get("id") != 789438
            or version.get("taskId") != 306527
            or version.get("versionNumber") != 2
            or version.get("name") != TASK
            or version.get("definition") != base._hosted_definition(source.decode())
            or version.get("sourceKernelId") != 135642823
            or version.get("sourceKernelSessionId") != 352379643
            or run.get("outputKernelSessionId") != 352379643
            or model.get("modelProxySlug") != MODEL
            or run.get("state") != "BENCHMARK_TASK_RUN_STATE_COMPLETED"
            or len(run.get("results", [])) != 1
            or run["results"][0].get("booleanResult") is not True):
        raise ValueError("C browser run is not the exact authorized v2 run")
    return run


def _download_digest() -> str:
    original = ROOT / ORIGINAL_DOWNLOAD
    canonical = ROOT / CANONICAL
    files = sorted(path for path in original.rglob("*") if path.is_file())
    if len(files) < 10:
        raise ValueError("C original run-ID download is incomplete")
    manifest = []
    for path in files:
        relative = path.relative_to(original)
        copied = canonical / relative
        if not copied.is_file() or copied.read_bytes() != path.read_bytes():
            raise ValueError("C canonical run differs from original run-ID download")
        manifest.append((relative.as_posix(), _sha(path.read_bytes())))
    return base._digest(manifest)


@contextmanager
def _bridge():
    run = _browser_run((ROOT / API_PATH).read_bytes())
    download_digest = _download_digest()
    original_pin, original_platform = base._pin_run, base._platform

    def pin(run_root, source_path, task, parent_ledger_path=None):
        pinned = original_pin(run_root, source_path, task, parent_ledger_path)
        if pinned["run_root"] == CANONICAL:
            if (pinned["task_name"] != TASK or pinned["shard_index"] != 3
                    or pinned["artifacts"]["frozen_source"]["path"] != SOURCE
                    or pinned["task_version"] != 1):
                raise ValueError("C platform bridge target differs")
            pinned["task_version"] = 2
        return pinned

    def platform(record, paths, source, model):
        if record.get("run_root") != CANONICAL:
            return original_platform(record, paths, source, model)
        if (record.get("task_version") != 2 or record.get("task_name") != TASK
                or model != MODEL or _sha(source.encode()) != SOURCE_SHA):
            raise ValueError("C platform bridge scope differs")
        # The unmodified verifier must accept every downloaded field at its
        # literal version-1 value before the browser version-2 claim is joined.
        locally_checked = original_platform(
            {**record, "task_version": 1}, paths, source, model)
        if (locally_checked["task_version"] != 1
                or locally_checked["start_time"] != run["startTime"]
                or locally_checked["end_time"] != run["endTime"]):
            raise ValueError("C browser and downloaded execution disagree")
        return {**locally_checked, "task_version": 2}

    with mock.patch.object(base, "_pin_run", side_effect=pin), mock.patch.object(
            base, "_platform", side_effect=platform):
        yield download_digest


def build(run_specs_path: Path) -> dict:
    specs_bytes = run_specs_path.read_bytes()
    specs = json.loads(specs_bytes)
    with _bridge() as download_digest:
        original = base.build_manifest_from_runs(specs)
    body = {key: value for key, value in original.items() if key != "collection_sha256"}
    body["schema"] = SCHEMA
    body["provenance_bridge"] = {
        "schema": "chronos.experiment-c-gemini-s03-platform-bridge.v1",
        "task": TASK, "run_id": RUN_ID,
        "downloaded_task_version": 1, "browser_task_version": 2,
        "source_path": SOURCE, "source_sha256": SOURCE_SHA,
        "browser_response_path": API_PATH, "browser_response_sha256": API_SHA,
        "original_download_root": ORIGINAL_DOWNLOAD,
        "original_download_digest": download_digest,
        "run_specs_path": str(run_specs_path.resolve().relative_to(ROOT)),
        "run_specs_sha256": _sha(specs_bytes),
    }
    return {**body, "collection_sha256": base._digest(body)}


def verify(path: Path) -> dict:
    recorded = json.loads(path.read_text())
    bridge = recorded.get("provenance_bridge") or {}
    specs_path = ROOT / bridge.get("run_specs_path", "")
    if (not specs_path.is_file()
            or _sha(specs_path.read_bytes()) != bridge.get("run_specs_sha256")):
        raise ValueError("C platform-bridge run specs changed")
    rebuilt = build(specs_path)
    if recorded != rebuilt:
        raise ValueError("C platform-bridge collection differs from raw replay")
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
