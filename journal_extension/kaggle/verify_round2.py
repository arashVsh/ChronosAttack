"""Strict offline verifier for the round-two repair checkpoint.

The verifier starts from pinned raw evidence on every run. It never reads the
legacy B3/C1 ``analysis.json`` and treats the generated round-two analysis and
Markdown reports as outputs to compare, not inputs to trust.
"""

from __future__ import annotations

import sys

from render_round2_reports import check_outputs
from round2_analysis import build_round2_analysis


def verify() -> list[str]:
    result = build_round2_analysis()
    checks = []

    if result["source"] != "immutable_raw_jsonl":
        raise AssertionError("analysis source is not raw JSONL")
    checks.append("frozen amendment, source modules and 18 evidence files match hashes")

    completion = result["completion_scenarios"]
    if not completion["complete"] or completion["verified_calls"] != 2100:
        raise AssertionError("B3/C1 matrix did not regenerate completely")
    checks.append("B3/C1 regenerates 2,100 calls without an intermediate analysis file")

    studies = result["study_models"]
    if any(cell["audit"]["completed_jobs"] != 690 for cell in studies.values()):
        raise AssertionError("a four-observation study cell is incomplete")
    checks.append("four raw study cells audit at 690 decisions each")

    defenses = result["defense_models"]
    if any(
        cell["totals"]["completed_decisions"] != 120 for cell in defenses.values()
    ):
        raise AssertionError("a defense suite is incomplete")
    claude = defenses["anthropic/claude-sonnet-4-6@default"]["totals"]
    if (
        claude["observed_invocations"] != 610
        or claude["failed_invocations"] != 3
        or abs(claude["known_cost_usd"] - 2.6361216) > 1e-12
    ):
        raise AssertionError("Claude charged-failure correction drifted")
    checks.append("defense accounting includes charged failures and 610 Claude invocations")

    regression = result["model_by_order_regression"]
    if not (
        regression["full_interaction"]["converged"]
        and regression["additive"]["converged"]
        and regression["raw_boundary_cells"] == 63
        and regression["observations"] == 960
    ):
        raise AssertionError("Firth model-by-order analysis failed its frozen shape")
    checks.append("Firth full/additive fits converge across 960 panel observations")

    mismatches = check_outputs(result)
    if mismatches:
        raise AssertionError("generated output drift:\n" + "\n".join(mismatches))
    checks.append("analysis JSON and six reports exactly match fresh regeneration")
    return checks


def main() -> None:
    try:
        checks = verify()
    except Exception as exc:
        print(f"ROUND2 VERIFICATION FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    for check in checks:
        print(f"PASS  {check}")
    print(f"ROUND2 VERIFIED: {len(checks)} strict gates passed")


if __name__ == "__main__":
    main()
