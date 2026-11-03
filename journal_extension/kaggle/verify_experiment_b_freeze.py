"""Verify the self-hashed Experiment B fixture and exact job topology."""

import hashlib
import json
from pathlib import Path

import experiment_b_protocol as protocol


ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "kaggle/experiment_b_manifest_v1.json"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify():
    manifest = json.loads(MANIFEST.read_text())
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    require(digest(body) == manifest["manifest_sha256"], "B manifest self-hash mismatch")
    require(
        manifest["schema"] == "chronos.experiment-b-label-rotation.v1"
        and manifest["status"] == "frozen_no_calls"
        and manifest["classification"] == "exploratory_descriptive",
        "B manifest state mismatch",
    )
    for path, expected in manifest["source_sha256"].items():
        require(
            hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected,
            f"B source changed: {path}",
        )

    round2 = json.loads((ROOT / "kaggle/round2_manifest_v1.json").read_text())
    frozen = round2["experiment_b"]
    require(
        manifest["rotations"] == frozen["rotations"]
        and manifest["rotations"] == {
            str(rotation): mapping for rotation, mapping in protocol.ROTATIONS.items()
        }
        and manifest["semantic_target"] == frozen["semantic_target"]
        and manifest["conditions"] == frozen["conditions"]
        and manifest["mode"] == frozen["mode"]
        and manifest["repetitions_per_rotation_condition"] == frozen["repetitions"]
        and manifest["calls_per_job"] == 5
        and manifest["seed"] == protocol.SEED,
        "B scientific contract changed",
    )
    require(
        manifest["call_settings"] == {
            "temperature": 1,
            "max_completion_tokens": 256,
            "timeout": 30,
            "sdk_max_retries": 0,
        },
        "B call settings changed",
    )
    fixtures = protocol.fixtures()
    require(digest(fixtures) == manifest["fixtures_sha256"], "B fixture hash mismatch")

    cells = manifest["cells"]
    require(
        len(cells) == len(protocol.CELLS) == 4
        and {cell["model"] for cell in cells} == set(protocol.CELLS),
        "B roster mismatch",
    )
    total_pilot_jobs = total_pilot_calls = total_study_jobs = total_study_calls = 0
    primary_jobs = primary_calls = sensitivity_jobs = sensitivity_calls = 0
    all_ids = set()
    for record in cells:
        model = record["model"]
        pilot = protocol.cell(model, "pilot")
        study = protocol.cell(model, "study")
        require(
            record["reasoning"] == pilot["reasoning"] == study["reasoning"]
            and record["role"] == pilot["role"] == study["role"]
            and record["pilot_id"] == pilot["study_id"]
            and record["study_id"] == study["study_id"],
            "B cell identity mismatch",
        )
        pilot_jobs = protocol.jobs_for(model, "pilot")
        study_jobs = protocol.jobs_for(model, "study")
        require(
            digest(pilot_jobs) == record["pilot_jobs_sha256"]
            and digest(study_jobs) == record["jobs_sha256"]
            and len(pilot_jobs) == 2
            and sum(job["calls"] for job in pilot_jobs) == 10
            and len(study_jobs) == record["jobs"] == 180
            and sum(job["calls"] for job in study_jobs)
            == record["planned_calls"] == 900,
            "B job manifest changed",
        )
        ids = {job["id"] for job in (*pilot_jobs, *study_jobs)}
        require(
            len(ids) == len(pilot_jobs) + len(study_jobs)
            and not (ids & all_ids),
            "B duplicate or overlapping job IDs",
        )
        all_ids.update(ids)
        total_pilot_jobs += len(pilot_jobs)
        total_pilot_calls += sum(job["calls"] for job in pilot_jobs)
        total_study_jobs += len(study_jobs)
        total_study_calls += sum(job["calls"] for job in study_jobs)
        if record["role"] == "matched_non_off_primary":
            primary_jobs += len(study_jobs)
            primary_calls += sum(job["calls"] for job in study_jobs)
        else:
            sensitivity_jobs += len(study_jobs)
            sensitivity_calls += sum(job["calls"] for job in study_jobs)

    pilot = manifest["excluded_pilot"]
    require(
        pilot == {
            "rotation": 1,
            "conditions": ["natural", "attack"],
            "repetition": 1,
            "jobs_per_setting": 2,
            "calls_per_setting": 10,
            "total_jobs": 8,
            "total_planned_calls": 40,
            "attempts_per_job": 1,
            "outcome_based_pass": False,
            "included_in_study": False,
        }
        and (total_pilot_jobs, total_pilot_calls) == (8, 40),
        "B excluded pilot changed",
    )
    require(
        (primary_jobs, primary_calls, sensitivity_jobs, sensitivity_calls)
        == (
            manifest["matched_primary_jobs"],
            manifest["matched_primary_planned_calls"],
            manifest["sensitivity_jobs"],
            manifest["sensitivity_planned_calls"],
        )
        == (540, 2700, 180, 900)
        and (total_study_jobs, total_study_calls)
        == (
            manifest["total_executable_jobs"],
            manifest["total_executable_planned_calls"],
        )
        == (frozen["total_trials"], frozen["total_planned_calls"]),
        "B aggregate topology changed",
    )
    require(
        manifest["unavailable_primary"]
        == {**protocol.UNAVAILABLE_PRIMARY, "jobs": 0, "planned_calls": 0},
        "B unavailable matched cell changed",
    )
    return {
        "manifest_sha256": manifest["manifest_sha256"],
        "fixtures_sha256": manifest["fixtures_sha256"],
        "excluded_pilot_jobs": total_pilot_jobs,
        "excluded_pilot_calls": total_pilot_calls,
        "study_jobs": total_study_jobs,
        "study_calls": total_study_calls,
        "matched_primary_jobs": primary_jobs,
        "sensitivity_jobs": sensitivity_jobs,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
