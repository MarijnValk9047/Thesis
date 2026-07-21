# Methodological Guardrails

## Purpose

This file collects thesis-level optimisation guardrails that should be read when a task touches forecasting artifacts, scenarios, benchmarks, market extensions, metrics, reporting, or methodological interpretation.

`AGENTS.md` stays short; this file keeps the detailed rules.

## Thesis framing

The thesis investigates risk-return performance of demand-side flexibility for energy-intensive industry, especially steel, under volatile electricity markets.

The long-term model should evaluate:

- whether operational flexibility improves economic performance;
- whether 15-minute DA granularity changes flexibility value compared with hourly DA;
- whether scenario-based stochastic bidding outperforms simple benchmarks;
- whether CVaR risk aversion reduces downside exposure at acceptable opportunity cost;
- whether mFRR adds value beyond DA-only operation;
- whether optimisation remains physically feasible under industrial constraints and uncertain market outcomes.

The project is inspired by Badarinath's staged research design, hydrogen verification case, stochastic bidding model, CVaR formulation, Pyomo/Gurobi implementation, and benchmark logic. Do not copy it blindly. This thesis currently focuses on forecast/scenario inputs, market granularity, and forecast horizon more than bidding-strategy variation.

## Forecasting artifacts

Do not unnecessarily redesign or rerun forecasting work. Consume its outputs as inputs:

- deterministic forecasts;
- scenario files;
- scenario probabilities;
- forecast origins;
- delivery timestamps;
- model identifiers;
- granularity labels;
- lead-day or horizon labels;
- scenario-generation diagnostics.

Preserve upstream assumptions:

- forecast origin is 08:00 on D-1 in Europe/Amsterdam time;
- forecast horizon is D through D+4 where applicable;
- timestamps are stored internally in UTC;
- local time is for reporting and plots only;
- no random splits;
- no leakage;
- no tuning on the final test set;
- validation-based model, scenario, and CVaR selection;
- quarter-hour forecasting evaluation scores observed targets only.

## Fixed time and split methodology

For hourly DA artifacts, preserve the existing thesis split policy unless explicitly changed:

- train: 2022-01-01 to 2023-09-30;
- validation: 2023-10-01 to 2024-09-30;
- test: 2024-10-01 to 2025-09-30.

Quarter-hour rules:

- score observed targets only;
- do not treat interpolated, synthetic, gap-filled, or flagged 15-minute target rows as realised truth;
- keep `y_true = NaN` for non-observed target rows in forecasting evaluation;
- frozen synthetic quarter-hour paths may be downstream experiment inputs, but must be labelled as such.

DST rule:

- A 5-day local delivery horizon is not always exactly 120 hours or 480 quarter-hours.
- Do not hard-code horizon length without checking DST windows.

## Scenario undercoverage

Current DA scenarios are not fully satisfactory: on many days, realised prices fall partly or fully outside the generated scenario spread.

This is a serious methodological warning, not automatically fatal. Optimisation work should test whether undercoverage affects:

- realised net profit or cost;
- downside risk;
- CVaR;
- production fulfilment;
- bid clearing behaviour;
- feasibility;
- future reserve deliverability;
- value captured relative to perfect foresight;
- uplift relative to price-insensitive operation.

For each scenario input used by the optimiser, record:

- scenario source or model;
- number of scenarios;
- probability convention;
- delivery horizon;
- granularity;
- p50, p90, and p95 coverage diagnostics where available;
- realised-path containment diagnostics where available;
- whether stress or tail scenarios are included;
- known limitations.

Do not claim robust risk performance when scenario tails are known to be poorly calibrated and the impact has not been tested.

## Information timing and non-anticipativity

Optimisation must respect information release.

First-stage decisions are made before uncertain prices and activation outcomes are realised. They must be identical across scenarios sharing the same information set.

Second-stage decisions may adapt only when the model timeline allows that information to be known.

Red flags include:

- using realised DA prices to set DA bids;
- using test-set actuals for scenario calibration;
- letting scenario-specific bid decisions differ before uncertainty is revealed;
- using future storage states or prices in earlier decisions;
- choosing CVaR parameters based on final test performance.

## Benchmarks and market extensions

Do not implement exclusive group bids unless explicitly reopened.

For later DA work:

- focus first on normal hourly or quarter-hour price-sensitive DA bidding and settlement;
- keep bid clearing and realised settlement separate from forecast-stage objective value;
- be explicit whether the model chooses quantities only, bid prices and quantities, or an approximate cleared-consumption policy.

Required benchmark logic when markets return to scope:

- price-insensitive benchmark: fixed or simple production logic settled against realised DA prices;
- perfect-foresight benchmark: uses realised future prices only as an upper bound and never as a realistic operating strategy.

For later stochastic optimisation:

- use scenario IDs, probabilities, coherent price trajectories, and non-anticipative first-stage decisions;
- do not sample each hour or quarter independently in a way that destroys temporal structure.

