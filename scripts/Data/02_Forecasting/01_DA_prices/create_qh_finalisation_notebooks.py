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
        import sys

        import matplotlib.pyplot as plt
        import numpy as np
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
            build_qh_phase2_reporting_bundle,
            finalisation_output_root,
            find_latest_qh_finalisation_run,
            find_latest_observed_deterministic_run,
            find_latest_phase07_run,
            get_feature_columns_by_set,
            get_feature_families_for_set,
            load_feature_family_map,
            load_feature_registry,
            smoke_check_qh_phase2_finalisation_bundle,
            smoke_check_qh_phase2_reporting,
            write_qh_phase2_finalisation_bundle,
        )

        config = QuarterHourDAExtensionConfig()
        pd.set_option("display.max_columns", 200)
        pd.set_option("display.width", 220)
        plt.style.use("seaborn-v0_8-whitegrid")
        """
    ).strip()


def build_phase2_model_comparison_notebook() -> nbformat.NotebookNode:
    cells = [
        md(
            """
            # 01 QH FS1 FS2 Model Comparison

            This notebook is the Phase 2 quarter-hour finalisation scaffold.

            Current scope:

            - load the quarter-hour FS-layer registry;
            - define the intended QH-FS1 and QH-FS2 comparison surface for `LEAR` and `XGBoost`;
            - expose the reporting utilities for standard metrics and ranking or opportunity metrics;
            - smoke-test those utilities against the latest canonical observed deterministic quarter-hour artifact.

            Out of scope in this notebook scaffold:

            - full model training;
            - final model selection;
            - endogenous ablation;
            - exogenous feature inclusion;
            - scenario generation.
            """
        ),
        code(_common_setup_cell()),
        md(
            """
            ## Registry Surface

            The new quarter-hour registry is model-agnostic. `QH-FS1` is the active realistic feature layer. `QH-FS2` is present only as an inactive placeholder until the causal endogenous or shape-history expansion is implemented.
            """
        ),
        code(
            """
            feature_registry = load_feature_registry(config)
            feature_family_map = load_feature_family_map(config)
            qh_fs1_columns = get_feature_columns_by_set("QH-FS1", config=config)
            qh_fs1_families = get_feature_families_for_set("QH-FS1", config=config)

            display(feature_family_map)
            display(pd.DataFrame([{
                "qh_fs1_feature_count": len(qh_fs1_columns),
                "qh_fs1_families": ", ".join(qh_fs1_families),
            }]))
            """
        ),
        md(
            """
            ## Phase 2 Comparison Contract

            The final Phase 2 implementation should compare at least:

            - `QH-FS0` naive or anchor baseline;
            - `LEAR` on `QH-FS1`;
            - `XGBoost` on `QH-FS1`;
            - `QH-FS2` candidates only if that layer becomes active and causally valid.

            `xgboost_deviation` from the current canonical observed deterministic run remains reference-only here. It is not treated as the selected final winner.
            """
        ),
        code(
            """
            comparison_contract = pd.DataFrame(
                [
                    {"candidate_family": "baseline", "feature_set_id": "QH-FS0", "status": "reference_required"},
                    {"candidate_family": "lear", "feature_set_id": "QH-FS1", "status": "phase2_target"},
                    {"candidate_family": "xgboost", "feature_set_id": "QH-FS1", "status": "phase2_target"},
                    {"candidate_family": "lear", "feature_set_id": "QH-FS2", "status": "inactive_placeholder"},
                    {"candidate_family": "xgboost", "feature_set_id": "QH-FS2", "status": "inactive_placeholder"},
                ]
            )
            display(comparison_contract)
            """
        ),
        md(
            """
            ## Manual Heavy-Run Contract

            The real `QH-FS1` LEAR and `XGBoost` candidate generation is intentionally manual in this scaffold.

            Why:

            - it is a heavy run;
            - it uses the existing quarter-hour realistic Track A evaluation path;
            - the notebook should load saved artifacts after the manual run instead of launching it implicitly.
            """
        ),
        code(
            """
            RUN_HEAVY = False

            HEAVY_RUN_COMMANDS = [
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices" / "run_15min_qh_fs1_model_comparison.py"),
                ],
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices" / "run_15min_phase07_realistic_track_a.py"),
                ],
            ]

            EXPECTED_OUTPUT_ROOT = REPO_ROOT / "data" / "02_Forecasting" / "01_DA_prices" / "quarterhour_da" / "phase07_runs"
            EXPECTED_OUTPUT_FILES = [
                "run_summary.json",
                "predictions_long.csv",
                "reconstructed_price_metrics.csv",
                "model_configuration_summary.csv",
                "feature_column_summary.csv",
                "recommended_model_summary.csv",
                "selected_hourly_anchor_models.csv",
            ]
            EXPECTED_RUNTIME_WARNING = (
                "Heavy manual run. This path trains LEAR and XGBoost on the realistic quarter-hour Track A flow, "
                "writes outputs under quarterhour_da/phase07_runs/<run_id>/, and should be launched outside normal notebook execution."
            )

            print(EXPECTED_RUNTIME_WARNING)
            print("Manual command options:")
            for command in HEAVY_RUN_COMMANDS:
                print(" ".join(command))

            if RUN_HEAVY:
                raise RuntimeError(
                    "RUN_HEAVY must stay False in the scaffold. Run one of the printed commands manually from the terminal, then rerun the loading cells below."
                )
            """
        ),
        md(
            """
            ## Load Saved Heavy-Run Artifacts

            After the manual run finishes, this notebook should load the latest saved `phase07` artifact set rather than retriggering training.
            """
        ),
        code(
            """
            latest_phase07_run = find_latest_phase07_run(config)
            if latest_phase07_run is None:
                raise FileNotFoundError(
                    "No saved QH-FS1 heavy-run artifact exists yet. Run the manual command printed above, then rerun this cell."
                )

            phase07_run_summary = json.loads((latest_phase07_run / "run_summary.json").read_text(encoding="utf-8"))
            phase07_model_config = pd.read_csv(latest_phase07_run / "model_configuration_summary.csv")
            phase07_feature_summary = pd.read_csv(latest_phase07_run / "feature_column_summary.csv")
            phase07_price_metrics = pd.read_csv(latest_phase07_run / "reconstructed_price_metrics.csv")
            phase07_recommended = pd.read_csv(latest_phase07_run / "recommended_model_summary.csv")
            phase07_selected_hourly_anchor_models = pd.read_csv(latest_phase07_run / "selected_hourly_anchor_models.csv")

            display(pd.DataFrame([{
                "latest_phase07_run": str(latest_phase07_run),
                "phase07_status": phase07_run_summary.get("status"),
                "phase07_phase": phase07_run_summary.get("phase"),
            }]))
            display(phase07_model_config)
            display(phase07_recommended)
            """
        ),
        md(
            """
            ## Stable Finalisation Bundle Contract

            The finalisation comparison should not depend directly on whichever raw `phase07` run is currently latest.

            Instead, after the manual heavy run has produced raw candidate outputs, this notebook can refresh a stable Phase 2 comparison bundle under:

            - `data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/qh_fs1_fs2_model_comparison/<run_id>/`

            The bundle inventory must report:

            - available and missing candidates;
            - the saved source run IDs used to normalise predictions;
            - machine-readable metric artifacts for the available candidates only.
            """
        ),
        code(
            """
            REFRESH_FINALISATION_BUNDLE = False
            FINALISATION_OUTPUT_ROOT = finalisation_output_root(config)

            print("Stable finalisation output root:")
            print(FINALISATION_OUTPUT_ROOT)

            if REFRESH_FINALISATION_BUNDLE:
                bundle_paths = write_qh_phase2_finalisation_bundle(config=config, smoke_mode=False)
                print("Refreshed finalisation bundle:")
                print(bundle_paths.run_dir)
            else:
                print(
                    "REFRESH_FINALISATION_BUNDLE is False. After the manual heavy run finishes, set it to True once to normalise the saved raw outputs into a stable finalisation bundle."
                )
            """
        ),
        md(
            """
            ## Candidate Inventory And Bundle Loading

            This section loads the latest stable finalisation bundle. If no bundle exists yet, create one by:

            1. running the heavy command manually in the terminal;
            2. rerunning the previous cell with `REFRESH_FINALISATION_BUNDLE = True`;
            3. returning here to load the normalized comparison artifacts.
            """
        ),
        code(
            """
            latest_finalisation_run = find_latest_qh_finalisation_run(config)
            if latest_finalisation_run is None:
                raise FileNotFoundError(
                    "No stable Phase 2 finalisation bundle exists yet. Run the manual heavy command, then refresh the bundle with REFRESH_FINALISATION_BUNDLE = True."
                )

            finalisation_run_summary = json.loads((latest_finalisation_run / "run_summary.json").read_text(encoding="utf-8"))
            candidate_inventory = pd.read_csv(latest_finalisation_run / "candidate_prediction_inventory.csv")
            candidate_predictions = pd.read_csv(latest_finalisation_run / "candidate_predictions_long.csv", low_memory=False)
            metrics_by_reporting_level = pd.read_csv(latest_finalisation_run / "metrics_by_reporting_level.csv")
            common_sample_metrics_by_reporting_level = pd.read_csv(latest_finalisation_run / "common_sample_metrics_by_reporting_level.csv")
            ranking_opportunity_metrics = pd.read_csv(latest_finalisation_run / "ranking_opportunity_metrics.csv")
            coverage_diagnostic_by_model = pd.read_csv(latest_finalisation_run / "coverage_diagnostic_by_model.csv")
            metrics_by_frozen_week = pd.read_csv(latest_finalisation_run / "metrics_by_frozen_week.csv")
            residuals_by_quarter = pd.read_csv(latest_finalisation_run / "residuals_by_quarter.csv")
            model_settings_summary = pd.read_csv(latest_finalisation_run / "model_settings_summary.csv")
            candidate_scope_warnings = pd.read_csv(latest_finalisation_run / "candidate_scope_warnings.csv")

            display(pd.DataFrame([{
                "latest_finalisation_run": str(latest_finalisation_run),
                "phase07_source_run_id": finalisation_run_summary["source_runs"].get("phase07_run_id"),
                "observed_source_run_id": finalisation_run_summary["source_runs"].get("observed_run_id"),
                "available_candidate_groups": finalisation_run_summary.get("available_candidate_groups"),
                "missing_or_inactive_candidate_groups": finalisation_run_summary.get("missing_or_inactive_candidate_groups"),
                "prediction_rows": finalisation_run_summary.get("prediction_rows"),
            }]))

            display(candidate_inventory)
            display(candidate_inventory[candidate_inventory["availability_status"].astype(str) != "available"])
            display(pd.DataFrame([finalisation_run_summary.get("phase07_temporal_metadata", {})]))
            """
        ),
        md(
            """
            ## Finalisation Artifacts

            These tables are the stable machine-readable Phase 2 comparison outputs. They should be consumed for interpretation and later thesis reporting rather than reading raw `phase07` files directly.
            """
        ),
        code(
            """
            display(metrics_by_reporting_level.head(20))
            display(common_sample_metrics_by_reporting_level.head(20))
            display(ranking_opportunity_metrics.head(20))
            display(coverage_diagnostic_by_model.head(20))
            display(metrics_by_frozen_week.head(20))
            display(residuals_by_quarter.head(20))
            display(model_settings_summary.head(20))
            display(candidate_scope_warnings)
            """
        ),
        md(
            """
            ## Coverage And Scope Warnings

            Imported `phase07` learned candidates must be treated as source-scoped `D` candidates unless the raw saved predictions expose true rolling-origin and horizon metadata.

            If a candidate's full-horizon row is identical to its `D only` row because only `D` observations are present, this notebook should warn explicitly instead of implying `D..D+4` support.
            """
        ),
        code(
            """
            problematic_candidates = candidate_scope_warnings[
                candidate_scope_warnings["warning_code"].astype(str) == "full_horizon_equals_d_only_due_to_d_only_source_scope"
            ].copy()

            if not problematic_candidates.empty:
                print("Warning: some candidates only have D-scoped saved predictions, so their full-horizon metrics are not true D..D+4 comparisons.")
                display(problematic_candidates)
            else:
                print("No D-only full-horizon warning rows were found in the current stable bundle.")
            """
        ),
        md(
            """
            ## Reporting Utility Smoke Test On The Latest Canonical Artifact

            This is a utility smoke test only. It confirms that the metric bundle can be computed from an existing quarter-hour prediction table without running any new training.
            """
        ),
        code(
            """
            latest_run = find_latest_observed_deterministic_run(config)
            if latest_run is None:
                raise FileNotFoundError("No canonical observed deterministic quarter-hour run exists yet.")

            predictions = pd.read_csv(latest_run / "predictions_long.csv")
            run_summary = json.loads((latest_run / "run_summary.json").read_text(encoding="utf-8"))
            smoke_predictions = predictions[predictions["dataset_split"].astype(str) == "validation"].copy()
            smoke_origins = (
                pd.to_datetime(smoke_predictions["forecast_origin_utc"], utc=True, errors="coerce")
                .dropna()
                .drop_duplicates()
                .sort_values()
                .head(4)
            )
            smoke_predictions = smoke_predictions[
                pd.to_datetime(smoke_predictions["forecast_origin_utc"], utc=True, errors="coerce").isin(smoke_origins)
            ].copy()

            display(pd.DataFrame([{
                "latest_observed_run": str(latest_run),
                "model_strategy": run_summary.get("model_strategy"),
                "hourly_backbone_run_id": run_summary.get("hourly_backbone_run_id"),
                "smoke_split": "validation",
                "smoke_origin_count": int(len(smoke_origins)),
                "smoke_rows": int(smoke_predictions.shape[0]),
            }]))
            """
        ),
        code(
            """
            smoke_checks = smoke_check_qh_phase2_reporting(smoke_predictions, business_timezone=config.business_timezone)
            reporting_bundle = build_qh_phase2_reporting_bundle(smoke_predictions, business_timezone=config.business_timezone)

            display(smoke_checks)
            display(reporting_bundle["metrics_overall"].sort_values(["dataset_split", "mae", "model"]).reset_index(drop=True))
            display(reporting_bundle["ranking_opportunity_metrics"].head(20))
            display(reporting_bundle["spearman_summary"].head(20))
            display(reporting_bundle["tail_mae_summary"].head(20))
            display(reporting_bundle["spread_error_summary"].head(20))
            """
        ),
        md(
            """
            ## Bundle Smoke Checks

            This smoke check exercises the non-training bundle logic on a small saved-artifact slice. It should report:

            - schema validation;
            - missing-candidate handling;
            - at least one discoverable learned candidate from `phase07`;
            - writable metric artifacts.
            """
        ),
        code(
            """
            bundle_smoke_checks = smoke_check_qh_phase2_finalisation_bundle(config=config)
            smoke_bundle_paths = write_qh_phase2_finalisation_bundle(config=config, smoke_mode=True)

            display(bundle_smoke_checks)
            display(pd.DataFrame([{
                "smoke_bundle_run_dir": str(smoke_bundle_paths.run_dir),
                "inventory_exists": smoke_bundle_paths.inventory_csv.exists(),
                "predictions_exists": smoke_bundle_paths.predictions_csv.exists(),
                "metrics_exists": smoke_bundle_paths.metrics_by_reporting_level_csv.exists(),
                "ranking_metrics_exists": smoke_bundle_paths.ranking_metrics_csv.exists(),
                "run_summary_exists": smoke_bundle_paths.run_summary_json.exists(),
            }]))
            """
        ),
    ]
    return new_notebook(cells=cells, metadata={"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}})


def main() -> int:
    NOTEBOOK_ROOT.mkdir(parents=True, exist_ok=True)
    notebook_specs = {
        "01_qh_fs1_fs2_model_comparison.ipynb": build_phase2_model_comparison_notebook(),
    }
    for filename, notebook in notebook_specs.items():
        target = NOTEBOOK_ROOT / filename
        target.write_text(nbformat.writes(notebook), encoding="utf-8")
        print(f"Wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
