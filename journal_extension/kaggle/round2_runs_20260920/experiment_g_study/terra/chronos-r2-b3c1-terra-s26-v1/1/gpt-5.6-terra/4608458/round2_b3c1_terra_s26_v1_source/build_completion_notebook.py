"""Mechanically package the frozen protocol for Kaggle's existing notebook UI."""

import argparse
import ast
import base64
import gzip
import hashlib
import inspect
import json
import math
from pathlib import Path

import completion_protocol as protocol

HERE = Path(__file__).resolve().parent


def literal_constants(path):
    values = {}
    for node in ast.parse(path.read_text()).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        if not isinstance(node.targets[0], ast.Name):
            continue
        value = node.value
        if (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                and value.func.attr == "strip" and isinstance(value.func.value, ast.Constant)):
            values[node.targets[0].id] = value.func.value.value.strip()
        else:
            try:
                values[node.targets[0].id] = ast.literal_eval(value)
            except (ValueError, TypeError):
                pass
    return values


def fixtures():
    records = {}
    files = {"b3": "chronos_software_release_b3_confirmation_batch.py",
             "c1": "chronos_microgrid_c1_pair.py"}
    for sid, filename in files.items():
        path = HERE / filename
        c = literal_constants(path)
        records[sid] = dict(
            source=filename, source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            payloads=c.get("PAYLOADS", c.get("MICROGRID_C1_PAYLOADS")),
            hashes=c.get("PAYLOAD_HASHES", c.get("MICROGRID_C1_HASHES")),
            natural=c["NATURAL_ORDER"], attack=c["ATTACK_ORDER"],
            arrivals=c["NATURAL_ARRIVALS_MS"], system=c["SYSTEM_PROMPT"],
            final_prompt=c["FINAL_PROMPT"], target=c["TARGET_CHOICE"],
        )
        protocol.validate_fixture(records[sid])
    return records


def preflight_jobs(jobs):
    select = {("c1", "stateful", "natural"), ("c1", "stateful", "attack"),
              ("b3", "stateless", "natural"), ("b3", "stateless", "attack"),
              ("b3", "control", "simultaneous"), ("b3", "barrier", "canonical"),
              ("b3", "budget", "1")}
    return [j for j in jobs if j["rep"] == 1 and (
        (j["scenario"], j["mode"], j["condition"]) in select or
        (j["scenario"] == "c1" and j["mode"] == "consistency"))]


def execution_cell(model, phase, checkpoint_text="", directory="/kaggle/working/chronos_completion_20260905", ceiling_usd=None):
    """Carry audited trials and their cost into a fresh hosted kernel."""
    name = f"chronos-completion-{'terra' if model == protocol.MODELS[0] else 'claude'}-{phase}"
    seed = ""
    if checkpoint_text:
        encoded = base64.b64encode(gzip.compress(checkpoint_text.encode(), mtime=0)).decode()
        seed = f'''import base64, gzip
CHECKPOINT_TEXT = gzip.decompress(base64.b64decode({encoded!r})).decode()
checkpoint_path = Path({directory!r}) / (EXPECTED_MODEL.replace("/", "_") + ".jsonl")
checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
if checkpoint_path.exists():
    if not checkpoint_path.read_text().startswith(CHECKPOINT_TEXT):
        raise ValueError("Existing checkpoint does not extend the audited seed")
else:
    with checkpoint_path.open("x", encoding="utf-8") as checkpoint_file:
        checkpoint_file.write(CHECKPOINT_TEXT)
'''
    setup = ""
    if phase == "remaining":
        setup = f"JOBS = jobs_for(EXPECTED_MODEL, FIXTURES)\nCOST_CEILING_USD = {2.6 if model == protocol.MODELS[0] else 3.6}\n"
    elif phase == "repair":
        events = [json.loads(line) for line in checkpoint_text.splitlines()]
        failed_job = [e["job"]["id"] for e in events if e["event"] == "job_error"][-1]
        spent = sum(e.get("cost_usd") or 0 for e in events if e["event"] in ("call_complete", "call_failed"))
        setup = f"JOBS = [j for j in jobs_for(EXPECTED_MODEL, FIXTURES) if j['id'] == {failed_job!r}]\nCOST_CEILING_USD = {spent + .10!r}\n"
    if ceiling_usd is not None:
        if phase != "remaining" or not math.isfinite(ceiling_usd) or ceiling_usd <= 0:
            raise ValueError("Explicit positive spending ceiling applies only to remaining jobs")
        setup += f"COST_CEILING_USD = {ceiling_usd!r}\n"
    return f'''import kaggle_benchmarks as kbench
{setup}{seed}
@kbench.task(name={name!r}, description="Frozen new-scenario completion with raw evidence and cost controls", version=1)
def completion_task(llm) -> float:
    if getattr(llm, "model", None) != EXPECTED_MODEL:
        raise ValueError("Unexpected model: no experiment calls made")
    result = run_jobs(kbench, llm, FIXTURES, JOBS,
                      {directory!r}, COST_CEILING_USD)
    return 1.0

COMPLETION_RESULT = completion_task.run(kbench.llms[EXPECTED_MODEL])
'''


