"""Freeze Experiment C order selection from complete, pinned tree-study logs.

This file performs no model calls.  The source study's strict collection audit
is a separate launch gate; this seal additionally requires all 690 completed
jobs and the ten complete stateful 24-order panels used for selection.
"""

from __future__ import annotations

import hashlib
from itertools import permutations
import json
from pathlib import Path

import four_observation_protocol as tree


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
AMENDMENT = ROOT / "specs/journal-extension-sep14/round2-bc-availability-amendment-2026-09-23.md"
AMENDMENT_SHA256 = "5ab050c777c309138b811c29f347f75816419d8811df5fc54189d533d7ceb6f5"
SCHEMA = "chronos.experiment-c-selection.v1"
ROSTER = {
    ("openai/gpt-5.6-terra", "low"): "primary",
    ("google/gemini-3.6-flash", "minimal"): "primary",
    ("qwen/qwen3-235b-a22b-instruct-2507", "low"): "primary",
    ("anthropic/claude-sonnet-4-6@default", "none"): "sensitivity",
}


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_hash(value: dict) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _source_events(source_files: list[Path], root: Path) -> tuple[list[dict], list[dict], str]:
    if not source_files or len(source_files) != len(set(source_files)):
        raise ValueError("source logs must be nonempty and unique")
    parts = []
    for path in source_files:
        resolved = path.resolve(strict=True)
        relative = resolved.relative_to(root.resolve()).as_posix()
        raw = resolved.read_bytes()
        if not raw or not raw.endswith(b"\n"):
            raise ValueError(f"source log is empty or not newline terminated: {relative}")
        parts.append((relative, raw))
    parts.sort(key=lambda item: item[0])
    records = [{"path": relative, "sha256": sha256(raw), "bytes": len(raw)} for relative, raw in parts]
    events = []
    for relative, raw in parts:
        for number, line in enumerate(raw.splitlines(), 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid source JSONL {relative}:{number}") from error
            if not isinstance(event, dict):
                raise ValueError(f"nonobject source event {relative}:{number}")
            events.append(event)
    return events, records, sha256(b"".join(raw for _, raw in parts))


def _select(events: list[dict], model: str) -> dict:
    fixture = tree.fixtures()["tree4"]
    expected_orders = [list(order) for order in permutations(fixture["natural"])]
    completed = [event for event in events if event.get("event") == "job_complete"]
    ids = [event.get("job", {}).get("id") for event in completed]
    if len(completed) != 690 or len(set(ids)) != 690:
        raise ValueError("selection source requires 690 unique completed tree-study jobs")
    if any(event.get("model") != model for event in events):
        raise ValueError("source model mismatch")
    identities = {event.get("identity") for event in events}
    if len(identities) != 1 or not next(iter(identities)):
        raise ValueError("selection source has mixed or missing scientific identity")
    panels: dict[tuple[int, int], str] = {}
    for event in completed:
        job = event["job"]
        if job.get("phase") != "study" or job.get("scenario") != "tree4":
            raise ValueError("source contains a non-study trial")
        if job.get("mode") != "permutation_stateful":
            continue
        rep, condition = job.get("rep"), job.get("condition")
        if type(rep) is not int or rep not in range(1, 11) or str(condition) not in {str(i) for i in range(24)}:
            raise ValueError("unexpected permutation panel coordinate")
        condition = int(condition)
        if job.get("order") != expected_orders[condition]:
            raise ValueError("permutation condition changed its frozen order")
        key = (rep, condition)
        if key in panels:
            raise ValueError("duplicate permutation panel cell")
        choice = event.get("final", {}).get("final_choice")
        if choice not in tree.engine.CHOICES:
            raise ValueError("invalid panel final choice")
        panels[key] = choice
    if set(panels) != {(rep, condition) for rep in range(1, 11) for condition in range(24)}:
        raise ValueError("selection source lacks ten complete 24-order panels")
    successes = [sum(panels[(rep, condition)] == fixture["target"] for rep in range(1, 11)) for condition in range(24)]
    selected = min(index for index, value in enumerate(successes) if value == max(successes))
    study_ids = {event["job"]["id"].split("|", 1)[0] for event in completed}
    if len(study_ids) != 1:
        raise ValueError("source studies were mixed")
    return {
        "source_study_id": next(iter(study_ids)),
        "source_identity": next(iter(identities)),
        "selected_condition_index": selected,
        "selected_order": expected_orders[selected],
        "target_successes": successes[selected],
        "condition_target_successes": successes,
    }


def make_selection(*, model: str, reasoning: str, role: str, source_files: list[Path], root: Path = ROOT) -> dict:
    if ROSTER.get((model, reasoning)) != role:
        raise ValueError("setting/role is outside the frozen B/C availability roster")
    if sha256(AMENDMENT.read_bytes()) != AMENDMENT_SHA256:
        raise ValueError("B/C availability amendment changed")
    events, records, aggregate = _source_events(source_files, root)
    body = {
        "schema": SCHEMA,
        "model": model,
        "reasoning": reasoning,
        "role": role,
        "amendment_sha256": AMENDMENT_SHA256,
        "source_logs": records,
        "source_log_sha256": aggregate,
        "selection_repetitions": list(range(1, 11)),
        "objective": "target_C_choice_rate",
        "tie_break": "lowest_frozen_condition_index",
        **_select(events, model),
    }
    return {**body, "selection_manifest_sha256": canonical_hash(body)}


def validate_selection(selection: dict, *, model: str | None = None, reasoning: str | None = None) -> None:
    body = {key: value for key, value in selection.items() if key != "selection_manifest_sha256"}
    if selection.get("schema") != SCHEMA or canonical_hash(body) != selection.get("selection_manifest_sha256"):
        raise ValueError("selection seal is malformed or changed")
    if selection.get("amendment_sha256") != AMENDMENT_SHA256:
        raise ValueError("selection uses the wrong B/C availability amendment")
    if ROSTER.get((selection.get("model"), selection.get("reasoning"))) != selection.get("role"):
        raise ValueError("selection has an unavailable setting or wrong inferential role")
    if model is not None and selection["model"] != model:
        raise ValueError("selection model mismatch")
    if reasoning is not None and selection["reasoning"] != reasoning:
        raise ValueError("selection reasoning mismatch")
    if selection.get("selection_repetitions") != list(range(1, 11)) or selection.get("objective") != "target_C_choice_rate" or selection.get("tie_break") != "lowest_frozen_condition_index":
        raise ValueError("selection rule changed")
    if len(selection.get("condition_target_successes", [])) != 24:
        raise ValueError("selection lacks all 24 condition rates")
    successes = selection["condition_target_successes"]
    if any(type(value) is not int or value not in range(11) for value in successes):
        raise ValueError("invalid condition success count")
    condition = selection.get("selected_condition_index")
    if type(condition) is not int or condition not in range(24):
        raise ValueError("invalid selected condition")
    expected = min(index for index, value in enumerate(successes) if value == max(successes))
    if condition != expected or selection.get("target_successes") != successes[condition]:
        raise ValueError("selected condition violates objective or tie break")
    orders = [list(order) for order in permutations(tree.fixtures()["tree4"]["natural"])]
    if selection.get("selected_order") != orders[condition]:
        raise ValueError("selected order is inconsistent with the frozen condition")
    records = selection.get("source_logs")
    if not isinstance(records, list) or not records or not all(isinstance(item, dict) and set(item) == {"path", "sha256", "bytes"} for item in records):
        raise ValueError("source log records are missing")
    if not isinstance(selection.get("source_log_sha256"), str) or len(selection["source_log_sha256"]) != 64:
        raise ValueError("source log SHA256 is missing")


def verify_selection_source(selection: dict, *, root: Path = ROOT) -> None:
    validate_selection(selection)
    paths = [root / item["path"] for item in selection["source_logs"]]
    rebuilt = make_selection(model=selection["model"], reasoning=selection["reasoning"], role=selection["role"], source_files=paths, root=root)
    if rebuilt != selection:
        raise ValueError("selection source or outcome-derived order changed")
