"""Run the C5 opt-in downstream origin-interface feasibility check."""

from __future__ import annotations

from steel.s4_4c5p_an_downstream_origin_interface_feasibility import run_downstream_origin_interface_feasibility


if __name__ == "__main__":
    print(run_downstream_origin_interface_feasibility()["summary"])
