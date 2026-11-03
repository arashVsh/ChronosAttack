"""Verify the current research companion without model calls or evidence writes."""

from pathlib import Path
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "kaggle"))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_extensions():
    for name, total in [("df", 960), ("g", 1260)]:
        module = __import__(f"analyze_experiment_{name}_v1")
        expected = json.loads(module.OUT.read_text())
        actual = module.analyze()
        if actual != expected:
            raise ValueError(f"Experiment {name.upper()} differs from raw replay")
        cells = actual["models"] if name == "df" else actual["cells"]
        jobs = sum(c["three_observations"]["completed_jobs"] if name == "df"
                   else c["completed_jobs"] for c in cells.values())
        if jobs != total:
            raise ValueError(f"Incomplete {name}: {jobs}/{total}")
        print(f"PASS {name.upper()}: {jobs}/{total} jobs; saved analysis matches raw replay", flush=True)
    with tempfile.TemporaryDirectory(prefix="chronos-tables-") as temporary:
        tables = __import__("render_final_tables_v1")
        tables.OUT = Path(temporary)
        tables.main()
        generated = sorted(tables.OUT.glob("*.tex"))
        expected = sorted((ROOT / "deliverables/final_report/tables").glob("*.tex"))
        if [p.name for p in generated] != [p.name for p in expected]:
            raise ValueError("Report table set differs from regeneration")
        for path in generated:
            if path.read_bytes() != (ROOT / "deliverables/final_report/tables" / path.name).read_bytes():
                raise ValueError(f"Report table differs: {path.name}")
        print(f"PASS report: {len(generated)} tables regenerate byte for byte", flush=True)


def check_unavailability():
    for resume in (6, 7, 8):
        directory = ROOT / f"kaggle/round2_generated/claude_study_low_s00_r{resume}_task_download"
        ledgers = list(directory.rglob("*.jsonl"))
        if len(ledgers) != 1:
            raise ValueError(f"Missing Claude-low excluded provenance r{resume}")
        events = [json.loads(line) for line in ledgers[0].read_text().splitlines()]
        attempts = sorted(e["attempt"] for e in events
                          if e.get("event") == "call_failed"
                          and e.get("job_id", "").endswith("|permutation_stateful|5|9")
                          and e.get("step") == 4
                          and e.get("error_type") == "LengthFinishReasonError")
        if attempts != [1, 2, 3]:
            raise ValueError(f"Claude-low cap-failure provenance differs in r{resume}")
    print("PASS unavailable Claude-low: three capped attempts per recorded resume; excluded from study outcomes", flush=True)


def main():
    legacy = load_module("legacy_packet_verifier", ROOT / "kaggle/round2_package/verify_packet.py")
    manifest = legacy.verify_manifest()
    print(f"PASS manifest: {len(manifest)} payload hashes", flush=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
               PYTHONPATH=os.pathsep.join([str(ROOT / "offline"), str(ROOT / "kaggle")]),
               MPLCONFIGDIR=str(Path(tempfile.gettempdir()) / "chronos-matplotlib"))
    for command in legacy.commands():
        subprocess.run([sys.executable, *command], cwd=ROOT, env=env, check=True)
    subprocess.run([sys.executable, str(Path(__file__).resolve()), "--extensions"],
                   cwd=ROOT, env=env, check=True)
    for checker in ["check_current_auxiliary.py", "check_current_manuscript.py", "kaggle/claude_low_chain_v1.py"]:
        subprocess.run([sys.executable, checker], cwd=ROOT, env=env, check=True)
    check_unavailability()
    legacy.verify_manifest()
    print("CURRENT RESEARCH VERIFIED: hashes, historical/A/B/C/E gates, D/F/G and report tables", flush=True)


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--extensions"]:
            check_extensions()
        elif not sys.argv[1:]:
            main()
        else:
            raise ValueError("Usage: python3 verify_current.py")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"CURRENT RESEARCH VERIFICATION FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
