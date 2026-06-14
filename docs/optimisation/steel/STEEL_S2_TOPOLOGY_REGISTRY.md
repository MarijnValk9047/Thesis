# Steel S2 Topology Registry

## Purpose

This note records the first governed structural topology registry for the deterministic `S2` metallic material-flow LP.

The registry lives under:

- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_topology_skeleton/`

It is a candidate-review topology surface only.

## What The Registry Is

The registry is a machine-readable structural description of:

- which `S2` configurations exist structurally;
- which routes belong to those configurations;
- which process units, carriers, stores, and arcs are in scope;
- which inventory-policy candidates are structurally relevant.

It is intended to support later `S2.6c` and `S2.7` work by freezing the first non-executable topology surface before any approved numerical input exists.

## What The Registry Is Not

The registry is not:

- an approved model-input table;
- an executable Tata-like plant model;
- a numerical capacity table;
- a coefficient table;
- an objective-parameter table;
- an energy, emissions, market, or risk layer.

Structural inclusion of a route, unit, carrier, store, or arc does not approve:

- capacity;
- throughput envelope;
- inventory level;
- coefficient;
- cost;
- tariff;
- emissions factor;
- product value;
- bid quantity;
- any other numerical operating input.

## Configuration Boundary

The registry uses `C0` and `C1` only as real structural configuration rows:

- `C0_current_BF_BOF_reference`
- `C1_phase1_hybrid_BF_BOF_NG_DRP_EAF`

It does not implement separate topology branches for:

- `C1S_phase1_sensitivity_variants`
- `C2_exogenous_hydrogen_sensitivity_optional_later`

Those remain governance concepts:

- `C1S` is sensitivity metadata inside `C1`;
- `C2` is optional-later metadata only and does not create a hydrogen topology here.

## Structural Topology Versus Numerical Approval

The governing distinction remains:

- structure may be candidate-supported;
- numerical inputs remain unapproved and non-executable.

This registry therefore records:

- presence of routes and assets;
- structural material-flow connectivity;
- bounded-buffer policy direction;
- external-supply versus internal-buffer boundary choices.

It does not weaken the `S2.5`, `S2.5b`, `S2.5c`, `S2.5d`, `S2.5e`, or `S2.6a` restrictions.

## Why Internal Buffers Are Bounded

The registry records only bounded internal buffers because the `S2` model must not create fake flexibility through unbounded stock movement.

The structural candidates therefore focus on:

- small bounded hot-metal transfer treatment;
- bounded `DRI` or `HDRI` decoupling treatment;
- bounded slab or downstream `WIP` treatment;
- tiny feasibility-only hot-slab or liquid-metal transfer treatment where needed.

The registry intentionally omits unbounded internal stores.

## Why External Raw Materials Are Supply Boundaries

Raw materials are represented as external supply boundaries rather than internal flexibility buffers.

This applies to items such as:

- coal or coke input;
- ore or pellet input;
- scrap input;
- flux input.

That choice keeps the first topology surface aligned with the thesis question:

- process flexibility and bounded internal decoupling;
- not artificial flexibility created by large internal raw-material stock assumptions.

## CYC50 As Policy Candidate Only

The registry records `CYC50` as an inventory-policy candidate only.

Its role is structural:

- initial inventory equals `50%` of explicit buffer capacity;
- terminal inventory equals initial inventory;
- the cyclic endpoint avoids false flexibility from one-sided depletion.

At this stage, `CYC50` is still:

- non-executable;
- non-approved;
- not a promoted numerical rule.

## How The Registry Prepares Later Work

This registry prepares later `S2.6c` and `S2.7` work by giving the steel workstream:

- a stable `C0` and `C1` topology vocabulary;
- a governed route list;
- a governed process-unit list;
- a governed carrier list;
- bounded internal-store structure;
- explicit topology arcs for material flow only;
- a small inventory-policy surface.

That is enough to support future structural parsing, structural validation, and later non-executable topology-building logic without silently promoting numerical assumptions.

## What Is Explicitly Not Included

The registry excludes:

- `S3` WAG and internal-energy logic;
- energy economics;
- emissions-cost logic;
- tariff logic;
- DA prices;
- DA bidding;
- stochastic scenarios;
- `mFRR`;
- `CVaR`;
- product-revenue logic;
- order-book or deadline logic.

It also excludes `D-only` versus `D+4` comparison logic because horizon comparison is not a structural topology question.
