"""Build the four frozen Experiment A compatibility-pilot tasks offline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

import audit_water_supply as water_audit
import reasoning_preflight_v1 as pilot_gate
from round2_hosted import manifest_digest, validate_resume_ledger
import verify_experiment_a_availability as availability_verifier
import water_supply_protocol as protocol


HERE = Path(__file__).resolve().parent
AVAILABILITY_MANIFEST = HERE / "experiment_a_availability_v1.json"
FIXTURE_MANIFEST = HERE / "experiment_a_manifest_v1.json"
SOURCE_FILES = (
    "completion_protocol.py",
    "water_supply_protocol.py",
    "audit_water_supply.py",
    "round2_hosted.py",
    "reasoning_preflight_v1.py",
    "experiment_a_manifest_v1.json",
    "experiment_a_availability_v1.json",
)
STUDY_ID_PATTERN = re.compile(
    r"^chronos_round2_water4_pilot_[a-z0-9_]+_v1$"
)
TASK_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
FOLDER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{2,79}$")
PILOT_CEILING_USD = 0.25


def _availability() -> dict:
    availability_verifier.verify()
    return json.loads(AVAILABILITY_MANIFEST.read_text())


def _cell(model: str, reasoning: str) -> dict:
    matches = [
        cell
        for cell in _availability()["pilots"]["cells"]
        if cell["model"] == model and cell["reasoning"] == reasoning
    ]
    if len(matches) != 1:
        raise ValueError("model/reasoning is not an authorized Experiment A pilot")
    return matches[0]


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


def _with_runtime(model: str, reasoning: str, study_id: str):
    old = (
        protocol.engine.MODELS,
        protocol.engine.STUDY_ID,
        protocol.engine.CALL_SETTINGS,
    )
    protocol.engine.MODELS = tuple(
        dict.fromkeys((*protocol.engine.MODELS, model))
    )
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


def plan_pilot(*, model: str, reasoning: str, study_id: str) -> dict:
    cell = _cell(model, reasoning)
    if not STUDY_ID_PATTERN.fullmatch(study_id):
        raise ValueError("pilot study_id must be a new role-tagged v1 identifier")
    old = _with_runtime(model, reasoning, study_id)
    try:
        full_jobs = protocol.jobs_for(model, "study")
        jobs = pilot_gate.jobs(full_jobs)
        fixtures = protocol.fixtures()
        identity = _identity(study_id, model, fixtures)
        seed_audit = validate_resume_ledger(
            [],
            model=model,
            identity=identity,
            expected_jobs={job["id"]: job for job in jobs},
            structural_audit=lambda events: water_audit.audit(
                events, model, "study", require_complete=False
            ),
        )
        protocol_hash = fixtures["water4"]["extension_sha256"]
    finally:
        _restore_runtime(old)
    if (
        len(jobs) != cell["jobs"]
        or sum(job["calls"] for job in jobs) != cell["calls"]
        or [job["condition"] for job in jobs] != ["natural", "attack"]
        or any(job["mode"] != "stateful" or job["rep"] != 1 for job in jobs)
    ):
        raise ValueError("pilot topology differs from the availability amendment")
    return {
        "schema": "chronos.experiment-a-pilot-contract.v1",
        "model": model,
        "reasoning": reasoning,
        "role": cell["role"],
        "study_id": study_id,
        "jobs": jobs,
        "job_count": len(jobs),
        "planned_calls": sum(job["calls"] for job in jobs),
        "manifest_sha256": manifest_digest(jobs),
        "identity": identity,
        "protocol_extension_sha256": protocol_hash,
        "availability_manifest_sha256": _availability()["manifest_sha256"],
        "resume_ledger": seed_audit,
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
            raise ValueError(f"frozen Experiment A source hash changed: {name}")
    availability = json.loads(sources["experiment_a_availability_v1.json"])
    body = {
        key: value
        for key, value in availability.items()
        if key != "manifest_sha256"
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(canonical).hexdigest() != availability["manifest_sha256"]:
        raise ValueError("embedded availability manifest self-hash mismatch")
    return sources, hashes


def build_source(
    *,
    model: str,
    reasoning: str,
    study_id: str,
    task_name: str,
    output_folder: str,
    ceiling_usd: float = PILOT_CEILING_USD,
) -> str:
    if not TASK_PATTERN.fullmatch(task_name):
        raise ValueError("invalid hosted task name")
    if not FOLDER_PATTERN.fullmatch(output_folder):
        raise ValueError("invalid explicit output folder")
    if ceiling_usd != PILOT_CEILING_USD:
        raise ValueError("Experiment A pilot ceiling is frozen at $0.25")
    contract = plan_pilot(
        model=model,
        reasoning=reasoning,
        study_id=study_id,
    )
    sources, source_hashes = _source_payload()
    public_contract = {
        key: value for key, value in contract.items() if key != "jobs"
    }
    public_contract.update(
        {
            "source_sha256": source_hashes,
            "incremental_ceiling_usd": ceiling_usd,
            "effective_ceiling_usd": ceiling_usd,
            "parent_ledger_sha256": None,
            "call_settings": {
                "temperature": 1,
                "reasoning": reasoning,
                "max_completion_tokens": 256,
                "timeout": 30,
                "sdk_max_retries": 0,
            },
        }
    )
    return f'''# Generated offline by build_experiment_a_pilot_v1.py.
import hashlib
import json
import sys
from pathlib import Path
import kaggle_benchmarks as kbench

SOURCES = {sources!r}
SOURCE_SHA256 = {source_hashes!r}
CONTRACT = {public_contract!r}
EXPECTED_JOBS = {contract["jobs"]!r}
MODEL = {model!r}
REASONING = {reasoning!r}
ROLE = {contract["role"]!r}
STUDY_ID = {study_id!r}
OUTPUT_FOLDER = {output_folder!r}
CEILING_USD = {ceiling_usd!r}

source_root = Path('/kaggle/working') / (OUTPUT_FOLDER + '_source')
source_root.mkdir(parents=True, exist_ok=False)
for name, content in SOURCES.items():
    if hashlib.sha256(content.encode()).hexdigest() != SOURCE_SHA256[name]:
        raise ValueError('Embedded source hash mismatch: ' + name)
    (source_root / name).write_text(content)
sys.path.insert(0, str(source_root))

availability = json.loads(SOURCES['experiment_a_availability_v1.json'])
availability_body = {{
    key: value for key, value in availability.items()
    if key != 'manifest_sha256'
}}
availability_hash = hashlib.sha256(json.dumps(
    availability_body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
if (availability_hash != availability['manifest_sha256']
        or availability_hash != CONTRACT['availability_manifest_sha256']
        or availability['collection_status'] != 'not_started'):
    raise ValueError('Availability manifest differs from the pre-audited contract')
matches = [cell for cell in availability['pilots']['cells']
           if cell['model'] == MODEL and cell['reasoning'] == REASONING]
if len(matches) != 1 or matches[0]['role'] != ROLE:
    raise ValueError('Runtime pilot role is not authorized')

import audit_water_supply as cell_auditor
import reasoning_preflight_v1 as pilot_gate
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
jobs = pilot_gate.jobs(full_jobs)
fixtures = cell.fixtures()
structural_audit = lambda events: cell_auditor.audit(
    events, MODEL, 'study', require_complete=False)
expected_settings = {{
    key: value for key, value in CONTRACT['call_settings'].items()
    if key != 'sdk_max_retries'
}}
if cell.engine.CALL_SETTINGS != expected_settings:
    raise ValueError('Runtime settings differ from the intended pilot settings')
if jobs != EXPECTED_JOBS or hosted.manifest_digest(jobs) != CONTRACT['manifest_sha256']:
    raise ValueError('Runtime pilot jobs differ from the intended manifest')
identity = cell.engine.digest(json.dumps(dict(
    study=STUDY_ID, model=MODEL, fixtures=fixtures,
    settings=cell.engine.CALL_SETTINGS), sort_keys=True))
if identity != CONTRACT['identity']:
    raise ValueError('Runtime identity differs from the intended identity')

output = Path('/kaggle/working') / OUTPUT_FOLDER
output.mkdir(parents=True, exist_ok=False)
manifest = dict(CONTRACT, jobs=jobs, seed_audit=CONTRACT['resume_ledger'])
(output / 'intended_manifest.json').write_text(
    json.dumps(manifest, indent=2, sort_keys=True))
evidence_path = output / (MODEL.replace('/', '_') + '.jsonl')


@kbench.task(name={task_name!r})
def hosted_cell(llm):
    if llm.model != MODEL:
        raise ValueError('Unexpected selected model')
    llm.client = llm.client.with_options(max_retries=0)

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
        pilot_gate.run_once(
            cell.engine, cell.execute_job, kbench, llm, fixtures, jobs,
            output, CEILING_USD)
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
    events, parse_failures = hosted.parse_jsonl_best_effort(raw_bytes)
    accounting = hosted.raw_event_summary(
        events, invalid_json_lines=len(parse_failures))
    evidence_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    terminal = dict(
        schema='chronos.experiment-a-pilot-terminal.v1',
        model=MODEL,
        reasoning=REASONING,
        role=ROLE,
        study_id=STUDY_ID,
        identity=CONTRACT['identity'],
        manifest_sha256=CONTRACT['manifest_sha256'],
        protocol_extension_sha256=CONTRACT['protocol_extension_sha256'],
        availability_manifest_sha256=CONTRACT['availability_manifest_sha256'],
        call_settings=CONTRACT['call_settings'],
        source_sha256=CONTRACT['source_sha256'],
        job_ids=[job['id'] for job in jobs],
        planned_calls=10,
        evidence_sha256=evidence_sha256,
        error=terminal_error,
        transient_waits={{'count': 0, 'seconds': 0}},
    )
    (output / 'pilot_terminal.json').write_text(
        json.dumps(terminal, indent=2, sort_keys=True))

    try:
        if parse_failures:
            raise ValueError('Pilot ledger contains invalid JSON lines')
        ledger = hosted.validate_resume_ledger(
            events, model=MODEL, identity=identity,
            expected_jobs={{job['id']: job for job in jobs}},
            structural_audit=structural_audit)
        structural = structural_audit(events)
        subset = hosted.subset_summary(events, {{job['id'] for job in jobs}})
        gate = pilot_gate.pass_gate(events, jobs)
        checked = dict(
            CONTRACT,
            ledger_audit=ledger,
            structural_audit=structural,
            subset=subset,
            pilot=gate,
            allocation_exhausted=exhausted,
            stopped_early=stopped,
            terminal_error=terminal_error,
            transient_waits={{'count': 0, 'seconds': 0}},
            evidence_sha256=evidence_sha256,
            raw_accounting=accounting,
            parent_prefix_preserved=True,
        )
        checked['passed'] = bool(
            gate['passed'] and not exhausted and not stopped
            and terminal_error is None)
    except Exception as error:
        checked = dict(
            CONTRACT,
            passed=False,
            audit_failed=repr(error),
            allocation_exhausted=exhausted,
            stopped_early=stopped,
            terminal_error=terminal_error,
            transient_waits={{'count': 0, 'seconds': 0}},
            evidence_sha256=evidence_sha256,
            raw_accounting=accounting,
            parse_failures=parse_failures,
            parent_prefix_preserved=True,
        )
    (output / 'audit.json').write_text(
        json.dumps(checked, indent=2, sort_keys=True))
    print('EXPERIMENT_A_PILOT_AUDIT', json.dumps(checked, sort_keys=True), flush=True)
    if stopped:
        print('STOPPED_EARLY', stopped, flush=True)


hosted_cell.run(kbench.llms[MODEL])
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning", choices=("none", "minimal", "low"), required=True)
    parser.add_argument("--study-id", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--output-folder", required=True)
    parser.add_argument("--ceiling", type=float, default=PILOT_CEILING_USD)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = build_source(
        model=args.model,
        reasoning=args.reasoning,
        study_id=args.study_id,
        task_name=args.task,
        output_folder=args.output_folder,
        ceiling_usd=args.ceiling,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(source)
    print(f"WROTE {args.output}")


if __name__ == "__main__":
    main()
