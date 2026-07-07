from __future__ import annotations

import json

from steel.s4_4c5i_plant_development_status_audit import (
    run_s4_4c5i_plant_development_status_audit,
)


def main() -> int:
    print(json.dumps(run_s4_4c5i_plant_development_status_audit(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
