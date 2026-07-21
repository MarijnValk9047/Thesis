from __future__ import annotations

import sys
from pathlib import Path


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5p_ab_24h_wag_runtime_profile import _build_profile  # noqa: E402


def test_build_profile_reports_complexity_without_solving():
    profile = _build_profile("pytest_c1_wag", wag=True, retained=True, fixed_schedule=True)
    assert float(profile["build_runtime_seconds"]) >= 0.0
    assert int(profile["variable_count"]) > 0
    assert int(profile["constraint_count"]) > 0
    assert profile["minimal_wag_layer"] == "true"
