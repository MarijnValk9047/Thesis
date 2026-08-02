from __future__ import annotations

import sys
from pathlib import Path


CASE_ROOT = Path(__file__).resolve().parents[1]
if str(CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(CASE_ROOT))

from steel.s4_4c_unified_physical_modelbuilder import (  # noqa: E402
    S44B_INPUT_DIR,
    _STEEL_TABLE_CACHE,
    _load_tables_with_status,
)


def test_steel_input_table_cache_hits_and_legacy_mode_bypasses() -> None:
    _STEEL_TABLE_CACHE.clear()
    first, first_status, first_hash = _load_tables_with_status(
        S44B_INPUT_DIR, performance_mode="optimized_equivalent"
    )
    second, second_status, second_hash = _load_tables_with_status(
        S44B_INPUT_DIR, performance_mode="optimized_equivalent"
    )
    legacy, legacy_status, legacy_hash = _load_tables_with_status(
        S44B_INPUT_DIR, performance_mode="legacy_rebuild"
    )
    assert first_status == "miss_registered"
    assert second_status == "hit"
    assert first is second
    assert first_hash == second_hash == legacy_hash
    assert legacy_status == "disabled_legacy_rebuild"
    assert legacy is not first
