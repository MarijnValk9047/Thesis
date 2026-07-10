# C5 Residual Electricity / NG Boundary Diagnostics

Diagnostic-only C5p_g stage. It does not add residual electricity loads, residual NG loads, costs, CO2 logic, DA revenue, mFRR, WAG market value, or a frozen denominator.

## Stage Gate

- Decision: `pass_development_residual_electricity_ng_boundary_diagnostics`
- Failure count: `0`
- Caveat count: `12`
- Electricity boundary: `incomplete_reporting_only_not_full_site_net_import`
- NG boundary: `incomplete_no_full_site_NG_claim`
- CO2 dependency: `CO2_boundary_depends_on_energy_boundary`

## Findings

- C0 current process-only electricity exposure pre-floor is `-0.324941` TWh/y and post-floor is `0` TWh/y.
- C1 current process-only electricity exposure post-floor is `2.098472` TWh/y.
- C1 modelled NG is `31.783675` PJ/y, composed of DRP, EAF and generator NG in the current boundary.
- Electricity and NG residual options are registered but not applied.
- Economics and DA readiness remain NO-GO.
