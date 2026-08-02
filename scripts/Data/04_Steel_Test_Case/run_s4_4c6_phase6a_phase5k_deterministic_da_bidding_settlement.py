from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from steel.s4_4c6_phase6a_phase5k_deterministic_da_bidding_settlement import main


if __name__ == "__main__":
    main()
