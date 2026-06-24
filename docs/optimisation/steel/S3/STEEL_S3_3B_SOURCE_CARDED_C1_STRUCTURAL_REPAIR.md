# S3.3b Source-Carded C1 Structural Repair

## Status

S3.3b is a bounded C1 structural diagnostic stage. It does not start S4, does not create approved inputs, and does not promote the S3.3a diagnostic WAG availability or natural-gas gap-closure values.

S3.3 remains blocked. The source-carded/provisional changes move the C1 carrier composition in the right direction, but no C1 case passes the principal holdout targets.

## Source-Card Decisions

The internal evidence supports the following C1 mechanisms strongly enough for source-carded or provisional-dev use:

- BF7 closure in Phase 1.
- KGF2 closure in Phase 1.
- KGF1 retention in the default Phase 1 interpretation.
- DRP natural-gas intensity of 195 m3 NG/t pellets.
- DRP capacity of 500 t pellets/h.
- Pellets-to-DRI efficiency of 0.74.
- DRI-to-steel/EAF efficiency of 0.95.
- A capacity-implied route-share diagnostic near BF-BOF 0.503 / DRP-EAF 0.497.
- A WAG hierarchy of process/self-use, steam/boiler, import-offset power, then flare.

The evidence is not yet sufficient for numeric C1 implementation of:

- generic C1 natural-gas residual/process-boundary gap closure;
- C1 NG boiler/process-heat top-up magnitude;
- C1 Vattenfall/WAG generator/interface reduction magnitude.

## Implemented Mechanisms

S3.3b adds the capacity-implied C1 route-share case:

```text
DRP-EAF output = 500 * 0.74 * 0.95 = 351.5 t/h
6.2 Mt/y average final product = 707.762557 t/h
DRP-EAF share = 351.5 / 707.762557 = 0.496635
BF-BOF share = 0.503365
```

The existing route-share cases 0.55, 0.61, and 0.68 are retained. The 0.503 case is a capacity-implied diagnostic, not an approved exact Phase 1 route share.

The metrics adapter now reports explicit DRP NG, inherited residual NG, steam/boiler NG, reheating NG, and WAG process/steam/reheating/power use components separately. WAG fuel energy remains internal conversion energy and is not double-counted in the Athanasiadis-compatible primary-energy proxy.

## Directional Validation

S3.3b ran the fixed C0 parameter sets:

- S33_CAND_001_CALIBRATION_ANCHOR
- S33_CAND_002_LOW_WAG_ENVELOPE
- S33_CAND_003_HIGH_WAG_ENVELOPE

over C1 BF-BOF route shares:

- 0.503365
- 0.55
- 0.61
- 0.68

The best existing S3.3 C1 holdout case was S33_CAND_002 at BF-BOF 0.55:

- gross electricity error: +4.17%
- WAG electricity error: +21.44%
- NG error: -19.84%
- CO2 error: +2.50%
- primary proxy error: -1.63%

The best S3.3b source-carded/provisional case is S33_CAND_002 at BF-BOF 0.503365:

- gross electricity error: +8.29%
- WAG electricity error: +11.14%
- NG error: -13.80%
- CO2 error: -2.09%
- primary proxy error: -1.87%
- explicit DRP NG: 97,500 m3/h
- inherited residual NG: 33,243.61 m3/h
- total NG: 130,743.61 m3/h

The result is directionally better for WAG and NG but still outside C1 tolerance. The remaining NG gap is about 20,930 m3/h.

## Interpretation

The capacity-implied DRP share explains part, but not all, of the C1 NG shortfall. It also reduces WAG electricity by reducing the BF-BOF/coking route fraction, but not enough to satisfy Table 9 without an additional source-backed mechanism.

The remaining gap is consistent with missing C1-specific process/steam/boiler NG top-up, missing WAG-to-process/boiler allocation detail, missing WAG generator/interface evidence, or a Phase 1 boundary mismatch. It is not defensible to close the gap with the S3.3a back-calculated residual NG value.

## Artifacts

S3.3b writes:

- `s3_3b_c1_source_support_register.csv`
- `s3_3b_c1_structural_change_register.csv`
- `s3_3b_c1_directional_validation_results.csv`
- `s3_3b_c1_route_share_capacity_check.csv`
- `s3_3b_c1_remaining_gap_analysis.csv`

All are candidate-review/provisional artifacts. No approved-input shell is populated.

## Freeze Decision

No S3.3 freeze record is created. S3.3 remains blocked because the source-carded/provisional C1 structural changes do not pass C1 holdout validation.

## Next Step

The next modelling step should be a narrow source-evidence pass for numeric C1 NG top-up/process-heat/steam demand and Vattenfall/WAG interface constraints. Coding a fitted residual or a fixed WAG cap would not be methodologically defensible.
