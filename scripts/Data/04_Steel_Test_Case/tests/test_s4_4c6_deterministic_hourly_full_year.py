from __future__ import annotations

import json

import pandas as pd
from pyomo.environ import ConcreteModel, Constraint, RangeSet, Var

from steel.s4_4c6_deterministic_c0_temporal_validation import (
    load_c0_validation_config,
)
from steel.s4_4c6_deterministic_hourly_full_year import (
    CONFIG_PATH,
    _annual_physical_horizon_hours,
    _apply_shifted_physical_tail_warm_start,
    _hourly_eaf_load_decomposition,
    _load_config,
    _materialize_compatible_c0_calibration_seed,
    _physical_commitment_day_lengths,
    _physical_tail_heat_days,
    _production_comparability_rows,
    materialize_lear_strict_realised_price_ledger,
)
from steel.s4_4c6_deterministic_hourly_temporal_validation import (
    PHYSICAL_HORIZON_HOURS,
    build_hourly_annual_calendar,
)
from steel.s4_4c6_deterministic_temporal_repair import (
    load_temporal_repair_config,
)
from steel.s4_4c_unified_physical_modelbuilder import REPO_ROOT


def _calendar():
    c0 = load_c0_validation_config()
    c1 = load_temporal_repair_config(REPO_ROOT / c0["base_temporal_config"])
    return build_hourly_annual_calendar(
        c1,
        start_local_date="2024-10-01",
        end_exclusive_local_date="2025-10-01",
        timezone_name="Europe/Amsterdam",
    )


def test_lear_strict_calendar_is_one_contiguous_native_dst_year():
    calendar = _calendar()
    day_lengths = (
        calendar.groupby("calendar_day_index")["local_day_length_hours"]
        .first()
        .value_counts()
        .to_dict()
    )
    assert len(calendar) == 8760
    assert calendar["calendar_day_index"].nunique() == 365
    assert day_lengths == {24: 363, 25: 1, 23: 1}
    timestamps = pd.DatetimeIndex(calendar["timestamp_utc"])
    assert timestamps.is_unique
    assert timestamps.equals(pd.date_range(timestamps[0], periods=8760, freq="h"))


def test_lear_strict_realised_price_method_closes_the_same_8760_hours():
    config = _load_config()
    source = REPO_ROOT / config["realised_price_source"]["path"]
    ledger = materialize_lear_strict_realised_price_ledger(
        _calendar(), source_path=source
    )
    assert len(ledger) == 8760
    assert ledger["price_eur_per_mwh"].notna().all()
    assert ledger["timestamp_utc"].is_unique
    assert int(ledger["is_imputed"].sum()) == 62
    assert set(ledger["dst_policy"]) == {"native_23_25_hour_delivery_days"}


def test_full_year_config_requests_only_the_four_hourly_deterministic_cases():
    config = _load_config(CONFIG_PATH)
    assert config["execution_order"] == [
        "C0__price_insensitive",
        "C0__perfect_foresight_D",
        "C1__price_insensitive",
        "C1__perfect_foresight_D",
    ]
    assert config["scope"] == {
        "hourly_only": True,
        "qh": False,
        "dam": False,
        "bidding": False,
        "mfrr": False,
        "stochasticity": False,
        "s10": False,
        "full_four_week_matrix_authorized": False,
    }
    assert PHYSICAL_HORIZON_HOURS == 72


def test_annual_reported_production_must_each_close_675_within_004_mt():
    economics = pd.DataFrame(
        [
            {"configuration": "C0", "strategy": strategy, "steel_produced_t": 6_750_000.0}
            for strategy in ("price_insensitive", "perfect_foresight_D")
        ]
        + [
            {"configuration": "C1", "strategy": "price_insensitive", "steel_produced_t": 6_746_000.0},
            {"configuration": "C1", "strategy": "perfect_foresight_D", "steel_produced_t": 6_745_999.0},
        ]
    )
    rows = _production_comparability_rows(economics)
    assert rows[0]["passed"] is True
    assert rows[0]["absolute_difference_t"] == 4_000.0
    assert rows[0]["common_target_t"] == 6_750_000.0
    assert rows[0]["tolerance_t"] == 4_000.0
    assert rows[1]["passed"] is False


def test_shifted_tail_warm_start_audits_only_initialized_overlap():
    previous = ConcreteModel()
    previous.TIME = RangeSet(0, 2)
    previous.rate = Var(previous.TIME)
    for index in previous.TIME:
        previous.rate[index].set_value(float(index + 1))

    current = ConcreteModel()
    current.TIME = RangeSet(0, 2)
    current.rate = Var(current.TIME)
    current.overlap = Constraint(expr=current.rate[0] + current.rate[1] >= 0.0)
    current.new_tail = Constraint(expr=current.rate[2] >= 0.0)

    audit = _apply_shifted_physical_tail_warm_start(
        previous,
        current,
        execution_hours=1,
    )

    assert current.rate[0].value == 2.0
    assert current.rate[1].value == 3.0
    assert current.rate[2].value is None
    assert audit["assigned_variable_count"] == 2
    assert audit["evaluated_constraint_count"] == 1
    assert audit["skipped_uninitialized_constraint_count"] == 1


