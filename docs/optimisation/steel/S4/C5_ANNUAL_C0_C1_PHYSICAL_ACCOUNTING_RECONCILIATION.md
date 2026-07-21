# C5 Annual C0/C1 Physical/Accounting Reconciliation

This report is reconstructed from current C5 artifacts by the C5p_e diagnostic stage. It is development-only and not thesis-approved.

## Stage Gate

- Decision: `pass_development_annual_reconciliation_diagnostic`
- Failure count: `0`
- Caveat count: `13`
- Denominator status: `unresolved_until_residual_loads_and_boundary_complete`
- Electricity boundary: `incomplete_reporting_only_not_full_site_net_import`
- NG boundary: `incomplete_no_full_site_NG_claim`
- CO2 boundary: `component_diagnostic_only_not_ETS_ready`

## Main Findings

- C1 generator fuel gap remains explicit and is not hidden.
- C0 2.0 TWh residual-gas electricity is treated as validation anchor only.
- `generated_or_supplied` in the carrier flow table is a controller-reconciled pre-steam supply compatibility field, not source gross WAG generation.
- Gross generation, mandatory source self-use, network availability, and downstream controller supply are side-by-side in `c5_annual_wag_ledger_point_reconciliation.csv`; cross-stage gaps are diagnostics, not tuning targets.
- Final-product denominator, residual electricity/NG, and CO2 boundaries remain open.
- C5p_d buffer/store validation remains pass-with-caveats with no free-source stores.

## Candidate Lever Register

Candidate levers are review/sensitivity rows only. No parameter is changed by this stage.
