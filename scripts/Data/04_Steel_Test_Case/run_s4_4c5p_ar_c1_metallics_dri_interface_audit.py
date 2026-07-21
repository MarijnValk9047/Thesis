from __future__ import annotations

from steel.s4_4c5p_ar_c1_metallics_dri_interface_audit import run_c1_metallics_dri_interface_audit


if __name__ == "__main__":
    result = run_c1_metallics_dri_interface_audit()
    print(result["summary"])
