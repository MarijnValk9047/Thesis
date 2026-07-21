from __future__ import annotations

import argparse

from steel.s4_4c5p_aq_c1_continuous_chain_steady_state_reconciliation import run_c1_continuous_chain_steady_state_reconciliation


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the source-corrected C1 continuous-chain capacity diagnostic.")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()
    result = run_c1_continuous_chain_steady_state_reconciliation(**({"run_id": args.run_id} if args.run_id else {}))
    print(result["summary"])
