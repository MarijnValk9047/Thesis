from __future__ import annotations

import argparse

from steel.s4_4c5p_as_c1_bof_eaf_metallics_ledger import run_c1_bof_eaf_metallics_ledger


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the bounded C1 BOF/EAF metallics feasibility diagnostic.")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    result = run_c1_bof_eaf_metallics_ledger(**({"config_path": args.config} if args.config else {}))
    print(result["summary"])
