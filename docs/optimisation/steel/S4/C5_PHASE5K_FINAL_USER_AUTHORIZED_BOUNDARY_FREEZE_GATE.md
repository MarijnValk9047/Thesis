# C5 Phase 5K Final User-Authorized Boundary Freeze Gate

## Decision

`user_authorized_represented_boundary_deterministic_model_frozen_for_phase6`

Phase 5K closes the deterministic physical-development campaign at the
represented procurement boundary. All 56 validation and 56 newly frozen
held-out rolling models are optimal, all physical and terminal checks pass,
and the contract was not reselected after held-out inspection.

This is not a full-site digital twin, an exact annual backtest or an ETS-ready
emissions model. The final aggregate terms are development abstractions
authorized to close the model and move to market-method development.

## Promoted contract

| Term | C0 | C1 | Treatment |
|---|---:|---:|---|
| Constant electricity baseload | 4.458259 PJ/y (141.370467 MWh/h) | 4.977880 PJ/y (157.847548 MWh/h) | 90% of the frozen eligible pool; fixed net demand |
| Constant site NG service | 7.000000 PJ/y (221.968544 MWh/h) | 7.000000 PJ/y (221.968544 MWh/h) | fixed external NG purchase, costed once and not WAG-displaceable |
| Residual direct CO2 | 2.000000 MtCO2/y | 2.000000 MtCO2/y | reporting only; no dispatch, cost or ETS treatment |
| Residual steam | 0 | 0 | inactive |
| WAG yield multiplier | 0.95 | 1.00 | C0-only user-authorized fallback |

Legacy Phase-5D NG bridges and failed Phase-5G residual rows remain inactive.
HSM policy, production physics, capacities, terminal rules, zero export and C1
WAG yields are unchanged.

## Carrier-level WAG investigation

The governed MER source reports C0/C1 production by carrier: BFG 33.2/14.8,
COG 14.7/8.1 and BOFG 5.0/2.2 PJ/y. The model's original generic yields are
inside their documented parameter ranges and no unit, activity-basis or
configuration defect was found that justifies a new carrier coefficient.

The held-out C0 excess before adjustment is concentrated in COG: BFG is 0.78%
below its source component, COG 31.76% above and BOFG 0.83% above. Therefore a
uniform reduction is not a source-identified correction. The predeclared 5%
C0-only fallback is nevertheless promoted as a
`user_authorized_represented_boundary_development_abstraction`.

After the adjustment, held-out C0 WAG is 54.485 PJ/y: 3.00% above the direct
52.9-PJ/y carrier sum and 0.90% above the rounded 54-PJ/y context. Its carrier
errors remain -5.74% BFG, +25.18% COG and -4.21% BOFG. C1 remains unmodified at
25.449 PJ/y, 1.39% above its 25.1-PJ/y carrier sum. These carrier deviations are
reported limitations, not reasons to reopen calibration.

## Fresh held-out result

The four fresh periods were selected and fingerprinted using timestamp
structure only, then opened once. Across C0/C1 and seven rolling replans there
are 56/56 optimal models, zero unserved steam and no production, material,
carrier-WAG, electricity, HSM or terminal failure.

| Annual-equivalent metric | C0 | C1 |
|---|---:|---:|
| Gross electricity | 12.3237 PJ/y; 10.05% below 13.7 | 17.2305 PJ/y; 3.20% below 17.8 |
| Named NG procurement | 11.4428 PJ/y; 8.46% below 12.5 | 40.9601 PJ/y; 12.29% below 46.7 |
| Total WAG | 54.4847 PJ/y; 3.00% above 52.9 | 25.4492 PJ/y; 1.39% above 25.1 |
| WAG flare | 0.0801 PJ/y | 0.0022 PJ/y |
| Direct-CO2 comparison | 12.0908 Mt/y; 4.04% below 12.6 | 8.7218 Mt/y; 5.08% above 8.3 |

The common CO2 term was selected on validation only from the predeclared
0.5-MtCO2/y grid after recalculating WAG and NG combustion. The 2.0-MtCO2/y
candidate minimizes the maximum C0/C1 relative error. Fuel combustion and the
aggregate residual remain separate; the 7-PJ/y NG combustion is counted in the
explicit NG-emissions ledger and is not added twice.

Annual-equivalent fixed-reference represented procurement cost is EUR 1.911
billion/y for C0 and EUR 3.227 billion/y for C1. These are representative-period
extrapolations, not market backtests.

## Freeze scope and handoff

The frozen scope is physically and terminally validated for represented
production, utilities and external procurement. The electricity and NG loads
are constant, inelastic and included exactly once. The CO2 residual is
reporting-only. Whole-site steam, emissions attribution, carrier-specific COG
discrepancy and complete Tata-site coverage remain outside the claim.

The governed run is
`steel_c5_phase5k_final_user_authorized_boundary_freeze_v1_20260729`, uses
`output_policy=minimal`, and contains 17 compact files (about 59 KB). Phase 6A
must use this exact fingerprinted boundary before any stochastic work.
