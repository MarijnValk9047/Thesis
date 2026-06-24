# S3.3c Utility Boundary Extension Summary

## Purpose

S3.3c tests whether the remaining C1 Table 9 carrier mismatch is partly caused by a too-narrow public model boundary. It does not start S4 and does not add DA prices, stochastic logic, CVaR, mFRR, bidding, settlement, product revenue, or Vattenfall unit commitment.

## Evidence Basis

The extension uses existing public-source-carded structure:

- the Tata IJmuiden site has an Energiebedrijf / internal gas, steam and electricity interface;
- VN24, VN25 and IJM-01 are represented only as a power/steam interface abstraction;
- WAG should be allocated to process, steam/heat, power, then flare;
- downstream/light-side natural-gas demand of 7.5-8.0 PJ/y is treated as candidate boundary evidence, not fitted residual truth;
- WAG-to-power efficiency remains a public candidate range or sensitivity, not a Tata dispatch claim.

The S3.3a diagnostic values `c1_wag_availability_factor = 0.75` and `residual NG = 89.478 m3/t_final_product` remain rejected as thesis inputs.

## Implemented Boundary Layer

The integrated S3 model now has an explicit downstream/light-side utility heat node with:

- WAG-to-utility-heat arcs by carrier;
- natural-gas-to-utility-heat top-up;
- an optional minimum natural-gas boundary for cases where the source value is interpreted as reported downstream/light-side NG rather than generic heat demand;
- direct natural-gas emissions for utility heat;
- reporting of utility NG, WAG utility heat, WAG-to-power, flare, DRP NG, residual inherited C0 NG, gross electricity and primary proxy.

The default demand is zero, so legacy C0/S3.2/S3.3 behaviour is unchanged unless the S3.3c runner explicitly activates a candidate boundary case.

## Candidate Cases

S3.3c writes governed candidate-review artifacts for:

- previous S3.3b baseline with no utility extension;
- WAG/NG heat-service and explicit-NG interpretations of the downstream/light-side boundary;
- low, central and high downstream/light-side utility boundary cases at 7.5, 7.75 and 8.0 PJ/y;
- one public lower WAG-to-power efficiency sensitivity at 0.321.

These are candidate-review and directional-validation rows only. Approved input shells are not populated.

## Validation Interpretation

Table 9 should be interpreted as broader-boundary validation while this layer remains candidate/provisional. A strict C1 pass is thesis-defensible only if the utility boundary values are promoted through the governed source-review path and the carrier totals pass without arbitrary residual closure.

The current directional result indicates that a low explicit downstream/light-side NG boundary case plus the public lower WAG-to-power efficiency sensitivity can pass the principal C1 carrier-error tolerances. That is evidence that the prior C1 failure was plausibly a boundary/utility-layer issue, not a licence to freeze the values as approved Tata inputs.

## S4 Status

S4 remains blocked until S3.3/C1 validation gates are explicitly reopened and passed.
