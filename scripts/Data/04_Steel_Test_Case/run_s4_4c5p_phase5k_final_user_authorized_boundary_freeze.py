from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from steel.s4_4c5p_phase5k_final_user_authorized_boundary_freeze import main


if __name__ == "__main__":
    main()
