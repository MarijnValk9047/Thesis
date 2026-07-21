# C5 Quota, Denominator and Representative-Week Normalisation

## Decision

The thesis-scale all-endogenous stress scenario uses final-product proxy as its
single production denominator. A 6.75 Mt/y target over a 365-day reporting
year equals 18,493.150685 t per 24-hour execution block and 129,452.054795 t
per 168-hour planning week.

It is not the sole production denominator for annual comparison.  C5 now
reports endogenous liquid steel, explicit imported slab, and site final
product separately under
`C5_PRODUCT_DENOMINATOR_AND_SLAB_IMPORT_BOUNDARY_POLICY.md`.

## Why this changes the comparison

The previous 5,905.2 t/day development quota annualises to about 2.155 Mt/y.
It was therefore a smoke target, not a meaningful basis for comparing annual
electricity, WAG, NG or emissions with a 6.75 Mt/y context target. The new
scenario tests physical feasibility at the target scale before any parameter
sensitivity is interpreted.

## Configuration policy

- C0 uses the existing fixed binary schedule.
- C1 uses the existing `bottom_up_fixed_retained_route` configuration.
- No C1 BF-BOF versus DRP/EAF fraction is newly selected. S3 records feasible
  scenario intervals and earlier diagnostic cases, but does not freeze an
  empirical central share. The current executable topology is therefore kept
  unchanged for this test.
- Final-product proxy is the denominator of this all-endogenous stress case,
  regardless of whether a tonne exits through HSM or DSP.
- Liquid-steel anchors remain separately labelled as upstream context.
- The C1 0.6 Mt/y imported-slab context is not active in this run.  It is an
  external material boundary, not an implicit supply, and must be modelled
  with origin-tagged downstream routing before a MER-boundary site-product
  feasibility scenario is interpreted.

## Interpretation gate

The run may establish only one of two outcomes:

1. the current fixed physical configuration can meet the thesis-scale quota;
   annualised energy and carrier diagnostics can then be compared as a
   representative-week result; or
2. it cannot meet the quota; the capacity, availability, route or material
   constraints are then the next physical gate. Energy/WAG/CO2 parameters must
   not be tuned to conceal that production-scale failure.

No prices, costs, DA, ETS, Wobbe model, aggregate-WAG physical allocation,
residual plug, or C1 split calibration is added.

## First thesis-scale result

`steel_thesis_scale_final_product_feasibility_v3` applies the normalised
129,452.054795 t final-product-proxy target over its 168-hour planning window.
Both C0 and C1 are infeasible in the first planning window under their current
fixed availability and retained-route policies. The solver returns this result
in about 1.1 seconds for C0 and 1.3 seconds for C1; it is not a runtime-limit
failure.

Consequently, no annual energy, WAG, NG or CO2 anchor table is produced for
the thesis-scale case. Annualising a physically infeasible week would create a
misleading comparison. The next gate is a production-capacity and
availability-calendar reconciliation: identify which fixed process rates,
on-hours, material capacities or C1 route assumptions prevent the final
product target. This must precede any energy or emissions parameter tuning.
