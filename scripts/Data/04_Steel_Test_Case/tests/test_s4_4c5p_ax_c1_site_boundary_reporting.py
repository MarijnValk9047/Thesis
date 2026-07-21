from __future__ import annotations

from pathlib import Path
import sys

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_ax_c1_site_boundary_reporting import _ng_pj


def test_named_ng_energy_keeps_volume_and_controller_energy_separate() -> None:
    assert _ng_pj(100.0, 2.0, 35.8) == 5.58
