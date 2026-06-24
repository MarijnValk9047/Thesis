# S3.3f Bounded C1 Alignment Diagnostic

## Purpose

S3.3f is a bounded C1 alignment diagnostic. It asks how close the current Tata Steel IJmuiden-inspired static steel model can get to the Athanasiadis Phase 1 / C1 Table 9 and Figure 104 targets when only already governed or source-carded parameter ranges are varied.

This is not a calibration freeze, not independent validation, and not S4 entry.

## Boundary

The diagnostic uses the C1 targets only for diagnostic scoring:

- gross electricity: 4.89 TWh/y;
- WAG electricity generation: 1.23 TWh/y;
- natural gas: 151,673.52 m3/h;
- direct CO2: 9,107,793.17 t/y;
- primary-energy proxy: 102.1941 PJ/y;
- carrier shares: coal 40.1%, electricity 17.2%, natural gas 42.7%.

The runner writes compact candidate-review artifacts only under:

`data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review/`

No run folder and no approved-input table are created.

## Eligible Parameters

S3.3f derives eligible values from existing S3.3/S3.3b/S3.3c/S3.3d/S3.3e registers and source-carded ranges. Eligible categories include:

- retained C0 ensemble parameters with governed ranges, excluding residual C0 natural gas;
- C1 BF-BOF route-share cases, including the capacity-implied 0.503365 diagnostic case and the retained 0.55, 0.61, and 0.68 cases;
- DRP natural-gas multiplier range 0.8 to 1.3;
- downstream/light-side utility natural-gas boundary cases 0.0, 7.5, 7.75, and 8.0 PJ/y;
- WAG yields, LHV scale, residual-utilisation fraction, and WAG-to-power efficiency inside registered bounds;
- direct CO2 and primary-energy proxy factors inside registered bounds.

## Excluded Mechanisms

The diagnostic explicitly excludes:

- inherited C0 residual natural gas in C1;
- Table 9 back-calculated residual natural-gas closure;
- arbitrary C1 WAG availability correction factors;
- arbitrary WAG-to-power caps or Vattenfall dispatch corrections;
- hidden zero filling for missing ranges;
- DA, stochastic, CVaR, mFRR, market, or S4 logic.

## Scoring

The C1 score is weighted mean absolute percentage error over:

- gross electricity, weight 1.0;
- WAG electricity, weight 1.5;
- natural gas, weight 1.5;
- direct CO2, weight 1.0;
- primary-energy proxy, weight 1.0.

The output also reports unweighted mean absolute percentage error, maximum absolute percentage error, all-target 5%, 10%, and 15% screens, carrier-share errors, feasibility status, balance residuals, terminal residuals, and range-edge flags.

## Interpretation Rule

A numerical near-fit under nonzero downstream/light-side utility assumptions can support only contextual broader-boundary validation or bounded alignment. It cannot by itself support strict C1 validation, S3.3 freeze, approved-input promotion, or S4 readiness.

Strict validation would require source-reviewed acceptance of the relevant boundary assumptions and a pass without residual gap closure, arbitrary WAG correction, or hidden unsupported values.

