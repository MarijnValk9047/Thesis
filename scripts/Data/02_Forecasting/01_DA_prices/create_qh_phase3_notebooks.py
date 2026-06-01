from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook


NOTEBOOK_ROOT = Path(__file__).resolve().parents[4] / "notebooks" / "Data" / "02_Forecasting" / "01_DA_prices" / "quarterhour_da"


def md(text: str) -> nbformat.NotebookNode:
    return new_markdown_cell(dedent(text).strip())


def code(text: str) -> nbformat.NotebookNode:
    return new_code_cell(dedent(text).strip())


def _common_setup_cell() -> str:
    return dedent(
        """
        from pathlib import Path
        import json
        import os
        import subprocess
        import sys

        import pandas as pd
        from IPython.display import display

        NOTEBOOK_CWD = Path.cwd()
        REPO_ROOT = next(
            path
            for path in [NOTEBOOK_CWD, *NOTEBOOK_CWD.parents]
            if (path / "scripts/Data/02_Forecasting/01_DA_prices").exists()
        )
        os.chdir(REPO_ROOT)

        PACKAGE_ROOT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"
        if str(PACKAGE_ROOT) not in sys.path:
            sys.path.append(str(PACKAGE_ROOT))

        from quarterhour_da import (
            QuarterHourDAExtensionConfig,
            build_ablation_run_plan,
            build_phase3_qh_fs1_ablation_bundle,
            detect_active_qh_fs1_families,
            find_latest_qh_phase3_ablation_run,
            find_latest_qh_finalisation_run,
            phase3_output_root,
            smoke_check_qh_phase3_endogenous_ablation,
            write_phase3_qh_fs1_ablation_bundle,
        )

        config = QuarterHourDAExtensionConfig()
        pd.set_option("display.max_columns", 240)
        pd.set_option("display.width", 240)
        """
    ).strip()


