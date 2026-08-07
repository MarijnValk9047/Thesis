from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd

from steel.s4_4c6_deterministic_figure_package import (
    PACKAGE_VERSION,
    _descending_stack_categories,
    _load_figure_package_settings,
    _resolved_plant_bounds_from_rows,
    _time_axis,
    _weekly_result_rows,
)


def _economics() -> pd.DataFrame:
    rows = []
    for configuration in ("C0", "C1"):
        for strategy in ("price_insensitive", "perfect_foresight_D"):
            rows.append(
                {
                    "configuration": configuration,
                    "granularity": "H",
                    "strategy": strategy,
                    "realised_procurement_cost_eur": 10_000.0,
                    "steel_produced_t": 100.0,
                    "site_electricity_consumed_mwh": 80.0,
                    "average_electricity_price_paid_eur_per_mwh": 75.0,
                    "total_electricity_cost_eur": 3_000.0,
                    "total_ng_cost_eur": 2_000.0,
                    "total_coal_cost_eur": 4_000.0,
                    "total_imported_pellets_cost_eur": 1_000.0,
                    "direct_emissions_tco2": 50.0,
                    "mfrr_revenue_eur": "",
                }
            )
    return pd.DataFrame(rows)


def test_figure_package_reserves_market_variants_without_fabricating_zeroes():
    rows = _weekly_result_rows(_economics())
    dam = [row for row in rows if row["model_variant"] == "DAM only"]
    mfrr = [row for row in rows if row["model_variant"] == "Including mFRR"]
    assert dam and mfrr
    assert all(row["status"] == "not_run" and row["value"] == "" for row in dam + mfrr)


def test_mfrr_revenue_is_not_applicable_for_non_market_benchmarks():
    rows = _weekly_result_rows(_economics())
    revenue = [
        row
        for row in rows
        if row["parameter"] == "mFRR revenue"
        and row["model_variant"] in {"Price insensitive", "Perfect foresight"}
    ]
    assert revenue
    assert all(row["status"] == "not_applicable_no_mfrr_layer" for row in revenue)


def test_time_axis_ends_at_available_data():
    timestamps = pd.Series(pd.date_range("2030-01-01", periods=4, freq="h", tz="UTC"))
    fig, axis = plt.subplots()
    axis.plot(timestamps, range(4))
    _time_axis(axis, timestamps)
    left, right = axis.get_xlim()
    assert left == timestamps.iloc[0].to_pydatetime().timestamp() / 86_400.0
    assert right == timestamps.iloc[-1].to_pydatetime().timestamp() / 86_400.0
    plt.close(fig)


def test_package_version_and_saved_selection_are_v8():
    settings = _load_figure_package_settings()
    assert PACKAGE_VERSION == "deterministic_plant_behaviour_figures_v8"
    assert settings["package_version"] == PACKAGE_VERSION
    assert len(settings["default_complete_selection"]) == 19
    assert settings["create_pdf_duplicates"] is False
    assert settings["scope"]["full_four_week_matrix_authorized"] is False
    assert settings["style"]["eaf_load_shape"] == (
        "pure_arc_at_available_resolution_with_optional_5_minute_display"
    )
    assert settings["style"]["eaf_explanatory_footer"] == "omitted"
    assert settings["style"]["hsm_load_shape"] == "hourly_step_campaign_load"


def test_stacked_categories_are_ordered_largest_to_smallest():
    frame = pd.DataFrame(
        {
            "category": ["small", "large", "medium", "large"],
            "value": [1.0, 6.0, 3.0, 2.0],
        }
    )
    assert _descending_stack_categories(
        frame,
        category_column="category",
        value_column="value",
    ) == ["large", "medium", "small"]


def test_capacity_figures_read_exact_resolved_run_contract():
    bounds = _resolved_plant_bounds_from_rows(
        [
            {
                "configuration": "C0",
                "display_name": "KGF1",
                "resolved_minimum": 116.4,
                "resolved_maximum": 123.6,
            },
            {
                "configuration": "C1",
                "display_name": "KGF1",
                "resolved_minimum": 139.4,
                "resolved_maximum": 148.0,
            },
        ]
    )
    assert bounds["C0"]["KGF1"] == (116.4, 123.6)
    assert bounds["C1"]["KGF1"] == (139.4, 148.0)
    assert "DRP" in bounds["C1"]
