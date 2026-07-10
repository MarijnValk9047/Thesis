# C5 CO2 and Plant Energy-Anchor Boundary Diagnostics

Diagnostic-only C5p_h stage. It audits plant-level electricity/NG anchor coverage and the component-level CO2 boundary. It does not add residual loads, CO2 costs, ETS logic, economics, DA revenue, or a frozen denominator.

## Stage Gate

- Decision: `pass_development_co2_and_plant_energy_anchor_boundary_diagnostics`
- Failure count: `0`
- Caveat count: `14`
- Electricity anchor coverage: `partial_incomplete`
- NG anchor coverage: `partial_incomplete`
- CO2 boundary: `component_diagnostic_only_not_full_site_not_ETS_ready`
- ETS readiness: `NO_GO`

## Key Findings

- Plant-level electricity anchors are partial: PEFA, DRP, EAF, DSP, Sinter and ASU are represented, while KGF/BF/BOF/HSM/residual background coverage remains weak or not source-separated enough for a hard residual policy.
- Plant-level NG anchors are partial: C1 DRP, EAF and VN25/IJ01 generator NG are represented, while residual/background NG and HSM/sinter/utility NG remain missing or weak.
- CO2 remains component diagnostic only. PEFA and EAF aggregate diagnostics, DRP capture stream, and DSP inactive-fuel zero are reported separately from WAG, NG and scope-2 emissions.
- Recommended CO2 option is component diagnostic only until the energy boundary and WAG carbon policy are fixed.