def build_qh_phase3_endogenous_ablation_notebook() -> nbformat.NotebookNode:
    cells = [
        md(
            """
            # 02 QH Endogenous Feature Ablation

            Phase 3 introduces endogenous feature-family ablation scaffolding for `QH-FS1` while keeping `LEAR` and `XGBoost` as equal candidate model families.

            Why this is needed:
            - grouped family-drop ablation quantifies contribution of coherent information blocks rather than noisy one-feature perturbations;
            - both `LEAR` and `XGBoost` are preserved to avoid premature winner selection before diagnostic evidence is complete;
            - MAE alone is insufficient for MILP-relevant forecasting, so ranking/opportunity behavior is tracked alongside standard error metrics.

            Scope guardrails in this notebook:
            - endogenous families only;
            - no exogenous additions;
            - no scenario-generation integration;
            - no final winner selection.
            """
        ),
        code(_common_setup_cell()),
        md("## Phase 2 Parent Confirmation"),
        code(
            """
            latest_phase2 = find_latest_qh_finalisation_run(config)
            if latest_phase2 is None:
                raise FileNotFoundError("No Phase 2 finalisation run is available.")

            phase2_summary = json.loads((latest_phase2 / "run_summary.json").read_text(encoding="utf-8"))
            phase2_inventory = pd.read_csv(latest_phase2 / "candidate_prediction_inventory.csv", low_memory=False)
            learned_rows = phase2_inventory[
                phase2_inventory["candidate_inventory_id"].astype(str).isin(["qh_fs1_lear_phase07", "qh_fs1_xgboost_phase07"])
            ].copy()

            display(pd.DataFrame([{
                "latest_phase2_run": str(latest_phase2),
                "phase07_source_run_id": phase2_summary["source_runs"].get("phase07_run_id"),
                "observed_source_run_id": phase2_summary["source_runs"].get("observed_run_id"),
            }]))
            display(learned_rows)
            """
        ),
        md("## Active QH-FS1 Families"),
        code(
            """
            active_families = detect_active_qh_fs1_families(config)
            display(pd.DataFrame({"active_qh_fs1_families": active_families}))
            """
        ),
        md("## Parent-Child Ablation Plan"),
        code(
            """
            ablation_plan = build_ablation_run_plan(config)
            display(ablation_plan[[
                "parent_model_id",
                "child_model_id",
                "model_family",
                "feature_set_id",
                "dropped_feature_family",
                "retained_feature_count",
                "dropped_feature_count",
                "expected_output_path",
                "run_status",
            ]])
            """
        ),
        md("## Optional Heavy Run"),
        code(
            """
            RUN_HEAVY = False
            HEAVY_COMMAND = [
                sys.executable,
                str(REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices" / "run_15min_qh_fs1_endogenous_ablation.py"),
                "--include-existing-child-predictions",
                "--run-child-training",
            ]
            PHASE3_OUTPUT_ROOT = phase3_output_root(config)
            LOG_PATH = PHASE3_OUTPUT_ROOT / "manual_heavy_phase3.log"

            print("Heavy command:")
            print(" ".join(HEAVY_COMMAND))

            if RUN_HEAVY:
                PHASE3_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
                print("Running heavy command and writing full logs to:", LOG_PATH)
                with LOG_PATH.open("w", encoding="utf-8") as handle:
                    process = subprocess.run(
                        HEAVY_COMMAND,
                        cwd=REPO_ROOT,
                        stdout=handle,
                        stderr=subprocess.STDOUT,
                        text=True,
                        check=False,
                    )
                if process.returncode == 0:
                    print("Heavy command finished successfully.")
                else:
                    print("Heavy command failed with return code:", process.returncode)
                    lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
                    print("Last log lines:")
                    for line in lines[-40:]:
                        print(line)
                    raise RuntimeError("Phase 3 heavy command failed. Inspect the log file.")
            """
        ),
        md("## Scaffold Refresh and Smoke Checks"),
        code(
            """
            smoke_checks = smoke_check_qh_phase3_endogenous_ablation(config)
            display(smoke_checks)

            scaffold_paths = write_phase3_qh_fs1_ablation_bundle(
                config=config,
                include_existing_child_predictions=True,
                run_child_training=False,
            )
            print("Phase 3 bundle refresh written to:")
            print(scaffold_paths.run_dir)
            """
        ),
        md("## Load Saved Phase 3 Artifacts"),
        code(
            """
            latest_phase3 = find_latest_qh_phase3_ablation_run(config)
            if latest_phase3 is None:
                raise FileNotFoundError("No Phase 3 endogenous ablation scaffold run was found.")

            run_summary = json.loads((latest_phase3 / "ablation_run_summary.json").read_text(encoding="utf-8"))
            ablation_plan = pd.read_csv(latest_phase3 / "ablation_run_plan.csv", low_memory=False)
            candidate_inventory = pd.read_csv(latest_phase3 / "ablation_candidate_inventory.csv", low_memory=False)
            value_summary = pd.read_csv(latest_phase3 / "feature_family_value_summary.csv", low_memory=False)
            value_by_model = pd.read_csv(latest_phase3 / "feature_family_value_by_model.csv", low_memory=False)
            value_by_reporting = pd.read_csv(latest_phase3 / "feature_family_value_by_reporting_level.csv", low_memory=False)
            value_by_horizon = pd.read_csv(latest_phase3 / "feature_family_value_by_horizon.csv", low_memory=False)
            value_by_frozen_week = pd.read_csv(latest_phase3 / "feature_family_value_by_frozen_week.csv", low_memory=False)
            value_ranking = pd.read_csv(latest_phase3 / "feature_family_value_ranking_metrics.csv", low_memory=False)
            scope_warnings = pd.read_csv(latest_phase3 / "ablation_scope_warnings.csv", low_memory=False)

            display(pd.DataFrame([{
                "latest_phase3_run": str(latest_phase3),
                "phase2_parent_run_id": run_summary["source_runs"].get("phase2_finalisation_run_id"),
                "phase2_phase07_run_id": run_summary["source_runs"].get("phase2_phase07_run_id"),
                "parent_model_count": run_summary.get("parent_model_count"),
                "child_model_count": run_summary.get("child_model_count"),
                "child_prediction_rows_available": run_summary.get("child_prediction_rows_available"),
                "full_heavy_ablation_executed": run_summary.get("scope", {}).get("full_heavy_ablation_executed"),
            }]))
            if int(run_summary.get("child_prediction_rows_available", 0)) <= 0:
                print("WARNING: child predictions are absent. Run the notebook heavy cell with RUN_HEAVY=True.")
            display(candidate_inventory)
            display(scope_warnings)
            display(value_summary.head(50))
            display(value_by_reporting.head(50))
            display(value_ranking.head(50))
            """
        ),
    ]
    return new_notebook(cells=cells)


def write_notebooks() -> list[Path]:
    NOTEBOOK_ROOT.mkdir(parents=True, exist_ok=True)
    notebook_path = NOTEBOOK_ROOT / "02_qh_endogenous_feature_ablation.ipynb"
    notebook = build_qh_phase3_endogenous_ablation_notebook()
    notebook_path.write_text(nbformat.writes(notebook), encoding="utf-8")
    return [notebook_path]


def main() -> None:
    written = write_notebooks()
    for path in written:
        print(path)


if __name__ == "__main__":
    main()
