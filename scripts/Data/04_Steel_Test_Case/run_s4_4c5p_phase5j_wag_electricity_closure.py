from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from steel.s4_4c5p_phase5j_wag_electricity_closure import main


if __name__ == "__main__":
    main()
