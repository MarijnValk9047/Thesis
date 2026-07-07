from __future__ import annotations

import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from steel.s4_4c5l_c_hsm_slab_age_bucket_buffer_and_charge_reheat import (  # noqa: E402
    run_s4_4c5l_c_hsm_slab_age_bucket_buffer_and_charge_reheat,
)


def main() -> int:
    print(json.dumps(run_s4_4c5l_c_hsm_slab_age_bucket_buffer_and_charge_reheat(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
