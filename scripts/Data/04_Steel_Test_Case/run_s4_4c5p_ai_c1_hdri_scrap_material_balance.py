"""Run the diagnostic C1 HDRI plus scrap material-balance stage."""

from __future__ import annotations

from steel.s4_4c5p_ai_c1_hdri_scrap_material_balance import run_c1_hdri_scrap_material_balance


if __name__ == "__main__":
    print(run_c1_hdri_scrap_material_balance()["summary"])
