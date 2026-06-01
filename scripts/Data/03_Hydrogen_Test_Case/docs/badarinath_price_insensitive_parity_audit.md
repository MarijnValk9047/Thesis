# Badarinath Price-Insensitive Parity Audit

## Purpose

This note checks whether the current `price_insensitive` benchmark matches the intended Badarinath-style benchmark structure:

1. ignore DA prices during planning;
2. build a deterministic physical production plan;
3. extract the resulting electricity demand profile;
4. submit that profile as high-price demand bids;
5. clear against realised DA prices;
6. pay the realised clearing price;
7. redispatch physically using the cleared electricity with an unused-cleared-energy penalty.

## What the current `price_insensitive` benchmark does

Now, `price_insensitive` in [benchmarks.py](</C:/Users/marijnvalk/PycharmProjects/Thesis/scripts/Data/03_Hydrogen_Test_Case/hydrogen/benchmarks.py>) is:

- a deterministic **optimisation-based physical plan**;
- built without using actual DA prices or scenario prices in the planning objective;
- solved with the lexicographic planning objective `minimise_shortfall_then_maximise_hydrogen_output`;
- based on electrolyser limits, compressor limits, ramping, storage, reserve floor, and hydrogen delivery feasibility;
- evaluated economically afterwards in the schedule-and-settle baseline.

The old heuristic baseline is preserved separately as:

- `price_insensitive_heuristic`

This legacy path is kept only for comparison and auditability.

## Where it matches Badarinath

- It ignores DA prices during planning.
- It produces a deterministic hourly electricity consumption profile.
- It uses the same broad hydrogen physics structure as the other hydrogen strategies.
- That planned profile can be passed through high-price bidding, actual clearing, and Phase 3 redispatch.
- Accepted electricity is settled at the realised DA price, not the bid price, once the Phase 2 and Phase 3 layers are used.
- Redispatch should treat cleared electricity as sunk and should not re-optimise DA procurement cost.
- A large configurable `C_unused` penalty should discourage wasting cleared electricity unless physical constraints force it.

## Audit conclusion

Conclusion: **implemented**.

Reason:

- the planning step is now a deterministic optimisation that ignores DA prices;
- the resulting planned load is passed through:
  - high-price or market-cap-like bid submission,
  - actual clearing,
  - pay-as-cleared settlement,
  - deterministic redispatch after clearing with `C_unused > 0`.

So `price_insensitive_plan_first_market_cap` now represents a full implemented benchmark chain rather than only a label wrapped around a heuristic plan.

## Recommended explicit label

To make the full sequence explicit without breaking old outputs, the bridge layer now exposes:

- `price_insensitive_plan_first_market_cap`

Interpretation:

- use the solver-based `price_insensitive` physical plan;
- submit the planned load as a one-block high-price demand bid;
- clear against realised DA prices;
- pay the realised DA clearing price;
- redispatch physically from cleared electricity with `C_unused > 0`.

This is the clearest current proxy for the Badarinath-style price-insensitive benchmark in the hydrogen test case.

## Recommendation on naming

- Keep `price_insensitive` for backward compatibility and for the plan-only benchmark meaning.
- Use `price_insensitive_plan_first_market_cap` when referring to the full plan -> bid -> clear -> redispatch chain.

## Methodological warning

This still is **not** the true stochastic bidding MILP.

It remains:

- deterministic planning for the benchmark;
- ex-post historical clearing;
- deterministic redispatch from actual cleared electricity;
- pay-as-cleared settlement based on actual clearing price, not bid price.
