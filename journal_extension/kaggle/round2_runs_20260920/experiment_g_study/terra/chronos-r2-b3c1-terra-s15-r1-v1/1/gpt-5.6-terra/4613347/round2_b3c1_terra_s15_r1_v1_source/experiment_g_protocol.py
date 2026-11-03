"""Frozen B3/C1 cells on the matched roster for round-two Experiment G.

The 5 September B3 and C1 fixtures and job matrix, run on a private, unpatched
instance of ``completion_protocol.py`` for Terra-low, Gemini-minimal and Qwen-low.
No model call occurs on import.
Plan: specs/journal-extension-sep14/round2-g-b3c1-matched-plan-2026-10-08.md.
"""

from contextlib import contextmanager
import importlib.util
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


engine = _private("_chronos_g_engine", "completion_protocol.py")
loader = _private("_chronos_g_fixture_loader", "build_completion_notebook.py")

TARGETS = {"b3": "B", "c1": "C"}
SEED = 20261008
CELLS = {
    "openai/gpt-5.6-terra": ("low", "matched_non_off_primary", "terra_low"),
    "google/gemini-3.6-flash": ("minimal", "matched_non_off_primary", "gemini_minimal"),
    "qwen/qwen3-235b-a22b-instruct-2507": ("low", "matched_non_off_primary", "qwen_low"),
}


def cell(model, phase="study"):
    if model not in CELLS:
        raise ValueError("Model is outside the frozen Experiment G roster")
    if phase != "study":
        raise ValueError("Experiment G has only a study phase")
    reasoning, role, tag = CELLS[model]
    return {"model": model, "reasoning": reasoning, "role": role, "phase": phase,
            "study_id": f"chronos_round2_b3c1_{tag}_{phase}_v1"}


def call_settings(model):
    return {"temperature": 1, "reasoning": cell(model)["reasoning"],
            "max_completion_tokens": 256, "timeout": 30}


@contextmanager
def cell_runtime(model, phase="study"):
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


def fixtures():
    result = loader.fixtures()
    if {sid: f["target"] for sid, f in result.items()} != TARGETS:
        raise ValueError("B3/C1 fixtures changed")
    for f in result.values():
        engine.validate_fixture(f)
    return result


def jobs_for(model, phase="study"):
    chosen = cell(model, phase)
    old = engine.MODELS
    engine.MODELS = (model,)
    try:
        base = engine.jobs_for(model, fixtures(), include_existing=True)
    finally:
        engine.MODELS = old
    jobs = [dict(job, id=f"{chosen['study_id']}|{job['id']}") for job in sorted(base, key=lambda j: j["id"])]
    random.Random(SEED).shuffle(jobs)
    return jobs


def identity(model, phase="study"):
    chosen = cell(model, phase)
    return engine.digest(json.dumps({"study": chosen["study_id"], "model": model,
                                     "fixtures": fixtures(), "settings": call_settings(model)},
                                    sort_keys=True))
