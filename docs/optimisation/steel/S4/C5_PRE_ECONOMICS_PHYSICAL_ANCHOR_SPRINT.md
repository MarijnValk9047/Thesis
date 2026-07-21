# C5 Pre-Economics Physical Anchor Sprint

## Decision

The pre-economics sprint is implemented as a diagnostic gate. Development-only
parameters may be used when they are marked, traceable and unit-consistent, but
economics, DA, ETS, product revenue, stochasticity, CVaR and mFRR remain out of
scope.

## Result

- Status: `pass`.
- Recommendation: `needs_one_more_physical_gate`.
- Sensitivity analyses evaluated: 5 of 5.
- Comparable anchor families: 6.
- Families within +/-15%: 0.
- Early stop achieved: False.

## Interpretation

The current physical model is useful as a pre-economics diagnostic, but it does
not yet pass the annual-anchor proximity gate. The sprint therefore stops after
the five planned analyses and reports the remaining blockers rather than
starting a cost layer.

Residual electricity and NG remain visible reporting quantities. They are not
used as model inputs, fuel allocations, costs or calibration terms.

## Main Outputs

- `data/03_Optimisation/runs/steel_pre_economics_physical_anchor_sprint_v1/pre_economics_readiness_summary.csv`
- `data/03_Optimisation/runs/steel_pre_economics_physical_anchor_sprint_v1/annual_anchor_proximity.csv`
- `data/03_Optimisation/runs/steel_pre_economics_physical_anchor_sprint_v1/max_five_sensitivity_register.csv`
- `data/03_Optimisation/runs/steel_pre_economics_physical_anchor_sprint_v1/remaining_blockers.csv`
