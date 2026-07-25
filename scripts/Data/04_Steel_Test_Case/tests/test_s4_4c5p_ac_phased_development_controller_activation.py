from __future__ import annotations

import json
import sys
from pathlib import Path


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5p_ac_phased_development_controller_activation import OUTPUT_DIR, PHASES, run_s4_4c5p_ac_phased_development_controller_activation  # noqa: E402
from steel.s4_4c_unified_physical_modelbuilder import _development_controller_flags  # noqa: E402
from steel.wag_development_controller_contract import load_development_controller_profile  # noqa: E402


def test_phase_order_is_explicit_and_never_enables_free_c0_planning():
    assert PHASES == ("hsm", "hsm_pefa", "hsm_pefa_boiler", "full")
    assert _development_controller_flags("hsm")["hsm"]
    assert not _development_controller_flags("hsm")["pefa"]
    assert _development_controller_flags("full")["generator"]


def test_profiles_reuse_existing_c5_outputs_without_capacity_derived_demand():
    profile = load_development_controller_profile("C0_current_BF_BOF_reference")
    assert profile.pefa_pellets_t_h > 0.0
    assert profile.boiler_fuel_mwh_h > 0.0
    assert profile.generator_wag_interface_cap_mwh_h > 0.0


def test_fixed_schedule_activation_checks_pass():
    summary = run_s4_4c5p_ac_phased_development_controller_activation()
    assert summary["status"] == "pass"
    assert summary["free_c0_binary_planning_used"] is False
    saved = json.loads((OUTPUT_DIR / "summary.json").read_text(encoding="utf-8"))
    assert saved["go_no_go"]["free_c0_planning"] == "NO_GO"
