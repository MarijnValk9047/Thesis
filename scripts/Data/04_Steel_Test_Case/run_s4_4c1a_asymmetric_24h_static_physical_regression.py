"""Run S4.4c1a asymmetric 24h static physical regression."""

from __future__ import annotations

from steel.s4_4c_asymmetric_static_regression import run_c1a_24h


def main() -> None:
    report = run_c1a_24h()
    gate = report.get("phase_stage_gate", report)
    print(
        "S4.4c1a gate:",
        gate.get("decision"),
        "| horizon_hours:",
        gate.get("horizon_hours"),
    )
    for row in report.get("configuration_build_audit", []):
        print(
            row["configuration_id"],
            row.get("build_status"),
            row.get("termination_condition"),
            "target=",
            row.get("final_product_target_t"),
            "residual=",
            row.get("final_product_residual_t"),
        )


if __name__ == "__main__":
    main()
