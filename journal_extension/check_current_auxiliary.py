"""Read-only raw replay of the current manuscript's auxiliary analysis files.

Run from any directory with the packet's pinned Python/NumPy/SciPy environment.
The imported analysis functions audit raw evidence without their writing CLI
entry points. Historical paired statistics in these files remain historical;
the current paper's independent Fisher/Holm/Newcombe checks run separately.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "kaggle").is_dir() else HERE.parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "kaggle"))

CHECKS = {
    "terra-low": (
        "analyze_terra_low_study_v1", "analyze", "terra_low_study_analysis_v1.json"
    ),
    "tree4": ("build_tree4_cells_v1", "build", "tree4_cells_v1.json"),
    "matched-regression": (
        "regression_matched_roster_v1", "build", "regression_matched_roster_v1.json"
    ),
}
REPLAYED = {}


def canonical(value: object) -> bytes:
    normalized = json.loads(json.dumps(value, allow_nan=False))
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def verify_regression_inputs() -> None:
    """Verify every stored panel read by the regression builder against raw replay."""
    if "terra-low" not in REPLAYED:
        check("terra-low")
    r2 = importlib.import_module("round2_analysis")
    analysis_dir = ROOT / "kaggle" / "round2_analysis"
    september = json.loads((analysis_dir / "analysis.json").read_text())["study_models"]
    terra = json.loads((analysis_dir / "terra_low_study_analysis_v1.json").read_text())
    if canonical(terra["study"]["model_order_panel_choices"]) != canonical(
        REPLAYED["terra-low"]["study"]["model_order_panel_choices"]
    ):
        raise ValueError("Stored Terra-low regression panels differ from raw replay")
    split = json.loads(r2.MANIFEST_PATH.read_text())["held_out_order"]
    models = set()
    for cell in r2.STUDY_CELLS:
        model = cell["model"]
        if model == "openai/gpt-5.6-terra":
            continue
        raw = r2._audited_study(cell, split)
        if canonical(raw["model_order_panel_choices"]) != canonical(
            september[model]["model_order_panel_choices"]
        ) or raw["reasoning"] != september[model]["reasoning"]:
            raise ValueError(f"Stored regression panels/settings differ from raw replay: {model}")
        models.add(model)
    if models != {"google/gemini-3.6-flash", "qwen/qwen3-235b-a22b-instruct-2507",
                  "anthropic/claude-sonnet-4-6@default"}:
        raise ValueError("Unexpected historical inputs to the matched regression")


def check(name: str) -> dict:
    module_name, function_name, filename = CHECKS[name]
    path = ROOT / "kaggle" / "round2_analysis" / filename
    sealed_bytes = path.read_bytes()
    expected = canonical(json.loads(sealed_bytes))
    if name == "matched-regression":
        verify_regression_inputs()
    module = importlib.import_module(module_name)
    actual = getattr(module, function_name)()
    if canonical(actual) != expected:
        raise ValueError(f"Raw replay differs from sealed analysis: {path.relative_to(ROOT)}")
    if path.read_bytes() != sealed_bytes:
        raise ValueError(f"Analysis file changed during replay: {path.relative_to(ROOT)}")
    if name == "terra-low":
        if actual["reasoning"] != "low" or actual["defense"]["totals"]["completed_decisions"] != 120:
            raise ValueError("Incomplete or unexpected Terra-low auxiliary cell")
    elif name == "tree4":
        if set(actual) != {"terra_low", "terra_none", "gemini_minimal", "qwen_low", "claude_none"}:
            raise ValueError("Unexpected tree-study roster")
        if any(cell["panels"]["permutation_stateful"]["complete_panels"] != 10
               for cell in actual.values()):
            raise ValueError("Incomplete tree-study order panel")
    else:
        expected_roster = {
            "openai/gpt-5.6-terra": "low", "google/gemini-3.6-flash": "minimal",
            "qwen/qwen3-235b-a22b-instruct-2507": "low",
            "anthropic/claude-sonnet-4-6@default": "none",
        }
        if actual["roster"] != expected_roster or actual["observations"] != 960:
            raise ValueError("Unexpected matched regression roster or observation count")
    REPLAYED[name] = actual
    result = {
        "check": name,
        "status": "PASS",
        "analysis": path.relative_to(ROOT).as_posix(),
        "sealed_sha256": hashlib.sha256(sealed_bytes).hexdigest(),
        "verification": "canonical JSON equality after audited raw replay",
    }
    if name == "matched-regression":
        result["global_interaction"] = actual["global_interaction"]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=tuple(CHECKS), help="Run one auxiliary replay instead of all three")
    args = parser.parse_args()
    for name in ([args.only] if args.only else CHECKS):
        print(json.dumps(check(name), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
