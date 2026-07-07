from __future__ import annotations

import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from steel.s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration import (  # noqa: E402
    run_s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration,
)


def main() -> int:
    print(json.dumps(run_s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
