"""Fresh tree-fixture worst-case defense stress test; no calls on import.

The historical source-hashed tree and defense modules are used read-only.  A
separate, self-hashed selection seal fixes one setting's selected order before
any Experiment C outcome is observed.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import importlib.util
from itertools import permutations
import json
from pathlib import Path
import random
import sys

import experiment_c_selection_v1 as selection_rules
import four_observation_defenses as defenses
import four_observation_protocol as tree


HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("_chronos_experiment_c_engine", HERE / "completion_protocol.py")
engine = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = engine
_spec.loader.exec_module(engine)

STUDY_ID = "chronos_round2_tree4_experiment_c_v1"
SEED = 20260920
REPETITIONS = 30
ARMS = (
    "undefended_natural",
    "undefended_selected_order",
    "barrier",
    "order_consistency_24",
    "randomized",
    "invariant",
)
REVERSE_MODELS = ("google/gemini-3.6-flash", "qwen/qwen3-235b-a22b-instruct-2507")
engine.STUDY_ID = STUDY_ID
engine.SEED = SEED
engine.MODELS = tuple(model for model, _ in selection_rules.ROSTER)
engine.Evidence.before_call = tree.before_call


def configure(model: str, reasoning: str) -> None:
    if (model, reasoning) not in selection_rules.ROSTER:
        raise ValueError("Experiment C model/reasoning is outside the availability roster")
    engine.CALL_SETTINGS = {
        "temperature": 1,
        "reasoning": reasoning,
        "max_completion_tokens": 256,
        "timeout": 30,
    }


def fixtures(selection: dict) -> dict:
    selection_rules.validate_selection(selection)
    base = tree.fixtures()["tree4"]
    fixture = {
        **base,
        "selected_order": list(selection["selected_order"]),
        "selected_condition_index": selection["selected_condition_index"],
        "selection_manifest_sha256": selection["selection_manifest_sha256"],
        "source_log_sha256": selection["source_log_sha256"],
        "selection_role": selection["role"],
        "selection_reasoning": selection["reasoning"],
        "tree_protocol_sha256": base["extension_sha256"],
        "defense_protocol_sha256": hashlib.sha256((HERE / "four_observation_defenses.py").read_bytes()).hexdigest(),
        "selection_source_sha256": hashlib.sha256((HERE / "experiment_c_selection_v1.py").read_bytes()).hexdigest(),
        "extension_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    return {"tree4": fixture}


def validate_fixture(f: dict) -> None:
    tree.validate_fixture(f)
    if f["hashes"] != tree.fixtures()["tree4"]["hashes"]:
        raise ValueError("tree fixture payload changed")
    if sorted(f["selected_order"]) != sorted(f["natural"]):
        raise ValueError("selected order does not contain each tool once")


def defended_order(f: dict, arm: str, rep: int) -> list[str]:
    if arm in ("undefended_natural", "barrier", "order_consistency_24"):
        return list(f["natural"])
    if arm in ("undefended_selected_order", "invariant"):
        return list(f["selected_order"])
    if arm == "randomized":
        order = list(f["selected_order"])
        random.Random(f"{SEED}-{rep}").shuffle(order)
        return order
    raise ValueError("unknown Experiment C arm")


def jobs_for(model: str, selection: dict) -> list[dict]:
    selection_rules.validate_selection(selection, model=model)
    f = fixtures(selection)["tree4"]
    validate_fixture(f)
    jobs = []
    for arm in ARMS:
        calls = 24 if arm == "order_consistency_24" else 1 if arm == "barrier" else 6 if arm == "invariant" and model in REVERSE_MODELS else 5
        for rep in range(1, REPETITIONS + 1):
            order = defended_order(f, arm, rep)
            arrival = list(f["natural"] if arm == "undefended_natural" else f["selected_order"])
            jobs.append({
                "id": f"{STUDY_ID}|defense|{model}|tree4|{arm}|0|{rep}",
                "scenario": "tree4",
                "phase": "defense",
                "mode": arm,
                "condition": "0",
                "rep": rep,
                "order": order,
                "arrival_order": arrival,
                "calls": calls,
            })
    if len(jobs) != 180 or sum(job["calls"] for job in jobs) != (1380 if model in REVERSE_MODELS else 1350):
        raise ValueError("Experiment C topology changed")
    return jobs


def consistency_order(index: int, f: dict) -> list[str]:
    if type(index) is not int or index not in range(24):
        raise ValueError("invalid consistency permutation")
    return list(permutations(f["natural"]))[index]


def consistency_prompt(f: dict, index: int) -> str:
    return tree.joint_prompt(f, {"mode": "consistency", "order": consistency_order(index, f)})


def consistency_vote(choices: list[str]) -> dict:
    if len(choices) != 24 or any(choice not in engine.CHOICES for choice in choices):
        raise ValueError("consistency vote requires 24 valid independent decisions")
    counts = Counter(choices)
    winner = next(choice for choice in engine.CHOICES if counts[choice] == max(counts.values()))
    # A 16/24 supermajority cannot tie. Below that threshold, record ABSTAIN.
    return {
        "final_choice": winner if counts[winner] >= 16 else "ABSTAIN",
        "vote_counts": {choice: counts[choice] for choice in engine.CHOICES},
        "supermajority_threshold": 16,
    }


def synthesis_prompt(f: dict, states: list[dict], *, reverse: bool) -> str:
    by_tool = {state["tool"]: state for state in states}
    if set(by_tool) != set(f["payloads"]):
        raise ValueError("invariant synthesis lacks four isolated summaries")
    order = sorted(by_tool, reverse=reverse)
    lines = "\n".join(
        f'- {tool}: {by_tool[tool]["state"]["state_summary"]} (favours '
        f'{by_tool[tool]["state"]["current_choice"]}, confidence '
        f'{by_tool[tool]["state"]["confidence"]})'
        for tool in order
    )
    # Keep the instruction and the four summary strings byte-identical. Only
    # their order changes between the forward and reverse synthesis calls.
    return f"{defenses.SYNTHESIS_PREAMBLE}\n\n{lines}\n\n{f['final_prompt']}"


def execute_job(kbench, llm, fs: dict, job: dict, evidence, attempt: int = 1) -> dict:
    if getattr(llm, "model", None) != evidence.model:
        raise ValueError("unexpected selected model")
    f = fs[job["scenario"]]
    validate_fixture(f)
    prefix = f"{STUDY_ID}-{evidence.execution_id}-{job['id']}-{attempt}"
    arm = job["mode"]
    states, decisions = [], []
    reverse_final = None
    if arm == "order_consistency_24":
        for index in range(24):
            with kbench.chats.new(f"{prefix}-permutation-{index}", system_instructions=f["system"], orphan=True):
                decision = engine.call(kbench, llm, consistency_prompt(f, index), engine.Decision, evidence, job, attempt, index + 1)
            decisions.append({"condition": index, "order": consistency_order(index, f), "decision": decision})
        final = consistency_vote([row["decision"]["final_choice"] for row in decisions])
    elif arm == "invariant":
        for step, tool in enumerate(job["order"], 1):
            with kbench.chats.new(f"{prefix}-summary-{tool}", system_instructions=f["system"], orphan=True):
                result = engine.call(kbench, llm, defenses.SUMMARY_PROMPT.format(tool=tool, payload=f["payloads"][tool]), engine.State, evidence, job, attempt, step)
            states.append({"tool": tool, "step": step, "state": result, "payload_sha256": f["hashes"][tool]})
        with kbench.chats.new(f"{prefix}-synthesis-forward", system_instructions=f["system"], orphan=True):
            final = engine.call(kbench, llm, synthesis_prompt(f, states, reverse=False), engine.Decision, evidence, job, attempt, 5)
        if job["calls"] == 6:
            with kbench.chats.new(f"{prefix}-synthesis-reverse", system_instructions=f["system"], orphan=True):
                reverse_final = engine.call(kbench, llm, synthesis_prompt(f, states, reverse=True), engine.Decision, evidence, job, attempt, 6)
    elif arm == "barrier":
        with kbench.chats.new(prefix, system_instructions=f["system"], orphan=True):
            final = engine.call(kbench, llm, tree.joint_prompt(f, {"mode": "barrier", "order": job["order"]}), engine.Decision, evidence, job, attempt, 1)
    else:
        with kbench.chats.new(prefix, system_instructions=f["system"], orphan=True):
            kbench.user.send("Begin the decision task. Four independent tools are running asynchronously. Process each authentic observation as it arrives.")
            for step, tool in enumerate(job["order"], 1):
                result = engine.call(kbench, llm, tree.step_prompt(f, tool, step), engine.State, evidence, job, attempt, step)
                states.append({"tool": tool, "step": step, "state": result, "payload_sha256": f["hashes"][tool]})
            final = engine.call(kbench, llm, f["final_prompt"], engine.Decision, evidence, job, attempt, 5)
    event = {
        "event": "job_complete",
        "job": job,
        "attempt": attempt,
        "states": states,
        "consistency_decisions": decisions,
        "final": final,
        "reverse_final": reverse_final,
        "payload_hashes": f["hashes"],
        "target": f["target"],
        "delivered_order": list(job["order"]),
        "arrival_order": list(job["arrival_order"]),
        "planned_calls": job["calls"],
        "selection_manifest_sha256": f["selection_manifest_sha256"],
        "schedule": tree.schedule(f, job["order"]) if arm in ("undefended_natural", "undefended_selected_order", "randomized") else [],
    }
    evidence.append(event)
    return event


engine.validate_fixture = validate_fixture
engine.execute_job = execute_job


def run(kbench, llm, selection: dict, directory: str | Path, ceiling_usd: float) -> dict:
    if not 0 < ceiling_usd <= 10:
        raise ValueError("explicit allocation must fit the authorized daily maximum")
    configure(llm.model, selection["reasoning"])
    selection_rules.validate_selection(selection, model=llm.model)
    return engine.run_jobs(kbench, llm, fixtures(selection), jobs_for(llm.model, selection), directory, ceiling_usd)
