from steel.s4_4c5p_ag_normalised_anchor_diagnostics import run_normalised_anchor_diagnostics


if __name__ == "__main__":
    result = run_normalised_anchor_diagnostics()
    print(result["summary"])
