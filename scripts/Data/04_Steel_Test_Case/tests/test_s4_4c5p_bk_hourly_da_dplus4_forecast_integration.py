from __future__ import annotations

import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
import yaml


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    ClosedLoopFeasibilityError,
    _config,
    _rolling_production_progress_contract,
)
from steel.s4_4c5p_bf_price_series_interface import (
    DPLUS4_SOURCE_CONTRACT_PATH,
    PriceSeriesInterfaceError,
    _validate_dplus4_rows,
    load_dplus4_source_contract,
)
from steel.s4_4c5p_bk_hourly_da_dplus4_forecast_integration import (
    _case_definitions,
)
from steel.rolling_production_quota import build_rolling_production_quota_plan


def _rows(first_local_day: date) -> tuple[list[dict[str, object]], datetime]:
    contract = load_dplus4_source_contract()
    zone = ZoneInfo("Europe/Amsterdam")
    start_local = datetime.combine(first_local_day, time.min, tzinfo=zone)
    end_local = datetime.combine(first_local_day + timedelta(days=5), time.min, tzinfo=zone)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)
    origin = start_utc - timedelta(hours=16)
    rows: list[dict[str, object]] = []
    delivery = start_utc
    while delivery < end_utc:
        local = delivery.astimezone(zone)
        rows.append(
            {
                "run_id": contract["source_run_id"],
                "model": contract["model_id"],
                "feature_variant": contract["feature_variant"],
                "dataset_split": "validation",
                "forecast_origin_utc": origin,
                "forecast_origin_local": origin.astimezone(zone).isoformat(),
                "target_timestamp_utc": delivery,
                "target_delivery_local_date": local.date().isoformat(),
                "target_hour_local": local.hour,
                "target_known_at_utc": origin.isoformat(),
                "lead_day": (local.date() - first_local_day).days,
                "y_pred": 80.0,
            }
        )
        delivery += timedelta(hours=1)
    return rows, origin


@pytest.mark.parametrize(
    ("first_day", "expected_hours"),
    [(date(2025, 3, 28), 119), (date(2023, 10, 27), 121)],
)
def test_dplus4_contract_preserves_23_and_25_hour_dst_delivery_days(
    first_day: date, expected_hours: int
) -> None:
    rows, origin = _rows(first_day)
    validated = _validate_dplus4_rows(
        rows,
        contract=load_dplus4_source_contract(),
        dataset_split="validation",
        origin=origin,
        expected_horizon_hours=None,
    )
    assert len(validated) == expected_hours
    assert {row["lead_day"] for row in validated} == {0, 1, 2, 3, 4}


def test_dplus4_contract_fails_closed_on_duplicate_or_missing_hour() -> None:
    rows, origin = _rows(date(2023, 10, 1))
    with pytest.raises(PriceSeriesInterfaceError, match="duplicate"):
        _validate_dplus4_rows(
            rows + [dict(rows[-1])],
            contract=load_dplus4_source_contract(), dataset_split="validation",
            origin=origin, expected_horizon_hours=None,
        )
    with pytest.raises(PriceSeriesInterfaceError, match="contiguous|expected"):
        _validate_dplus4_rows(
            rows[:40] + rows[41:],
            contract=load_dplus4_source_contract(), dataset_split="validation",
            origin=origin, expected_horizon_hours=119,
        )


def test_optimisation_contract_never_requires_or_returns_y_true() -> None:
    contract = load_dplus4_source_contract()
    rows, origin = _rows(date(2023, 10, 1))
    assert all("y_true" not in row for row in rows)
    validated = _validate_dplus4_rows(
        rows, contract=contract, dataset_split="validation", origin=origin,
        expected_horizon_hours=120,
    )
    assert all("y_true" not in row for row in validated)
    assert contract["ex_post_outcome_policy"] == "prohibited_from_optimisation_interface"


def test_120_hour_model_horizon_requires_explicit_dplus4_contract() -> None:
    config_path = STEEL_ROOT / "configs" / "steel_hourly_da_dplus4_point_forecast_integration.yaml"
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert _config(config_path)["planning_horizon_hours"] == 120
    payload["dplus4_horizon_contract_active"] = False
    with patch.object(Path, "read_text", return_value=yaml.safe_dump(payload)):
        with pytest.raises(ClosedLoopFeasibilityError, match="120-hour"):
            _config(Path("invalid.yaml"))


def test_source_contract_keeps_runtime_root_external_and_hashes_governed() -> None:
    contract = yaml.safe_load(DPLUS4_SOURCE_CONTRACT_PATH.read_text(encoding="utf-8"))
    assert contract["runtime_root_policy"].startswith("explicit_argument")
    assert set(contract["source_file_sha256"]) == {
        "predictions", "run_summary", "metrics_by_lead_day"
    }
    assert all(len(value) == 64 for value in contract["source_file_sha256"].values())


def test_integration_cases_freeze_validation_before_one_heldout_window() -> None:
    cases = _case_definitions()
    assert [case["case_id"] for case in cases] == [
        "price_insensitive_reference",
        "flat_framework_reference",
        "dplus4_adapter_flat_parity",
        "validation_dplus4_point_forecast",
        "heldout_test_dplus4_point_forecast",
    ]
    assert cases[0]["overrides"]["generator_operating_mode"] == "price_insensitive_reference"
    assert cases[2]["overrides"]["forecast_price_override_eur_per_mwh"] == 80.0
    assert cases[3]["overrides"]["forecast_dataset_split"] == "validation"
    assert cases[4]["overrides"]["forecast_dataset_split"] == "test"
    assert all("y_true" not in case["overrides"] for case in cases)


def test_terminal_replan_closes_cumulative_quota_exactly() -> None:
    plan = build_rolling_production_quota_plan(
        planning_horizon_hours=120,
        execution_block_hours=24,
        quota_per_execution_block_t=18493.1506849315,
    )
    cumulative = {
        "C0_current_BF_BOF_reference": 6.0 * plan.quota_per_execution_block_t + 50.0,
        "C1_phase1_BF_BOF_plus_DRP_EAF": 6.0 * plan.quota_per_execution_block_t - 75.0,
    }
    contract = _rolling_production_progress_contract(
        plan=plan,
        replan_index=6,
        cumulative_before=cumulative,
        base_target_multiplier=120.0 / 24.0,
        enabled=True,
        terminal_exact=True,
    )
    for configuration, state in contract["state_by_configuration"].items():
        assert state["terminal_exact_quota_active"] is True
        assert state["next_cumulative_lower_envelope_t"] == pytest.approx(
            7.0 * plan.quota_per_execution_block_t
        )
        assert state["next_cumulative_upper_envelope_t"] == pytest.approx(
            7.0 * plan.quota_per_execution_block_t
        )
        assert contract["progress_target_by_configuration_t"][configuration] == pytest.approx(
            7.0 * plan.quota_per_execution_block_t - cumulative[configuration]
        )
