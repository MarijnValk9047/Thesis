from __future__ import annotations

import json

from steel.s4_4c5e_internal_consistency_repair import (
    run_s4_4c5e_internal_consistency_repair,
)


def main() -> int:
    print(json.dumps(run_s4_4c5e_internal_consistency_repair(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