For later CVaR:

- use a transparent linear formulation with VaR threshold, excess-loss variables, confidence level alpha, and risk-aversion weight;
- choose settings on validation-like periods, not final test performance.

For later mFRR:

- distinguish capacity bids, capacity clearing, activation, energy settlement, and penalties;
- model reserve deliverability as a physical feasibility constraint;
- be careful with load-side upward/downward regulation signs;
- report DA-only versus DA + mFRR incremental value.

## Required optimisation metrics

Economic metrics:

- realised net profit or net cost;
- expected objective value at optimisation time;
- uplift versus price-insensitive benchmark;
- value captured versus perfect foresight;
- DA electricity cost;
- average electricity price paid;
- product revenue or production margin where in scope;
- imbalance, unused-energy, or non-delivery penalties where relevant;
- later mFRR capacity and activation revenue/cost.

Risk metrics:

- VaR;
- CVaR;
- worst-scenario profit or cost;
- downside-tail mean;
- risk-return frontier over CVaR weights;
- realised outcome versus forecast scenario distribution.

Reliability and feasibility metrics:

- production target fulfilment;
- hydrogen or steel production volume;
- unmet demand or shortfall;
- storage or buffer boundary hits;
- infeasible periods;
- grid-capacity violations if modelled;
- reserve non-delivery once mFRR is added;
- penalty activations.

Operational metrics:

- load profiles for flexible assets;
- storage or buffer state trajectory;
- ramping behaviour;
- starts and stops if binaries are introduced;
- price responsiveness;
- consumption shifted from high-price to low-price periods.

Computational metrics:

- solve time;
- MIP gap;
- variable count;
- binary variable count;
- constraint count;
- scenario count;
- horizon length;
- memory or runtime warnings.

## Reporting standards

For thesis reporting, produce:

- compact thesis-body tables with strategy/model, granularity, horizon, net profit/cost, production, average price paid, downside-risk indicator, value versus price-insensitive, and value captured versus perfect foresight;
- appendix-level tables with metric definitions, units, interpretation, and why each metric matters;
- diagnostic figures for price/scenario fan versus realised price, dispatch, storage, bid clearing, profit/cost distribution, CVaR sensitivity, and benchmark comparison;
- run-level README explaining what was tested, inputs used, validity, main result, and methodological warnings.

Use `docs/optimisation/result_table_definitions.md` for field-level reporting definitions.

## Forecasting diagnostics for optimisation interpretation

Do not rely only on MAE or RMSE to choose optimisation inputs.

When available, use:

- MAE;
- RMSE;
- bias;
- rMAE;
- tail MAE;
- top/bottom-k hit rates;
- daily Spearman rank correlation;
- contiguous operating-window regret;
- high-low spread error;
- scenario coverage;
- realised-path containment.

The optimiser may prefer a forecast with slightly worse MAE if it better identifies cheap operating windows or avoids extreme downside events.

## Tractability

Start small and scale only after validation:

1. one asset before multiple assets;
2. one day before one week;
3. three scenarios before 30 scenarios;
4. hourly before quarter-hour when debugging logic;
5. deterministic before stochastic;
6. DA-only before DA + mFRR;
7. continuous relaxation before binary-heavy MILP where possible.

Avoid:

- loose Big-M values without justification;
- unnecessary binaries;
- repeated full hyperparameter/model searches inside rolling-origin optimisation;
- overlarge scenario counts before validating basic logic.

## Historical hydrogen reference

The historical hydrogen sequence is retained only as a methodological reference:

1. deterministic physical scheduling;
2. price-insensitive and perfect-foresight benchmarks;
3. DA bidding and settlement;
4. stochastic scenario optimisation;
5. CVaR risk aversion;
6. forecast/scenario comparison experiments;
7. mFRR extension;
8. steel extension.

For current work, this sequence is superseded by the active steel S1/S2/S3 path in `docs/optimisation/STEEL_OPTIMISATION_SCOPE.md`.

## Methodological red flags

Warn explicitly if any of the following occur:

- test-set tuning;
- scenario selection based on test performance;
- comparing hourly and quarter-hour cases while changing other assumptions;
- treating synthetic quarter-hour paths as observed truth;
- using scenario files without probabilities;
- independent per-time-step scenario sampling;
- missing non-anticipativity;
- reporting expected profit without realised settlement;
- reporting profit without production fulfilment;
- hiding infeasibility behind penalties without reporting violations;
- adding mFRR before DA-only is stable;
- treating a partial steel boundary as annual whole-site or ETS-ready;
- using aggregate WAG, mixed WAG, or warning outputs as physical fuel allocation;
- filling residual electricity or NG rather than reporting it;
- using perfect foresight as anything other than an upper bound;
- silently changing units between MW, MWh, EUR/MWh, kg H2, and EUR/kg.
