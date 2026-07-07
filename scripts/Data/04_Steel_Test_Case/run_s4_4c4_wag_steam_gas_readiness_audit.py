"""Run S4.4c4 WAG, steam, and gas readiness audit."""

from __future__ import annotations

from steel.s4_4c4_wag_steam_gas_readiness_audit import run_s4_4c4_audit


def main() -> None:
    result = run_s4_4c4_audit()
    gate = result["stage_gate"]
    print(
        "S4.4c4 gate:",
        gate["decision"],
        "| output_dir:",
        result["output_dir"],
    )
    for name, count in sorted(result["row_counts"].items()):
        print(name, count)


if __name__ == "__main__":
    main()
