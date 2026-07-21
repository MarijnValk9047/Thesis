from __future__ import annotations

from pathlib import Path
import sys

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_aq_c1_continuous_chain_steady_state_reconciliation import _candidate, build_steady_state_interval_rows


def test_source_candidate_repairs_coke_interval_overlap_without_mutating_inputs() -> None:
    rows = {row["check_id"]: row for row in build_steady_state_interval_rows(_candidate())}
    assert rows["legacy_coke_balance"]["steady_state_possible"] == "false"
    assert rows["source_candidate_coke_balance"]["steady_state_possible"] == "true"


def test_bof_is_not_misclassified_as_continuous_rate_match() -> None:
    rows = {row["check_id"]: row for row in build_steady_state_interval_rows(_candidate())}
    assert rows["BF_to_BOF_direct_rate_overlap"]["steady_state_possible"] == "not_required_batch_equivalent"
