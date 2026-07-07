from __future__ import annotations

import json

from steel.s4_4c5h_blast_furnace_controller_parameterisation import (
    run_s4_4c5h_blast_furnace_controller_parameterisation,
)


def main() -> int:
    print(json.dumps(run_s4_4c5h_blast_furnace_controller_parameterisation(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
