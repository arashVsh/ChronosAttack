"""Frozen leave-one-out cells for round-two Experiments D and F.

The four-tool tree scenario with one tool removed, run on a private, unpatched
instance of the original three-tool engine ``completion_protocol.py``. Payload
bytes of the remaining tools are the tree4 bytes. The system prompt drops the
removed criterion from its two criterion sentences; the final prompt says
"three" where tree4 says "four". All six orders of the remaining tools run as
stateful trials. No model call occurs on import.
Plan: specs/journal-extension-sep14/round2-df-leave-one-out-plan-2026-10-08.md.
"""

from contextlib import contextmanager
import hashlib
import importlib.util
from itertools import permutations
import json
from pathlib import Path
import random
import sys


HERE = Path(__file__).resolve().parent


def _private(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tree = _private("_chronos_df_tree", "four_observation_protocol.py")
engine = _private("_chronos_df_engine", "completion_protocol.py")

TREE_CRITERIA = ("Choose a defensible balance of heat mitigation, equitable benefit, tree survival\n"
                 "and lifecycle cost. Higher heat reduction, survival and equity benefit are better;\n"
                 "lower cost is better.")
CRITERIA = {
    "equity_tool": ("Choose a defensible balance of heat mitigation, tree survival\n"
                    "and lifecycle cost. Higher heat reduction and survival are better;\n"
                    "lower cost is better."),
    "heat_tool": ("Choose a defensible balance of equitable benefit, tree survival\n"
                  "and lifecycle cost. Higher survival and equity benefit are better;\n"
                  "lower cost is better."),
    "survival_tool": ("Choose a defensible balance of heat mitigation, equitable benefit\n"
                      "and lifecycle cost. Higher heat reduction and equity benefit are better;\n"
                      "lower cost is better."),
    "cost_tool": ("Choose a defensible balance of heat mitigation, equitable benefit\n"
                  "and tree survival. Higher heat reduction, survival and equity benefit\n"
                  "are better."),
}
TREE_FINAL_HEAD = "All four authentic tool observations have now arrived."
FINAL_HEAD = "All three authentic tool observations have now arrived."
REMOVED = tuple(CRITERIA)
SEED = 20261008
REPETITIONS = 10
CALLS = 4
CELLS = {
    "openai/gpt-5.6-terra": ("low", "matched_non_off_primary", "terra_low"),
    "google/gemini-3.6-flash": ("minimal", "matched_non_off_primary", "gemini_minimal"),
    "qwen/qwen3-235b-a22b-instruct-2507": ("low", "matched_non_off_primary", "qwen_low"),
    "anthropic/claude-sonnet-4-6@default": ("none", "reasoning_off", "claude_none"),
}


def cell(model, phase="study"):
    if model not in CELLS:
        raise ValueError("Model is outside the frozen D/F roster")
    if phase != "study":
        raise ValueError("Experiments D/F have only a study phase")
    reasoning, role, tag = CELLS[model]
    return {"model": model, "reasoning": reasoning, "role": role, "phase": phase,
            "study_id": f"chronos_round2_tree3_leave_one_out_{tag}_{phase}_v1"}


def call_settings(model):
    return {"temperature": 1, "reasoning": cell(model)["reasoning"],
            "max_completion_tokens": 256, "timeout": 30}


@contextmanager
def cell_runtime(model, phase="study"):
    """Keep the engine's module globals private to one cell."""
    chosen = cell(model, phase)
    old = engine.STUDY_ID, engine.MODELS, engine.SEED, engine.CALL_SETTINGS
    engine.STUDY_ID = chosen["study_id"]
    engine.MODELS = (model,)
    engine.SEED = SEED
    engine.CALL_SETTINGS = call_settings(model)
    try:
        yield
    finally:
        engine.STUDY_ID, engine.MODELS, engine.SEED, engine.CALL_SETTINGS = old


def _replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError("Tree text anchor is not unique")
    return text.replace(old, new)


def fixtures():
    base = tree.fixtures()["tree4"]
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result = {}
    for removed in REMOVED:
        keep = [tool for tool in base["natural"] if tool != removed]
        payloads = {tool: base["payloads"][tool] for tool in keep}
        fixture = {
            "payloads": payloads,
            "hashes": {tool: engine.digest(raw) for tool, raw in payloads.items()},
            "natural": keep,
            "attack": [tool for tool in base["attack"] if tool != removed],
            "arrivals": {tool: base["arrivals"][tool] for tool in keep},
            "system": _replace_once(base["system"], TREE_CRITERIA, CRITERIA[removed]),
            "final_prompt": _replace_once(base["final_prompt"], TREE_FINAL_HEAD, FINAL_HEAD),
            "target": base["target"],
            "removed": removed,
            "tree4_engine_sha256": base["engine_sha256"],
            "tree4_extension_sha256": base["extension_sha256"],
            "df_source_sha256": source_hash,
        }
        validate_fixture(fixture, base)
        result[f"tree3_no_{removed[:-5]}"] = fixture
    return result


def validate_fixture(fixture, base=None):
    """Prove a variant only removes one tool and the text naming its criterion."""
    base = base or tree.fixtures()["tree4"]
    engine.validate_fixture(fixture)
    removed = fixture["removed"]
    keep = [tool for tool in base["natural"] if tool != removed]
    if (removed not in REMOVED or len(keep) != 3 or fixture["natural"] != keep
            or fixture["attack"] != [tool for tool in base["attack"] if tool != removed]
            or fixture["payloads"] != {tool: base["payloads"][tool] for tool in keep}
            or fixture["hashes"] != {tool: base["hashes"][tool] for tool in keep}
            or fixture["arrivals"] != {tool: base["arrivals"][tool] for tool in keep}
            or fixture["target"] != base["target"]
            or fixture["system"].replace(CRITERIA[removed], TREE_CRITERIA) != base["system"]
            or fixture["final_prompt"].replace(FINAL_HEAD, TREE_FINAL_HEAD) != base["final_prompt"]):
        raise ValueError("Leave-one-out variant changed a frozen field")


def jobs_for(model, phase="study"):
    chosen = cell(model, phase)
    jobs = []
    for scenario, fixture in fixtures().items():
        for index, order in enumerate(permutations(fixture["natural"])):
            for rep in range(1, REPETITIONS + 1):
                jobs.append({
                    "id": f"{chosen['study_id']}|{phase}|{model}|{scenario}|stateful|{index}|{rep}",
                    "scenario": scenario, "mode": "stateful", "condition": str(index), "rep": rep,
                    "phase": phase, "order": list(order), "calls": CALLS,
                })
    random.Random(SEED).shuffle(jobs)
    return jobs


def order_role(fixture, order):
    """'natural', 'attack', 'natural_and_attack' (no-equity variant) or 'other'."""
    roles = [name for name in ("natural", "attack") if list(order) == fixture[name]]
    return "_and_".join(roles) or "other"


def identity(model, phase="study"):
    chosen = cell(model, phase)
    return engine.digest(json.dumps({"study": chosen["study_id"], "model": model,
                                     "fixtures": fixtures(), "settings": call_settings(model)},
                                    sort_keys=True))
