"""Separation-resistant model-by-order analysis for complete 24-order panels."""

from __future__ import annotations

from collections import defaultdict

import numpy as np
from scipy.special import expit
from scipy.stats import chi2


def _information(design: np.ndarray, probabilities: np.ndarray) -> np.ndarray:
    weights = probabilities * (1.0 - probabilities)
    return design.T @ (weights[:, None] * design)


def _penalized_log_likelihood(
    predictor: np.ndarray,
    penalty_design: np.ndarray,
    outcome: np.ndarray,
    coefficients: np.ndarray,
) -> float:
    probabilities = np.clip(expit(predictor @ coefficients), 1e-12, 1 - 1e-12)
    log_likelihood = np.sum(
        outcome * np.log(probabilities)
        + (1.0 - outcome) * np.log1p(-probabilities)
    )
    sign, log_determinant = np.linalg.slogdet(
        _information(penalty_design, probabilities)
    )
    if sign <= 0:
        raise ValueError("Firth penalty information is not positive definite")
    return float(log_likelihood + 0.5 * log_determinant)


def _adjusted_score(
    predictor: np.ndarray,
    penalty_design: np.ndarray,
    outcome: np.ndarray,
    coefficients: np.ndarray,
) -> np.ndarray:
    probabilities = np.clip(expit(predictor @ coefficients), 1e-12, 1 - 1e-12)
    penalty_information = _information(penalty_design, probabilities)
    penalty_inverse = np.linalg.inv(penalty_information)
    weights = probabilities * (1.0 - probabilities)
    leverages = weights * np.einsum(
        "ij,jk,ik->i", penalty_design, penalty_inverse, penalty_design
    )
    return predictor.T @ (
        outcome - probabilities + leverages * (0.5 - probabilities)
    )


def firth_logistic(
    design,
    outcome,
    *,
    penalty_design=None,
    tolerance: float = 1e-9,
    max_iterations: int = 100,
) -> dict:
    """Fit logistic regression with Firth's Jeffreys-prior score adjustment.

    ``penalty_design`` is normally the predictor design. For a nested global
    test it may be the full design while ``design`` contains only unrestricted
    columns; this applies the same full-model Jeffreys penalty under both fits.
    """
    x = np.asarray(design, dtype=float)
    y = np.asarray(outcome, dtype=float)
    penalty_x = x if penalty_design is None else np.asarray(penalty_design, dtype=float)
    if x.ndim != 2 or penalty_x.ndim != 2 or y.ndim != 1:
        raise ValueError("designs must be matrices and outcome must be a vector")
    if len(x) != len(y) or len(penalty_x) != len(y):
        raise ValueError("design and outcome row counts differ")
    if not set(np.unique(y)).issubset({0.0, 1.0}):
        raise ValueError("outcome must be binary")
    if np.linalg.matrix_rank(x) != x.shape[1]:
        raise ValueError("predictor design must have full column rank")
    if np.linalg.matrix_rank(penalty_x) != penalty_x.shape[1]:
        raise ValueError("penalty design must have full column rank")

    coefficients = np.zeros(x.shape[1], dtype=float)
    current = _penalized_log_likelihood(x, penalty_x, y, coefficients)
    converged = False
    score_norm = None
    for iteration in range(1, max_iterations + 1):
        probabilities = np.clip(expit(x @ coefficients), 1e-12, 1 - 1e-12)
        predictor_information = _information(x, probabilities)
        adjusted_score = _adjusted_score(x, penalty_x, y, coefficients)
        score_norm = float(np.max(np.abs(adjusted_score)))
        step = np.linalg.solve(predictor_information, adjusted_score)
        if score_norm <= tolerance and float(np.max(np.abs(step))) <= tolerance:
            converged = True
            break

        scale = 1.0
        accepted = False
        while scale >= 2**-25:
            candidate = coefficients + scale * step
            candidate_value = _penalized_log_likelihood(
                x, penalty_x, y, candidate
            )
            if candidate_value >= current - 1e-12:
                coefficients = candidate
                current = candidate_value
                accepted = True
                break
            scale /= 2.0
        if not accepted:
            raise RuntimeError("Firth iteration failed step-halving")
        if float(np.max(np.abs(scale * step))) <= tolerance:
            converged = score_norm <= tolerance * 10
            break
    else:
        iteration = max_iterations

    if not converged:
        raise RuntimeError(
            f"Firth regression did not converge after {iteration} iterations; "
            f"adjusted score max={score_norm}"
        )
    probabilities = expit(x @ coefficients)
    covariance = np.linalg.inv(_information(x, probabilities))
    score_norm = float(
        np.max(np.abs(_adjusted_score(x, penalty_x, y, coefficients)))
    )
    return {
        "coefficients": coefficients,
        "covariance": covariance,
        "predicted": probabilities,
        "penalized_log_likelihood": _penalized_log_likelihood(
            x, penalty_x, y, coefficients
        ),
        "iterations": iteration,
        "converged": True,
        "adjusted_score_max": score_norm,
    }


