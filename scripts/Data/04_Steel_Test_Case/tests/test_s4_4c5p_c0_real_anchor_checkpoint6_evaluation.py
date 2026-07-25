from __future__ import annotations

from pathlib import Path
import sys

import pytest
import yaml


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel import s4_4c5p_c0_real_anchor_checkpoint6_evaluation as checkpoint6
from steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    C1_CONFIGURATION,
)


def _approved_selection_rows() -> list[dict[str, object]]:
    return [
        {
            "period_id": period_id,
            "execution_hours": 169 if period_id == "test_2024-10-21" else 168,
            "split_weight": weight,
            "dataset_split": "test",
            "frozen_forecast_start_origin_utc": "2024-01-01T06:00:00+00:00",
        }
        for period_id, weight in zip(
            checkpoint6.EXPECTED_PERIODS,
            checkpoint6.EXPECTED_WEIGHTS,
        )
    ]


def test_checkpoint6_config_freezes_exact_scope_and_claims() -> None:
    config = checkpoint6.load_checkpoint6_config()
    checkpoint6.validate_checkpoint6_config(config)
    frozen = config["checkpoint_6"]

    assert config["output_policy"] == "minimal"
    assert config["annualisation_label"] == checkpoint6.OUTPUT_LABEL
    assert frozen["expected_candidate_week_count"] == 46
    assert frozen["selected_period_count"] == 8
    assert frozen["expected_rolling_case_count"] == 48
    assert frozen["expected_model_count"] == 672
    assert frozen["dataset_split"] == "test"
    assert frozen["historical_4plus4_contract_overwrite_allowed"] is False
    assert config["checkpoint_6"]["claims"] == {
        "exact_tata_twin": False,
        "annual_backtest": False,
        "athanasiadis_ng_thermal_substitution_validated": False,
        "badarinath_bf_relationships_validated": False,
        "vn25_outage_validated": False,
        "recovery_bg25_promoted": False,
    }


