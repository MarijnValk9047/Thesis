from __future__ import annotations

import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from steel.s4_4c5m_e_bf_coke_driver_alignment_and_bounded_reconciliation_scenario_report import (  # noqa: E402
    run_s4_4c5m_e_bf_coke_driver_alignment_and_bounded_reconciliation_scenario_report,
)


def main() -> int:
    print(json.dumps(run_s4_4c5m_e_bf_coke_driver_alignment_and_bounded_reconciliation_scenario_report(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
