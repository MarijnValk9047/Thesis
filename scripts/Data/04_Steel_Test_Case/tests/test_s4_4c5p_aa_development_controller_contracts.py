from __future__ import annotations

import json
import sys
from pathlib import Path


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5p_aa_development_controller_contracts import OUTPUT_DIR, run_s4_4c5p_aa_development_controller_contracts  # noqa: E402
from steel.wag_development_controller_contract import bf_hot_stove_mwh_per_t_hot_metal, load_development_controller_contracts  # noqa: E402


def test_contract_covers_both_configurations_and_keeps_bfg_first():
    contracts = load_development_controller_contracts()
    hot_stove = contracts["BF_HOT_STOVE_CONTROLLER"]
    assert hot_stove.config_scope == ("C0", "C1")
    assert hot_stove.eligible_fuels_base == ("BFG",)
    assert bf_hot_stove_mwh_per_t_hot_metal() == 2.20 / 3.6


def test_prepared_controllers_are_not_silently_activated():
    summary = run_s4_4c5p_aa_development_controller_contracts()
    assert summary["go_no_go"]["hsm_controller"] == "PREPARED_NOT_ACTIVE"
    assert summary["go_no_go"]["pefa_total_gas_controller"] == "PREPARED_NOT_ACTIVE"
    assert json.loads((OUTPUT_DIR / "summary.json").read_text(encoding="utf-8"))["contract_row_count"] == 8
