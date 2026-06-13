# Steel Implementation Freeze V1

## Purpose And Scope

This document freezes the first implementation plan for the public, Tata Steel IJmuiden-inspired steel MILP workstream after research Waves A through E.

It is a versioned implementation freeze:

- not final thesis truth;
- not approved numerical input truth;
- not a code design document;
- not permission to skip source review or candidate-review steps.

Its purpose is to convert the research scaffold into a controlled implementation path with explicit stage gates, tractability rules, and thesis-writing outputs.

## What Waves A Through E Established

### Wave A

Established the governed parameter-universe structure and the distinction between:

- modelling structure;
- candidate numerical evidence;
- validation targets;
- assumptions;
- sensitivities;
- postponed layers.

### Wave B

Established the public Tata-inspired topology reading, including:

- baseline `BF_BOF`;
- default Phase 1 hybrid `BF_BOF_plus_DRP_EAF`;
- public topology and validation-target candidate layers;
- source hierarchy with `MER Deel B` above simplified public webpages.

### Wave C

Established the generic technology and annual-to-hourly translation layer, including:

- continuity-driven treatment for `BF` and `DRP`;
- batch-equivalent treatment for `BOF` and `EAF`;
- anti-free-battery rules for `DRI`, slab, and `WIP`;
- future `S2` validation and infeasibility-check definitions.

### Wave D

Established the minimal `S3` internal-energy and emissions structure, including:

- `BFG`, `COG`, and `BOF_or_LD_gas` as separate carriers;
- `Vattenfall` as interface rather than dispatch plant;
- explicit flare or spill logic;
- explicit no-double-counting emissions architecture;
- `B_lite` as the recommended minimal `S3` layer.

### Wave E

Established the minimal financial and market-policy layer, including:

- fixed production target plus cost minimisation as the base objective;
- gross ETS cost visible;
- free allocation separate;
- `CBAM` postponed;
- `N1` generic Dutch tariff proxy policy;
- sequenced later market and risk stages.

## Approved Modelling Structures

In this freeze, approved modelling structure means:

- the repository may plan around the structure;
- future implementation may use the structure once coding starts;
- the structure is frozen unless a methodological change is explicitly declared.

It does **not** mean approved numerical values.

The approved structures are:

- `S2` deterministic hourly metallic material-flow LP as the first coding target;
- `S3` minimal `B_lite` WAG, internal-energy, emissions, and economic layer;
- fixed production target plus cost minimisation through `S2` and `S3`;
- gross ETS cost as a visible later `S3` cost term;
- separate free-allocation treatment if later activated;
- `N1` tariff proxy as the initial tariff structure policy;
- `Vattenfall` as interface, not dispatch plant;
- staged later market sequence through `S4` to `S9`.

## Candidate-Only Numerical Evidence

The following remain candidate-only until a future approval step promotes them:

- operating coefficients;
- technology ranges;
- annual-to-hourly envelopes;
- WAG generation and heating-value coefficients;
- emissions factors beyond frozen accounting rules;
- tariff values and proxy cost blocks;
- commodity-price scenarios;
- hydrogen and CCS timing and cost assumptions;
- any free-allocation credit values;
- any product-value or margin proxies.

Candidate-only evidence may support:

- validation anchors;
- scenario design;
- sensitivity design;
- future approved-input review.

It must not be treated as silently approved model-input truth.

## Current Model Policy Decisions

This freeze adopts the current policy surface from `STEEL_MODEL_POLICY_DECISIONS.md`.

### Production Policy

- `A`: fixed production target plus cost minimisation is the base policy.
- `B`: ex-post product margin may be reported, but product revenue is not part of the base objective.
- `E`: order-book or deadline production may be considered later only.
- flexible production with product revenue is forbidden in the base case.

### Carbon Policy

- gross ETS cost is visible once the economic layer is active;
- free allocation is a separate later credit or sensitivity module;
- `CBAM` is postponed and must not be added as a simple direct cost on EU steel output.

### Network Policy

- `N1` generic Dutch tariff proxy is the initial network policy;
- average MW demand is validation-only;
- technical connection capacity, contracted transport capacity, tariff components, and peak or capacity costs remain separate.

### Market And Advanced-Stage Policy

- `S7` `mFRR` and `S8` 15-minute or `D_plus_4` are important planned thesis stages;
- they remain gated and must not start before earlier foundations are stable;
- `S9` CVaR is lower priority and remains postponed.

