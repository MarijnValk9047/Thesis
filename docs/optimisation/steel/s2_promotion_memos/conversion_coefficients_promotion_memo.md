# Conversion Coefficients Promotion Memo

## Category Purpose In S2

`conversion_coefficients` drive metallic balances and route feasibility.

## Evidence Status

Current rows are generic technology ranges or structural sign placeholders.

No site-calibrated approved recipe set exists.

## Unit Conventions

- examples: `t_hot_metal_per_tLS`, `t_burden_per_tHM`
- each coefficient must carry an explicit numerator and denominator basis

## Sign Conventions

The loader-side sign convention is still under review.

The future executable rule must freeze whether:

- inputs are stored as positive requirements and applied by loader logic, or
- signed coefficients are stored directly.

## Model Role

- candidate numerical model input later;
- sign-convention review surface now.

## Approval Blockers

- site calibration missing;
- loader-side sign convention not frozen;
- generic ranges are not Tata-specific operating truth.

## Thesis-Usability Requirements

- explicit sign convention;
- explicit unit basis;
- reviewed source support;
- route-specific recipe choice and caveat disclosure.

## Misuse Red Flags

- mixing signed and unsigned coefficients silently;
- treating generic ranges as approved plant recipes;
- omitting yield-loss treatment and claiming feasibility.
