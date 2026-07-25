from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel import s4_4c5p_bg_price_series_interface_validation as validation


def test_price_series_validation_proves_flat_reproduction_and_no_leak() -> None:
    output = (
        validation.REPO_ROOT
        / "data"
        / "03_Optimisation"
        / "runs"
        / f"_test_price_series_validation_{os.getpid()}"
    )
    shutil.rmtree(output, ignore_errors=True)
    try:
        result = validation.run_price_series_interface_validation(
            output_directory=output
        )
        assert result["summary"]["status"] == "pass"
        assert (
            result["summary"]["completion_decision"]
            == "ready_for_future_DAM_price_integration"
        )
        assert result["summary"]["flat_phase4_max_abs_reproduction_residual"] <= 1e-6
        assert result["summary"]["DAM_bidding_active"] is False
        assert result["summary"]["settlement_active"] is False
    finally:
        shutil.rmtree(output, ignore_errors=True)
