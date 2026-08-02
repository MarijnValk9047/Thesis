from __future__ import annotations

from pathlib import Path
import sys


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))


from steel.s4_4c6_physical_tiebreak_runtime_audit import (  # noqa: E402
    AUDIT_CONFIG,
    VARIANT_TO_MODE,
    load_audit_config,
)
from steel.s4_4c6_phase6d_eaf_heat_state_one_day import (  # noqa: E402
    EXPECTED_COST_INCUMBENT,
    EXECUTION_WINDOW_TIEBREAK,
    FULL_PHYSICAL_TIEBREAK,
    HANDOFF_STATE_TIEBREAK,
    NATIVE_GUROBI_HIERARCHY,
)


def test_runtime_audit_freezes_ordered_early_stop_variants() -> None:
    config = load_audit_config(AUDIT_CONFIG)
    assert VARIANT_TO_MODE == {
        "V0": FULL_PHYSICAL_TIEBREAK,
        "V1": EXPECTED_COST_INCUMBENT,
        "V2": HANDOFF_STATE_TIEBREAK,
        "V3": EXECUTION_WINDOW_TIEBREAK,
        "V4": NATIVE_GUROBI_HIERARCHY,
    }
    assert config["primary_repeats"] == {
        "V0": 1,
        "V1": 3,
        "V2": 1,
        "V3": 1,
        "V4": 1,
    }
    assert config["non_executable_variants"]["V5"]["status"] == (
        "not_admissible_without_proof"
    )
    assert config["frozen_case"]["week_start"] == "2025-01-13"
    assert config["frozen_case"]["arm"] == "B_qh_flat"
    assert config["frozen_case"]["configuration"] == "C1"
    assert config["frozen_case"]["scenario_count"] == 10
    assert config["solver"]["seed"] == 0
    assert config["excluded"]["central_56_run"] is True
