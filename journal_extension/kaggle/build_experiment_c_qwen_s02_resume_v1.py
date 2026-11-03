"""Generate only the narrow byte-preserving Qwen s02 429 runtime variant.

This does not issue a quota receipt or launch Kaggle. The frozen C module text
and scientific inputs are unchanged; only one pinned null-cost 429 is viewed
as externally reconciled zero for resume validation and budget control.
"""

from __future__ import annotations

import copy
import hashlib
import json

import build_experiment_c_cell_v1 as frozen
import experiment_c_qwen_s02_reconciled_view_v1 as view
import experiment_c_selection_v1 as selection_rules
import verify_experiment_c_qwen_s02_reconciliation_v1 as reconciliation


TASK = "chronos-r2-tree4-c-qwen-low-s02-v1"
FOLDER = "round2_tree4_c_qwen_low_s02_v1"

VALIDATION = """validate_resume_ledger(parse_jsonl_bytes(RESUME_SEED), model=MODEL, identity=IDENTITY,
    expected_jobs={job['id']:job for job in JOBS},
    structural_audit=lambda values: auditor.audit(values, MODEL, SELECTION, require_complete=False, expected_job_ids=set(CONTRACT['expected_job_ids'])))"""

RECONCILED_VALIDATION = """def _reconciled_events(raw):
    if not raw.startswith(RESUME_SEED) or not raw.endswith(b'\\n'):
        raise ValueError('Qwen s02 raw prefix changed')
    lines = raw.splitlines(keepends=True)
    if len(lines) <= 9 or hashlib.sha256(lines[9]).hexdigest() != '844cc962acb7869864fd636700f0e3a14d712f43cf85f4292d520b9a39d67081':
        raise ValueError('Qwen s02 failed 429 line changed')
    rows = parse_jsonl_bytes(raw)
    failure = rows[9]
    if (failure.get('event') != 'call_failed' or failure.get('error_type') != 'RateLimitError'
            or failure.get('cost_usd') is not None or failure.get('raw_completion') is not None
            or failure.get('step') != 2 or failure.get('attempt') != 1
            or failure.get('job_id') != 'chronos_round2_tree4_experiment_c_v1|defense|qwen/qwen3-235b-a22b-instruct-2507|tree4|undefended_selected_order|0|3'
            or not isinstance(failure.get('usage'), dict)
            or any(value is not None for value in failure['usage'].values())):
        raise ValueError('Qwen s02 failed 429 identity changed')
    if any(row.get('event') in ('call_complete', 'call_failed') and row.get('cost_usd') is None
           for index, row in enumerate(rows) if index != 9):
        raise ValueError('another unknown-cost call remains')
    checked = copy.deepcopy(rows)
    checked[9]['cost_usd'] = 0.0
    checked[9]['usage']['input_tokens_cost_nanodollars'] = 0
    checked[9]['usage']['output_tokens_cost_nanodollars'] = 0
    return checked

if (CONTRACT['cost_reconciliation']['qwen_raw_sha256'] != hashlib.sha256(RESUME_SEED).hexdigest()
        or CONTRACT['cost_reconciliation']['qwen_failed_event_line_sha256'] != hashlib.sha256(RESUME_SEED.splitlines(keepends=True)[9]).hexdigest()):
    raise ValueError('Qwen s02 account reconciliation changed')

validate_resume_ledger(_reconciled_events(RESUME_SEED), model=MODEL, identity=IDENTITY,
    expected_jobs={job['id']:job for job in JOBS},
    structural_audit=lambda values: auditor.audit(values, MODEL, SELECTION, require_complete=False, expected_job_ids=set(CONTRACT['expected_job_ids'])))

_parent_failed_event = parse_jsonl_bytes(RESUME_SEED)[9]
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
            or proof["qwen_raw_sha256"] != view.PARENT_SHA256
            or proof["qwen_failed_event_line_sha256"] != view.FAILED_LINE_SHA256):
        raise ValueError("Qwen s02 account proof no longer matches the pinned 429")
    return {key: value for key, value in proof.items() if key != "resume_authorized"}


def augment_contract(contract: dict, proof: dict) -> dict:
    if (contract.get("model") != view.MODEL
            or contract.get("shard_index") != 2
            or contract.get("parent_ledger_sha256") != view.PARENT_SHA256
            or contract.get("resume_ledger", {}).get("completed_jobs") != 1
            or contract.get("resume_ledger", {}).get("failed_calls") != 1
            or proof.get("qwen_raw_sha256") != view.PARENT_SHA256
            or proof.get("qwen_failed_event_line_sha256") != view.FAILED_LINE_SHA256):
        raise ValueError("Qwen s02 contract is not the exact 429 resume")
    body = copy.deepcopy({key: value for key, value in contract.items() if key != "contract_sha256"})
    body["cost_reconciliation"] = copy.deepcopy(proof)
    return {**body, "contract_sha256": selection_rules.canonical_hash(body)}


def build_source(contract: dict, selection: dict, parent: bytes,
                 *, standard_builder=None) -> str:
    if (contract.get("cost_reconciliation", {}).get("qwen_raw_sha256") != view.PARENT_SHA256
            or hashlib.sha256(parent).hexdigest() != view.PARENT_SHA256):
        raise ValueError("Qwen s02 source lacks the exact parent and account proof")
    builder = standard_builder or frozen.build_source
    source = builder(
        contract=contract, selection=selection, task_name=TASK,
        output_folder=FOLDER, resume_seed=parent,
    )
    source = _replace_once(source, "import hashlib\n", "import hashlib\nimport copy\n")
    source = _replace_once(source, VALIDATION, RECONCILED_VALIDATION)
    source = _replace_once(source, ORIGINAL_AUDIT, RECONCILED_AUDIT)
    source = _replace_once(source, ORIGINAL_TERMINAL_END, RECONCILED_TERMINAL_END)
    compile(source, "qwen_s02_reconciled_resume.py", "exec")
    return source
