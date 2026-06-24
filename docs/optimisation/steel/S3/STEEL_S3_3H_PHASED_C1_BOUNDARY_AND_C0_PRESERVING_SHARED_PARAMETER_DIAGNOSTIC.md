# S3.3h Phased C1 Boundary And C0-Preserving Shared-Parameter Diagnostic

## Status

S3.3h is a phased diagnostic only. It is not an S3.3 freeze, not S4 entry, and not an approved-input promotion.

The diagnostic answers two separate questions:

- Block A: how close C1 can get when only C1-specific boundary, utility, and named gas-sink mechanisms vary while shared C0-calibrated parameters stay fixed;
- Block B: whether governed shared energy/electricity parameters can improve C1 while preserving C0 calibration tolerances.

No residual C1 natural-gas closure, inherited C0 residual NG, Table 9 back-calculated residual, or arbitrary WAG availability factor is used.

## Source Basis

S3.3h inherits the S3.3g source-card review for Athanasiadis gas-network structures. The local Athanasiadis PDF was not found in the allowed checked locations, so Figure 31, Figure 32, Figure 33, Table 9, and Figure 104 are referenced through existing source cards, S3.3 target registers, and research-memo context rather than direct PDF verification.

## Block A

Block A keeps the central C0-calibrated shared parameter set fixed and varies only C1-specific mechanisms:

- BF-BOF route share `0.5033645161` and `0.55`;
- HSM NG within the existing S3.3g lower/central/upper range;
- pelletizing firing NG within the existing S3.3g lower/central/upper range;
- boiler/steam NG and WAG values at `0`, `1`, and `2 PJ/y`, plus `3`, `4`, and `6 PJ/y` as clearly labelled gap-sizing values;
- Vattenfall BFG-equivalent WAG fraction from existing governed diagnostic values.

Extended boiler/steam values above `2 PJ/y` are not source-approved inputs. They are gap-sizing diagnostics.

## Block B

Block B starts from the best Block A cases and varies only currently exposed governed shared parameters:

- downstream electricity scale;
- residual auxiliary electricity scale;
- WAG-to-power efficiency;
- WAG LHV scale.

Separate EAF and DRP electricity intensities remain relevant source categories but are not varied in S3.3h because the current runner does not expose independent governed parameters for them.

Every Block B candidate runs both C1 and a C0 regression. A C1 improvement is rejected if C0 breaches calibration tolerances.

## Outputs

All S3.3h outputs are compact candidate-review artifacts under:

`data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review/`

The main interpretation files are:

- `s3_3h_best_case_comparison.csv`
- `s3_3h_rejected_cases.csv`
- `s3_3h_remaining_gap_analysis.csv`
- `s3_3h_boundary_decision_support.csv`

S3.3h can support bounded alignment or gap-sizing only unless all active assumptions gain approved numeric source cards and C0 preservation remains demonstrated.
