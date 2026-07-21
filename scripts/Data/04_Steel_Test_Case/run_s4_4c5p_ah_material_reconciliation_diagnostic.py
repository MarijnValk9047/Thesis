"""Run the material-reconciliation diagnostic."""

from __future__ import annotations

from steel.s4_4c5p_ah_material_reconciliation_diagnostic import run_material_reconciliation_diagnostic


if __name__ == "__main__":
    print(run_material_reconciliation_diagnostic()["sensitivity_rows"])
