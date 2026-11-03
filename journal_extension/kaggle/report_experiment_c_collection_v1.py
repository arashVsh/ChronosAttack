"""Status-aware final C report from the independently replayed raw collection.

Only a complete 180-job setting receives six-arm effect estimates. A stopped or
unstarted setting retains its observed raw/cost accounting and null effects;
it cannot be silently treated as a negative result or a complete comparison.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import copy
import math
from pathlib import Path
from unittest import mock

import analyze_experiment_c_v1 as analysis
import experiment_c_selection_v1 as selection_rules
import stage_experiment_c_tasks_v1 as staged_tasks
import verify_experiment_c_collection_v1 as collection_verifier
import verify_experiment_c_gemini_s03_platform_bridge_v1 as bridge_verifier
import verify_experiment_c_gemini_s06_resume_collection_v1 as gemini_s06_verifier
import verify_experiment_c_collection_v3 as composed_verifier
import verify_experiment_c_collection_v4 as provider429_verifier
import experiment_c_provider_429_v1 as provider429_procedure


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_COLLECTION = HERE / "round2_generated/experiment_c_collection_v1.json"
DEFAULT_REPORT = HERE / "round2_analysis/experiment_c_collection_report_v1.json"
SCHEMA = "chronos.experiment-c-collection-report.v1"
CELL_STATUSES = frozenset({"complete", "study_partial", "not_started"})


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _settled_analysis(selection_path: Path, evidence_paths: list[Path], model: str) -> tuple[dict, int]:
    """Frozen full-cell analysis with only registry-settled provider 429s costed at zero, in memory.

    Every null-cost call must be a registered pin whose account-level settlement proof
    passes (procedure of 2026-09-25, rule 1); raw bytes keep the null cost. Settled events
    are matched by content, as the hosted resume runtime does.
    """
    original, count = analysis.analyze_cell, [0]

    def zeroed(events, selection, *, raw_sources=None, **kwargs):
        if any(event.get("cost_usd", 0) is None for event in events):
            settled = []
            for source in raw_sources:
                raw = (ROOT / source["path"]).read_bytes()
                lines = raw.splitlines(keepends=True)
                if any(json.loads(line).get("cost_usd", 0) is None for line in lines):
                    pins, _ = provider429_procedure.settled_pins(raw, model)
                    settled += [json.loads(lines[pin.line_index]) for pin in pins]
            events = [copy.deepcopy(event) if event in settled else event for event in events]
            for event in events:
                if event in settled:
                    event["cost_usd"] = 0.0
                    event["usage"]["input_tokens_cost_nanodollars"] = 0
                    event["usage"]["output_tokens_cost_nanodollars"] = 0
            count[0] = len(settled)
        return original(events, selection, raw_sources=raw_sources, **kwargs)

    with mock.patch.object(analysis, "analyze_cell", zeroed):
        return analysis.analyze_files(selection_path, evidence_paths), count[0]


def _effects(full: dict) -> dict:
    return {
        arm: {
            "target_C_reduction_pp_vs_fresh_selected_order": value["defense_efficacy_target_C_reduction_pp_vs_selected_attack"],
            "utility_total_variation_vs_fresh_natural": value["utility_total_variation_vs_fresh_natural"],
            "coverage": value["coverage"],
        }
        for arm, value in full["arms"].items()
    }


def _logical_ledgers(ledgers: list[dict]) -> list[dict]:
    """Use the final cumulative version of each shard for scientific analysis.

    Physical v1/v2 attempts remain visible in raw_evidence_sources and cost.
    The collection verifier separately replays their exact-prefix chain.
    """
    latest = []
    previous = None
    for record in ledgers:
        index = record.get("shard_index")
        if type(index) is not int or index not in range(30):
            raise ValueError("C collection has an invalid shard index")
        if index == len(latest):
            latest.append(record)
        elif index == len(latest) - 1 and previous is not None:
            if (record.get("task_name") != previous.get("task_name")
                    or type(record.get("task_version")) is not int
                    or record["task_version"] != previous.get("task_version", -1) + 1):
                raise ValueError("C collection has an invalid versioned shard chain")
            latest[-1] = record
        else:
            raise ValueError("C collection has a duplicate or skipped logical shard")
        previous = record
    return latest


def _evidence_pin(record: dict) -> dict:
    pin = record.get("artifacts", {}).get("evidence", record)
    if not isinstance(pin, dict) or not isinstance(pin.get("path"), str) or not isinstance(pin.get("sha256"), str):
        raise ValueError("C collection ledger lacks a pinned raw evidence file")
    return pin


def _cell_report(cell: dict, seal: dict) -> tuple[dict, dict | None]:
    model = cell["model"]
    if (
        cell["reasoning"] != seal["reasoning"]
        or cell["role"] != seal["role"]
        or selection_rules.ROSTER.get((model, cell["reasoning"])) != cell["role"]
        or cell["status"] not in CELL_STATUSES
    ):
        raise ValueError("C collection cell setting, role or status changed")
    ledgers = cell["raw_ledgers"]
    logical_ledgers = _logical_ledgers(ledgers)
    known = cell["known_cost_usd"]
    unknown = cell["unknown_cost_calls"]
    if (
        isinstance(known, bool) or not isinstance(known, (int, float))
        or not math.isfinite(known) or known < 0
        or isinstance(unknown, bool) or not isinstance(unknown, int) or unknown < 0
    ):
        raise ValueError("C collection cost accounting is invalid")
    observed = {
        "completed_jobs": cell["completed_jobs"],
        "attempted_shard_planned_calls": cell["planned_calls"],
        "observed_provider_invocations": cell["observed_invocations"],
        "failed_provider_invocations": cell["failed_calls"],
        "known_cost_usd_all_attempts_lower_bound": known,
        "unknown_cost_calls": unknown,
        "total_cost_usd": known if unknown == 0 else None,
    }
    record = {
        "model": model,
        "reasoning": cell["reasoning"],
        "role": cell["role"],
        "status": cell["status"],
        "stop_reason": cell["stop_reason"],
        "selection_manifest_sha256": seal["selection_manifest_sha256"],
        "selected_condition_index": seal["selected_condition_index"],
        "selected_order": seal["selected_order"],
        "expected_full_cell_jobs": 180,
        "expected_full_cell_calls": 1380 if model in analysis.protocol.REVERSE_MODELS else 1350,
        "raw_evidence_sources": [
            {"path": _evidence_pin(ledger)["path"],
             "sha256": _evidence_pin(ledger)["sha256"], "complete": ledger["complete"]}
            for ledger in ledgers
        ],
        "observed_accounting": observed,
        "analysis": None,
        "arm_effects": None,
        "effect_status": "not_estimable_from_incomplete_cell",
    }
    if cell["status"] != "complete":
        if cell["status"] == "not_started" and (ledgers or cell["completed_jobs"] or cell["observed_invocations"]):
            raise ValueError("C not-started cell contains study evidence")
        return record, None
    if len(logical_ledgers) != 30 or any(not ledger["complete"] for ledger in logical_ledgers):
        raise ValueError("C complete cell lacks thirty complete raw shards")
    selection_path = ROOT / seal["path"]
    evidence_paths = [ROOT / _evidence_pin(ledger)["path"] for ledger in logical_ledgers]
    full, settled = _settled_analysis(selection_path, evidence_paths, model)
    totals = full["totals"]
    if (
        full["model"] != model
        or full["reasoning"] != cell["reasoning"]
        or full["role"] != cell["role"]
        or full["selection_manifest_sha256"] != seal["selection_manifest_sha256"]
        or totals["completed_decisions"] != cell["completed_jobs"]
        or totals["planned_calls"] != cell["planned_calls"]
        or totals["observed_provider_invocations"] != cell["observed_invocations"]
        or totals["failed_provider_invocations"] != cell["failed_calls"]
        or totals["unknown_cost_calls"] != unknown - settled
        or not math.isclose(totals["known_cost_usd_all_attempts"], known, rel_tol=0, abs_tol=1e-10)
    ):
        raise ValueError("C full-cell effects differ from collection raw accounting")
    record.update({
        "analysis": full,
        "arm_effects": _effects(full),
        "effect_status": "estimated_from_complete_raw_cell",
        "settled_provider_429_calls": settled,
    })
    return record, full


def build_report(collection_path: Path = DEFAULT_COLLECTION) -> dict:
    """Regenerate status and every available effect from pinned local raw bytes."""
    schema = json.loads(collection_path.read_text()).get("schema")
    if schema == collection_verifier.SCHEMA:
        collection = collection_verifier.verify_collection_manifest(collection_path)
    elif schema == bridge_verifier.SCHEMA:
        collection = bridge_verifier.verify(collection_path)
    elif schema == gemini_s06_verifier.SCHEMA:
        collection = gemini_s06_verifier.verify(collection_path)
    elif schema == composed_verifier.SCHEMA:
        collection = composed_verifier.verify(collection_path)
    elif schema == provider429_verifier.SCHEMA:
        collection = provider429_verifier.verify(collection_path)
    else:
        raise ValueError("C collection uses an unrecognized provenance schema")
    staged = staged_tasks.verify_manifest()
    seals = {item["model"]: item for item in staged["selection_seals"]}
    if (
        collection["status"] not in ("complete_raw_revalidated", "partial_raw_revalidated")
        or len(collection["cells"]) != 4
        or set(seals) != set(analysis.PRIMARY_MODELS) | {analysis.SENSITIVITY_MODEL}
        or [cell["model"] for cell in collection["cells"]] != [
            item["model"] for item in staged["selection_seals"]
        ]
    ):
        raise ValueError("C final collection does not cover the frozen four-setting roster")
    reports, complete_analyses = {}, []
    for cell in collection["cells"]:
        report, full = _cell_report(cell, seals[cell["model"]])
        reports[cell["model"]] = report
        if full is not None:
            complete_analyses.append(full)
    complete = len(complete_analyses)
    partial = sum(report["status"] == "study_partial" for report in reports.values())
    not_started = sum(report["status"] == "not_started" for report in reports.values())
    expected_status = "complete_raw_revalidated" if complete == 4 else "partial_raw_revalidated"
    if collection["status"] != expected_status or complete + partial + not_started != 4:
        raise ValueError("C final collection and cell statuses disagree")
    full_report = analysis.combine_cells(complete_analyses) if complete == 4 else None
    known_cost = math.fsum(report["observed_accounting"]["known_cost_usd_all_attempts_lower_bound"] for report in reports.values())
    unknown_calls = sum(report["observed_accounting"]["unknown_cost_calls"] for report in reports.values())
    body = {
        "schema": SCHEMA,
        "status": expected_status,
        "classification": "post_hoc_worst_case_defense_stress_test",
        "collection_sha256": collection["collection_sha256"],
        "staged_manifest_sha256": staged["staged_manifest_sha256"],
        "matched_non_off_primary": {model: reports[model] for model in analysis.PRIMARY_MODELS},
        "unavailable_matched_primary": {
            "model": analysis.SENSITIVITY_MODEL,
            "reasoning": "non_off_unavailable",
            "status": "operationally_unavailable",
        },
        "claude_none_sensitivity": reports[analysis.SENSITIVITY_MODEL],
        "full_four_setting_report": full_report,
        "aggregate_accounting": {
            "complete_cells": complete,
            "study_partial_cells": partial,
            "not_started_cells": not_started,
            "completed_jobs": sum(report["observed_accounting"]["completed_jobs"] for report in reports.values()),
            "observed_provider_invocations": sum(report["observed_accounting"]["observed_provider_invocations"] for report in reports.values()),
            "failed_provider_invocations": sum(report["observed_accounting"]["failed_provider_invocations"] for report in reports.values()),
            "known_cost_usd_all_attempts_lower_bound": known_cost,
            "unknown_cost_calls": unknown_calls,
            "total_cost_usd": known_cost if unknown_calls == 0 else None,
        },
        "model_pooling": "none",
        "interpretation_limits": [
            "Only complete 180-job cells have six-arm efficacy, utility and coverage estimates.",
            "Stopped or unstarted cells are explicitly reported with null effects; observed cost is a lower bound when a call cost is unknown.",
            "Claude reasoning-none is a sensitivity cell and never fills the unavailable matched non-off primary cell.",
        ],
    }
    return {**body, "report_sha256": _digest(body)}


def verify_report_file(path: Path = DEFAULT_REPORT, *, collection_path: Path = DEFAULT_COLLECTION) -> dict:
    saved = json.loads(Path(path).read_text())
    body = {key: value for key, value in saved.items() if key != "report_sha256"}
    if saved.get("report_sha256") != _digest(body) or saved != build_report(collection_path):
        raise ValueError("C final report differs from strict raw regeneration")
    return saved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", type=Path, default=DEFAULT_COLLECTION)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.output and args.verify:
        parser.error("choose --output or --verify")
    report = verify_report_file(args.verify, collection_path=args.collection) if args.verify else build_report(args.collection)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(f"WROTE {args.output} {report['report_sha256']}")
    elif args.verify:
        print(f"PASS Experiment C final report {report['report_sha256']}")
    else:
        print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
