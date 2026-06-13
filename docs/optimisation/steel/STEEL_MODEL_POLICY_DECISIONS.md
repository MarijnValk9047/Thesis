# Steel Model Policy Decisions

## Purpose And Scope

This document freezes the current policy choices for the first steel implementation stages.

It is a governance document, not a model, not an approved input table, and not an instruction to skip the evidence or candidate-review path.

These policy choices exist to keep the first steel implementation narrow, auditable, and comparable across forecast-quality experiments.

## Production Policy

### Base Policy A

The base production policy is:

- fixed production target;
- cost minimisation.

The first S2 and S3 implementations must therefore optimise against an exogenous production target or fulfilment policy rather than against an endogenous product-revenue objective.

### Reporting Extension B

An ex-post product margin may be reported after the model run as diagnostic or comparative context.

That reporting extension:

- does not change the base objective;
- does not authorise endogenous revenue-seeking production changes;
- must stay clearly labelled as reporting-only or sensitivity-only.

### Advanced Future Policy E

Order-book or deadline-based production may be considered later, but not in the first S2 or S3 implementation.

It requires stronger evidence on:

- product mix;
- delivery timing;
- order priorities;
- route-specific revenue logic.

### Base-Case Restriction

Flexible production with product revenue is not allowed in the base case.

## Carbon Policy

The base carbon policy is:

- gross ETS cost visible in the objective.

This means:

- physical emissions remain explicit;
- ETS cost is applied as a separate visible policy term;
- free allocation is not hidden inside emissions factors or a net emissions shortcut.

### Free Allocation

Free allocation is a separate later credit or sensitivity module.

It may later support:

- separate credit accounting;
- net ETS reporting;
- benchmark-sensitive analysis.

It is not part of the first approved base objective.

### CBAM

CBAM is postponed.

It should not be modelled as a simple direct cost adder on EU steel output in the first steel implementation stages.

## Network / Tariff Policy

The initial network policy is `N1`:

- generic Dutch network or tariff proxy;
- clearly labelled as proxy or sensitivity;
- not treated as Tata-specific contract truth.

The following distinctions must stay explicit:

- technical connection capacity;
- contracted transport capacity;
- tariff or peak-cost parameters;
- average demand validation targets.

Average MW demand is validation-only and must never be used as connection capacity.

## Market Sequencing Policy

The steel model sequence is:

1. `S2`: deterministic hourly material-flow LP for the metallic network.
2. `S3`: WAG, internal-energy, emissions, and economic layer with fixed production and cost minimisation.
3. `S4`: deterministic hourly day-ahead price-taking dispatch, without bidding logic.
4. `S5`: day-ahead bidding and settlement.
5. `S6`: stochastic day-ahead, risk-neutral, comparing `XGBoost_FS3`, `LEAR_FS3`, and `LEAR_Strict`.
6. `S7`: `mFRR` extension, only after `DA_only` behaviour is stable.
7. `S8`: 15-minute and or `D_plus_4` extensions, changing one dimension at a time.
8. `S9`: CVaR or risk-aversion layer.

`mFRR` before 15-minute or `D_plus_4` is treated as a market-scope extension, not as a forecast-granularity test.

## What Is Explicitly Not Allowed In The Base Case

The following are not allowed in the base case:

- endogenous product-revenue objective;
- hidden free-allocation treatment inside emissions factors;
- CBAM as a direct output cost adder;
- average MW demand as network capacity;
- Tata-specific tariff or contract assumptions inferred from public proxy sheets;
- hydrogen or CCS treated as always available by default;
- day-ahead bidding before deterministic physical and economic layers are stable;
- stochastic DA, CVaR, `mFRR`, 15-minute, or `D_plus_4` implementation in the current governance stage.

## How Policy Choices Protect Forecast-Quality Comparisons

These policies protect forecast-quality comparisons by keeping constant:

- production policy;
- carbon accounting policy;
- network-cost policy;
- stage sequence.

That matters because forecast-quality comparisons become methodologically weak if economic objective structure changes at the same time as forecast or scenario inputs.

The intended comparison rule is:

- change forecast or scenario inputs deliberately;
- hold production, carbon, tariff, and stage-policy choices fixed unless the experiment explicitly studies those policies.

## Review Triggers For Changing Policy

Review these policies only when at least one of the following is true:

- approved site-specific contract or tariff evidence is added;
- approved product-mix or order-book evidence is added;
- approved free-allocation evidence is strong enough for a separate module;
- the deterministic S2 and S3 layers are stable and validated;
- a dedicated experiment explicitly studies policy sensitivity instead of forecast quality.

Policy changes must be reflected in:

- this file;
- `STEEL_ASSUMPTION_REGISTER.md`;
- `STEEL_IMPLEMENTATION_ROADMAP.md`;
- the relevant candidate tables and validation checks.
