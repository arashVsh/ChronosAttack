"""Build Experiments D/F (leave one observation out) study shard sources offline.

Adapted from ``build_experiment_e_hosted_v1``: the same runtime, ledger, resume,
audit and transport-wait gates, with the D/F protocol and auditor.
Plan: specs/journal-extension-sep14/round2-df-leave-one-out-plan-2026-10-08.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import audit_experiment_df as auditor
import experiment_c_provider_429_v1 as c_policy
import experiment_df_protocol as protocol
from round2_hosted import manifest_digest, parse_jsonl_bytes, select_shard, validate_resume_ledger

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GENERATED = HERE / "round2_generated"
PLAN = "specs/journal-extension-sep14/round2-df-leave-one-out-plan-2026-10-08.md"
MANIFEST = HERE / "experiment_df_manifest_v1.json"
SOURCE_FILES = (
    "completion_protocol.py",
    "four_observation_protocol.py",
    "experiment_df_protocol.py",
    "audit_experiment_df.py",
    "round2_hosted.py",
)
SHARD_COUNT = 30
CEILING_USD = 0.60
TRANSPORT_POLICY = {
    **{key: value for key, value in c_policy.TRANSPORT_POLICY.items() if key not in ("schema", "procedure")},
    "schema": "chronos.experiment-df-transport-wait.v1",
    "procedure": PLAN,
    "max_wait_seconds_per_call": 7200,
    "wait_on": ["RateLimitError", "APITimeoutError"],
}
# 2026-10-09 00:45 UTC (round2-dfg-operations-note-2026-10-08.md): Qwen shards made after this time
# retry a refused call sooner (10 s, at most 60 s apart); waits stay below the evidence layer.
QWEN = "qwen/qwen3-235b-a22b-instruct-2507"
QWEN_TRANSPORT_POLICY = {**TRANSPORT_POLICY, "initial_delay_seconds": 10, "max_delay_seconds": 60}
SHORT = {"openai/gpt-5.6-terra": "terra", "google/gemini-3.6-flash": "gemini",
         "qwen/qwen3-235b-a22b-instruct-2507": "qwen", "anthropic/claude-sonnet-4-6@default": "claude"}


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: dict) -> str:
    return _sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def freeze() -> dict:
    """Write the manifest once; afterwards every build checks the sources against it."""
    body = {"schema": "chronos.experiment-df-leave-one-out.v1", "status": "frozen_no_calls",
            "classification": "exploratory_descriptive", "plan": PLAN,
            "plan_sha256": _sha256((ROOT / PLAN).read_bytes()),
            "source_sha256": {f"kaggle/{name}": _sha256((HERE / name).read_bytes()) for name in SOURCE_FILES}}
    if not MANIFEST.exists():
        MANIFEST.write_text(json.dumps({**body, "manifest_sha256": _digest(body)}, indent=2, sort_keys=True) + "\n")
    frozen = json.loads(MANIFEST.read_text())
    if frozen != {**body, "manifest_sha256": _digest(body)}:
        raise ValueError("Frozen Experiment D/F sources or plan changed")
    return frozen


def names(model: str, shard: int, resume: int = 0) -> tuple[str, str, Path]:
    r = f"r{resume}" if resume else ""
    short = SHORT[model]
    return (f"chronos-r2-tree3-loo-{short}-s{shard:02d}{'-' * bool(r)}{r}-v1",
            f"round2_tree3_loo_{short}_s{shard:02d}{'_' * bool(r)}{r}_v1",
            GENERATED / f"tree3_loo_{short}_s{shard:02d}{'_' * bool(r)}{r}_v1.py")


def plan_cell(*, model: str, shard_index: int, resume_seed: bytes = b"") -> dict:
    frozen = freeze()
    chosen = protocol.cell(model)
    if not 0 <= shard_index < SHARD_COUNT:
        raise ValueError("Study requires one of 30 deterministic shards")
    jobs = select_shard(protocol.jobs_for(model), shard_index=shard_index, shard_count=SHARD_COUNT)
    if resume_seed and not resume_seed.endswith(b"\n"):
        raise ValueError("Resume ledger must be newline terminated")
    identity = protocol.identity(model)
    seed_audit = validate_resume_ledger(
        parse_jsonl_bytes(resume_seed, label="D/F resume ledger"), model=model, identity=identity,
        expected_jobs={job["id"]: job for job in jobs},
        structural_audit=lambda data: auditor.audit(data, model, "study", require_complete=False))
    if (len(jobs), sum(job["calls"] for job in jobs)) != (8, 32):
        raise ValueError("Experiment D/F shard topology changed")
    return {"schema": "chronos.experiment-df-hosted-cell.v1", **chosen, "shard_index": shard_index,
            "shard_count": SHARD_COUNT, "jobs": jobs, "job_count": 8, "planned_calls": 32,
            "jobs_sha256": manifest_digest(jobs), "identity": identity,
            "fixture_manifest_sha256": frozen["manifest_sha256"], "resume_ledger": seed_audit}


RUNTIME = '''# Generated offline by build_experiment_df_hosted_v1.py.
import hashlib
import json
import sys
import time
from pathlib import Path
import kaggle_benchmarks as kbench

__ASSIGNMENTS__

for name, raw in SOURCES.items():
    if hashlib.sha256(raw.encode()).hexdigest() != SOURCE_SHA256[name]:
        raise ValueError('Embedded D/F source hash mismatch: ' + name)

source_root = Path('/kaggle/working') / (OUTPUT_FOLDER + '_source')
source_root.mkdir(parents=True, exist_ok=False)
for name, raw in SOURCES.items():
    (source_root / name).write_text(raw)
sys.path.insert(0, str(source_root))

import audit_experiment_df as auditor
import experiment_df_protocol as cell
import round2_hosted as hosted

jobs = hosted.select_shard(cell.jobs_for(MODEL, 'study'),
                           shard_index=CONTRACT['shard_index'], shard_count=CONTRACT['shard_count'])
fixtures = cell.fixtures()
identity = cell.identity(MODEL)
structural_audit = lambda events: auditor.audit(events, MODEL, 'study', require_complete=False)
if (jobs != EXPECTED_JOBS
        or hosted.manifest_digest(jobs) != CONTRACT['jobs_sha256']
        or identity != CONTRACT['identity']
        or cell.call_settings(MODEL) != CALL_SETTINGS):
    raise ValueError('Runtime D/F cell differs from intended contract')
seed_audit = hosted.validate_resume_ledger(
    hosted.parse_jsonl_bytes(RESUME_LEDGER, label='D/F resume ledger'), model=MODEL, identity=identity,
    expected_jobs={job['id']: job for job in jobs}, structural_audit=structural_audit)
if (seed_audit != CONTRACT['resume_ledger']
        or (hashlib.sha256(RESUME_LEDGER).hexdigest() if RESUME_LEDGER else None)
        != CONTRACT['parent_ledger_sha256']):
    raise ValueError('Runtime D/F resume ledger changed')

output = Path('/kaggle/working') / OUTPUT_FOLDER
output.mkdir(parents=True, exist_ok=False)
(output / 'intended_manifest.json').write_text(json.dumps(dict(CONTRACT, jobs=jobs), indent=2, sort_keys=True))
evidence_path = output / (MODEL.replace('/', '_') + '.jsonl')
if RESUME_LEDGER:
    evidence_path.write_bytes(RESUME_LEDGER)

@kbench.task(name=__TASK_NAME_LITERAL__)
def hosted_cell(llm):
    if llm.model != MODEL:
        raise ValueError('Unexpected selected model')
__WAIT_WRAPPER__    error = None
    with cell.cell_runtime(MODEL, 'study'):
        try:
            cell.engine.run_jobs(kbench, llm, fixtures, jobs, output, CEILING_USD)
        except Exception as exc:
            response = getattr(exc, 'response', None)
            error = {'type': type(exc).__name__,
                     'status_code': getattr(exc, 'status_code', None) or getattr(response, 'status_code', None),
                     'message': str(exc)[:2000]}
    raw = evidence_path.read_bytes() if evidence_path.exists() else b''
    prefix_ok = raw.startswith(RESUME_LEDGER)
    events, parse_failures = hosted.parse_jsonl_best_effort(raw)
    raw_accounting = hosted.raw_event_summary(events, invalid_json_lines=len(parse_failures))
    terminal = {'schema': 'chronos.experiment-df-terminal.v1', 'model': MODEL, 'reasoning': REASONING,
                'role': ROLE, 'study_id': STUDY_ID, 'identity': identity,
                'fixture_manifest_sha256': CONTRACT['fixture_manifest_sha256'],
                'jobs_sha256': CONTRACT['jobs_sha256'], 'job_ids': [job['id'] for job in jobs],
                'planned_calls': CONTRACT['planned_calls'], 'call_settings': {**CALL_SETTINGS, 'sdk_max_retries': 0},
                'source_sha256': SOURCE_SHA256, 'evidence_sha256': hashlib.sha256(raw).hexdigest(),
                'parent_ledger_sha256': CONTRACT['parent_ledger_sha256'], 'error': error}
    (output / 'terminal.json').write_text(json.dumps(terminal, indent=2, sort_keys=True))
    try:
        if not prefix_ok or parse_failures:
            raise ValueError('Raw D/F ledger is malformed or lost its parent prefix')
        ledger = hosted.validate_resume_ledger(events, model=MODEL, identity=identity,
                                               expected_jobs={job['id']: job for job in jobs},
                                               structural_audit=structural_audit)
        subset = hosted.subset_summary(events, {job['id'] for job in jobs})
        checked = {'schema': 'chronos.experiment-df-hosted-audit.v1',
                   'passed': bool(subset['complete'] and error is None and raw_accounting['accounting_complete']),
                   'contract': CONTRACT, 'ledger_audit': ledger, 'structural_audit': structural_audit(events),
                   'subset': subset, 'raw_accounting': raw_accounting, 'parent_prefix_preserved': prefix_ok,
                   'evidence_sha256': terminal['evidence_sha256'], 'terminal_error': error}
    except Exception as exc:
        checked = {'schema': 'chronos.experiment-df-hosted-audit.v1', 'passed': False, 'contract': CONTRACT,
                   'audit_failed': repr(exc), 'raw_accounting': raw_accounting,
                   'parent_prefix_preserved': prefix_ok, 'evidence_sha256': terminal['evidence_sha256'],
                   'terminal_error': error, 'parse_failures': parse_failures}
    (output / 'audit.json').write_text(json.dumps(checked, indent=2, sort_keys=True))
    print('EXPERIMENT_DF_AUDIT', json.dumps(checked, sort_keys=True), flush=True)

hosted_cell.run(kbench.llms[MODEL])
'''


def build_source(*, model: str, shard_index: int, resume: int = 0, resume_seed: bytes = b"") -> str:
    task, folder, _ = names(model, shard_index, resume)
    plan = plan_cell(model=model, shard_index=shard_index, resume_seed=resume_seed)
    sources = {name: (HERE / name).read_text() for name in SOURCE_FILES}
    hashes = {name: _sha256(raw.encode()) for name, raw in sources.items()}
    contract = {key: value for key, value in plan.items() if key != "jobs"}
    contract.update({"source_sha256": hashes, "ceiling_usd": CEILING_USD + plan["resume_ledger"]["known_cost_usd"],
                     "parent_ledger_sha256": _sha256(resume_seed) if resume_seed else None,
                     "transport_policy": QWEN_TRANSPORT_POLICY if model == QWEN else TRANSPORT_POLICY, "sdk_max_retries": 0})
    assignments = {"SOURCES": sources, "SOURCE_SHA256": hashes, "CONTRACT": contract,
                   "EXPECTED_JOBS": plan["jobs"], "RESUME_LEDGER": resume_seed, "MODEL": model,
                   "REASONING": plan["reasoning"], "ROLE": plan["role"], "STUDY_ID": plan["study_id"],
                   "CALL_SETTINGS": protocol.call_settings(model), "CEILING_USD": contract["ceiling_usd"],
                   "OUTPUT_FOLDER": folder, "TASK_NAME": task}
    wrapper = c_policy._WAIT_WRAPPER.replace("OUTPUT / 'transient_waits.json'", "output / 'transient_waits.json'")
    source = (RUNTIME.replace("__ASSIGNMENTS__", "\n".join(f"{k} = {v!r}" for k, v in assignments.items()))
              .replace("__TASK_NAME_LITERAL__", repr(task)).replace("__WAIT_WRAPPER__", wrapper))
    compile(source, "experiment_df_shard.py", "exec")
    return source


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model", choices=sorted(SHORT))
    parser.add_argument("shard", type=int)
    parser.add_argument("--resume", type=int, default=0)
    parser.add_argument("--resume-from", type=Path)
    args = parser.parse_args()
    task, _, path = names(args.model, args.shard, args.resume)
    source = build_source(model=args.model, shard_index=args.shard, resume=args.resume,
                          resume_seed=args.resume_from.read_bytes() if args.resume_from else b"")
    if path.exists() and path.read_text() != source:
        raise SystemExit(f"{path} exists and differs from regeneration")
    path.write_text(source)
    print(task, path.relative_to(ROOT), _sha256(source.encode()))


if __name__ == "__main__":
    main()
