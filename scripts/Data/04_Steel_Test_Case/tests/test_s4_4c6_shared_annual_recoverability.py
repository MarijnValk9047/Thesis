from __future__ import annotations

import pytest

from steel.s4_4c6_shared_annual_recoverability import (
    ANNUAL_REPORTED_FINAL_PRODUCT_LOWER_T,
    ANNUAL_REPORTED_FINAL_PRODUCT_UPPER_T,
    AnnualRecoverabilityContractError,
    annual_final_product_band,
    future_quota_requirements,
    validate_future_heat_calendar,
)


def test_common_reported_terminal_band_maps_to_c0_physics_without_changing_yields():
    c0 = annual_final_product_band(
        configuration="C0_reference_BF_BOF",
        c0_material_contract={
            "reporting_normalization_factor": 6_750_000.0 / 6_468_750.0,
            "physical_final_product_t_y": 6_468_750.0,
        },
    )
    c1 = annual_final_product_band(
        configuration="C1_phase1_BF_BOF_plus_DRP_EAF",
        c0_material_contract={},
    )
    assert c0.reported_lower_t == ANNUAL_REPORTED_FINAL_PRODUCT_LOWER_T
    assert c0.reported_upper_t == ANNUAL_REPORTED_FINAL_PRODUCT_UPPER_T
    assert c0.physical_target_t == pytest.approx(6_468_750.0)
    assert c0.physical_lower_t * c0.reporting_factor == pytest.approx(
        6_746_000.0
    )
    assert c0.physical_upper_t * c0.reporting_factor == pytest.approx(
        6_754_000.0
    )
    assert c1.physical_lower_t == pytest.approx(6_746_000.0)
    assert c1.physical_upper_t == pytest.approx(6_754_000.0)


def test_future_heat_calendar_accepts_no_price_or_objective_fields():
    compact = validate_future_heat_calendar(
        [
            {
                "calendar_day_index": 2,
                "day_length_hours": 23,
                "lower": 20,
                "upper": 30,
                "quota_period_index": 0,
                "quota_period_target": 191,
                "quota_period_boundary": 0,
                "price_eur_per_mwh": -100.0,
            }
        ]
    )
    assert "price_eur_per_mwh" not in compact[0]
    with pytest.raises(AnnualRecoverabilityContractError):
        validate_future_heat_calendar(
            [
                {
                    "calendar_day_index": 2,
                    "day_length_hours": 22,
                    "lower": 20,
                    "upper": 30,
                    "quota_period_index": 0,
                    "quota_period_target": 191,
                    "quota_period_boundary": 0,
                }
            ]
        )


def test_quota_boundary_never_assigns_next_week_to_current_remaining_taps():
    rows = validate_future_heat_calendar(
        [
            {
                "calendar_day_index": day,
                "day_length_hours": 24,
                "lower": 20,
                "upper": 32,
                "quota_period_index": 1,
                "quota_period_target": 191,
                "quota_period_boundary": int(day == 14),
            }
            for day in range(8, 15)
        ]
    )
    requirements = future_quota_requirements(
        rows,
        current_period_index=0,
        current_remaining_taps=27,
    )
    assert requirements["current_closes_in_execution"] is True
    assert requirements["current_future_indices"] == ()
    assert requirements["later_periods"][1]["target_taps"] == 191
    assert requirements["later_periods"][1]["indices"] == tuple(range(7))