## Stage Sequence S1 Through S9

### `S1` Evidence, Source Cards, Parameter Universe

Status:

- governance and evidence stage only;
- Waves `A` through `E` formalised as candidate evidence;
- no approved numerical model inputs yet.

### `S2` Deterministic Hourly Metallic Material-Flow LP

Scope:

- continuous LP first;
- fixed production target;
- metallic flows only;
- no energy economics;
- no WAG valuation;
- no day-ahead prices;
- no stochasticity;
- no `mFRR`.

Required structure:

- explicit `BF_BOF` and `DRP_EAF` route logic;
- bounded `DRI` and slab or `WIP` buffers;
- terminal inventory rules;
- material-balance and infeasibility diagnostics.

### `S3` WAG, Internal Energy, Emissions, And Economic Layer

Scope:

- minimal `B_lite` WAG and internal-energy layer;
- separate `BFG`, `COG`, and `BOF_or_LD_gas`;
- natural-gas and electricity imports;
- flare or spill variables;
- gross ETS cost visible;
- `N1` network tariff proxy;
- fixed production target unchanged;
- no product revenue in the base objective;
- free allocation only as separate later sensitivity or credit;
- `Vattenfall` as interface, not dispatch plant.

### `S4` Deterministic Hourly DA Price-Taking Dispatch

Scope:

- exogenous DA prices;
- no bidding yet;
- price responsiveness under fixed production policy;
- carefully defined price-insensitive and perfect-foresight or oracle benchmarks;
- no stochasticity.

### `S5` DA Bidding And Settlement

Scope:

- market-taking DA bid, clear, and settle logic;
- first-stage decisions use only information available at bid time;
- settlement against realised DA prices;
- redispatch after clearing must respect physical feasibility;
- benchmarks preserved.

### `S6` Stochastic DA, Risk-Neutral

Scope:

- compare `XGBoost_FS3`, `LEAR_FS3`, and `LEAR_Strict`;
- scenario probabilities required;
- temporal coherence preserved;
- non-anticipativity enforced;
- same physical model, production policy, horizon or granularity, and tariff or carbon assumptions across forecast-model comparisons;
- no CVaR yet.

### `S7` `mFRR` Extension

Scope:

- important planned thesis stage;
- only after DA-only bidding, settlement, and physical deliverability are stable;
- market-scope extension, not forecast-granularity test;
- reserve deliverability, downstream buffer feasibility, baseline or rebound logic, activation, and non-delivery logic where applicable.

### `S8` 15-Minute And Or `D_plus_4` Extensions

Scope:

- important planned thesis stage;
- change one dimension at a time;
- hourly `D_only` to 15-minute `D_only`;
- hourly `D_only` to hourly `D_plus_4`;
- only later 15-minute `D_plus_4` if tractable;
- observed quarter-hour truth only;
- preserve forecast origin, lead-day, and scenario metadata.

### `S9` CVaR Or Risk Aversion

Scope:

- postponed advanced stage;
- only after risk-neutral stochastic DA and major market, granularity, and horizon stages are understood;
- preserves scenario probabilities and non-anticipativity.

## Stage Gates And Go / No-Go Criteria

### Go From `S1` To `S2`

Allowed only if:

- freeze documents are accepted;
- `S2` and `S3` scope is frozen;
- assumptions and candidate layers exist;
- no hidden approved numerical values are required for the first scaffold decision.

### Go From `S2` To `S3`

Allowed only if:

- metallic balances close;
- route logic is explainable;
- inventory terminal rules are explicit;
- production fulfilment is reported before any economics claims.

### Go From `S3` To `S4`

Allowed only if:

- WAG balances are stable;
- emissions accounting is coherent;
- gross ETS and any free-allocation placeholder remain separate;
- tariff proxy status is explicit;
- production policy remains fixed-target cost minimisation.

### Go From `S4` To `S5`

Allowed only if:

- deterministic DA dispatch is explainable;
- price-taking assumptions are explicit;
- settlement can be separated from optimisation-stage expectation.

### Go From `S5` To `S6`

Allowed only if:

- bidding and settlement logic is stable;
- scenario probabilities exist;
- first-stage decision definition is explicit;
- non-anticipativity design is frozen.

### Go From `S6` To `S7`

Allowed only if:

- DA-only stochastic behaviour is stable;
- reserve deliverability constraints are identified;
- no reserve revenue claim would outrun physical feasibility or production fulfilment.

### Go From `S6` Or `S7` To `S8`

Allowed only if:

- the earlier stage is explainable and reportable;
- hourly baseline behaviour is stable;
- one-dimension-at-a-time comparison design is frozen.

### Go To `S9`

Allowed only if:

- risk-neutral stochastic behaviour is already understood;
- scenario probabilities and information timing are stable;
- CVaR is being introduced deliberately rather than used to hide model weakness.

## Thesis-Critical `S7` And `S8` Treatment

`S7` and `S8` are important planned thesis stages, not casual optional extras.

### `S7`

Thesis role:

- tests whether multi-market or reserve participation adds value once DA-only steel is already credible.

Gate:

- do not start before DA-only physical, economic, and settlement logic are stable.

### `S8`

Thesis role:

- tests whether finer market granularity or longer forecast horizon changes flexibility value.

Gate:

- do not mix granularity and horizon changes with production-policy changes;
- do not change both dimensions simultaneously unless the experiment is explicitly labelled as a combined methodological change.

## What Is Explicitly Postponed

Postponed from the first implementation:

- approved numerical input tables;
- product-revenue base objective;
- order-book or deadline production;
- detailed free-allocation module;
- `CBAM`;
- full `Vattenfall` dispatch;
- detailed mixed-gas optimisation;
- detailed steam or oxygen utility scheduling;
- day-ahead bidding before `S5`;
- stochastic DA before `S6`;
- `mFRR` before `S7`;
- 15-minute or `D_plus_4` before `S8`;
- CVaR before `S9`.

## Change-Control Rules

The following changes are methodological, not merely engineering:

- production policy;
- carbon policy;
- tariff policy;
- market scope;
- horizon;
- granularity;
- scenario count or scenario family;
- risk treatment;
- non-anticipativity design;
- reserve logic.

Any such change must update at least:

- this freeze document if it changes the frozen path;
- `STEEL_MODEL_POLICY_DECISIONS.md`;
- `STEEL_ASSUMPTION_REGISTER.md`;
- `STEEL_IMPLEMENTATION_ROADMAP.md`;
- the relevant stage-gate and tractability docs.

## Tractability Rules

The default tractability order is:

1. one day before one week;
2. hourly before quarter-hour;
3. deterministic before stochastic;
4. `DA_only` before `mFRR`;
5. continuous LP before binaries;
6. `S2` before `S3`;
7. `S3` before `S4` and beyond.

Add complexity only after the prior stage is stable and diagnosed.

## Methodological Red Flags

Red flags include:

- using public annual values as hidden hourly truth;
- using average MW demand as connection capacity;
- mixing proxy tariffs with site-truth language;
- moving production policy while claiming a forecast-quality comparison;
- adding DA, stochastic, `mFRR`, or CVaR layers to compensate for unstable plant physics;
- treating `S7` reserve value as credible without deliverability;
- treating `S8` quarter-hour results as credible if synthetic or interpolated truth is scored as observed.

## Thesis-Writing Outputs Per Stage

### `S1`

- evidence and governance narrative;
- source-card and candidate-layer description;
- explicit caveat that no approved numerical input table exists yet.

### `S2`

- material-flow structure narrative;
- topology diagrams;
- balance and infeasibility diagnostics;
- candidate-envelope disclosure.

### `S3`

- energy, WAG, and emissions accounting narrative;
- gross ETS and tariff policy disclosure;
- explanation of fixed-target cost minimisation.

### `S4`

- deterministic DA price-response narrative;
- price-insensitive and oracle benchmark framing;
- no-bidding-yet caveat.

### `S5`

- bid, clear, settle explanation;
- information-timing explanation;
- physical feasibility after clearing.

### `S6`

- forecast-quality comparison narrative;
- scenario-probability and non-anticipativity explanation;
- risk-neutral caveat.

### `S7`

- reserve-value narrative after DA-only stability;
- deliverability and non-delivery risk explanation.

### `S8`

- granularity and horizon narrative;
- one-dimension-at-a-time comparison design.

### `S9`

- risk-return narrative;
- CVaR sensitivity and limitation narrative.

## Freeze Status

Implementation Freeze V1 is now the controlling planning surface for the first steel coding decision.

Future changes require explicit review rather than silent doc drift.