def build(model, phase, output, checkpoint=None, directory="/kaggle/working/chronos_completion_20260905", ceiling_usd=None):
    f = fixtures()
    jobs = protocol.jobs_for(model, f)
    if phase == "preflight":
        jobs = preflight_jobs(jobs)
    config = (f"FIXTURES = {f!r}\nEXPECTED_MODEL = {model!r}\nJOBS = jobs_for(EXPECTED_MODEL, FIXTURES)\n"
              f"COST_CEILING_USD = {0.25 if phase == 'preflight' else (2.6 if model == protocol.MODELS[0] else 3.6)}\n")
    if phase == "preflight":
        config += "\n" + inspect.getsource(preflight_jobs) + "\nJOBS = preflight_jobs(JOBS)\n"
    code = (HERE / "completion_protocol.py").read_text()
    checkpoint_text = ""
    if checkpoint:
        import audit_completion_evidence
        audit_completion_evidence.audit([checkpoint])
        checkpoint_text = Path(checkpoint).read_text()
        if any(json.loads(line)["model"] != model for line in checkpoint_text.splitlines()):
            raise ValueError("Checkpoint model differs from requested model")
        completed = {json.loads(line)["job"]["id"] for line in checkpoint_text.splitlines()
                     if json.loads(line)["event"] == "job_complete"}
        jobs = [j for j in jobs if j["id"] not in completed]
        if phase == "repair":
            last_error = [json.loads(line)["job"]["id"] for line in checkpoint_text.splitlines()
                          if json.loads(line)["event"] == "job_error"][-1]
            jobs = [j for j in jobs if j["id"] == last_error]
    elif phase == "repair":
        raise ValueError("Repair requires an audited checkpoint")
    invocation = execution_cell(model, phase, checkpoint_text, directory, ceiling_usd)
    source = "# Generated by build_completion_notebook.py; edit the canonical source.\n" + code + "\n" + config + "\n" + invocation
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".py").write_text(source)
    # One self-contained cell avoids ambiguous CodeMirror focus during browser edits.
    notebook = dict(nbformat=4, nbformat_minor=5, metadata={"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}}, cells=[
        dict(cell_type="code", id="execute-study", execution_count=None, metadata={}, outputs=[], source=source.splitlines(keepends=True))])
    output.with_suffix(".ipynb").write_text(json.dumps(notebook, indent=1))
    print(json.dumps(dict(path=str(output), model=model, phase=phase,
                          jobs=len(jobs), planned_calls=sum(j["calls"] for j in jobs),
                          source_sha256=hashlib.sha256(source.encode()).hexdigest())))
    return source


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=("terra", "claude"), required=True)
    parser.add_argument("--phase", choices=("preflight", "remaining", "repair"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--directory", default="/kaggle/working/chronos_completion_20260905")
    parser.add_argument("--ceiling", type=float, help="Previously authorized cumulative model ceiling")
    args = parser.parse_args()
    build(protocol.MODELS[args.model == "claude"], args.phase, args.output, args.checkpoint, args.directory, args.ceiling)
