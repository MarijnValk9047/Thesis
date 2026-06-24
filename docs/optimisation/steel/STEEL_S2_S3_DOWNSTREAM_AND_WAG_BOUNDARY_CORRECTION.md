# STEEL_S2_S3_DOWNSTREAM_AND_WAG_BOUNDARY_CORRECTION

## Purpose

This memo records the `S2.12 / S3.0a` boundary correction that must be applied before any `S3` energy, cost, or emissions implementation work starts.

It is a governance memo only:

- not an `S3` equation implementation
- not an executable model input approval
- not a reopening of the frozen `S2.11` flexible metallic core
- not thesis-grade evidence

All rows and surfaces introduced by this memo remain candidate or governance only with `thesis_usability=false`.

## Why The `S2.11` Liquid-Steel Smoke Remains Frozen

`S2.11` correctly froze the flexible metallic core at the last governed liquid-steel diagnostic sink.

That freeze remains intact because it already fixed:

- the active `C0` and `C1` route topology
- the active flexible metallic assets
- the three active `S2` buffer structures
- the smoke-target interpretation
- the guarded one-week diagnostic interpretation
- the rule that `S2` remains deterministic, hourly, development-only, and non-thesis

`S2.12` does not reopen that core. It only corrects the downstream and accounting boundary that `S3` must inherit.

## Why `S3` Must Not Start From A Liquid-Steel-Only Plant Boundary

Liquid steel is an acceptable `S2` smoke target, but it is not automatically an acceptable full-plant accounting boundary.

If `S3` started from a liquid-steel-only accounting boundary, it could silently omit:

- secondary metallurgy
- casting
- slab handling and transfer
- reheating
- `HSM` or later rolled-product continuation
- throughput-coupled auxiliary loads such as `ASU` and oxygen supply
- waste-gas production, internal use, on-site generation interfaces, and flare or spill sinks

That omission would bias cost, emissions, and internal-energy accounting. It would also distort later production-fulfilment interpretation by treating the frozen liquid-steel smoke sink as if it were already the final plant boundary.

## Corrected Boundary Layers

### 1. Flexible Metallic Core

The flexible metallic core remains the frozen `S2.11` scope:

- `BF`
- `BOF`
- `NG-DRP`
- `EAF`
- `c0_hot_metal_buffer`
- `c1_hot_metal_buffer`
- `c1_dri_hdri_buffer`

This is still the only executable flexibility layer inherited from `S2`.

### 2. Inflexible Throughput-Coupled Production Continuation

The downstream production-continuation layer must now be represented structurally for `S3` entry:

- secondary metallurgy
- casting
- slab handling or slab transfer
- reheating
- `HSM` or downstream rolled-product boundary
- optional later direct-sheet continuation only if already documented elsewhere

These nodes are not independent flexibility assets in `S2.12`.

They exist so that later `S3` accounting can attach energy, cost, and emissions eligibility to the continuation of production beyond liquid steel.

### 3. Accounting-Only Auxiliary Layer

Some nodes are not downstream production assets but are still throughput-coupled and must be represented before `S3` execution:

- `ASU` or oxygen interface
- other throughput-coupled auxiliary loads where documented
- residual site-load placeholders only as candidate accounting classes

These remain accounting-only nodes. They are not schedulable truth and they do not reopen flexible utility dispatch.

### 4. Site-Energy And `WAG` Accounting Layer

`S3` must also inherit an explicit site-energy and `WAG` accounting eligibility layer covering:

- `BFG` from `BF`
- `BOFG` or `LD` gas from `BOF`
- `COG` as a coking-boundary accounting candidate where relevant
- internal `WAG` consumers for process fuel and steam or boilers
- the `Vattenfall` or on-site generation interface
- grid electricity and natural-gas import boundaries
- flare, spill, and unused-`WAG` sinks
- direct-process, combustion, flare, and captured-`CO2` visibility rules

This layer is an accounting boundary, not yet a dispatch layer.

## Why Downstream Nodes Stay Throughput-Coupled

Secondary metallurgy, casting, slab transfer, reheating, and `HSM` continuation are initially throughput-coupled or accounting nodes because the current governed evidence does not justify treating them as independent scheduling assets.

`S2.12` therefore blocks:

- independent downstream dispatch
- cold slab or slab-`WIP` strategic storage
- hot slab `WIP` strategic flexibility
- finished-goods flexibility
- product-revenue or order-book optimisation

The correction is about fair accounting coverage, not about widening the flexibility claim.

## Why `WAG` Must Be Included But Not Monetised As Free Revenue

`WAG` flows affect fuel substitution, internal energy use, flaring, and emissions. Excluding them would understate coupled site-energy behaviour.

At the same time, `WAG` must not be treated as unconstrained arbitrage or automatic export profit.

The governing rules are:

- `WAG` generation must be linked to route throughput or documented accounting nodes
- useful value comes first through governed internal use or net-import reduction
- flare or spill must stay visible as a residual sink
- direct electricity-price valuation is blocked without explicit conversion logic
- automatic export revenue is blocked
- unconstrained `WAG` arbitrage is blocked

## Why `Vattenfall` Or On-Site Generation Remains An Interface

The `Vattenfall` or on-site generation object remains an interface at this stage, not a dispatch plant.

`S3.0a` may classify whether `WAG` can later reduce net import through a governed power-conversion interface, but it must not introduce:

- plant-dispatch optimisation
- market export behaviour
- power arbitrage
- day-ahead settlement logic

## Production-Boundary Decision Consequence

The frozen liquid-steel smoke targets remain diagnostic only.

Later thesis-quality fulfilment may legitimately move to:

- cast slab
- hot-rolled product or `HRC`

That later target move must be explicit and governed.

It must not happen silently by letting `S3` pretend that liquid steel already closes the plant boundary.

## S2.12 / S3.0a Governance Outcome

Before `S3` implementation work may proceed, the repository must contain governed registers for:

- downstream production continuation
- energy-accounting asset eligibility
- `WAG` accounting boundary
- `WAG` allocation modes and blocked revenue logic
- target-boundary decisions

Those registers define eligibility and blocked scope only.

They do not approve numerical inputs, activate new flexible assets, or authorise market logic.

## Non-Thesis Status

Every memo and register introduced by this correction remains:

- candidate-only
- governance-only
- non-approved
- non-executable as thesis truth
- `thesis_usability=false`
