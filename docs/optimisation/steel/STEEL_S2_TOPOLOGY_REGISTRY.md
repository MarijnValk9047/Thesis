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

## Topology Loader And Parser

`S2.6c` adds a small governed loader and parser under:

- `scripts/Data/04_Steel_Test_Case/steel/topology_loader.py`

It reads the seven topology-skeleton CSV files and validates:

- required columns and table presence;
- frozen `C0` and `C1` configuration scope;
- route, process-unit, store, carrier, and arc reference consistency;
- bounded internal-store structure;
- external raw-material boundaries staying external;
- `CYC50` remaining a non-executable policy candidate;
- absence of executable, thesis-usable, approved, numerical, or later-stage market/risk content.

The loader deliberately refuses to:

- create a Pyomo model;
- create capacities, coefficients, costs, emissions factors, or objective terms;
- approve numerical inputs;
- convert candidate-review topology into executable model parameters.

Its role is narrower: it gives `S2.6d` and later `S2.7` work a checked structural input surface before any deterministic steel LP builder is allowed.

## In-Memory Topology Object Layer

`S2.6d` adds a structural-only object layer under:

- `scripts/Data/04_Steel_Test_Case/steel/topology_objects.py`

This sits one step above the CSV registry and the loader:

- the CSV registry is the governed tabular source;
- the loader validates raw table consistency;
- the object layer converts the already-validated rows into lightweight Python objects for `C0` and `C1` only.

The object layer exposes compact structural helpers such as:

- get configuration by ID;
- list routes by configuration;
- list process units, stores, and arcs by configuration or route;
- list carriers in scope;
- identify source-like and sink-like nodes from the arc structure;
- summarize topology counts.

It is still structural only. It does not:

- create a Pyomo model;
- create solver inputs;
- expose optimisation-ready capacities, coefficients, costs, or market parameters;
- approve numerical inputs;
- turn `C1S` or `C2` into implementation branches.

Its role is to prepare `S2.6e` and later `S2.7` work with a small in-memory topology surface that stays inside the same governance boundary as the registry and loader.

## Topology Query And Assembly Layer

`S2.6e` adds a structural-only query and assembly layer under:

- `scripts/Data/04_Steel_Test_Case/steel/topology_queries.py`

This sits above the object layer:

- the loader validates the CSV registry;
- the object layer converts validated rows into lightweight Python objects;
- the query layer assembles configuration-level and route-level structural views from those objects.

The query layer provides structural views for:

- `C0` and `C1` configuration subsets;
- all three frozen route subsets;
- process-chain ordering by route;
- incoming and outgoing arc lookup by node;
- source-like, sink-like, and buffer-store node identification;
- shared downstream node identification in `C1`;
- external supply boundary carrier identification;
- internal metallic carrier identification;
- disconnected-node checks and compact structural summaries.

It is still not a model builder. It does not:

- create balances, variables, constraints, or objectives;
- create a Pyomo model;
- create solver inputs;
- expose numerical capacities, coefficients, costs, or market parameters;
- approve numerical inputs or create later-stage implementation branches.

Its role is narrower: it prepares `S2.6f` and later `S2.7` work with reusable structural query views while keeping the same refusal of numerical and later-stage content as the loader and object layer.

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
