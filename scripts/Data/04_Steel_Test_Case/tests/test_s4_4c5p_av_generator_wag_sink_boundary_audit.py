from __future__ import annotations

from pathlib import Path
import sys

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_av_generator_wag_sink_boundary_audit import audit_rows


def _row(carrier: str, generation: float, generator: float) -> dict[str, str]:
    return {
        "carrier": carrier,
        "generation_MWh_LHV_y": str(generation),
        "process_or_self_use_MWh_LHV_y": "0",
        "hsm_pefa_MWh_LHV_y": "0",
        "steam_boiler_MWh_LHV_y": "0",
        "generator_MWh_LHV_y": str(generator),
        "flare_MWh_LHV_y": "0",
        "residual_MWh_LHV_y": "0",
        "physical_carrier_status": "carrier_specific_accepted",
    }


def test_audit_keeps_carriers_separate_and_detects_nonbinding_cap() -> None:
    scale = 1_000_000.0 / 3.6
    comparison, sinks, findings = audit_rows(
        [_row("BFG", 12.0 * scale, 1.0 * scale), _row("COG", 8.0 * scale, 0.1 * scale), _row("BOFG", 2.0 * scale, 0.2 * scale)],
        interface_cap_mwh_h=200.0,
    )
    assert [row["carrier"] for row in comparison] == ["BFG", "COG", "BOFG"]
    assert sum(row["generation_PJ_y"] for row in sinks) == 22.0
    assert findings[0]["finding_id"] == "AV_001"
    assert "not binding" in findings[0]["finding"]


def test_audit_does_not_call_an_excluded_profile_cap_nonbinding() -> None:
    scale = 1_000_000.0 / 3.6
    _, _, findings = audit_rows(
        [_row("BFG", 12.0 * scale, 8.0 * scale), _row("COG", 8.0 * scale, 0.1 * scale), _row("BOFG", 2.0 * scale, 1.0 * scale)],
        interface_cap_mwh_h=200.0,
        interface_cap_active=False,
    )
    assert "not active" in findings[0]["finding"]


def test_audit_marks_a_numerically_equal_active_cap_as_potentially_binding() -> None:
    scale = 1_000_000.0 / 3.6
    interface_cap = (1.0 + 0.1 + 0.2) * scale / 8_760.0
    _, _, findings = audit_rows(
        [_row("BFG", 12.0 * scale, 1.0 * scale), _row("COG", 8.0 * scale, 0.1 * scale), _row("BOFG", 2.0 * scale, 0.2 * scale)],
        interface_cap_mwh_h=interface_cap,
    )
    assert "numerical equality" in findings[0]["finding"]
