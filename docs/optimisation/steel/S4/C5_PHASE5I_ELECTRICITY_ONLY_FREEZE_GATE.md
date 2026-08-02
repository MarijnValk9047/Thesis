# C5 Phase 5I Electricity-Only Freeze Gate

## Decision

`represented_boundary_deterministic_model_frozen_for_phase6`

The narrow Phase-5I contract promotes only the Phase-5H validation-selected
10% electricity baseload. The four newly frozen held-out periods pass 56/56
terminal-aware C0/C1 rolling models with no reselection. Residual NG, steam and
direct CO2 remain zero and outside dispatch and cost.

## Promoted contract

The shared electricity share is 0.10. Exact configuration-specific loads are:

| Configuration | Eligible pool (PJ/y) | Annual represented load (PJ/y) | Constant load (MWh/h) |
|---|---:|---:|---:|
| C0 | 4.953621156905 | 0.495362115690 | 15.707829645182 |
| C1 | 5.530978067411 | 0.553097806741 | 17.538616398437 |

The contract classification is
`validation_selected_user_authorized_aggregate_electricity_baseload_abstraction`.
It is not an observed hourly profile, Tata-approved input, complete-site
allocation or price-responsive resource. It enters gross demand exactly once;
existing internal generation may serve it before zero-export grid purchase.

The Phase-5D NG bridges and failed Phase-5G electricity/NG baseload rows are
inactive. HSM shares and the 24-hour block abstraction, WAG yields, production
targets, capacities and terminal rules are unchanged.

## Fresh held-out result

The periods frozen by Phase 5H are October 2024 and February, April and July
2025. Each executes seven rolling replans for both configurations. All 56
models are optimal and every native production, material, carrier-WAG, steam,
inventory and terminal check passes. Steam unserved demand and export are zero;
the electricity baseload is constant and all electricity identities close.

Held-out annual-equivalent electricity results are generalisation evidence,
not exact annual backtests:

| Configuration | Model electricity (PJ/y) | Source anchor (PJ/y) | Absolute relative error |
|---|---:|---:|---:|
| C0 | 8.360848 | 13.7 | 38.97% |
| C1 | 12.805541 | 17.8 | 28.06% |

C0 generator NG is 0.109457 PJ/y against the absolute 1.9-PJ/y MER component.
C1 generator NG remains zero. All other mapped NG components remain within
their source or pre-existing validation limits; the rounded C1 EAF caveat is
not enlarged. WAG production remains production-driven.

## Freeze scope

The frozen claim is a physically and terminally validated represented physical
and procurement boundary. It is not a full-site digital twin, exact annual
anchor replication or ETS-ready emissions model. Annual NG, steam and direct-
CO2 gaps remain reporting limitations outside dispatch and cost. The governed
run is `steel_c5_phase5i_electricity_only_heldout_freeze_v1_20260728` with
`output_policy=minimal`.

The pass authorises Phase 6A deterministic DA purchase bidding and settlement
only. Stochastic scenarios, CVaR, mFRR, ETS, export and product revenue remain
outside this gate.
