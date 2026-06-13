# Steel Thesis Writing Plan

## Purpose

This document supports thesis writing alongside staged steel implementation.

It tells the implementation workstream:

- what to write after each stage;
- which tables and figures matter;
- how to describe the model honestly;
- how to protect forecast-quality comparisons from narrative drift.

## Chapter Or Section Mapping

Suggested steel-model structure in the thesis:

1. steel-model motivation and relation to the hydrogen verification case;
2. Tata-inspired scope, boundary, and policy choices;
3. evidence and governance path from Waves `A` through `E`;
4. `S2` metallic material-flow model;
5. `S3` WAG, internal-energy, emissions, and economic layer;
6. later DA, stochastic, reserve, granularity, and risk extensions as they become implemented;
7. validation, tractability, and limitations;
8. experiment design and result interpretation.

## What To Write After Each Stage

### After `S1`

Write:

- why the steel model is Tata-inspired rather than a digital twin;
- why candidate evidence and approved structure must be separated;
- what Waves `A` through `E` established;
- why no approved numerical model-input table exists yet.

### After `S2`

Write:

- the metallic network boundary;
- route definitions;
- fixed production target logic;
- buffer treatment;
- infeasibility diagnostics and validation story.

### After `S3`

Write:

- the minimal `B_lite` WAG layer;
- emissions architecture;
- gross ETS treatment;
- `N1` tariff proxy policy;
- fixed-target cost-minimisation logic.

### After `S4`

Write:

- deterministic DA price-taking dispatch;
- why this is not bidding yet;
- benchmark logic and oracle caveat.

### After `S5`

Write:

- DA bidding, clearing, and settlement sequence;
- information timing and physical redispatch;
- benchmark continuity from earlier stages.

### After `S6`

Write:

- scenario construction and probability handling;
- non-anticipativity;
- forecast-quality comparison design.

### After `S7`

Write:

- reserve-value logic after DA-only stability;
- deliverability and production-fulfilment safeguards;
- why `S7` is a market-scope extension.

### After `S8`

Write:

- why 15-minute and `D_plus_4` matter for the thesis;
- one-dimension-at-a-time design;
- observed quarter-hour truth caveat.

### After `S9`

Write:

- risk-return framing;
- CVaR sensitivity logic;
- why risk aversion was postponed until late.

## Tables And Figures Per Stage

### `S1`

- governance table for structure versus candidate values versus assumptions;
- wave-to-artifact mapping table.

### `S2`

- configuration and route table;
- balance-validation table;
- material-flow diagram;
- inventory trajectory figure;
- infeasibility-class table if relevant.

### `S3`

- carrier and interface table;
- emissions-accounting table;
- gross ETS and tariff-policy disclosure table;
- WAG balance figure;
- energy and emissions summary table.

### `S4`

- DA price versus dispatch figure;
- price-insensitive versus oracle benchmark table;
- settlement summary table.

### `S5`

- bid, clear, settle figure;
- realised versus optimisation-stage value table.

### `S6`

- scenario fan versus realised path;
- scenario-probability summary table;
- forecast-model comparison table.

### `S7`

- reserve deliverability table;
- DA-only versus `mFRR` incremental-value table.

### `S8`

- hourly versus quarter-hour comparison table;
- `D_only` versus `D_plus_4` comparison table;
- explicit caveat box for observed versus synthetic quarter-hour truth.

### `S9`

- CVaR sensitivity curve;
- risk-return frontier;
- downside-tail summary table.

## Wording Guidance: Tata-Inspired, Not Digital Twin

Use wording like:

- `Tata Steel IJmuiden-inspired`;
- `publicly reconstructable industrial test bed`;
- `bounded site representation`;
- `not a confidential site digital twin`.

Avoid wording that implies:

- exact plant replication;
- hidden contract knowledge;
- exact operating rulebooks;
- approved site coefficients when only candidate evidence exists.

## Wording Guidance: Candidate Values Versus Approved Model Inputs

State explicitly:

- approved modelling structure is not the same as approved numerical values;
- candidate values remain reviewable and caveated;
- validation targets are not direct operating inputs;
- sensitivities are not base-case truths.

## Limitations Section Outline

At minimum include:

- public-source and proxy limitations;
- lack of confidential tariff and contract data;
- lack of site-approved recipes and yields;
- scope boundary simplifications;
- staged omission of `CBAM`, `mFRR`, 15-minute, `D_plus_4`, and CVaR where still postponed.

## Validation Narrative Outline

Explain:

- why solver success is not enough;
- which balance and feasibility checks were passed;
- how tariff, ETS, and infrastructure flags were disclosed;
- how proxy structures were kept separate from site truth.

## Experiment-Design Narrative Outline

Explain:

- which policy choices were frozen;
- which forecast or scenario inputs changed;
- which physical structure stayed constant;
- why this is necessary for valid forecast-quality comparisons.

## `S7` And `S8` Thesis Contribution

### `S7`

Contribution:

- measures multi-market or reserve value only after the DA-only baseline is trusted.

Interpretation rule:

- no reserve-value claim without deliverability and production fulfilment.

### `S8`

Contribution:

- measures the value of granularity and horizon extensions once the baseline and stochastic model are stable.

Interpretation rule:

- do not mix granularity or horizon changes with production-policy changes.

## Forecast-Quality Comparison Warning

Production policy must stay fixed across forecast-quality comparisons.

If production, carbon, tariff, or market-scope policy changes together with forecast inputs, the result must be reported as a policy comparison rather than a forecast-quality comparison.
