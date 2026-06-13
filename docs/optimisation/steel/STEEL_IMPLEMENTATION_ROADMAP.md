# Steel Implementation Roadmap

## Goal

Provide the practical implementation sequence for future Codex work on the steel workstream.

This roadmap is intentionally restrictive. It exists to stop future chats from jumping straight into a full steel MILP without the data, assumptions, and validation surface needed to trust the result.

## Codex Operating Rules

- do not create one-off scripts for every experiment;
- prefer configs over duplicated code;
- inspect existing hydrogen helpers before adding new optimisation infrastructure;
- preserve the hydrogen test case as the verification baseline;
- reuse shared optimisation and reporting concepts where appropriate;
- no full steel model implementation until these planning docs and the input schemas are accepted.

## Phase Roadmap

This roadmap now follows the frozen `S1` through `S9` sequence in `STEEL_IMPLEMENTATION_FREEZE_V1.md`.

### S1 Data, Source-Card, And Register Setup

**Goal**

Create the steel data-governance surface before coding parameters into loaders.

**Files Likely To Inspect Or Modify**

- future steel input tables under `data/03_Optimisation/inputs/assets/steel/`
- future source-card docs or CSVs
- future schema or loader modules

**Expected Outputs**

- source-card contract;
- candidate parameter register;
- approved input-table schemas.

**Validation Checks**

- every material parameter has unit, source, status, and confidence;
- no approved parameter exists only inside Python code.

**Stop/Go Criteria**

- go to modelling only when the freeze docs, assumption surface, and candidate layers are accepted and the first `S2` and `S3` scope is frozen.

**Risks**

- public sources disagreeing materially;
- redacted values silently becoming fixed model truth.

### S2 Deterministic Hourly Metallic Material-Flow LP

**Goal**

Build the deterministic hourly metallic material-flow LP without market complexity.

**Files Likely To Inspect Or Modify**

- future `scripts/Data/04_Steel_Test_Case/steel/` modules
- shared optimisation utilities reused from hydrogen where appropriate
- tests for balances and schema validation

**Expected Outputs**

- topology-aware LP;
- mass-balance tests;
- small deterministic smoke cases.

**Validation Checks**

- structure validation;
- unit validation;
- mass-balance closure;
- production accounting sanity.

**Stop/Go Criteria**

- do not add bidding or stochastic logic until balances close and outputs are interpretable.

**Risks**

- missing route constraints creating fake feasibility;
- hidden inventory assumptions acting as slack.

### S3 WAG, Internal Energy, Emissions, And Economic Layer

**Goal**

Add the minimal economic layer with WAG, internal-energy, emissions, fixed production, gross ETS cost, and `N1` tariff proxy treatment.

**Files Likely To Inspect Or Modify**

- future cost/emissions input tables
- objective modules
- validation targets and reporting modules

**Expected Outputs**

- deterministic hourly costed model;
- route-level energy and emissions summaries;
- explicit ETS accounting convention;
- explicit statement that production remains fixed-target plus cost minimisation.

**Validation Checks**

- energy-scale plausibility;
- emissions plausibility;
- cost-term reconciliation against hand checks;
- gross ETS and any later free-allocation credit kept separate;
- tariff proxy clearly labelled;
- average-demand target not used as connection capacity.

**Stop/Go Criteria**

- do not introduce flexibility claims until route economics and emissions are coherent.

**Risks**

- unit mismatches;
- ETS treatment quietly changing route ranking.

### S4 Deterministic Hourly DA Price-Taking Dispatch

**Goal**

Add deterministic hourly DA price-taking dispatch without bidding logic.

**Files Likely To Inspect Or Modify**

- future DA price adapters
- dispatch and settlement modules
- reporting and metrics definitions
- timing and market-parameter docs

**Expected Outputs**

- deterministic DA-aware dispatch layer;
- explicit realised-price settlement logic without submitted bidding.

**Validation Checks**

- timing consistency with market parameters;
- price-taking assumption explicit;
- physical feasibility preserved under exogenous DA prices.

**Stop/Go Criteria**

- do not move to DA bidding until deterministic DA dispatch is explainable and reportable.

**Risks**

- schedule logic being mislabeled as bidding;
- physical or economic instability being mistaken for market behaviour.

### S5 DA Bidding And Settlement

**Goal**

Add DA participation logic to the steel model.

**Files Likely To Inspect Or Modify**