def model_order_design(rows, *, interaction: bool) -> tuple[np.ndarray, np.ndarray, dict]:
    """Treatment-coded design for categorical model, order, and interaction."""
    if not rows:
        raise ValueError("at least one model-order observation is required")
    models = sorted({row[0] for row in rows})
    orders = sorted({int(row[1]) for row in rows})
    model_baseline, order_baseline = models[0], orders[0]
    columns = ["intercept"]
    columns.extend(f"model[{model}]" for model in models[1:])
    columns.extend(f"order[{order}]" for order in orders[1:])
    if interaction:
        columns.extend(
            f"model[{model}]:order[{order}]"
            for model in models[1:]
            for order in orders[1:]
        )

    matrix = []
    outcome = []
    for model, order, value in rows:
        order = int(order)
        vector = [1.0]
        vector.extend(float(model == item) for item in models[1:])
        vector.extend(float(order == item) for item in orders[1:])
        if interaction:
            vector.extend(
                float(model == model_item and order == order_item)
                for model_item in models[1:]
                for order_item in orders[1:]
            )
        matrix.append(vector)
        outcome.append(float(value))
    x = np.asarray(matrix, dtype=float)
    y = np.asarray(outcome, dtype=float)
    return x, y, {
        "models": models,
        "orders": orders,
        "model_baseline": model_baseline,
        "order_baseline": order_baseline,
        "columns": columns,
        "parameter_count": len(columns),
    }


def _validate_panels(panels_by_model: dict[str, dict[int, list[str]]]) -> tuple[list[str], list[int]]:
    models = sorted(panels_by_model)
    if len(models) < 2:
        raise ValueError("at least two models are required")
    expected_orders = None
    expected_repetitions = None
    for model in models:
        panels = panels_by_model[model]
        if len(panels) < 2:
            raise ValueError("each model needs at least two complete panels")
        lengths = {len(choices) for choices in panels.values()}
        repetitions = sorted(panels)
        if len(lengths) != 1 or 0 in lengths:
            raise ValueError("model-order regression requires complete balanced panels")
        order_count = next(iter(lengths))
        if expected_orders is None:
            expected_orders = list(range(order_count))
            expected_repetitions = len(repetitions)
        if order_count != len(expected_orders) or len(repetitions) != expected_repetitions:
            raise ValueError("model-order regression requires complete balanced panels")
    return models, expected_orders


def _percentile_interval(values: list[float]) -> list[float]:
    return [
        float(np.quantile(values, 0.025, method="linear")),
        float(np.quantile(values, 0.975, method="linear")),
    ]


