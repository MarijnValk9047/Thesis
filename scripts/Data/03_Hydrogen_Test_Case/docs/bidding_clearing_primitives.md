# Bidding And Clearing Primitives

## Purpose

Phase 1 adds only pure bidding and clearing primitives on toy data.

It does not change the hydrogen optimisation model. It does not create a stochastic bidding MILP. It does not add redispatch.

## Demand bid blocks

A demand bid block is one quantity-price pair for one delivery interval:

- `bid_quantity_mw`
- `bid_price_eur_per_mwh`

Multiple bid blocks for the same hour form a simple bid curve.

## Acceptance rule

For demand bids in a price-taking ex-post clearing approximation:

- accepted if `bid_price_eur_per_mwh >= actual_price_eur_per_mwh`
- rejected otherwise

This means the bid price acts as a willingness-to-pay threshold.

## Pay-as-cleared interpretation

Accepted demand bids pay the market clearing price, not the bid price.

That distinction matters:

- bid price decides acceptance;
- actual market price decides settlement.

So the bid price is not the paid price. It is only an acceptance threshold in this simplified Phase 1 clearing layer.

## Why this is not full EUPHEMIA

This clearing layer is a price-taking ex-post acceptance rule.

It does not represent:

- full order-book competition;
- block-order coupling;
- paradoxical acceptance or rejection;
- endogenous market clearing;
- welfare-maximising market equilibrium.

That is deliberate. Phase 1 is only for transparent primitives and toy validation.

## Why fixed bid-price tiers are used first

Fixed bid-price tiers are used before endogenous bid prices because they make debugging easier:

- acceptance logic is explicit;
- toy examples have exact expected outcomes;
- later optimisation can choose quantities against a fixed grid without first introducing a more complex nonlinear or mixed-integer bidding design.

## Conceptual distinction between electricity states

- submitted electricity: demand volume placed into bids
- cleared electricity: submitted volume accepted by the market price rule
- rejected electricity: submitted volume not accepted
- used electricity: electricity physically consumed by the plant
- unused electricity: cleared electricity that later turns out not to be physically used

Phase 1 only models:

- submitted electricity
- cleared electricity
- rejected electricity

It does not yet model used or unused electricity because redispatch is not implemented in this phase.