- clearing and settlement modules
- bidding-policy modules
- reporting and metrics definitions
- run contract docs if a new steel runner is added

**Expected Outputs**

- submitted-bid representation or explicit cleared-consumption policy;
- realised settlement outputs;
- benchmark comparison outputs.

**Validation Checks**

- optimisation-stage vs realised settlement separation;
- timing consistency with forecast origin;
- benchmark definitions unchanged.

**Stop/Go Criteria**

- do not call results bidding evidence if procurement and settlement are not represented explicitly.

**Risks**

- reusing hydrogen logic in ways that ignore steel process constraints;
- schedule-and-settle being mislabeled as bidding.

### S6 Stochastic DA, Risk-Neutral

**Goal**

Introduce risk-neutral scenario-based DA optimisation for forecast and scenario comparison.

**Files Likely To Inspect Or Modify**

- scenario adapters
- stochastic model builders
- validation-period experiment configs

**Expected Outputs**

- scenario-aware steel runner;
- risk metrics and scenario diagnostics in reporting.

**Validation Checks**

- explicit probabilities;
- non-anticipativity;
- scenario diagnostics stored with results.

**Stop/Go Criteria**

- do not introduce risk aversion or reserve logic before risk-neutral stochastic DA is coherent.

**Risks**

- scenario undercoverage giving false confidence;
- scenario-specific first-stage decisions.

### S7 `mFRR` Extension After DA-Only Stability

**Goal**

Add reserve participation only after DA-only steel is explainable and trusted.

This is an important planned thesis stage.

It is a market-scope extension, not a forecast-granularity test.

**Files Likely To Inspect Or Modify**

- reserve interface docs
- future steel market modules
- deliverability and activation constraints

**Expected Outputs**

- reserve-capable steel extension with separate capacity, activation, and penalty reporting.

**Validation Checks**

- reserve deliverability;
- sign-convention correctness;
- incremental value vs `DA_only`.

**Stop/Go Criteria**

- blocked until `DA_only` steel is stable and trusted.

**Risks**

- adding market-scope complexity before physical flexibility is credible;
- using reserve revenue to hide feasibility problems.

### S8 15-Minute And Or `D_plus_4` Extensions

**Goal**

Compare granularity and horizon once hourly deterministic, DA, and reserve sequencing decisions are already stable.

This is an important planned thesis stage.

It is the forecast granularity and horizon extension stage.

**Files Likely To Inspect Or Modify**

- granularity-aware adapters
- horizon-aware config and validation logic
- reporting tables and comparability checks

**Expected Outputs**

- controlled comparison experiments;
- explicit caveats on observed vs synthetic quarter-hour truth where relevant.

**Validation Checks**

- DST-safe horizon handling;
- one dimension changed at a time;
- same asset assumptions across comparison cases.

**Stop/Go Criteria**

- do not compare hourly and quarter-hour or `D_only` and `D_plus_4` if other assumptions moved at the same time.

**Risks**

- changing both horizon and asset policy in one experiment;
- treating synthetic quarter-hour paths as observed truth.

### S9 CVaR And Risk Aversion

**Goal**

Introduce CVaR or other risk-aversion logic only after deterministic and risk-neutral layers are stable.

**Files Likely To Inspect Or Modify**

- CVaR modules
- stochastic reporting
- validation-period selection configs

**Expected Outputs**

- explicit risk-aversion layer;
- CVaR sensitivity runs;
- clear risk-return reporting.

**Validation Checks**

- validation-only parameter selection;
- downside metric clearly defined;
- no contamination of earlier benchmark logic.

**Stop/Go Criteria**

- do not use test-period outcomes to tune CVaR settings.

**Risks**

- using risk aversion to paper over weak scenarios;
- introducing CVaR before base deterministic and risk-neutral behaviour is trusted.

## Future Structure Recommendation

If the steel implementation is started, prefer:

```text
scripts/Data/04_Steel_Test_Case/
  configs/
  steel/
  tests/
```

and keep approved input tables separate under:

```text
data/03_Optimisation/inputs/assets/steel/
```

This avoids mixing steel code, generated runs, and asset facts into the hydrogen tree.

## Acceptance Rule

A future Codex session may start steel code scaffolding only after:

- these planning docs are accepted;
- implementation freeze `V1` and the `S2` or `S3` scope docs are accepted;
- initial steel input-table schemas are accepted;
- the first steel asset boundary and target policy are frozen for `S2`.
