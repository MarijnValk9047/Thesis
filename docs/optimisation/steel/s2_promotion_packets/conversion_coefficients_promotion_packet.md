# Conversion Coefficients Promotion Packet

## Category Purpose In S2

`conversion_coefficients` would eventually define the metallic flow relationships between process activity and carrier consumption or production in deterministic `S2`.

## Rows / Tables Covered

- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/conversion_coefficients_candidate_review.csv`
- current reviewed row count: `4`
- related governance rows in:
  - `s2_promotion_checklist.csv`
  - `s2_structural_numerical_classification.csv`

## Candidate Evidence Status

Current support is non-executable and generic:

- technology-range support;
- structural sign placeholders;
- route-generic coefficient interpretations.

No row is site-calibrated or approved as a plant coefficient.

## Unit Conventions And Unresolved Unit Issues

Future executable coefficients need a single frozen basis such as:

- `t_input / t_activity`
- `t_output / t_activity`
- or another explicit carrier-per-activity basis.

Unresolved issues:

- current candidate rows do not yet freeze one loader convention;
- mixed basis across routes would create silent comparability errors;
- yield-style coefficients and recipe-style coefficients are not yet distinguished tightly enough for executable use.

## Sign Conventions And Unresolved Sign Issues

This is the main blocker.

The future executable loader must choose one convention, for example:

- positive production and negative consumption; or
- positive magnitudes with explicit role fields.

Current reviewed rows are only sign placeholders and may not freeze that choice yet.

## Annual-To-Hourly Translation Risks

Not the primary blocker here, but there is still a risk of mixing:

- annual recipe anchors;
- route-generic yield assumptions;
- hourly executable coefficients.

Any annual evidence must remain review support, not an hourly executable coefficient.

## Allowed Review Uses

- structural support that a process requires metallic conversion logic;
- unit and sign convention review;
- assumption support for later coefficient schema design;
- sensitivity framing only after explicit labelling.

## Forbidden Executable Uses

Do not use current rows as:

- executable recipes;
- executable yields;
- route-share truth;
- fixed plant-specific metallic balances.

## Approval Blockers

- site calibration absent;
- signed loader convention not frozen;
- recipe versus yield semantics not frozen;
- public evidence does not yet justify thesis-grade executable coefficients.

## Minimum Evidence Needed For Later Approval

- process-by-process reviewed source support;
- frozen sign convention;
- frozen coefficient-role taxonomy;
- consistent unit basis across all executable rows;
- explicit distinction between validation support and executable coefficients.

## Thesis-Usability Requirements

Before any thesis-usable numerical promotion:

- source review complete;
- unit review complete;
- sign review complete;
- coefficient-role review complete;
- cross-route consistency check passed.

## Misuse Red Flags

- generic DRI or BOF yields copied into executable plant coefficients;
- silent sign flips across files;
- using one coefficient table for both validation anchors and executable constraints;
- mixing recipe-style and yield-style rows without an explicit role field.

## Recommended Next Review Action

Draft a coefficient-loader convention note with one executable sign rule and one executable unit basis, then reclassify each reviewed row as either:

- executable candidate later;
- validation support only; or
- assumption support only.
