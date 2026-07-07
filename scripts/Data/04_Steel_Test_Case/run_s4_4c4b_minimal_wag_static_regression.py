"""Run S4.4c4b minimal WAG/steam/gas static regressions."""

from __future__ import annotations

from steel.s4_4c4b_minimal_wag_static_regression import run_s4_4c4b_minimal_wag_static_regression


def main() -> None:
    result = run_s4_4c4b_minimal_wag_static_regression()
    print("S4.4c4b phase1:", result.get("phase1_gate", {}).get("decision"))
    print("S4.4c4b phase2:", result.get("phase2_gate", {}).get("decision", "not_run"))
    print("S4.4c4b phase3:", result.get("phase3_gate", {}).get("decision", "not_run"))


if __name__ == "__main__":
    main()
