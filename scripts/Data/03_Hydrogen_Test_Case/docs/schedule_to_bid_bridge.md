# Schedule-To-Bid Bridge

## Purpose

Phase 2 does **not** add a bidding optimiser.

It takes an already computed schedule-and-settle dispatch and asks a narrower question:

- if this scheduled electricity demand had been submitted as day-ahead demand bids,
- how much of it would have cleared against the realised market price?

This makes the gap between scheduling and bidding visible without changing the optimisation model yet.

## What the bridge does

For each delivery hour, the bridge computes:

- `scheduled_load_mw = electrolyser_power_mw + compressor_power_mw`

In the current hydrogen outputs this is mapped from:

- `P_el_mw`
- `P_comp_mw`

That scheduled load is converted into a **one-block demand bid** for the same delivery hour.

## Bridge strategies

Two bridge bid variants are implemented:

1. `reference_price_bid`
   - quantity = scheduled load
   - bid price = `158 EUR/MWh` by default

2. `high_price_bid`
   - quantity = scheduled load
   - bid price = `3000 EUR/MWh`

For the price-insensitive benchmark, an explicit wrapper label is also available:

3. `price_insensitive_plan_first_market_cap`
   - same planned load as the deterministic optimisation-based price-insensitive physical plan
   - high market-cap-like bid price from config
   - intended as the clearest Badarinath-style parity label

If the legacy heuristic is passed through the same bridge for audit comparison, the bridge emits:

4. `price_insensitive_heuristic_plan_first_market_cap`
   - same planned load as the legacy heuristic price-insensitive plan
   - same market-cap-like bid price from config
   - used only to compare the old heuristic with the solver-based benchmark

Interpretation:

- `reference_price_bid` represents a finite willingness to pay for electricity.
- `high_price_bid` approximates firm procurement or effectively price-insensitive buying, except in extreme hours above `3000 EUR/MWh`.
- `price_insensitive_plan_first_market_cap` makes the solver-based plan-first, high-bid benchmark structure explicit for the price-insensitive case.

## Acceptance and settlement

The bridge uses the Phase 1 price-taking clearing rule for demand bids:

- accepted if `bid_price_eur_per_mwh >= actual_price_eur_per_mwh`
- rejected otherwise

Accepted electricity is **paid at the realised market clearing price**, not at the bid price.

That means:

- bid price determines whether the block clears;
- actual day-ahead price determines settlement cost.

The bridge therefore reports the settlement diagnostic:

- `realised_DA_settlement_cost_eur = actual_price_eur_per_mwh * cleared_energy_mwh`

It does **not** treat `bid_price * cleared_energy` as cost.

## What this is not

This phase is still **not** a true bidding optimiser.

It does not:

- choose bid quantities endogenously;
- optimise bid prices;
- use a stochastic bidding MILP;
- perform post-clearing redispatch;
- model unused cleared electricity;
- model hydrogen shortfall caused by rejected electricity.

So the bridge is still an ex-post debug and interpretation layer.

## Conceptual electricity states

In this bridge, the electricity layers are:

- scheduled electricity: what the dispatch model planned to consume
- submitted electricity: what was submitted as a bid
- cleared electricity: what the market accepted
- rejected electricity: submitted electricity that did not clear

Used electricity is **not** recomputed here. The dispatch remains the original schedule. Full physical consequences of under-clearing require Phase 3 redispatch.

## Why this phase matters

The schedule-and-settle baseline can hide an important issue:

- a schedule may look profitable when all planned electricity is assumed available,
- but the same schedule may be partly infeasible once demand bids are cleared against actual prices.

The bridge makes that difference measurable through:

- submitted vs cleared electricity;
- rejected energy;
- hours with zero clearing;
- hours with partial clearing;
- pay-as-cleared settlement cost on the accepted volume only.

## Current limitation

If `reference_price_bid` rejects expensive hours, this phase does **not** yet answer how the plant should react physically.

That missing step is intentional. It belongs to the later redispatch phase, where the plant must operate using only the electricity that actually cleared.
