# S3.3e Inherited NG Residual Resolution

## Purpose

S3.3e resolves the inherited C0 natural-gas residual found in S3.3d. It does not start S4 and does not add DA prices, stochastic logic, CVaR, mFRR, bidding, settlement, Vattenfall unit commitment, or a fitted residual.

## Residual Being Resolved

The inherited residual was `46.97 m3_NG/t_final_product`, which equals `33,243.607 m3/h` at the 6.2 Mt/y calibration scale. This is effectively the C0 Table 8 natural-gas target and was carried into C1 through the C0 calibration parameter `residual_c0_ng_m3_per_t_final`.

It is not a decomposed C1 process-gas component.

## Option A Result

Option A attempted to decompose the residual into source-backed named C1 gas components.

Accepted existing components:

- explicit NG-DRP gas demand: `195 m3/t_pellets`, already represented on the pellets-input basis;
- downstream/light-side utility NG: `7.5-8.0 PJ/y`, retained only as a provisional broader-boundary component.

Rejected for residual decomposition:

- steam/boiler top-up: qualitative support only, no governed numeric value;
- BF/hot-stove auxiliary NG: available evidence is BFG/COG process fuel, not natural gas;
- coking underfiring/steam demand: C0/coking context only without a governed C1 retained-coking NG split;
- gas enrichment or backup fuel: qualitative support only;
- inherited C0 residual: blocked as a C0 calibration closure, not C1 source evidence.

Option A therefore failed without weak assumptions or hidden residual fitting.

## Option B Applied

Athanasiadis Table 9 carrier totals are downgraded from strict S3.3 freeze criteria to broader-boundary/contextual holdout references.

Strict S3.3e validation is now based on the represented public MILP boundary:

- production fulfilment;
- terminal inventory neutrality;
- material balance closure;
- WAG and electricity balance closure;
- carbon decomposition closure;
- no WAG double-counting in the primary-energy proxy;
- explicit separation of DRP NG, utility NG, represented steam/reheating NG, and rejected residual NG.

The rejected inherited residual is set to zero in C1 residual-resolution validation.

## Validation Result

The S3.3e runner evaluated the three selected S3.3 ensemble candidates across route shares `0.5033645161`, `0.55`, `0.61`, and `0.68`, using no-extension, low, central, and high utility cases.

Results:

- C0 retained-ensemble regression: `3/3` accepted.
- C1 current-boundary strict checks: `48/48` passed.
- C1 residual NG after resolution: `0.0 m3/h` in all C1 rows.
- WAG double-counting check: `48/48` passed.

Best contextual row:

- candidate: `S33_CAND_001_CALIBRATION_ANCHOR`;
- route share: BF-BOF `0.5033645161`;
- utility case: `s3_3d_provisional_utility_low`;
- explicit DRP NG: `97,500.0 m3/h`;
- downstream/utility NG: `24,343.6 m3/h`;
- rejected inherited residual NG: `33,243.6 m3/h`;
- residual NG included in C1 total: `0.0 m3/h`;
- WAG-to-power fuel: `13.907 PJ/y`;
- flare: `0.732 PJ/y`.

Contextual Table 9 errors for that row:

- gross electricity: `+8.29%`;
- WAG electricity: `+0.82%`;
- NG: `-19.67%`;
- CO2: `+2.53%`;
- primary proxy: `-4.56%`.

These carrier-total errors are reported for transparency but are no longer strict freeze gates for the current public MILP boundary.

## Stage Decision

S3.3e status is `provisionally_acceptable_current_public_boundary_table9_contextual_s4_blocked`.

This means the inherited residual blocker is resolved by validation-boundary downgrade, not by source-backed decomposition. S4 should not start until the user explicitly accepts the Table 9 contextual downgrade as the S3.3 freeze boundary.

