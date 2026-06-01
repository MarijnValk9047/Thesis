# Redispatch After Clearing

## Purpose

Phase 3 adds deterministic redispatch after actual day-ahead clearing.

This phase still does **not** implement the true stochastic bidding MILP. It starts from an already cleared electricity profile and asks a physical operations question:

- given the electricity that actually cleared,
- how should the hydrogen plant operate?

## Core logic

Clearing determines electricity availability.

Redispatch determines whether the plant can physically use that electricity under:

- electrolyser limits;
- compressor limits;
- hydrogen storage balance;
- reserve floor;
- production target;
- shortfall logic.

The plant may **not** consume electricity that did not clear.
The plant also may not re-optimise procurement after clearing. Cleared electricity is already sunk at redispatch time.

## Required accounting identity

For every hour:

- `used_energy_mwh + unused_cleared_energy_mwh = cleared_energy_mwh`

with:

- `used_energy_mwh = timestep_hours * (electrolyser_power_mw + compressor_power_mw)`

This identity matters because `used_energy <= cleared_energy` is too weak. It can hide over-procurement by allowing the model to ignore paid electricity.

## Economic interpretation

Pay-as-cleared settlement still applies:

- accepted electricity is paid at the realised market clearing price;
- bid price is not the paid price.

So:

- `realised_DA_settlement_cost = sum(actual_price_eur_per_mwh * cleared_energy_mwh)`

Settlement cost is based on **cleared** energy, not used energy.
The bid price affects acceptance only. It is not the paid price.

Other redispatch terms are:

- hydrogen revenue from compressed or sold hydrogen;
- shortfall penalty;
- unused-cleared-energy penalty `C_unused`;
- terminal inventory correction.

For Badarinath-style redispatch, the optimisation objective is:

- maximise `hydrogen_revenue - C_unused * unused_cleared_energy - shortfall_penalty + terminal_inventory_correction`

So DA settlement cost is reported in realised profit, but excluded from the redispatch solve because it is sunk after clearing.

The hydrogen target remains a **lower-bound reference requirement**:

- it is used to measure shortfall and minimum delivery performance;
- it is **not** a fixed offtake cap;
- hydrogen production or hydrogen compressed/sold may exceed the target if the physical model allows it.

For reporting, reliability and overproduction are separated:

- capped reliability fulfilment = `min(hydrogen_compressed_or_sold, target) / target`
- uncapped production-to-target ratio = `hydrogen_compressed_or_sold / target`
- above-target hydrogen = `max(hydrogen_compressed_or_sold - target, 0)`

A ratio above `1.0` should not be read as better reliability. It is an economic or operational outcome, not a reliability improvement.

## Under-clearing and over-clearing

If clearing is too low:

- the plant may be forced to reduce electrolyser use;
- storage may be drawn down toward the reserve floor;
- explicit hydrogen shortfall may appear.

If clearing is too high:

- the plant may not be able to physically use all purchased electricity;
- `unused_cleared_energy_mwh` appears;
- that energy is still paid for in settlement;
- `C_unused` discourages the optimiser from wasting procured electricity when the plant could physically use it.

Remaining unused energy should therefore reflect binding physical limits, such as:

- electrolyser capacity;
- compressor capacity;
- storage-capacity saturation;
- minimum-load or ramping feasibility.

## What this phase is not

This is still not:

- a stochastic bidding optimiser;
- scenario-dependent recourse;
- CVaR bidding;
- mFRR participation;
- exclusive group bidding;
- full market clearing.

It is a deterministic post-clearing physical feasibility and settlement layer.

## Why it matters

The schedule-to-bid bridge from Phase 2 only answers:

- what cleared?

Phase 3 adds the next required question:

- what could the plant physically do with the cleared electricity?

That distinction is necessary before later phases can claim anything about realised profit, production fulfilment, or the operational consequences of rejected or over-cleared electricity.
