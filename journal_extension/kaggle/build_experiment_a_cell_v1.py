"""Build receipt-gated, deterministic Experiment A full-cell shards."""

from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

import audit_water_supply as water_audit
import issue_experiment_a_pilot_receipt_v1 as receipt_issuer
from round2_hosted import (
    manifest_digest,
    parse_jsonl_bytes,
    select_shard,
    validate_resume_ledger,
)
import verify_experiment_a_pilot_collection as pilot_collection
import water_supply_protocol as protocol


HERE = Path(__file__).resolve().parent
SOURCE_FILES = (
    "completion_protocol.py",
    "water_supply_protocol.py",
    "audit_water_supply.py",
    "round2_hosted.py",
    "experiment_a_manifest_v1.json",
    "experiment_a_availability_v1.json",
)
SHARD_COUNT = 30
MAX_CALLS_PER_SHARD = 99
TRANSPORT_WAIT_SECONDS = 7200
STUDY_ID_PATTERN = re.compile(
    r"^chronos_round2_water4_study_[a-z0-9_]+_v1$"
)
TASK_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
FOLDER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{2,79}$")

# Fixed before full-cell calls from the excluded pilot's cost per call, a 2x
# telemetry margin, the largest 30-way shard (99 calls), and the protocol's
# $0.10 pre-call reserve, rounded upward to cents.
INCREMENTAL_CEILINGS_USD = {
    ("openai/gpt-5.6-terra", "low"): 0.67,
    ("google/gemini-3.6-flash", "minimal"): 0.28,
    ("qwen/qwen3-235b-a22b-instruct-2507", "low"): 0.16,
    ("anthropic/claude-sonnet-4-6@default", "none"): 1.09,
}


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_hash(value: dict) -> str:
    return _sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )


@lru_cache(maxsize=1)
def _pilot_manifest() -> dict:
    return pilot_collection.verify()


def _pilot_spec(model: str, reasoning: str, role: str) -> dict:
    matches = [
        spec
        for spec in pilot_collection.RUNS
        if spec["model"] == model
        and spec["reasoning"] == reasoning
        and spec["role"] == role
    ]
    if len(matches) != 1:
        raise ValueError("model/reasoning/role has no passed Experiment A pilot")
    return matches[0]


def _pilot_bundle(model: str, reasoning: str, role: str) -> dict:
    manifest = _pilot_manifest()
    spec = _pilot_spec(model, reasoning, role)
    records = [record for record in manifest["runs"] if record["label"] == spec["label"]]
    if len(records) != 1 or records[0]["status"] != "passed_raw_revalidated":
        raise ValueError("pilot collection does not authorize this full cell")
    paths = pilot_collection.paths_for(spec)
    receipt_raw = paths["receipt"].read_bytes()
    evidence_raw = paths["evidence"].read_bytes()
    terminal_raw = paths["terminal"].read_bytes()
    intended_raw = paths["intended_manifest"].read_bytes()
    # Raw pilot evidence remains local.  Hosted shards carry only the
    # outcome-free receipt and collection seal after local raw revalidation.
    artifacts = {
        "receipt": receipt_raw,
        "collection_manifest": pilot_collection.MANIFEST.read_bytes(),
    }
    receipt = receipt_issuer.validate_pilot_receipt(
        receipt_raw=receipt_raw,
        evidence_raw=evidence_raw,
        terminal_raw=terminal_raw,
        intended_raw=intended_raw,
        expected_model=model,
        expected_reasoning=reasoning,
        expected_role=role,
        expected_study_id=spec["study_id"],
    )
    if (
        receipt["receipt_sha256"] != records[0]["receipt_sha256"]
        or receipt["evidence"]["sha256"] != records[0]["evidence_sha256"]
    ):
        raise ValueError("pilot receipt differs from the sealed collection")
    return {
        "spec": spec,
        "record": records[0],
        "receipt": receipt,
        "artifacts": artifacts,
        "artifact_sha256": {
            name: _sha256(raw) for name, raw in artifacts.items()
        },
        "collection_manifest_sha256": manifest["collection_manifest_sha256"],
    }


