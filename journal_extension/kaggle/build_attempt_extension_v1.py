"""Build the one authorized Terra shard-00 attempt-extension task."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import audit_four_observation_attempt_extension_v1 as amended_audit
import build_hosted_cell_v2 as hosted_builder
import four_observation_protocol as protocol
from round2_attempt_extension_v1 import validate_extended_resume_ledger
from round2_hosted import manifest_digest, parse_jsonl_bytes, select_shard


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MODEL = "openai/gpt-5.6-terra"
REASONING = "low"
STUDY_ID = "chronos_round2_terra_reasoning_study_low_v1"
AUTHORIZED_JOB_ID = f"{STUDY_ID}|study|{MODEL}|tree4|stateful|natural|7"
TASK_NAME = "chronos-r2-terra-study-low-s00-repair-v1"
OUTPUT_FOLDER = "round2_terra_reasoning_study_low_s00_repair_v1"
SHARD_INDEX = 0
SHARD_COUNT = 10
INCREMENTAL_CEILING_USD = 0.95
MAX_WAIT_SECONDS = 7200
MANIFEST_PATH = HERE / "attempt_extension_manifest_v1.json"

PARENT_PATH = (
    HERE
    / "round2_runs_20260920/terra_study_s00"
    / "chronos-r2-terra-study-low-s00-v1/1/gpt-5.6-terra/2648723"
    / "round2_terra_reasoning_study_low_s00_v1/openai_gpt-5.6-terra.jsonl"
)
MINIMAL_ROOT = (
    HERE
    / "round2_runs_20260920/terra_minimal"
    / "chronos-r2-terra-preflight-minimal-v1/1/gpt-5.6-terra/2644337"
    / "round2_terra_reasoning_preflight_minimal_v1"
)
LOW_ROOT = (
    HERE
    / "round2_runs_20260920/terra_low"
    / "chronos-r2-terra-preflight-low-v1/1/gpt-5.6-terra/2646426"
    / "round2_terra_reasoning_preflight_low_v1"
)
AMENDMENT_PATH = (
    ROOT
    / "specs/journal-extension-sep14"
    / "round2-attempt-extension-amendment-2026-09-20.md"
)

SOURCE_PATHS = (
    "kaggle/completion_protocol.py",
    "kaggle/four_observation_protocol.py",
    "kaggle/four_observation_defenses.py",
    "kaggle/audit_four_observation.py",
    "kaggle/audit_round2_defense.py",
    "kaggle/round2_hosted.py",
    "kaggle/reasoning_preflight_v1.py",
    "kaggle/capture_benchmark_quota_v1.py",
    "kaggle/build_hosted_cell_v2.py",
    "kaggle/round2_attempt_extension_v1.py",
    "kaggle/audit_four_observation_attempt_extension_v1.py",
    "kaggle/build_attempt_extension_v1.py",
    "kaggle/round2_manifest_v1.json",
)
ARTIFACT_PATHS = (
    str(AMENDMENT_PATH.relative_to(ROOT)),
    str(PARENT_PATH.relative_to(ROOT)),
    str((MINIMAL_ROOT / "openai_gpt-5.6-terra.jsonl").relative_to(ROOT)),
    str((MINIMAL_ROOT / "reasoning_terminal.json").relative_to(ROOT)),
    str((MINIMAL_ROOT / "reasoning_receipt.json").relative_to(ROOT)),
    str((MINIMAL_ROOT / "quota_attestation_1.json").relative_to(ROOT)),
    str((LOW_ROOT / "openai_gpt-5.6-terra.jsonl").relative_to(ROOT)),
    str((LOW_ROOT / "reasoning_terminal.json").relative_to(ROOT)),
    str((LOW_ROOT / "reasoning_receipt.json").relative_to(ROOT)),
)
PINNED_PATHS = SOURCE_PATHS + ARTIFACT_PATHS


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_hash(body: dict) -> str:
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _load_manifest(value: dict | None = None) -> tuple[dict, bytes]:
    raw = MANIFEST_PATH.read_bytes() if value is None else json.dumps(
        value, indent=2, sort_keys=True
    ).encode("utf-8")
    manifest = json.loads(raw)
    claimed = manifest.pop("manifest_sha256", None)
    if claimed != _canonical_hash(manifest):
        raise ValueError("attempt-extension manifest self-hash mismatch")
    manifest["manifest_sha256"] = claimed
    return manifest, raw


def _read_blobs() -> dict[str, bytes]:
    return {path: (ROOT / path).read_bytes() for path in PINNED_PATHS}


def _validate_manifest(manifest: dict, blobs: dict[str, bytes]) -> None:
    expected_contract = {
        "schema": "chronos.attempt-extension-manifest.v1",
        "model": MODEL,
        "reasoning": REASONING,
        "study_id": STUDY_ID,
        "task_name": TASK_NAME,
        "output_folder": OUTPUT_FOLDER,
        "shard_index": SHARD_INDEX,
        "shard_count": SHARD_COUNT,
        "authorized_job_id": AUTHORIZED_JOB_ID,
        "original_max_attempts": 3,
        "extended_max_attempts": 6,
        "incremental_ceiling_usd": INCREMENTAL_CEILING_USD,
        "max_wait_seconds": MAX_WAIT_SECONDS,
    }
    for key, expected in expected_contract.items():
        if manifest.get(key) != expected:
            raise ValueError(f"attempt-extension manifest changed {key}")
    pinned = manifest.get("pinned_sha256")
    if not isinstance(pinned, dict) or set(pinned) != set(PINNED_PATHS):
        raise ValueError("attempt-extension manifest has the wrong pinned input set")
    if set(blobs) != set(PINNED_PATHS):
        raise ValueError("attempt-extension builder has the wrong input set")
    for path, data in blobs.items():
        if _digest(data) != pinned[path]:
            raise ValueError(f"attempt-extension pinned hash mismatch: {path}")


def _load_receipts() -> tuple[dict, dict]:
    minimal = hosted_builder._load_receipt_bundle(
        receipt_path=MINIMAL_ROOT / "reasoning_receipt.json",
        evidence_path=MINIMAL_ROOT / "openai_gpt-5.6-terra.jsonl",
        terminal_path=MINIMAL_ROOT / "reasoning_terminal.json",
        model=MODEL,
        reasoning="minimal",
        disposition="minimal_unsupported",
        label="minimal-unsupported",
        quota_attestation_path=MINIMAL_ROOT / "quota_attestation_1.json",
    )
    accepted = hosted_builder._load_receipt_bundle(
        receipt_path=LOW_ROOT / "reasoning_receipt.json",
        evidence_path=LOW_ROOT / "openai_gpt-5.6-terra.jsonl",
        terminal_path=LOW_ROOT / "reasoning_terminal.json",
        model=MODEL,
        reasoning=REASONING,
        disposition="passed",
        label="passed preflight",
    )
    if accepted["minimal_unsupported_receipt_sha256"] != minimal["receipt_sha256"]:
        raise ValueError("Terra preflight receipts do not form the frozen chain")
    return minimal, accepted


def plan_repair(
    *, parent: bytes | None = None, manifest_value: dict | None = None
) -> dict:
    """Revalidate every authorization input without making a provider call."""
    manifest, manifest_raw = _load_manifest(manifest_value)
    blobs = _read_blobs()
    if parent is not None:
        blobs[str(PARENT_PATH.relative_to(ROOT))] = parent
    _validate_manifest(manifest, blobs)
    minimal, accepted = _load_receipts()
    parent_bytes = blobs[str(PARENT_PATH.relative_to(ROOT))]
    if not parent_bytes.endswith(b"\n"):
        raise ValueError("parent ledger is not append safe")

    old_models = protocol.engine.MODELS
    old_study_id = protocol.engine.STUDY_ID
    old_settings = protocol.engine.CALL_SETTINGS
    try:
        protocol.engine.MODELS = tuple(dict.fromkeys((*old_models, MODEL)))
        protocol.engine.STUDY_ID = STUDY_ID
        protocol.engine.CALL_SETTINGS = dict(old_settings, reasoning=REASONING)
        jobs = select_shard(
            protocol.jobs_for(MODEL, "study"),
            shard_index=SHARD_INDEX,
            shard_count=SHARD_COUNT,
        )
        fixtures = protocol.fixtures()
        identity = protocol.engine.digest(
            json.dumps(
                {
                    "study": STUDY_ID,
                    "model": MODEL,
                    "fixtures": fixtures,
                    "settings": protocol.engine.CALL_SETTINGS,
                },
                sort_keys=True,
            )
        )
        events = parse_jsonl_bytes(parent_bytes, label="attempt-extension parent")
        ledger = validate_extended_resume_ledger(
            events,
            model=MODEL,
            identity=identity,
            expected_jobs={job["id"]: job for job in jobs},
            authorized_job_id=AUTHORIZED_JOB_ID,
            structural_audit=lambda values: amended_audit.audit(
                values,
                MODEL,
                "study",
                authorized_job_id=AUTHORIZED_JOB_ID,
                require_complete=False,
            ),
        )
        protocol_hash = fixtures["tree4"]["extension_sha256"]
        settings = dict(protocol.engine.CALL_SETTINGS)
    finally:
        protocol.engine.MODELS = old_models
        protocol.engine.STUDY_ID = old_study_id
        protocol.engine.CALL_SETTINGS = old_settings

    if ledger["authorized_next_attempt"] != 4:
        raise ValueError("exact parent does not authorize attempt 4")
    if ledger["completed_jobs"] != 35 or ledger["observed_invocations"] != 119:
        raise ValueError("exact parent completion/accounting topology changed")
    if ledger["failed_calls"] != 4 or ledger["known_cost_usd"] != 0.338884:
        raise ValueError("exact parent failure/cost accounting changed")
    if len(jobs) != 69 or sum(job["calls"] for job in jobs) != 217:
        raise ValueError("exact shard manifest changed")

    contract = {
        "schema": "chronos.attempt-extension-cell.v1",
        "model": MODEL,
        "reasoning": REASONING,
        "study_id": STUDY_ID,
        "task_name": TASK_NAME,
        "output_folder": OUTPUT_FOLDER,
        "shard_index": SHARD_INDEX,
        "shard_count": SHARD_COUNT,
        "job_count": len(jobs),
        "planned_calls": sum(job["calls"] for job in jobs),
        "jobs_sha256": manifest_digest(jobs),
        "identity": identity,
        "protocol_extension_sha256": protocol_hash,
        "authorized_job_id": AUTHORIZED_JOB_ID,
        "original_max_attempts": 3,
        "extended_max_attempts": 6,
        "incremental_ceiling_usd": INCREMENTAL_CEILING_USD,
        "effective_ceiling_usd": ledger["known_cost_usd"]
        + INCREMENTAL_CEILING_USD,
        "max_wait_seconds": MAX_WAIT_SECONDS,
        "call_settings": {**settings, "sdk_max_retries": 0},
        "parent_ledger_sha256": _digest(parent_bytes),
        "parent_ledger_bytes": len(parent_bytes),
        "parent_ledger_audit": ledger,
        "attempt_extension_manifest_sha256": manifest["manifest_sha256"],
        "accepted_preflight_receipt_sha256": accepted["receipt_sha256"],
        "minimal_unsupported_receipt_sha256": minimal["receipt_sha256"],
        "pinned_sha256": manifest["pinned_sha256"],
    }
    return {
        "contract": contract,
        "jobs": jobs,
        "parent": parent_bytes,
        "blobs": blobs,
        "manifest": manifest,
        "manifest_raw": manifest_raw,
    }


RUNTIME_PART_1 = r'''
import hashlib
import json
import sys
import time
from pathlib import Path

import kaggle_benchmarks as kbench


def canonical_hash(body):
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


manifest_body = {
    key: value
    for key, value in REPAIR_MANIFEST.items()
    if key != "manifest_sha256"
}
if canonical_hash(manifest_body) != REPAIR_MANIFEST.get("manifest_sha256"):
    raise ValueError("Embedded attempt-extension manifest self-hash mismatch")
if REPAIR_MANIFEST["manifest_sha256"] != CONTRACT["attempt_extension_manifest_sha256"]:
    raise ValueError("Runtime attempt-extension manifest differs from the contract")
if set(BLOBS) != set(CONTRACT["pinned_sha256"]):
    raise ValueError("Runtime pinned input set changed")
for path, expected in CONTRACT["pinned_sha256"].items():
    if hashlib.sha256(BLOBS[path]).hexdigest() != expected:
        raise ValueError("Runtime pinned input hash mismatch: " + path)
for key in (
    "model", "reasoning", "study_id", "task_name", "output_folder",
    "shard_index", "shard_count", "authorized_job_id",
    "original_max_attempts", "extended_max_attempts",
    "incremental_ceiling_usd", "max_wait_seconds",
):
    if REPAIR_MANIFEST[key] != CONTRACT[key]:
        raise ValueError("Runtime amendment contract changed: " + key)
if hashlib.sha256(PARENT_LEDGER).hexdigest() != CONTRACT["parent_ledger_sha256"]:
    raise ValueError("Runtime parent hash mismatch")
if len(PARENT_LEDGER) != CONTRACT["parent_ledger_bytes"]:
    raise ValueError("Runtime parent byte count mismatch")
if not PARENT_LEDGER.endswith(b"\n"):
    raise ValueError("Runtime parent is not append safe")

source_root = Path("/kaggle/working") / (CONTRACT["output_folder"] + "_source")
source_root.mkdir(parents=True, exist_ok=False)
for repo_path, filename in MODULE_PATHS.items():
    (source_root / filename).write_bytes(BLOBS[repo_path])
sys.path.insert(0, str(source_root))

import build_hosted_cell_v2 as receipt_gate


def json_blob(path):
    value = json.loads(BLOBS[path])
    if not isinstance(value, dict):
        raise ValueError("Embedded JSON artifact is not an object: " + path)
    return value


minimal_terminal_raw = BLOBS[ARTIFACTS["minimal_terminal"]]
minimal_receipt = receipt_gate.validate_preflight_receipt(
    json_blob(ARTIFACTS["minimal_receipt"]),
    BLOBS[ARTIFACTS["minimal_evidence"]],
    json.loads(minimal_terminal_raw),
    model=CONTRACT["model"],
    reasoning="minimal",
    disposition="minimal_unsupported",
    quota_attestation=json_blob(ARTIFACTS["minimal_quota"]),
    terminal_raw=minimal_terminal_raw,
)
accepted_terminal_raw = BLOBS[ARTIFACTS["accepted_terminal"]]
accepted_receipt = receipt_gate.validate_preflight_receipt(
    json_blob(ARTIFACTS["accepted_receipt"]),
    BLOBS[ARTIFACTS["accepted_evidence"]],
    json.loads(accepted_terminal_raw),
    model=CONTRACT["model"],
    reasoning=CONTRACT["reasoning"],
    disposition="passed",
    terminal_raw=accepted_terminal_raw,
)
if minimal_receipt["receipt_sha256"] != CONTRACT["minimal_unsupported_receipt_sha256"]:
    raise ValueError("Runtime minimal receipt hash changed")
if accepted_receipt["receipt_sha256"] != CONTRACT["accepted_preflight_receipt_sha256"]:
    raise ValueError("Runtime accepted receipt hash changed")
if accepted_receipt["minimal_unsupported_receipt_sha256"] != minimal_receipt["receipt_sha256"]:
    raise ValueError("Runtime Terra receipt chain is broken")
'''


RUNTIME_PART_2 = r'''
import audit_four_observation_attempt_extension_v1 as amended_audit
import four_observation_protocol as cell
import round2_attempt_extension_v1 as extension
import round2_hosted as hosted

MODEL = CONTRACT["model"]
cell.engine.MODELS = tuple(dict.fromkeys((*cell.engine.MODELS, MODEL)))
cell.engine.STUDY_ID = CONTRACT["study_id"]
cell.engine.CALL_SETTINGS = dict(
    cell.engine.CALL_SETTINGS, reasoning=CONTRACT["reasoning"]
)
jobs = hosted.select_shard(
    cell.jobs_for(MODEL, "study"),
    shard_index=CONTRACT["shard_index"],
    shard_count=CONTRACT["shard_count"],
)
fixtures = cell.fixtures()
expected_settings = {
    key: value
    for key, value in CONTRACT["call_settings"].items()
    if key != "sdk_max_retries"
}
if cell.engine.CALL_SETTINGS != expected_settings:
    raise ValueError("Runtime call settings differ from the frozen repair")
if jobs != EXPECTED_JOBS or hosted.manifest_digest(jobs) != CONTRACT["jobs_sha256"]:
    raise ValueError("Runtime shard differs from the frozen repair")
identity = cell.engine.digest(
    json.dumps(
        {
            "study": CONTRACT["study_id"],
            "model": MODEL,
            "fixtures": fixtures,
            "settings": cell.engine.CALL_SETTINGS,
        },
        sort_keys=True,
    )
)
if identity != CONTRACT["identity"]:
    raise ValueError("Runtime identity differs from the frozen repair")
if fixtures["tree4"]["extension_sha256"] != CONTRACT["protocol_extension_sha256"]:
    raise ValueError("Runtime protocol extension hash changed")


def structural_audit(events):
    return amended_audit.audit(
        events, MODEL, "study",
        authorized_job_id=CONTRACT["authorized_job_id"],
        require_complete=False,
    )


parent_events = hosted.parse_jsonl_bytes(
    PARENT_LEDGER, label="attempt-extension parent"
)
parent_audit = extension.validate_extended_resume_ledger(
    parent_events,
    model=MODEL,
    identity=identity,
    expected_jobs={job["id"]: job for job in jobs},
    authorized_job_id=CONTRACT["authorized_job_id"],
    structural_audit=structural_audit,
)
if parent_audit != CONTRACT["parent_ledger_audit"]:
    raise ValueError("Runtime parent audit changed")
if parent_audit["authorized_next_attempt"] != 4:
    raise ValueError("Runtime parent does not authorize attempt 4")
if CONTRACT["effective_ceiling_usd"] != (
    parent_audit["known_cost_usd"] + CONTRACT["incremental_ceiling_usd"]
):
    raise ValueError("Runtime effective ceiling changed")

output = Path("/kaggle/working") / CONTRACT["output_folder"]
output.mkdir(parents=True, exist_ok=False)
intended = dict(CONTRACT, jobs=jobs, parent_audit=parent_audit)
(output / "intended_manifest.json").write_text(
    json.dumps(intended, indent=2, sort_keys=True)
)
evidence_path = output / (MODEL.replace("/", "_") + ".jsonl")
with evidence_path.open("xb") as stream:
    stream.write(PARENT_LEDGER)

TRANSIENT = (
    "RateLimitError", "InternalServerError", "APIConnectionError", "APITimeoutError",
)
WAITS = {"count": 0, "seconds": 0}
'''


RUNTIME_PART_3 = r'''
@kbench.task(name="chronos-r2-terra-study-low-s00-repair-v1")
def hosted_cell(llm):
    if llm.model != MODEL:
        raise ValueError("Unexpected selected model")
    llm.client = llm.client.with_options(max_retries=0)
    original_respond = llm.respond

    def respond(**kwargs):
        waited, delay = 0, 20
        while True:
            try:
                return original_respond(**kwargs)
            except Exception as error:
                if type(error).__name__ not in TRANSIENT:
                    raise
                remaining = CONTRACT["max_wait_seconds"] - waited
                if remaining <= 0:
                    raise
                pause = min(delay, remaining)
                print(
                    "TRANSIENT", type(error).__name__, "waiting", pause,
                    "s (total", waited, "s)", flush=True,
                )
                time.sleep(pause)
                waited += pause
                WAITS["count"] += 1
                WAITS["seconds"] += pause
                delay = min(delay * 2, 300)

    llm.respond = respond

    def error_metadata(error):
        response = getattr(error, "response", None)
        body = getattr(error, "body", None)
        if not isinstance(body, dict):
            body = {}
        return {
            "type": type(error).__name__,
            "status_code": getattr(error, "status_code", None)
            or getattr(response, "status_code", None),
            "code": getattr(error, "code", None) or body.get("code"),
            "param": getattr(error, "param", None) or body.get("param"),
            "message": str(error)[:2000],
        }

    exhausted, stopped, terminal_error = False, None, None
    try:
        extension.run_jobs(
            cell.engine, kbench, llm, fixtures, jobs, output,
            CONTRACT["effective_ceiling_usd"],
            authorized_job_id=CONTRACT["authorized_job_id"],
        )
    except RuntimeError as error:
        terminal_error = error_metadata(error)
        if str(error) == "Cost ceiling reached; checkpoint retained":
            exhausted = True
        else:
            stopped = repr(error)
    except Exception as error:
        terminal_error = error_metadata(error)
        stopped = repr(error)

    raw_bytes = evidence_path.read_bytes() if evidence_path.exists() else b""
    prefix_ok = raw_bytes.startswith(PARENT_LEDGER)
    suffix = raw_bytes[len(PARENT_LEDGER):] if prefix_ok else b""
    events, parse_failures = hosted.parse_jsonl_best_effort(raw_bytes)
    suffix_events, suffix_parse_failures = hosted.parse_jsonl_best_effort(suffix)
    raw_accounting = hosted.raw_event_summary(
        events, invalid_json_lines=len(parse_failures)
    )
    suffix_accounting = hosted.raw_event_summary(
        suffix_events, invalid_json_lines=len(suffix_parse_failures)
    )
    evidence_sha256 = hashlib.sha256(raw_bytes).hexdigest()
'''


RUNTIME_PART_4 = r'''
    try:
        if not prefix_ok:
            raise ValueError("Final ledger does not preserve the parent byte prefix")
        if parse_failures or suffix_parse_failures:
            raise ValueError("Final ledger contains invalid JSON lines")
        ledger = extension.validate_extended_resume_ledger(
            events,
            model=MODEL,
            identity=identity,
            expected_jobs={job["id"]: job for job in jobs},
            authorized_job_id=CONTRACT["authorized_job_id"],
            structural_audit=structural_audit,
        )
        structural = structural_audit(events)
        subset = hosted.subset_summary(events, {job["id"] for job in jobs})
        checked = dict(
            CONTRACT,
            passed=bool(
                ledger["completed_jobs"] == CONTRACT["job_count"]
                and subset["complete"]
                and structural["complete"]
                and not exhausted
                and not stopped
            ),
            ledger_audit=ledger,
            structural_audit=structural,
            subset=subset,
            allocation_exhausted=exhausted,
            stopped_early=stopped,
            terminal_error=terminal_error,
            transient_waits=dict(WAITS),
            evidence_sha256=evidence_sha256,
            raw_accounting=raw_accounting,
            new_suffix_accounting=suffix_accounting,
            parent_prefix_preserved=prefix_ok,
        )
    except Exception as error:
        checked = dict(
            CONTRACT,
            passed=False,
            audit_failed=repr(error),
            allocation_exhausted=exhausted,
            stopped_early=stopped,
            terminal_error=terminal_error,
            transient_waits=dict(WAITS),
            evidence_sha256=evidence_sha256,
            raw_accounting=raw_accounting,
            new_suffix_accounting=suffix_accounting,
            parse_failures=parse_failures,
            suffix_parse_failures=suffix_parse_failures,
            parent_prefix_preserved=prefix_ok,
        )
    (output / "audit.json").write_text(
        json.dumps(checked, indent=2, sort_keys=True)
    )
    print("ATTEMPT_EXTENSION_AUDIT", json.dumps(checked, sort_keys=True), flush=True)
    if stopped:
        print("STOPPED_EARLY", stopped, flush=True)


hosted_cell.run(kbench.llms[CONTRACT["model"]])
'''


def build_source() -> str:
    planned = plan_repair()
    module_paths = {path: Path(path).name for path in SOURCE_PATHS}
    artifacts = {
        "minimal_evidence": str(
            (MINIMAL_ROOT / "openai_gpt-5.6-terra.jsonl").relative_to(ROOT)
        ),
        "minimal_terminal": str(
            (MINIMAL_ROOT / "reasoning_terminal.json").relative_to(ROOT)
        ),
        "minimal_receipt": str(
            (MINIMAL_ROOT / "reasoning_receipt.json").relative_to(ROOT)
        ),
        "minimal_quota": str(
            (MINIMAL_ROOT / "quota_attestation_1.json").relative_to(ROOT)
        ),
        "accepted_evidence": str(
            (LOW_ROOT / "openai_gpt-5.6-terra.jsonl").relative_to(ROOT)
        ),
        "accepted_terminal": str(
            (LOW_ROOT / "reasoning_terminal.json").relative_to(ROOT)
        ),
        "accepted_receipt": str(
            (LOW_ROOT / "reasoning_receipt.json").relative_to(ROOT)
        ),
    }
    header = "\n".join(
        (
            "# Generated offline by build_attempt_extension_v1.py; private synthetic research.",
            f"BLOBS = {planned['blobs']!r}",
            f"MODULE_PATHS = {module_paths!r}",
            f"ARTIFACTS = {artifacts!r}",
            f"PARENT_PATH = {str(PARENT_PATH.relative_to(ROOT))!r}",
            "PARENT_LEDGER = BLOBS[PARENT_PATH]",
            f"CONTRACT = {planned['contract']!r}",
            f"EXPECTED_JOBS = {planned['jobs']!r}",
            f"REPAIR_MANIFEST = {planned['manifest']!r}",
            "",
        )
    )
    code = header + RUNTIME_PART_1 + RUNTIME_PART_2 + RUNTIME_PART_3 + RUNTIME_PART_4
    compile(code, "generated_attempt_extension", "exec")
    return code


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    code = build_source()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(code)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
