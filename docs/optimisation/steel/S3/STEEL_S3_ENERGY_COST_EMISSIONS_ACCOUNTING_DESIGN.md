# STEEL_S3_ENERGY_COST_EMISSIONS_ACCOUNTING_DESIGN

## Purpose

This memo completes `S3.0a` as a non-executable accounting design and input-schema stage.

It does not implement:

- Pyomo accounting constraints
- `WAG` allocation equations
- objective terms
- tariff or `ETS` calculations
- day-ahead dispatch, bidding, clearing, or settlement
- stochastic scenarios
- `CVaR`
- `mFRR`
- 15-minute logic
- product revenue or order-book logic

`S3.0a` exists to define what future `S3.0b` and `S3.0c` work may consume and what remains blocked.

## Frozen Inputs To S3

`S3` must treat the `S2.11` flexible metallic core as read-only.

The active core remains:

- `C0`: `BF` to hot-metal buffer to `BOF` to liquid-steel diagnostic target
- `C1`: retained `BF` to hot-metal buffer to `BOF` to liquid-steel diagnostic target, plus `NG-DRP` to `DRI/HDRI` buffer to `EAF` to liquid-steel diagnostic target

The only active buffer structures remain:

- `c0_hot_metal_buffer`
- `c1_hot_metal_buffer`
- `c1_dri_hdri_buffer`

`S3.0a` must not change S2 topology, process bounds, conversion coefficients, production targets, store capacities, endpoint policy, or smoke-test interpretation.

## S2.12 Boundary Precondition

The `S2.12` downstream and `WAG` boundary correction is a hard precondition for `S3`.

Future accounting must cover:

- the frozen flexible metallic core
- throughput-coupled downstream production continuation
- accounting-only auxiliary loads
- the `WAG` and site-energy accounting boundary

`S3` must not start from a liquid-steel-only plant boundary.

## Accounting Layers

### Flexible Metallic Core

Core process activity profiles may later receive accounting coefficients for energy use, emissions, costs, and `WAG` generation.

In `S3.0a`, those coefficients are schema candidates only. They are not approved model inputs.

### Throughput-Coupled Downstream Continuation

Secondary metallurgy, casting, slab handling or transfer, reheating, and `HSM` or downstream rolled-product boundary may later receive accounting coefficients.

They may not become independently schedulable assets in `S3.0a`.

They may not create cold slab, slab-`WIP`, hot slab, or finished-goods flexibility.

### Accounting-Only Auxiliaries

`ASU`, oxygen, and other throughput-coupled auxiliary placeholders may later receive electricity, fuel, emissions, or cost accounting coefficients.

They remain accounting-only nodes and do not reopen flexible utility dispatch.

### WAG And Site-Energy Boundary

`WAG` must be represented as producer, consumer, interface, or residual-sink accounting objects.

Required object classes include:

- `BFG` from `BF`
- `BOFG` or `LD` gas from `BOF`
- `COG` as a coking-boundary candidate
- process-fuel consumers
- steam or boiler consumers
- `Vattenfall` or on-site generation interface
- flare, spill, and unused residual sinks
- grid electricity imports
- natural-gas imports

`WAG` is not free revenue. Direct electricity-price valuation, automatic export revenue, and unconstrained `WAG` arbitrage remain blocked.

## Vattenfall And On-Site Generation

The `Vattenfall` or on-site generation object remains an interface in `S3.0a`.

It may later support diagnostic net-import offset accounting after explicit conversion logic exists.

It is not a dispatch plant, market participant, settlement object, or export-revenue source in `S3.0a`.

## Carbon And ETS Treatment

Gross `ETS` cost may later become a visible accounting term.

Free allocation remains separate and later:

- not netted silently against gross emissions
- not an automatic credit
- not a base-case shortcut

The first emissions architecture must keep direct process emissions, `WAG` combustion or flare emissions, natural-gas combustion emissions, captured-`CO2` visibility, and optional reporting-only indirect electricity emissions separate enough to avoid double counting.

## Network Tariff Treatment

Network tariff parameters are proxy-labelled candidates only.

They must not be represented as Tata contract truth, confidential tariff knowledge, or approved site-specific values without explicit review.

## Production Boundary Treatment

Liquid steel remains the `S2` diagnostic target.

Future fulfilment reporting must make an explicit target-boundary decision:

- liquid steel as diagnostic reference
- cast slab as full-chain candidate
- hot-rolled product or `HRC` as final reporting candidate

Finished-goods and order-book targets remain excluded unless the methodology is explicitly reopened.

## Source And Evidence Rules

Public annual anchors may inform validation and source review, but they must not become executable hourly truth.

Athanasiadis-style redacted or confidential values may inform category awareness only. They must not be treated as exact Tata inputs.

Every future coefficient row must carry source status, evidence class, review status, approval status, `thesis_usability`, and reviewer decision fields before execution can be considered.

Final thesis model assumption eligibility is now governed separately by `STEEL_S3_EVIDENCE_USE_AND_THESIS_ASSUMPTION_POLICY.md`. That policy allows public secondary, generic technology, user-selected scenario, and derived source-backed assumptions to be used in the final thesis model only when they are explicitly caveated, traceable, and sensitivity-reviewed where material. This does not make those rows Tata-exact facts, validation targets, or approved empirical truth.

## S3.0a Output Contract

The `S3.0a` output surface consists of:

- accounting parameter universe
- S3 to S2/S2.12 mapping register
- accounting input schema
- accounting status and review policy
- future `S3.0b` fixed-profile `WAG` diagnostic contract
- empty approved-input shell

All rows are candidate or governance only.

No row is executable in `S3.0a`.

No row is approved.

No row is thesis-usable.
