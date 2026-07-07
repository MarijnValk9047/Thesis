from __future__ import annotations

import json

from steel.s4_4c5g_wag_aggregate_diagnostic_hygiene import (
    run_s4_4c5g_wag_aggregate_diagnostic_hygiene,
)


def main() -> int:
    print(json.dumps(run_s4_4c5g_wag_aggregate_diagnostic_hygiene(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
