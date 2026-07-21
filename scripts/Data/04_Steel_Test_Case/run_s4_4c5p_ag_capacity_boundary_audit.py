"""Run the C5 quota-driven capacity-boundary audit."""

from __future__ import annotations

from steel.s4_4c5p_ag_capacity_boundary_audit import run_capacity_boundary_audit


if __name__ == "__main__":
    result = run_capacity_boundary_audit()
    print(result["summaries"])
