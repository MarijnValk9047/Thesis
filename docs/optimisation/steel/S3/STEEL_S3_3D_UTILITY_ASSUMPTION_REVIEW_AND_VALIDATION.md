# S3.3d Utility Assumption Review And Retained Validation

## Purpose

S3.3d reviews the S3.3c utility/heat/steam boundary assumptions and reruns C1 validation across the retained S3.3 parameter ensemble. It does not start S4 and does not add DA prices, stochastic logic, CVaR, mFRR, bidding, settlement, Vattenfall unit commitment, or approved-input promotion.

## Governance Decision

The S3.3c utility boundary is useful as a broader-boundary diagnostic, but it is not freeze-ready.

- The downstream/light-side natural-gas boundary is classified as a provisional input for validation only.
- WAG-to-power efficiency values are classified as sensitivity-only candidate values.
- S3.3a fitted values remain rejected: `c1_wag_availability_factor = 0.75` and `89.478 m3/t_final_product`.
- The inherited residual NG term is blocked for freeze. It is the C0 calibration parameter `residual_c0_ng_m3_per_t_final`, carried into C1 validation, not a decomposed C1 process-gas or utility consumer.

## Residual NG Audit

For all three selected ensemble members, the inherited residual is `46.97 m3/t_final_product`. At the 6.2 Mt/y scale this is `33,243.607 m3/h`, effectively the C0 Table 8 natural-gas target (`33,243.63 m3/h`). This is not evidence for retained C1 baseline/process gas. It is a C0 calibration closure and must either be decomposed into source-backed retained gas consumers or kept as a contextual boundary term.

## Validation Run

The S3.3d runner evaluated:

- candidates: `S33_CAND_001_CALIBRATION_ANCHOR`, `S33_CAND_002_LOW_WAG_ENVELOPE`, `S33_CAND_003_HIGH_WAG_ENVELOPE`;
- route shares: capacity-implied `0.5033645161`, `0.55`, `0.61`, `0.68`;
- utility cases: no-extension baseline, low, central, and high provisional utility assumptions.

C0 regression remained accepted for all three selected candidates with the utility boundary inactive.

The best score row was the central calibrated set at capacity-implied route share under the low provisional utility case. Its C1 errors were:

- gross electricity: `+8.29%`;
- WAG electricity: `+0.82%`;
- natural gas: `+2.25%`;
- CO2: `+2.53%`;
- primary proxy: `+5.47%`.

It does not pass the principal C1 gate because gross electricity remains outside the 5% tolerance.

One provisional numerical pass exists: `S33_CAND_002_LOW_WAG_ENVELOPE`, BF-BOF share `0.55`, low utility case. Its C1 errors were:

- gross electricity: `+4.17%`;
- WAG electricity: `+4.93%`;
- natural gas: `-3.79%`;
- CO2: `+7.12%`;
- primary proxy: `+5.71%`.

This row is not freeze-eligible because it still includes the inherited C0 residual NG component.

## Stage Gate

S3.3d status is `provisionally_acceptable_pending_source_card_review_but_s3_3_blocked`.

S3.3 remains blocked for S4 entry. The next decision must resolve whether Table 9 is treated as broader-boundary contextual validation or whether the residual C0 NG component can be decomposed into governed C1 utility/process consumers.