def _with_runtime(model: str, reasoning: str, study_id: str):
    old = (
        protocol.engine.MODELS,
        protocol.engine.STUDY_ID,
        protocol.engine.CALL_SETTINGS,
    )
    protocol.engine.MODELS = tuple(dict.fromkeys((*protocol.engine.MODELS, model)))
    protocol.engine.STUDY_ID = study_id
    protocol.engine.CALL_SETTINGS = {
        "temperature": 1,
        "reasoning": reasoning,
        "max_completion_tokens": 256,
        "timeout": 30,
    }
    return old


def _restore_runtime(old) -> None:
    (
        protocol.engine.MODELS,
        protocol.engine.STUDY_ID,
        protocol.engine.CALL_SETTINGS,
    ) = old


def _identity(study_id: str, model: str, fixtures: dict) -> str:
    return protocol.engine.digest(
        json.dumps(
            {
                "study": study_id,
                "model": model,
                "fixtures": fixtures,
                "settings": protocol.engine.CALL_SETTINGS,
            },
            sort_keys=True,
        )
    )


def plan_cell(
    *,
    model: str,
    reasoning: str,
    role: str,
    study_id: str,
    shard_index: int,
    shard_count: int = SHARD_COUNT,
    resume_seed: bytes = b"",
) -> dict:
    if (model, reasoning) not in INCREMENTAL_CEILINGS_USD:
        raise ValueError("model/reasoning is outside the frozen executable roster")
    _pilot_spec(model, reasoning, role)
    if not STUDY_ID_PATTERN.fullmatch(study_id):
        raise ValueError("study_id must be a new role-tagged Experiment A identifier")
    if shard_count != SHARD_COUNT or not 0 <= shard_index < SHARD_COUNT:
        raise ValueError("Experiment A full cells use exactly 30 deterministic shards")
    if resume_seed and not resume_seed.endswith(b"\n"):
        raise ValueError("resume ledger must be newline terminated")

    old = _with_runtime(model, reasoning, study_id)
    try:
        full_jobs = protocol.jobs_for(model, "study")
        if len(full_jobs) != 690 or sum(job["calls"] for job in full_jobs) != 2310:
            raise ValueError("full Experiment A topology changed")
        jobs = select_shard(
            full_jobs, shard_index=shard_index, shard_count=shard_count
        )
        fixtures = protocol.fixtures()
        identity = _identity(study_id, model, fixtures)
        events = parse_jsonl_bytes(resume_seed, label="resume ledger")
        seed = validate_resume_ledger(
            events,
            model=model,
            identity=identity,
            expected_jobs={job["id"]: job for job in jobs},
            structural_audit=lambda values: water_audit.audit(
                values, model, "study", require_complete=False
            ),
        )
        protocol_hash = fixtures["water4"]["extension_sha256"]
    finally:
        _restore_runtime(old)
    if len(jobs) != 23 or sum(job["calls"] for job in jobs) > MAX_CALLS_PER_SHARD:
        raise ValueError("Experiment A shard size changed")
    return {
        "schema": "chronos.experiment-a-full-shard-contract.v1",
        "model": model,
        "reasoning": reasoning,
        "role": role,
        "study_id": study_id,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "jobs": jobs,
        "job_count": len(jobs),
        "planned_calls": sum(job["calls"] for job in jobs),
        "manifest_sha256": manifest_digest(jobs),
        "identity": identity,
        "protocol_extension_sha256": protocol_hash,
        "resume_ledger": seed,
    }


def _source_payload() -> tuple[dict[str, str], dict[str, str]]:
    sources = {name: (HERE / name).read_text() for name in SOURCE_FILES}
    hashes = {
        name: hashlib.sha256(content.encode()).hexdigest()
        for name, content in sources.items()
    }
    fixture = json.loads(sources["experiment_a_manifest_v1.json"])
    for name, expected in fixture["sources"].items():
        if hashes.get(name) != expected:
            raise ValueError(f"frozen Experiment A source changed: {name}")
    availability = json.loads(sources["experiment_a_availability_v1.json"])
    body = {
        key: value
        for key, value in availability.items()
        if key != "manifest_sha256"
    }
    if _canonical_hash(body) != availability["manifest_sha256"]:
        raise ValueError("Experiment A availability self-hash mismatch")
    return sources, hashes


