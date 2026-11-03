"""Generate only the byte-preserving Gemini s06 429 runtime variant.

No source is uploaded or quota receipt issued here. The frozen scientific
module, prompts, jobs and raw JSONL remain unchanged. Only the single pinned
null-cost 429 is viewed as externally reconciled zero in memory.
"""

from __future__ import annotations

import copy
import hashlib

import build_experiment_c_cell_v1 as frozen
import experiment_c_gemini_s06_reconciled_view_v1 as view
import experiment_c_selection_v1 as selection_rules
import verify_experiment_c_gemini_s06_reconciliation_v1 as reconciliation


TASK = "chronos-r2-tree4-c-gemini-minimal-s06-v1"
FOLDER = "round2_tree4_c_gemini_minimal_s06_v1"

VALIDATION = """validate_resume_ledger(parse_jsonl_bytes(RESUME_SEED), model=MODEL, identity=IDENTITY,
    expected_jobs={job['id']:job for job in JOBS},
    structural_audit=lambda values: auditor.audit(values, MODEL, SELECTION, require_complete=False, expected_job_ids=set(CONTRACT['expected_job_ids'])))"""

RECONCILED_VALIDATION = """def _reconciled_events(raw):
    if not raw.startswith(RESUME_SEED) or not raw.endswith(b'\\n'):
        raise ValueError('Gemini s06 raw prefix changed')
    lines = raw.splitlines(keepends=True)
    if len(lines) <= 1 or hashlib.sha256(lines[1]).hexdigest() != '3eb040116d27899e8a9e4391f3b91b278ff2abb83a76d13483db7776aed9783f':
        raise ValueError('Gemini s06 failed 429 line changed')
    rows = parse_jsonl_bytes(raw)
    failure = rows[1]
    if (failure.get('event') != 'call_failed' or failure.get('error_type') != 'RateLimitError'
            or failure.get('cost_usd') is not None or failure.get('raw_completion') is not None
            or failure.get('step') != 1 or failure.get('attempt') != 1
            or failure.get('job_id') != 'chronos_round2_tree4_experiment_c_v1|defense|google/gemini-3.6-flash|tree4|undefended_natural|0|7'
            or not isinstance(failure.get('usage'), dict)
            or any(value is not None for value in failure['usage'].values())):
        raise ValueError('Gemini s06 failed 429 identity changed')
    if any(row.get('event') in ('call_complete', 'call_failed') and row.get('cost_usd') is None
           for index, row in enumerate(rows) if index != 1):
        raise ValueError('another unknown-cost call remains')
    checked = copy.deepcopy(rows)
    checked[1]['cost_usd'] = 0.0
    checked[1]['usage']['input_tokens_cost_nanodollars'] = 0
    checked[1]['usage']['output_tokens_cost_nanodollars'] = 0
    return checked

if (CONTRACT['cost_reconciliation']['raw_sha256'] != hashlib.sha256(RESUME_SEED).hexdigest()
        or CONTRACT['cost_reconciliation']['failed_event_line_sha256'] != hashlib.sha256(RESUME_SEED.splitlines(keepends=True)[1]).hexdigest()):
    raise ValueError('Gemini s06 account reconciliation changed')

validate_resume_ledger(_reconciled_events(RESUME_SEED), model=MODEL, identity=IDENTITY,
    expected_jobs={job['id']:job for job in JOBS},
    structural_audit=lambda values: auditor.audit(values, MODEL, SELECTION, require_complete=False, expected_job_ids=set(CONTRACT['expected_job_ids'])))

_parent_failed_event = parse_jsonl_bytes(RESUME_SEED)[1]
_original_accept = protocol.engine.Evidence._accept
def _reconciled_accept(self, event):
    if event == _parent_failed_event:
        adjusted = copy.deepcopy(event)
        adjusted['cost_usd'] = 0.0
        return _original_accept(self, adjusted)
    return _original_accept(self, event)
protocol.engine.Evidence._accept = _reconciled_accept"""

ORIGINAL_AUDIT = "report = auditor.audit(events, MODEL, SELECTION, require_complete=False, expected_job_ids=set(CONTRACT['expected_job_ids']))"
RECONCILED_AUDIT = "report = auditor.audit(_reconciled_events(EVIDENCE.read_bytes()), MODEL, SELECTION, require_complete=False, expected_job_ids=set(CONTRACT['expected_job_ids']))"
ORIGINAL_TERMINAL_END = "stopped_early=stopped, audit_error=audit_error, audit=report, raw_accounting=raw)"
RECONCILED_TERMINAL_END = "stopped_early=stopped, audit_error=audit_error, audit=report, raw_accounting=raw, cost_reconciliation=CONTRACT['cost_reconciliation'])"


def _replace_once(source: str, before: str, after: str) -> str:
    if source.count(before) != 1:
        raise ValueError("frozen C source no longer contains exactly one repair anchor")
    return source.replace(before, after, 1)


def reconciliation_record() -> dict:
    proof = reconciliation.verify()
    if (proof["resume_authorized"] is not False
            or proof["raw_sha256"] != view.PARENT_SHA256
            or proof["failed_event_line_sha256"] != view.FAILED_LINE_SHA256):
        raise ValueError("Gemini s06 account proof differs from the pinned 429")
    return {key: value for key, value in proof.items() if key != "resume_authorized"}


def augment_contract(contract: dict, proof: dict) -> dict:
    if (contract.get("model") != view.MODEL
            or contract.get("shard_index") != 6
            or contract.get("parent_ledger_sha256") != view.PARENT_SHA256
            or contract.get("resume_ledger", {}).get("completed_jobs") != 0
            or contract.get("resume_ledger", {}).get("failed_calls") != 1
            or proof.get("schema") != "chronos.experiment-c-gemini-s06-quota-reconciliation.v1"
            or proof.get("finding") != "account_level_zero_increment_for_one_429"
            or proof.get("raw_null_cost_calls") != 1
            or proof.get("raw_sha256") != view.PARENT_SHA256
            or proof.get("failed_event_line_sha256") != view.FAILED_LINE_SHA256
            or proof.get("collection_sha256") != reconciliation.COLLECTION_SHA256
            or not isinstance(proof.get("observation_sha256"), list)
            or len(proof["observation_sha256"]) != 3):
        raise ValueError("Gemini s06 contract is not the exact 429 resume")
    body = copy.deepcopy({key: value for key, value in contract.items()
                          if key != "contract_sha256"})
    body["cost_reconciliation"] = copy.deepcopy(proof)
    return {**body, "contract_sha256": selection_rules.canonical_hash(body)}


def build_source(contract: dict, selection: dict, parent: bytes,
                 *, standard_builder=None) -> str:
    if (contract.get("cost_reconciliation", {}).get("raw_sha256") != view.PARENT_SHA256
            or hashlib.sha256(parent).hexdigest() != view.PARENT_SHA256):
        raise ValueError("Gemini s06 source lacks the exact parent and account proof")
    builder = standard_builder or frozen.build_source
    source = builder(contract=contract, selection=selection, task_name=TASK,
                     output_folder=FOLDER, resume_seed=parent)
    source = _replace_once(source, "import hashlib\n", "import hashlib\nimport copy\n")
    source = _replace_once(source, VALIDATION, RECONCILED_VALIDATION)
    source = _replace_once(source, ORIGINAL_AUDIT, RECONCILED_AUDIT)
    source = _replace_once(source, ORIGINAL_TERMINAL_END, RECONCILED_TERMINAL_END)
    compile(source, "gemini_s06_reconciled_resume.py", "exec")
    return source