def test_hourly_figure_adapter_reconciles_eaf_components_without_inventing_subslots():
    dispatch = pd.DataFrame(
        [
            {
                "configuration": "C1",
                "strategy": "perfect_foresight_D",
                "day": 1,
                "hour": 0,
                "timestamp_utc": "2024-10-01T00:00:00+00:00",
                "price_eur_per_mwh": 80.0,
                "eaf_taps": 1.0,
                "eaf_cold_dri_reheat_electricity_mwh": 2.0,
                "eaf_electricity_mwh": 150.0,
            },
            {
                "configuration": "C0",
                "strategy": "perfect_foresight_D",
                "day": 1,
                "hour": 0,
                "timestamp_utc": "2024-10-01T00:00:00+00:00",
                "price_eur_per_mwh": 80.0,
                "eaf_taps": float("nan"),
                "eaf_cold_dri_reheat_electricity_mwh": float("nan"),
                "eaf_electricity_mwh": float("nan"),
            },
        ]
    )
    rows = _hourly_eaf_load_decomposition(dispatch)
    assert len(rows) == 1
    assert rows[0]["subslot"] == ""
    assert rows[0]["phase"] == "hourly_aggregate"
    assert rows[0]["temporal_resolution"] == "H_settlement_aggregate"
    assert (
        rows[0]["arc_power_mw"]
        + rows[0]["cold_dri_reheat_power_mw"]
        + rows[0]["secondary_metallurgy_power_mw"]
    ) == 150.0


def test_c0_calibration_seed_reuse_requires_identical_initial_physics(tmp_path):
    class State:
        temporal_contract_version = "new_contract"

        @staticmethod
        def snapshot():
            return {"inventory": 1.0, "temporal_contract_version": "new_contract"}

    source = tmp_path / "seed" / "c0_inventory_continuation_calibration.json"
    source.parent.mkdir()
    source.write_text(
        json.dumps(
            {
                "method": "strict_flat_price_finite_difference_at_governed_terminal_target",
                "price_eur_per_mwh": 80.0,
                "state": {"inventory": 1.0, "temporal_contract_version": "old_contract"},
                "values_eur_per_t": {
                    "coke_inventory_t": 1.0,
                    "cold_slab_inventory_t": 2.0,
                    "hot_iron_inventory_t": 0.0,
                    "sinter_inventory_t": 3.0,
                },
            }
        ),
        encoding="utf-8",
    )
    destination = tmp_path / "current.json"
    assert _materialize_compatible_c0_calibration_seed(
        destination,
        seed_run_id="seed",
        current_state=State(),  # type: ignore[arg-type]
        seed_root=tmp_path,
    )
    reused = json.loads(destination.read_text(encoding="utf-8"))
    assert reused["state"]["temporal_contract_version"] == "new_contract"
    assert reused["reuse_provenance"]["source_run_id"] == "seed"


def test_annual_physical_horizon_adds_exactly_48_future_hours_on_dst_days():
    for execution_hours, expected in ((23, 71), (24, 72), (25, 73)):
        assert _annual_physical_horizon_hours(
            configuration="C1_phase1_BF_BOF_plus_DRP_EAF",
            execution_hours=execution_hours,
            remaining_calendar_hours=8_000,
            final_day=False,
        ) == expected


def test_c1_annual_physical_horizon_truncates_at_calendar_end():
    assert _annual_physical_horizon_hours(
        configuration="C1_phase1_BF_BOF_plus_DRP_EAF",
        execution_hours=24,
        remaining_calendar_hours=48,
        final_day=False,
    ) == 48


def test_c1_year_terminal_becomes_fully_visible_inside_fourteen_days():
    assert _annual_physical_horizon_hours(
        configuration="C1_phase1_BF_BOF_plus_DRP_EAF",
        execution_hours=24,
        remaining_calendar_hours=336,
        final_day=False,
    ) == 336


def test_exact_48h_tail_uses_local_day_commitment_segments_around_fall_dst():
    days = [
        {"day_length_hours": 24},
        {"day_length_hours": 25},
        {"day_length_hours": 24},
        {"day_length_hours": 24},
    ]
    assert _physical_commitment_day_lengths(
        days, zero_index=0, physical_horizon_hours=72
    ) == [24, 25, 23]
    assert _physical_commitment_day_lengths(
        days, zero_index=1, physical_horizon_hours=73
    ) == [25, 24, 24]


def test_exact_48h_tail_can_end_in_partial_day_around_spring_dst():
    days = [
        {"day_length_hours": 24},
        {"day_length_hours": 23},
        {"day_length_hours": 24},
        {"day_length_hours": 24},
    ]
    assert _physical_commitment_day_lengths(
        days, zero_index=0, physical_horizon_hours=72
    ) == [24, 23, 24, 1]


def test_physical_tail_heat_days_closes_current_quota_inside_tail():
    calendar_days = [{"day_length_hours": 24}] * 4
    schedule = [
        {"lower": 23, "upper": 29, "quota_period_index": 5, "quota_period_boundary": 0},
        {"lower": 23, "upper": 29, "quota_period_index": 5, "quota_period_boundary": 0},
        {"lower": 23, "upper": 29, "quota_period_index": 5, "quota_period_boundary": 1},
        {"lower": 23, "upper": 29, "quota_period_index": 6, "quota_period_boundary": 0},
    ]
    rows = _physical_tail_heat_days(
        calendar_days,
        schedule,
        zero_index=0,
        execution_hours=24,
        physical_horizon_hours=72,
        current_quota_period_index=5,
        remaining_quota_taps=77,
    )
    assert [row["calendar_day_index"] for row in rows] == [2, 3]
    assert rows[-1]["closes_current_quota"] is True
    assert rows[-1]["remaining_quota_taps"] == 77