def model_order_regression(
    panels_by_model: dict[str, dict[int, list[str]]],
    *,
    target: str,
    bootstrap_repetitions: int = 2000,
    seed: int = 20260920,
) -> dict:
    """Fit the frozen model×order regression and panel-bootstrap cell rates."""
    if bootstrap_repetitions < 1:
        raise ValueError("bootstrap_repetitions must be positive")
    models, orders = _validate_panels(panels_by_model)
    rows = [
        (model, order, choice == target)
        for model in models
        for choices in panels_by_model[model].values()
        for order, choice in enumerate(choices)
    ]
    full_x, y, full_metadata = model_order_design(rows, interaction=True)
    additive_x, additive_y, additive_metadata = model_order_design(
        rows, interaction=False
    )
    if not np.array_equal(y, additive_y):
        raise AssertionError("nested designs changed the outcome ordering")

    full_fit = firth_logistic(full_x, y)
    additive_fit = firth_logistic(
        additive_x, y, penalty_design=full_x
    )
    statistic = max(
        0.0,
        2.0
        * (
            full_fit["penalized_log_likelihood"]
            - additive_fit["penalized_log_likelihood"]
        ),
    )
    degrees_of_freedom = (
        full_metadata["parameter_count"] - additive_metadata["parameter_count"]
    )

    fitted_by_cell: dict[str, dict[int, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row, probability in zip(rows, full_fit["predicted"]):
        fitted_by_cell[row[0]][int(row[1])].append(float(probability))

    rng = np.random.default_rng(seed)
    bootstrap: dict[str, dict[int, list[float]]] = {
        model: {order: [] for order in orders} for model in models
    }
    for _ in range(bootstrap_repetitions):
        for model in models:
            panels = panels_by_model[model]
            repetition_ids = sorted(panels)
            sampled = rng.choice(repetition_ids, size=len(repetition_ids), replace=True)
            for order in orders:
                successes = sum(panels[int(rep)][order] == target for rep in sampled)
                # The full interaction is saturated: Firth's binomial cell
                # estimate is the Jeffreys adjustment (y + 1/2)/(n + 1).
                probability = (successes + 0.5) / (len(sampled) + 1.0)
                bootstrap[model][order].append(probability)

    cell_probabilities = {
        model: {
            str(order): {
                "estimate": float(fitted_by_cell[model][order][0]),
                "panel_bootstrap_95": _percentile_interval(
                    bootstrap[model][order]
                ),
            }
            for order in orders
        }
        for model in models
    }
    # All rows in a saturated model-order cell share one fitted value.
    for model in models:
        for order in orders:
            values = fitted_by_cell[model][order]
            if max(values) - min(values) > 1e-12:
                raise AssertionError("saturated cell has inconsistent predictions")

    raw_cells = {}
    boundary_cells = 0
    for model in models:
        raw_cells[model] = {}
        for order in orders:
            choices = [
                panels_by_model[model][rep][order]
                for rep in sorted(panels_by_model[model])
            ]
            successes = sum(choice == target for choice in choices)
            boundary_cells += successes in (0, len(choices))
            raw_cells[model][str(order)] = {
                "successes": successes,
                "trials": len(choices),
                "target_rate": successes / len(choices),
            }

    return {
        "formula": "target_C ~ categorical_model * categorical_order",
        "estimator": "Firth logistic regression",
        "models": models,
        "orders": orders,
        "observations": len(rows),
        "raw_boundary_cells": boundary_cells,
        "raw_total_cells": len(models) * len(orders),
        "full_interaction": {
            "parameter_count": full_metadata["parameter_count"],
            "iterations": full_fit["iterations"],
            "converged": full_fit["converged"],
            "penalized_log_likelihood": full_fit["penalized_log_likelihood"],
        },
        "additive": {
            "parameter_count": additive_metadata["parameter_count"],
            "iterations": additive_fit["iterations"],
            "converged": additive_fit["converged"],
            "penalized_log_likelihood_with_full_penalty": additive_fit[
                "penalized_log_likelihood"
            ],
        },
        "global_interaction": {
            "method": (
                "Firth penalized likelihood-ratio test; the full-model Jeffreys "
                "penalty is used under both nested fits"
            ),
            "statistic": statistic,
            "degrees_of_freedom": degrees_of_freedom,
            "p_value": float(chi2.sf(statistic, degrees_of_freedom)),
            "classification": "exploratory_asymptotic_global_test",
        },
        "predicted_cell_probabilities": cell_probabilities,
        "raw_cell_target_rates": raw_cells,
        "uncertainty": {
            "method": "percentile bootstrap of saturated Firth cell probabilities",
            "resampling_unit": "complete_panel",
            "within": "model",
            "repetitions": bootstrap_repetitions,
            "seed": seed,
        },
    }