def build_source(
    *,
    model: str,
    reasoning: str,
    role: str,
    study_id: str,
    shard_index: int,
    task_name: str,
    output_folder: str,
    shard_count: int = SHARD_COUNT,
    resume_from: Path | None = None,
) -> str:
    if not TASK_PATTERN.fullmatch(task_name):
        raise ValueError("invalid hosted task name")
    if not FOLDER_PATTERN.fullmatch(output_folder):
        raise ValueError("invalid explicit output folder")
    resume_seed = Path(resume_from).read_bytes() if resume_from else b""
    contract = plan_cell(
        model=model,
        reasoning=reasoning,
        role=role,
        study_id=study_id,
        shard_index=shard_index,
        shard_count=shard_count,
        resume_seed=resume_seed,
    )
    pilot = _pilot_bundle(model, reasoning, role)
    sources, source_hashes = _source_payload()
    incremental = INCREMENTAL_CEILINGS_USD[(model, reasoning)]
    effective = contract["resume_ledger"]["known_cost_usd"] + incremental
    public_contract = {
        key: value for key, value in contract.items() if key != "jobs"
    }
    public_contract.update(
        {
            "source_sha256": source_hashes,
            "pilot_receipt_sha256": pilot["receipt"]["receipt_sha256"],
            "pilot_evidence_sha256": pilot["receipt"]["evidence"]["sha256"],
            "pilot_collection_manifest_sha256": pilot[
                "collection_manifest_sha256"
            ],
            "incremental_ceiling_usd": incremental,
            "effective_ceiling_usd": effective,
            "parent_ledger_sha256": _sha256(resume_seed) if resume_seed else None,
            "transport_wait_seconds": TRANSPORT_WAIT_SECONDS,
            "call_settings": {
                "temperature": 1,
                "reasoning": reasoning,
                "max_completion_tokens": 256,
                "timeout": 30,
                "sdk_max_retries": 0,
            },
        }
    )
    return f'''# Generated offline by build_experiment_a_cell_v1.py.
import hashlib
import json
import sys
import time
from pathlib import Path
import kaggle_benchmarks as kbench

SOURCES = {sources!r}
SOURCE_SHA256 = {source_hashes!r}
PILOT_ARTIFACTS = {pilot["artifacts"]!r}
PILOT_ARTIFACT_SHA256 = {pilot["artifact_sha256"]!r}
CONTRACT = {public_contract!r}
EXPECTED_JOBS = {contract["jobs"]!r}
RESUME_LEDGER = {resume_seed!r}
MODEL = {model!r}
REASONING = {reasoning!r}
ROLE = {role!r}
STUDY_ID = {study_id!r}
OUTPUT_FOLDER = {output_folder!r}
CEILING_USD = {effective!r}
MAX_WAIT_SECONDS = {TRANSPORT_WAIT_SECONDS!r}
WAITS = {{'count': 0, 'seconds': 0}}
TRANSIENT = {{'InternalServerError', 'APIConnectionError', 'APITimeoutError',
             'RateLimitError', 'ServiceUnavailableError'}}

for name, raw in PILOT_ARTIFACTS.items():
    if hashlib.sha256(raw).hexdigest() != PILOT_ARTIFACT_SHA256[name]:
        raise ValueError('Embedded pilot artifact hash mismatch: ' + name)
receipt = json.loads(PILOT_ARTIFACTS['receipt'])
receipt_body = {{key: value for key, value in receipt.items()
                if key != 'receipt_sha256'}}
receipt_hash = hashlib.sha256(json.dumps(
    receipt_body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
collection = json.loads(PILOT_ARTIFACTS['collection_manifest'])
collection_body = {{key: value for key, value in collection.items()
                   if key != 'collection_manifest_sha256'}}
collection_hash = hashlib.sha256(json.dumps(
    collection_body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
collection_rows = [row for row in collection['runs']
                   if row['model'] == MODEL and row['reasoning'] == REASONING
                   and row['role'] == ROLE]
if (receipt_hash != receipt['receipt_sha256']
        or receipt_hash != CONTRACT['pilot_receipt_sha256']
        or collection_hash != collection['collection_manifest_sha256']
        or collection_hash != CONTRACT['pilot_collection_manifest_sha256']
        or len(collection_rows) != 1
        or collection_rows[0]['receipt_sha256'] != receipt_hash
        or receipt['disposition'] != 'passed'
        or receipt['model'] != MODEL or receipt['reasoning'] != REASONING
        or receipt['role'] != ROLE
        or receipt['evidence']['sha256'] != CONTRACT['pilot_evidence_sha256']
        or receipt['outcomes_examined_for_authorization'] is not False
        or receipt['pilot_excluded_from_confirmation'] is not True):
    raise ValueError('Pilot receipt does not authorize this exact full cell')

source_root = Path('/kaggle/working') / (OUTPUT_FOLDER + '_source')
source_root.mkdir(parents=True, exist_ok=False)
for name, content in SOURCES.items():
    if hashlib.sha256(content.encode()).hexdigest() != SOURCE_SHA256[name]:
        raise ValueError('Embedded source hash mismatch: ' + name)
    (source_root / name).write_text(content)
sys.path.insert(0, str(source_root))

import audit_water_supply as cell_auditor
import round2_hosted as hosted
import water_supply_protocol as cell

cell.engine.MODELS = tuple(dict.fromkeys((*cell.engine.MODELS, MODEL)))
cell.engine.STUDY_ID = STUDY_ID
cell.engine.CALL_SETTINGS = {{
    'temperature': 1,
    'reasoning': REASONING,
    'max_completion_tokens': 256,
    'timeout': 30,
}}
full_jobs = cell.jobs_for(MODEL, 'study')
jobs = hosted.select_shard(
    full_jobs,
    shard_index=CONTRACT['shard_index'],
    shard_count=CONTRACT['shard_count'])
fixtures = cell.fixtures()
structural_audit = lambda events: cell_auditor.audit(
    events, MODEL, 'study', require_complete=False)
expected_settings = {{key: value for key, value in CONTRACT['call_settings'].items()
                     if key != 'sdk_max_retries'}}
if (cell.engine.CALL_SETTINGS != expected_settings
        or jobs != EXPECTED_JOBS
        or hosted.manifest_digest(jobs) != CONTRACT['manifest_sha256']):
    raise ValueError('Runtime shard differs from the intended contract')
identity = cell.engine.digest(json.dumps(dict(
    study=STUDY_ID, model=MODEL, fixtures=fixtures,
    settings=cell.engine.CALL_SETTINGS), sort_keys=True))
if identity != CONTRACT['identity']:
    raise ValueError('Runtime identity differs from the intended identity')
seed_events = hosted.parse_jsonl_bytes(RESUME_LEDGER, label='resume ledger')
seed_audit = hosted.validate_resume_ledger(
    seed_events, model=MODEL, identity=identity,
    expected_jobs={{job['id']: job for job in jobs}},
    structural_audit=structural_audit)
if (seed_audit != CONTRACT['resume_ledger']
        or (hashlib.sha256(RESUME_LEDGER).hexdigest()
            if RESUME_LEDGER else None) != CONTRACT['parent_ledger_sha256']):
    raise ValueError('Runtime resume ledger differs from the intended parent')

output = Path('/kaggle/working') / OUTPUT_FOLDER
output.mkdir(parents=True, exist_ok=False)
manifest = dict(CONTRACT, jobs=jobs, seed_audit=seed_audit)
(output / 'intended_manifest.json').write_text(
    json.dumps(manifest, indent=2, sort_keys=True))
evidence_path = output / (MODEL.replace('/', '_') + '.jsonl')
if RESUME_LEDGER:
    evidence_path.write_bytes(RESUME_LEDGER)


@kbench.task(name={task_name!r})
def hosted_cell(llm):
    if llm.model != MODEL:
        raise ValueError('Unexpected selected model')
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
                remaining = MAX_WAIT_SECONDS - waited
                if remaining <= 0:
                    raise
                pause = min(delay, remaining)
                print('TRANSIENT', type(error).__name__, 'waiting', pause,
                      's (total', waited, 's)', flush=True)
                time.sleep(pause)
                waited += pause
                WAITS['count'] += 1
                WAITS['seconds'] += pause
                delay = min(delay * 2, 300)

    llm.respond = respond

    def error_metadata(error):
        response = getattr(error, 'response', None)
        body = getattr(error, 'body', None)
        if not isinstance(body, dict):
            body = {{}}
        return dict(
            type=type(error).__name__,
            status_code=getattr(error, 'status_code', None)
            or getattr(response, 'status_code', None),
            code=getattr(error, 'code', None) or body.get('code'),
            param=getattr(error, 'param', None) or body.get('param'),
            message=str(error)[:2000],
        )

    exhausted, stopped, terminal_error = False, None, None
    try:
        cell.engine.run_jobs(
            kbench, llm, fixtures, jobs, output, CEILING_USD)
    except RuntimeError as error:
        terminal_error = error_metadata(error)
        if str(error) == 'Cost ceiling reached; checkpoint retained':
            exhausted = True
        else:
            stopped = repr(error)
    except Exception as error:
        terminal_error = error_metadata(error)
        stopped = repr(error)

    raw_bytes = evidence_path.read_bytes() if evidence_path.exists() else b''
    prefix_ok = raw_bytes.startswith(RESUME_LEDGER)
    suffix = raw_bytes[len(RESUME_LEDGER):] if prefix_ok else b''
    events, parse_failures = hosted.parse_jsonl_best_effort(raw_bytes)
    suffix_events, suffix_failures = hosted.parse_jsonl_best_effort(suffix)
    accounting = hosted.raw_event_summary(
        events, invalid_json_lines=len(parse_failures))
    new_accounting = hosted.raw_event_summary(
        suffix_events, invalid_json_lines=len(suffix_failures))
    evidence_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    terminal = dict(
        schema='chronos.experiment-a-full-shard-terminal.v1',
        model=MODEL,
        reasoning=REASONING,
        role=ROLE,
        study_id=STUDY_ID,
        identity=CONTRACT['identity'],
        manifest_sha256=CONTRACT['manifest_sha256'],
        pilot_receipt_sha256=CONTRACT['pilot_receipt_sha256'],
        pilot_collection_manifest_sha256=
            CONTRACT['pilot_collection_manifest_sha256'],
        shard_index=CONTRACT['shard_index'],
        shard_count=CONTRACT['shard_count'],
        job_ids=[job['id'] for job in jobs],
        planned_calls=CONTRACT['planned_calls'],
        evidence_sha256=evidence_sha256,
        parent_ledger_sha256=CONTRACT['parent_ledger_sha256'],
        error=terminal_error,
        transient_waits=dict(WAITS),
    )
    (output / 'terminal.json').write_text(
        json.dumps(terminal, indent=2, sort_keys=True))

    try:
        if not prefix_ok:
            raise ValueError('Final ledger does not preserve the parent byte prefix')
        if parse_failures or suffix_failures:
            raise ValueError('Final ledger contains invalid JSON lines')
        ledger = hosted.validate_resume_ledger(
            events, model=MODEL, identity=identity,
            expected_jobs={{job['id']: job for job in jobs}},
            structural_audit=structural_audit)
        structural = structural_audit(events)
        subset = hosted.subset_summary(events, {{job['id'] for job in jobs}})
        checked = dict(
            CONTRACT,
            ledger_audit=ledger,
            structural_audit=structural,
            subset=subset,
            allocation_exhausted=exhausted,
            stopped_early=stopped,
            terminal_error=terminal_error,
            transient_waits=dict(WAITS),
            evidence_sha256=evidence_sha256,
            raw_accounting=accounting,
            new_suffix_accounting=new_accounting,
            parent_prefix_preserved=prefix_ok,
        )
        checked['passed'] = bool(
            subset['complete'] and not exhausted and not stopped
            and terminal_error is None)
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
            raw_accounting=accounting,
            new_suffix_accounting=new_accounting,
            parse_failures=parse_failures,
            suffix_parse_failures=suffix_failures,
            parent_prefix_preserved=prefix_ok,
        )
    (output / 'audit.json').write_text(
        json.dumps(checked, indent=2, sort_keys=True))
    print('EXPERIMENT_A_SHARD_AUDIT', json.dumps(checked, sort_keys=True), flush=True)
    if stopped:
        print('STOPPED_EARLY', stopped, flush=True)


hosted_cell.run(kbench.llms[MODEL])
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning", choices=("none", "minimal", "low"), required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--study-id", required=True)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, default=SHARD_COUNT)
    parser.add_argument("--task", required=True)
    parser.add_argument("--output-folder", required=True)
    parser.add_argument("--resume-from", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = build_source(
        model=args.model,
        reasoning=args.reasoning,
        role=args.role,
        study_id=args.study_id,
        shard_index=args.shard_index,
        shard_count=args.shard_count,
        task_name=args.task,
        output_folder=args.output_folder,
        resume_from=args.resume_from,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(source)
    print(f"WROTE {args.output}")


if __name__ == "__main__":
    main()
