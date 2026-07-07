from __future__ import annotations

import json

from steel.s4_4c5c_plant_asset_conversion_diagnostics import (
    run_s4_4c5c_plant_asset_conversion_diagnostics,
)


def main() -> int:
    print(json.dumps(run_s4_4c5c_plant_asset_conversion_diagnostics(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
