# Hydrogen Baseline Dispatch Model Audit

## Purpose

This document freezes the current hydrogen baseline before any day-ahead bidding and clearing logic is added.

The current model is a **schedule-and-settle dispatch model**. It is useful as a benchmark, but it is **not** yet a true bidding model.

## What the current model does

For each delivery day, the model chooses a plant dispatch for:

- electrolyser power;
- compressor power;
- hydrogen production;
- hydrogen compressed/sold;
- hydrogen buffer state;
- shortfall against a daily production target.

For stochastic strategies, the optimiser sees a set of day-ahead price scenarios with probabilities and chooses one dispatch that minimizes:

- expected net cost; or
- expected net cost plus a CVaR term.

After optimisation, realised economics are evaluated by settling the same dispatch against realised day-ahead prices.

## Why this is not a bidding model

The current model does **not** submit market bids.

It has:

- no bid-price decision variables;
- no bid-quantity blocks;
- no market-clearing rule;
- no accepted vs rejected electricity;
- no post-clearing redispatch;
- no distinction between submitted electricity and cleared electricity.

The model therefore assumes that the scheduled electricity is available and only changes the **price paid**, not the **quantity procured**. That is why it must be labelled **schedule-and-settle**, not bidding.

## Physical logic implemented today

The core plant physics are already present.

| Constraint group | Implemented | Units | Notes |
|---|---|---:|---|
| Electrolyser minimum load | Yes | MW | Implemented with binary on/off in optimisation model. |
| Electrolyser maximum load | Yes | MW | Upper bound at nominal capacity. |
| Electrolyser ramping | Yes | MW/h | Applied between consecutive timesteps. |
| Hydrogen production conversion | Yes | kg = MW x h x kg/MWh | `H_prod = P_el * delta_t * efficiency`. |
| Compressor maximum power | Yes | MW | Hard upper bound. |
| Compressor specific energy | Yes | MWh/kg | `P_comp * delta_t = specific_mwh_per_kg * H_comp`. |
| Hydrogen buffer balance | Yes | kg | `H_buf[t] = H_buf[t-1] + H_prod[t] - H_comp[t]`. |
| Buffer capacity | Yes | kg | Hard upper bound. |
| Buffer reserve floor | Yes | kg | Hard lower bound equal to reserve stock. |
| Daily production target | Yes | kg/day | Enforced through `H_comp + shortfall >= target`. |
| Shortfall slack | Yes | kg/day | Non-negative slack variable. |
| Reserve market constraints | No | n/a | Only an internal storage reserve floor exists. No reserve bidding or deliverability logic is present. |

## Economic terms implemented today

| Economic term | Implemented | Units | Notes |
|---|---|---:|---|
| Electricity cost | Yes | EUR | `price * (P_el + P_comp) * delta_t`. |
| Hydrogen revenue | Yes | EUR | `H_comp * h2_sale_price_eur_per_kg`. |
| Shortfall penalty | Yes | EUR | `shortfall * shortfall_penalty_eur_per_kg`. |
| Terminal inventory correction | Yes | EUR | Applied from end inventory relative to reference start inventory. |
| Scenario expected net cost | Yes | EUR | Probability-weighted for stochastic strategies. |
| CVaR term | Yes | EUR | Used only in `stochastic_cvar`. |
| Bid clearing settlement | No | EUR | Not implemented yet. |
| Rejected/unused procurement penalty | No | EUR | Not relevant until bidding/clearing exists. |

## Units used

| Quantity | Unit |
|---|---:|
| Electrolyser power | MW |
| Compressor power | MW |
| Electricity use | MWh |
| Hydrogen production / compression / storage | kg H2 |
| Electricity price | EUR/MWh |
| Hydrogen sale price | EUR/kg H2 |
| Objective / profit / penalties | EUR |

## Terminal inventory correction

Terminal inventory correction **is included**.

The current configuration values hydrogen inventory **before compression**:

- `terminal_inventory_location: before_compression`
- terminal value per kg = `h2_sale_price_eur_per_kg - compressor_specific_mwh_per_kg * p_ref_eur_per_mwh`

Important nuance:

- within a multi-day rolling run, terminal correction is only applied on the **final executed day** of the run period;
- the reference inventory is the period-start inventory for the final day adjustment;
- this avoids creating artificial profit by ending the run with depleted storage.

## Production target and shortfall logic

Production target and shortfall logic **are included**.

The model does not force the target to be met physically in every case. Instead, it uses:

- a hard non-negative shortfall variable; and
- a configurable shortfall penalty in the objective.

The target should be interpreted as a **lower-bound reference requirement**, not as a fixed offtake cap. If the physical system and economics make higher production attractive, hydrogen production and hydrogen compressed/sold may exceed the target.

This is acceptable for the current benchmark, but results must always report:

- hydrogen produced/compressed;
- target fulfilment;
- above-target hydrogen, when present;
- shortfall;
- shortfall penalty.

Otherwise profit numbers can be misleading.

## Reserve constraints

Reserve constraints are **not** included in the market-participation sense.

What exists today is only:

- a minimum hydrogen buffer requirement derived from `reserve_fraction`.

What does **not** exist yet:

- reserve capacity bids;
- activation energy;
- mFRR deliverability;
- activation penalties;
- DA plus reserve co-optimisation.

## Current strategy labels

These should be interpreted as follows:

- `price_insensitive`: heuristic schedule-and-settle benchmark;
- `stochastic_risk_neutral`: stochastic schedule-and-settle dispatch with expected-cost objective;
- `stochastic_cvar`: stochastic schedule-and-settle dispatch with expected-cost plus CVaR objective;
- `deterministic_point_forecast`: deterministic schedule-and-settle dispatch using point prices;
- `perfect_foresight`: oracle schedule-and-settle upper bound using realised future prices.

`perfect_foresight` is a benchmark only. It is not a realistic operating strategy.

## Limitations that later bidding phases must fix

Phase 0 deliberately leaves these gaps in place:

1. No bid-price or bid-quantity decisions.
2. No market clearing against realised DA prices.
3. No possibility that scheduled electricity fails to clear.
4. No deterministic redispatch after actual clearing.
5. No separation between optimisation-time objective and cleared-procurement feasibility.
6. No unused cleared energy accounting.
7. No explicit submitted-bids artifact.
8. No DA bidding representation beyond schedule-and-settle consumption planning.

Those limitations are exactly why later phases must add:

- bid construction;
- acceptance logic;
- actual clearing;
- redispatch using only cleared electricity;
- realised settlement that distinguishes submitted, cleared, and used electricity.

## Phase 0 audit conclusion

The baseline is a defensible **dispatch benchmark** if it is described honestly as schedule-and-settle and if reporting always includes:

- solver status;
- model stats;
- terminal inventory correction;
- target fulfilment and shortfall;
- physical balance checks.

It is **not** yet suitable for claims about bidding performance or bid-clearing feasibility.

## Current operational issue

As of **May 15, 2026**, the default artifact path in `scripts/Data/03_Hydrogen_Test_Case/configs/scenario_catalog.yaml` points to:

- `data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly_with_lear_strict/20260513_073251/scenario_prices_long.csv`

That file is currently missing from the workspace, so the default hourly D-only backtest is not directly rerunnable until the scenario input is restored or the catalog is intentionally repointed.
