from __future__ import annotations

from pathlib import Path
import sys


STEEL_ROOT = Path(__file__).resolve().parent
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_phase5b_c0_export_sensitivity import main


if __name__ == "__main__":
    main()
