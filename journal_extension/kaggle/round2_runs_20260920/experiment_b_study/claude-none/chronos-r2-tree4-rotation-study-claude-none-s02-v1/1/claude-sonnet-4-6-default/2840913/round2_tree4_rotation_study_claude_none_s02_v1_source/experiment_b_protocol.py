"""Frozen tree-fixture label rotation for round-two Experiment B.

Only option letters change. The four tool reports, delivery orders, model
prompts, and numeric values retain their original semantic identities.
No model call occurs on import.
"""

from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import sys


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "_chronos_experiment_b_tree", HERE / "four_observation_protocol.py"
)
tree = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tree
spec.loader.exec_module(tree)
engine = tree.engine

ROTATIONS = {
    0: {"A": "A", "B": "B", "C": "C"},
    1: {"A": "B", "B": "C", "C": "A"},
    2: {"A": "C", "B": "A", "C": "B"},
}
SEMANTIC_TARGET = "C"
SEED = 20260920
REPETITIONS = 30
CELLS = {
    "openai/gpt-5.6-terra": ("low", "matched_non_off_primary", "terra_low"),
    "google/gemini-3.6-flash": ("minimal", "matched_non_off_primary", "gemini_minimal"),
    "qwen/qwen3-235b-a22b-instruct-2507": ("low", "matched_non_off_primary", "qwen_low"),
    "anthropic/claude-sonnet-4-6@default": ("none", "reasoning_off_sensitivity", "claude_none"),
}
UNAVAILABLE_PRIMARY = {
    "model": "anthropic/claude-sonnet-4-6@default",
    "reasoning": "lowest_supported_non_off",
    "status": "operationally_unavailable_after_bounded_retry",
}


def cell(model, phase="study"):
    if model not in CELLS:
        raise ValueError("Model is outside the frozen Experiment B roster")
    if phase not in ("pilot", "study"):
        raise ValueError("Unknown Experiment B phase")
    reasoning, role, tag = CELLS[model]
    return {
        "model": model,
        "reasoning": reasoning,
        "role": role,
        "phase": phase,
        "study_id": f"chronos_round2_tree4_label_rotation_{tag}_{phase}_v1",
    }


def call_settings(model):
    return {
        "temperature": 1,
        "reasoning": cell(model)["reasoning"],
        "max_completion_tokens": 256,
        "timeout": 30,
    }


@contextmanager
def cell_runtime(model, phase="study"):
    """Keep the historical engine's module globals private to one cell."""
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


def inverse_mapping(rotation):
    if rotation not in ROTATIONS:
        raise ValueError("Unknown label rotation")
    return {literal: semantic for semantic, literal in ROTATIONS[rotation].items()}


def semantic_choice(rotation, literal_choice):
    try:
        return inverse_mapping(rotation)[literal_choice]
    except KeyError as error:
        raise ValueError("Invalid literal option letter") from error


def fixtures():
    base = tree.fixtures()["tree4"]
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result = {}
    for rotation, mapping in ROTATIONS.items():
        payloads = {}
        for tool, raw in base["payloads"].items():
            report = json.loads(raw)
            if set(report["values"]) != set(mapping):
                raise ValueError("Source report has unexpected option labels")
            report["values"] = {
                mapping[semantic]: value
                for semantic, value in report["values"].items()
            }
            payloads[tool] = json.dumps(report, sort_keys=True)
        fixture = {
            **base,
            "payloads": payloads,
            "hashes": {tool: engine.digest(raw) for tool, raw in payloads.items()},
            "target": mapping[SEMANTIC_TARGET],
            "rotation": rotation,
            "semantic_to_literal": mapping,
            "literal_to_semantic": inverse_mapping(rotation),
            "semantic_target": SEMANTIC_TARGET,
            "rotation_source_sha256": source_hash,
        }
        validate_fixture(fixture, base)
        result[f"tree4_rot{rotation}"] = fixture
    return result


def validate_fixture(fixture, base=None):
    """Prove inverse rotation exactly recovers the frozen semantic report."""
    base = base or tree.fixtures()["tree4"]
    tree.validate_fixture(fixture)
    rotation = fixture["rotation"]
    mapping = ROTATIONS[rotation]
    inverse = inverse_mapping(rotation)
    if (
        fixture["semantic_to_literal"] != mapping
        or fixture["literal_to_semantic"] != inverse
        or fixture["semantic_target"] != SEMANTIC_TARGET
        or fixture["target"] != mapping[SEMANTIC_TARGET]
        or fixture["natural"] != base["natural"]
        or fixture["attack"] != base["attack"]
        or fixture["arrivals"] != base["arrivals"]
        or fixture["system"] != base["system"]
        or fixture["final_prompt"] != base["final_prompt"]
        or fixture["engine_sha256"] != base["engine_sha256"]
        or fixture["extension_sha256"] != base["extension_sha256"]
        or fixture["rotation_source_sha256"]
        != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    ):
        raise ValueError("Label rotation changed a frozen fixture field")
    for tool, raw in fixture["payloads"].items():
        rotated = json.loads(raw)
        restored = {
            **rotated,
            "values": {
                inverse[literal]: value
                for literal, value in rotated["values"].items()
            },
        }
        if restored != json.loads(base["payloads"][tool]):
            raise ValueError("Inverse label mapping did not restore source report")
    if rotation == 0 and fixture["payloads"] != base["payloads"]:
        raise ValueError("Identity rotation changed source payload bytes")


def jobs_for(model, phase="study"):
    chosen = cell(model, phase)
    fs = fixtures()
    jobs = []
    rotations = (1,) if phase == "pilot" else ROTATIONS
    repetitions = 1 if phase == "pilot" else REPETITIONS
    for rotation in rotations:
        scenario = f"tree4_rot{rotation}"
        fixture = fs[scenario]
        for rep in range(1, repetitions + 1):
            for condition in ("natural", "attack"):
                jobs.append(
                    {
                        "id": (
                            f"{chosen['study_id']}|{phase}|{model}|{scenario}|"
                            f"stateful|{condition}|{rep}"
                        ),
                        "scenario": scenario,
                        "mode": "stateful",
                        "condition": condition,
                        "rep": rep,
                        "phase": phase,
                        "order": list(fixture[condition]),
                        "calls": 5,
                    }
                )
    if phase == "study":
        random.Random(SEED).shuffle(jobs)
    return jobs


def identity(model, phase="study"):
    chosen = cell(model, phase)
    return engine.digest(
        json.dumps(
            {
                "study": chosen["study_id"],
                "model": model,
                "fixtures": fixtures(),
                "settings": call_settings(model),
            },
            sort_keys=True,
        )
    )

