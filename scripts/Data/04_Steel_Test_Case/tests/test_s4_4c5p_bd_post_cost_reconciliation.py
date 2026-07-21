from __future__ import annotations

import csv
import os
import shutil
import sys
from pathlib import Path


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel import s4_4c5p_bd_post_cost_reconciliation as reconciliation


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_post_cost_classification_excludes_scenario_definitions() -> None:
    assert reconciliation._post_cost_classification(
        {
            "scenario_definition_status": "validation_candidate",
            "anchor_role": "scenario_definition",
            "comparability_status": "directly_comparable",
            "use_in_primary_score": "yes",
        }
    ) == "scenario_definition"


def test_post_cost_reconciliation_uses_one_fingerprinted_parent() -> None:
    output = (
        reconciliation.REPO_ROOT
        / "data"
        / "03_Optimisation"
        / "runs"
        / f"_test_post_cost_{os.getpid()}"
    )
    shutil.rmtree(output, ignore_errors=True)
    try:
        result = reconciliation.run_post_cost_reconciliation(output_directory=output)
        assert result["summary"]["status"] == "pass"
        assert result["summary"]["cost_identity_max_abs_residual_eur"] <= 1e-4
        anchors = _csv(output / "post_cost_anchor_comparison.csv")
        assert anchors
        assert all(
            row["post_cost_classification"] != "primary_comparable"
            for row in anchors
            if row["scenario_definition_status"] == "scenario_definition"
            or row["anchor_role"] in {"scenario_definition", "active_model_target"}
        )
    finally:
        shutil.rmtree(output, ignore_errors=True)
