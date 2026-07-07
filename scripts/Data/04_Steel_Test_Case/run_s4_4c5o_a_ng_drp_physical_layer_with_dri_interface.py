from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_ROOT = ROOT / "scripts" / "Data" / "04_Steel_Test_Case"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from steel.s4_4c5o_a_ng_drp_physical_layer_with_dri_interface import (  # noqa: E402
    run_s4_4c5o_a_ng_drp_physical_layer_with_dri_interface,
)


def main() -> int:
    print(json.dumps(run_s4_4c5o_a_ng_drp_physical_layer_with_dri_interface(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
