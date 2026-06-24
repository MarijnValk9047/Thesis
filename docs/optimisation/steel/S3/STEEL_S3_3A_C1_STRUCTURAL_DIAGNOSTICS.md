# S3.3a C1 Structural Diagnostics

Date: 2026-06-20

## Scope

S3.3a is a diagnostic-only stage for the failed C1 holdout in S3.3. It does not start S4 and does not add DA prices, stochastic scenarios, CVaR, mFRR, bidding, settlement, or approved input rows.

The purpose is to test whether the C1 mismatch is caused by missing structural mechanisms rather than by further C0 parameter calibration.

## Diagnostic Matrix

The diagnostic keeps C0 calibrated candidate parameters fixed and varies only labelled C1 diagnostic switches:

- `c1_wag_availability_factor`: `1.00`, `0.75`, `0.50`, `0.25`; assumption-only, source needed.
- `drp_ng_multiplier`: `0.8`, `1.0`, `1.3`; governed holdout-sensitivity range.
- `c1_retained_coking_wag_displacement_factor`: `1.00`, `0.75`, `0.50`; assumption-only, source needed.
- `c1_residual_ng_boundary_m3_per_t_final`: `0`, inherited C0 residual, and Table 9 gap-closure back-calculations; diagnostic only, not approved.

The full switch sweeps are run for `S33_CAND_001_CALIBRATION_ANCHOR`. Baseline plus combined diagnostics are run for `S33_CAND_002_LOW_WAG_ENVELOPE` and `S33_CAND_003_HIGH_WAG_ENVELOPE`.

Route-share scenarios remain:

- `0.55`
- `0.61`
- `0.68`

## Artifacts

The compact governed artifacts are written under `data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review/`:

- `s3_3a_c1_structural_diagnostic_matrix.csv`
- `s3_3a_c1_structural_diagnostic_results.csv`
- `s3_3a_c1_diagnostic_decision_summary.csv`
- `s3_3a_c1_boundary_crosswalk_amendment.csv`

No generated run folder is created.

## Boundary Governance

The S3.3 C0 boundary crosswalk is amended by a diagnostic-only C1 crosswalk. The C1 rows document how Table 9 and Figure 104 are compared to model metrics, but they do not change C0 calibration scoring and do not populate approved inputs.

WAG fuel energy remains internal conversion energy and is not added again to the Athanasiadis-compatible primary-energy proxy.

## Decision Use

S3.3a can support one of three decisions:

1. A small C1 structural layer is enough if combined diagnostic switches bring WAG, NG, electricity, and CO2 inside holdout tolerances.
2. More source-card work is needed if the signs improve but values remain outside tolerance.
3. The simplified route-share abstraction is inadequate if WAG and NG remain wrong even after bounded structural switches.

S3.3 remains blocked unless a later governed stage creates a defensible C1 structure and validates it without retuning C0 parameters.

## Diagnostic Results

The implemented diagnostic matrix contains `54` solved/planned cases:

- full central-candidate sweeps for `S33_CAND_001_CALIBRATION_ANCHOR`;
- baseline plus combined diagnostics for `S33_CAND_002_LOW_WAG_ENVELOPE`;
- baseline plus combined diagnostics for `S33_CAND_003_HIGH_WAG_ENVELOPE`;
- route shares `0.55`, `0.61`, and `0.68`.

The inherited C0 baseline remains outside C1 holdout tolerance. The best inherited baseline is `S33_CAND_002_LOW_WAG_ENVELOPE` at BF-BOF share `0.55`, with gross electricity `+4.17%`, WAG electricity `+21.44%`, NG `-19.84%`, CO2 `+2.50%`, and primary proxy `-1.63%`.

WAG-side diagnostics can repair the WAG electricity target:

- WAG availability factor `0.75` brings WAG close to target while leaving NG too low.
- Retained-coking/WAG displacement can also bring WAG close to target, but it does not repair NG exposure by itself.

NG-side diagnostics show that the governed DRP NG multiplier alone is not sufficient in this public model:

- DRP multiplier `0.8` worsens the NG shortfall.
- DRP multiplier `1.3` is infeasible in the current structural formulation.
- The only diagnostic cases that repair NG use a Table 9 gap-closure residual boundary, which is explicitly source-needed and not an approved input.

The best overall diagnostic case is `S33_CAND_003_HIGH_WAG_ENVELOPE` at BF-BOF share `0.55` with WAG availability `0.75`, inherited DRP NG multiplier `1.0`, retained-coking/WAG displacement `1.0`, and a Table 9 back-calculated C1 residual NG boundary of about `89.48 m3/t_final_product`. It has gross electricity `+4.17%`, WAG electricity `+0.46%`, NG `0.00%`, CO2 `+2.50%`, and primary proxy `+7.44%`.

Five diagnostic cases pass the C1 principal-target tolerance screen, but all passing cases depend on a source-needed residual NG boundary back-calculation. Therefore, S3.3a supports the conclusion that the C1 mismatch is fixable in sign with a small structural/boundary layer, but not yet defensible as calibrated thesis input.

## Decision

S3.3 remains blocked. S4 is not ready.

Recommended next action: perform a narrow source-backed C1 evidence pass for the residual NG boundary, WAG availability/interface reduction, and retained-coking/WAG displacement before turning any diagnostic switch into a governed model input.
