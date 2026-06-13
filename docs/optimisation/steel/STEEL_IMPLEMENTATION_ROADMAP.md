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

### S0 Steel Scope Freeze

**Goal**

Freeze the first steel research scope and comparison logic.

**Files Likely To Inspect Or Modify**

- `docs/optimisation/steel/`
- `docs/optimisation/PROJECT_DECISIONS.md` if later cross-linking is needed

**Expected Outputs**

- accepted steel planning docs;
- explicit statement of baseline and main case;
- explicit statement of deferred features.

**Validation Checks**

- baseline BF-BOF and Phase 1 hybrid definitions are distinguishable;
- first implementation is deterministic, hourly, and `DA_only`.

**Stop/Go Criteria**

- go only when scope and deferrals are explicit.

**Risks**

- steel scope drifting into a digital-twin request;
- forecast comparisons polluted by hidden asset-policy changes.

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

- go to modelling only when at least a minimal approved baseline parameter set exists.

**Risks**

- public sources disagreeing materially;
- redacted values silently becoming fixed model truth.

### S2 Deterministic Material-Flow LP

**Goal**

Build the steel skeleton process-network LP without market complexity.

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

### S3 Energy, Cost, And Emissions Layer

**Goal**

Add electricity, cost, and ETS logic to the skeleton LP.

**Files Likely To Inspect Or Modify**

- future cost/emissions input tables
- objective modules
- validation targets and reporting modules

**Expected Outputs**

- deterministic hourly costed model;
- route-level energy and emissions summaries;
- explicit ETS accounting convention.

**Validation Checks**

- energy-scale plausibility;
- emissions plausibility;
- cost-term reconciliation against hand checks.

**Stop/Go Criteria**

- do not introduce flexibility claims until route economics and emissions are coherent.

**Risks**

- unit mismatches;
- ETS treatment quietly changing route ranking.

### S4 Phase 1 Flexibility

**Goal**

Represent the main hybrid-route flexibility, especially DRP-EAF and relevant buffers.

**Files Likely To Inspect Or Modify**

- process-unit tables
- store tables
- route constraints
- assumption register entries tied to EAF and DRI flexibility

**Expected Outputs**

- hybrid configuration model;
- flexibility reports showing where optionality comes from.

**Validation Checks**

- flexibility realism validation;
- buffer-boundedness checks;
- comparison against baseline rigidity assumptions.

**Stop/Go Criteria**

- do not move to DA bidding until flexibility comes from explicit process logic.

**Risks**

- over-crediting storage;
- over-crediting EAF ramping without supporting evidence.

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

### S6 Stochastic DA And CVaR

**Goal**

Introduce scenario-based DA optimisation and risk aversion.

**Files Likely To Inspect Or Modify**

- scenario adapters
- stochastic model builders
- CVaR modules
- validation-period experiment configs

**Expected Outputs**

- scenario-aware steel runner;
- CVaR sweep configs;
- risk metrics and scenario diagnostics in reporting.

**Validation Checks**

- explicit probabilities;
- non-anticipativity;
- validation-only CVaR selection;
- scenario diagnostics stored with results.

**Stop/Go Criteria**

- do not use test-period results for scenario or gamma selection.

**Risks**

- scenario undercoverage giving false confidence;
- scenario-specific first-stage decisions.

### S7 Hourly Vs Quarter-Hour And `D_only` Vs `D_plus_4`

**Goal**

Compare granularity and horizon once the hourly deterministic and stochastic surfaces are stable.

**Files Likely To Inspect Or Modify**

- granularity-aware adapters
- horizon-aware config and validation logic
- reporting tables and comparability checks

**Expected Outputs**

- controlled comparison experiments;
- explicit caveats on observed vs synthetic quarter-hour truth where relevant.

**Validation Checks**

- DST-safe horizon handling;
- same asset assumptions across granularity cases;
- same benchmark definitions across horizon cases.

**Stop/Go Criteria**

- do not compare hourly and quarter-hour if other assumptions moved.

**Risks**

- changing both horizon and asset policy in one experiment;
- treating synthetic quarter-hour paths as observed truth.

### S8 `mFRR` Extension Later

**Goal**

Add reserve participation only after DA-only steel is already explainable.

**Files Likely To Inspect Or Modify**

- reserve interface docs
- future steel market modules
- deliverability and activation constraints

**Expected Outputs**

- reserve-capable steel extension with separate capacity, activation, and penalty reporting.

**Validation Checks**

- reserve deliverability;
- sign-convention correctness;
- incremental value vs DA-only.

**Stop/Go Criteria**

- blocked until DA-only steel is stable and trusted.

**Risks**

- adding market complexity before physical flexibility is credible;
- using reserve revenue to hide feasibility problems.

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
- initial steel input-table schemas are accepted;
- the first steel asset boundary and target policy are frozen for Phase S2.
