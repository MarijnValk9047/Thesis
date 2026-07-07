from __future__ import annotations

import json

from steel.s4_4c4c_full_wag_static_regression import run_s4_4c4c_full_wag_static_regression


def main() -> int:
    result = run_s4_4c4c_full_wag_static_regression()
    print(json.dumps(result, indent=2, sort_keys=True))
    final_gate = result.get("phase3_gate") or result.get("phase2_gate") or result.get("phase1_gate", {})
    decision = final_gate.get("decision", "")
    return 0 if decision.startswith("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