def test_checkpoint6_reproduces_selection_with_accepted_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = checkpoint6.load_checkpoint6_config()
    calls: dict[str, object] = {}

    def fake_candidates(**kwargs: object) -> list[dict[str, object]]:
        calls["candidate_kwargs"] = kwargs
        return [{"period_id": f"candidate_{index}"} for index in range(46)]

    def fake_select(
        candidates: list[dict[str, object]],
        *,
        target_count: int,
        feature_fields: list[str],
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        calls["candidate_count"] = len(candidates)
        calls["target_count"] = target_count
        calls["feature_fields"] = feature_fields
        return _approved_selection_rows(), []

    monkeypatch.setattr(checkpoint6, "build_candidate_weeks", fake_candidates)
    monkeypatch.setattr(checkpoint6, "_select_and_weight", fake_select)
    monkeypatch.setattr(
        checkpoint6,
        "load_dplus4_source_contract",
        lambda: {"contract": "accepted"},
    )

    rows = checkpoint6.derive_frozen_test_selection(
        forecast_run_root="forecast-root",
        config=config,
    )

    assert calls["candidate_count"] == 46
    assert calls["target_count"] == 8
    assert calls["feature_fields"] == config["checkpoint_6"][
        "selection_feature_fields"
    ]
    assert tuple(row["period_id"] for row in rows) == checkpoint6.EXPECTED_PERIODS
    assert all(row["annualisation_label"] == checkpoint6.OUTPUT_LABEL for row in rows)
    assert rows[1]["execution_hours"] == 169
    assert rows[1]["duration_annualisation_factor"] == pytest.approx(8760 / 169)
    assert all(row["annual_backtest"] is False for row in rows)


def test_checkpoint6_matrix_is_two_by_eight_by_three_and_oracle_isolated() -> None:
    config = checkpoint6.load_checkpoint6_config()
    rows = checkpoint6.frozen_scenario_matrix(
        config,
        _approved_selection_rows(),
    )

    assert len(rows) == 48
    assert sum(row["candidate_id"] == "source_driven_baseline" for row in rows) == 24
    assert sum(row["candidate_id"] == "recovery_bg25" for row in rows) == 24
    assert sum(row["perfect_foresight_oracle"] for row in rows) == 16
    assert all(
        (row["strategy"] == "oracle_y_true")
        == (row["price_field"] == "y_true")
        == row["perfect_foresight_oracle"]
        for row in rows
    )
    assert all(row["dataset_split"] == "test" for row in rows)
    assert all(row["annualisation_label"] == checkpoint6.OUTPUT_LABEL for row in rows)


def test_checkpoint6_candidate_overrides_preserve_reviewed_pair() -> None:
    config = checkpoint6.load_checkpoint6_config()
    baseline, recovery = config["checkpoint_6"]["candidates"]

    baseline_overrides = checkpoint6._cp4_candidate_overrides(config, baseline)
    recovery_overrides = checkpoint6._cp4_candidate_overrides(config, recovery)

    assert baseline_overrides[
        "site_background_electricity_mwh_h_by_configuration"
    ] == {C0_CONFIGURATION: 0.0, C1_CONFIGURATION: 0.0}
    assert "c0_aggregate_generator_technical_interface" not in baseline_overrides
    assert "c0_full_site_energy_bridge" not in baseline_overrides
    assert recovery_overrides[
        "site_background_electricity_mwh_h_by_configuration"
    ] == {
        C0_CONFIGURATION: pytest.approx(90.46803652968036),
        C1_CONFIGURATION: 0.0,
    }
    interface = recovery_overrides["c0_aggregate_generator_technical_interface"]
    bridge = recovery_overrides["c0_full_site_energy_bridge"]
    assert interface["electricity_efficiency"] == pytest.approx(0.345)
    assert interface["total_fuel_volume_cap_nm3_h"] == pytest.approx(900000.0)
    assert interface["electrical_capacity_mw"] == pytest.approx(770.0)
    assert interface["export_allowed"] is False
    assert bridge["inferred_low_case_full_site_ng_floor_pj_y"] == pytest.approx(
        8.005
    )
    assert bridge["flexible_other_site_heat_service_envelope_pj_y"] == pytest.approx(
        3.07
    )


def test_checkpoint6_duration_annualisation_is_dst_safe() -> None:
    background_mwh_h = 90.46803652968036
    ordinary = checkpoint6.duration_aware_annual_equivalent(
        background_mwh_h * 168,
        168,
    )
    dst = checkpoint6.duration_aware_annual_equivalent(
        background_mwh_h * 169,
        169,
    )
    fixed_ng_mwh_h = (8.005 / 3.6e-6) / 8760
    dst_fixed_ng = checkpoint6.duration_aware_annual_equivalent(
        fixed_ng_mwh_h * 169,
        169,
    )

    assert ordinary == pytest.approx(792500.0)
    assert dst == pytest.approx(792500.0)
    assert dst_fixed_ng == pytest.approx(8.005 / 3.6e-6)
    with pytest.raises(checkpoint6.Checkpoint6Error, match="positive"):
        checkpoint6.duration_aware_annual_equivalent(1.0, 0)


def test_checkpoint6_cache_identity_accepts_exact_and_rejects_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = checkpoint6.load_checkpoint6_config()
    candidate = config["checkpoint_6"]["candidates"][1]
    period = _approved_selection_rows()[1]
    forecast_root = Path("forecast-root").resolve()
    expected_overrides = checkpoint6._expected_case_overrides(
        config=config,
        candidate=candidate,
        period=period,
        strategy="governed_y_pred",
        forecast_root=forecast_root,
    )
    expected_fingerprint = checkpoint6._mapping_sha256(
        checkpoint6._cache_identity_payload(
            config=config,
            candidate=candidate,
            period=period,
            strategy="governed_y_pred",
        )
    )
    persisted = {"scenario_overrides_applied": expected_overrides}
    metrics = [
        {
            "replan_index": str(replan),
            "configuration_id": configuration,
            "solver_status": "ok",
            "termination_condition": "optimal",
        }
        for replan in range(7)
        for configuration in (C0_CONFIGURATION, C1_CONFIGURATION)
    ]

    class FakeFile:
        def __init__(self, name: str) -> None:
            self.name = name

        def is_file(self) -> bool:
            return True

        def read_text(self, encoding: str) -> str:
            assert self.name == "config_resolved.yaml"
            return yaml.safe_dump(persisted, sort_keys=False)

    class FakeDirectory:
        def __truediv__(self, name: str) -> FakeFile:
            return FakeFile(name)

    monkeypatch.setattr(checkpoint6, "_case_ready", lambda directory: True)
    monkeypatch.setattr(checkpoint6, "_read_csv", lambda path: metrics)
    directory = FakeDirectory()

    assert checkpoint6._checkpoint6_case_ready(
        directory,  # type: ignore[arg-type]
        expected_overrides=expected_overrides,
        expected_scenario_override_sha256=expected_fingerprint,
    )

    persisted["scenario_overrides_applied"] = {
        **expected_overrides,
        "forecast_price_field": "y_true",
    }
    assert not checkpoint6._checkpoint6_case_ready(
        directory,  # type: ignore[arg-type]
        expected_overrides=expected_overrides,
        expected_scenario_override_sha256=expected_fingerprint,
    )

    persisted["scenario_overrides_applied"] = expected_overrides
    removed = metrics.pop()
    assert not checkpoint6._checkpoint6_case_ready(
        directory,  # type: ignore[arg-type]
        expected_overrides=expected_overrides,
        expected_scenario_override_sha256=expected_fingerprint,
    )
    metrics.append(removed)
    metrics[0]["termination_condition"] = "infeasible"
    assert not checkpoint6._checkpoint6_case_ready(
        directory,  # type: ignore[arg-type]
        expected_overrides=expected_overrides,
        expected_scenario_override_sha256=expected_fingerprint,
    )


def test_checkpoint6_anchor_denominators_are_explicit_boundaries() -> None:
    rows = []
    for candidate_id in checkpoint6.EXPECTED_CANDIDATES:
        for configuration in (C0_CONFIGURATION, C1_CONFIGURATION):
            rows.append(
                {
                    "candidate_id": candidate_id,
                    "strategy": "price_insensitive",
                    "configuration_id": configuration,
                    "gross_electricity_mwh_y": 3_000_000.0,
                    "internal_wag_electricity_mwh_y": 2_500_000.0,
                    "named_ng_mwh_lhv_y": 2_500_000.0,
                    "drp_dri_output_t_y": 2_800_000.0,
                }
            )

    anchors = checkpoint6._anchor_comparison_rows(rows)
    denominators = {row["anchor_id"]: row["denominator"] for row in anchors}

    assert denominators["real_c0_gross_electricity_band"] == (
        "annual_represented_full_site_gross_electricity_boundary"
    )
    assert denominators["real_c0_wag_generator_electricity"] == (
        "annual_WAG_only_gross_generator_electricity_output_boundary"
    )
    assert denominators["real_c0_named_ng"] == (
        "calendar_year_named_NG_LHV_energy_boundary_excluding_residual_NG"
    )
    assert denominators["mer_c1_dri_output_context"] == (
        "annual_C1_DRP_DRI_output_boundary"
    )
    assert all(
        row["denominator"] != row["real_first_source_value_or_band"]
        for row in anchors
    )
