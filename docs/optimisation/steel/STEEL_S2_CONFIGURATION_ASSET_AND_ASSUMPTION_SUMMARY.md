# STEEL_S2_CONFIGURATION_ASSET_AND_ASSUMPTION_SUMMARY

## Assets/Process Units In C0

`C0_current_BF_BOF_reference` contains the following main assets and boundaries:

- external raw-material and metallic feed boundaries
- coke and burden preparation boundary treatment
- blast furnace
- hot-metal synchronisation buffer
- retained `BOF` converter block
- liquid-steel target sink
- casting downstream and slab handling structure as deferred topology only

## Assets/Process Units In C1

`C1_phase1_hybrid_BF_BOF_NG_DRP_EAF` contains:

- retained `BF-BOF` route
- retained hot-metal synchronisation buffer
- `NG-DRP` process unit
- `DRI/HDRI` surge buffer
- `EAF`
- secondary-metallurgy structural node
- liquid-steel target sink
- shared casting downstream slab structure as deferred topology only

## What Changes Between C0 And C1

`C0` is a single-route current reference.

`C1` adds a second metallic route with `NG-DRP-EAF` while keeping the retained `BF-BOF` route. The main flexibility change is the appearance of the `DRI/HDRI` surge buffer and `EAF` metallic route. Hot metal remains a synchronisation role in both configurations and does not become strategic long-duration storage.

## Which Assets Are Active In The LP

Active `S2` LP components are limited to:

- `BF` activity and hot-metal output
- `BOF` activity and liquid-steel output
- `NG-DRP` activity in `C1`
- `EAF` activity in `C1`
- route-neutral liquid-steel sink target
- first-buffer inventories only for `c0_hot_metal_buffer`, `c1_hot_metal_buffer`, and `c1_dri_hdri_buffer`

## Which Are Structural Only

Structural-only components remain present for topology discipline but not as executable flow logic:

- casting and slab-handling nodes
- downstream metallic sink beyond the last modelled liquid-steel sink
- secondary metallurgy in `C1`
- burden preparation and coke treatment boundaries

## Which Are Exogenous Supply Boundaries

Exogenous supply boundaries include:

- iron ore pellet or burden feed boundaries
- scrap and flux feed boundaries
- coke or carbonaceous boundary treatment
- the `NG-DRP-EAF` route supply boundary in `C1`

These boundaries are treated as external feed structure rather than economically modelled procurement.

## Which Stores Are Active

Active stores are limited to:

- `c0_hot_metal_buffer`
- `c1_hot_metal_buffer`
- `c1_dri_hdri_buffer`

These are bounded development-only buffers with `CYC50` endpoint neutrality. They are not thesis-grade capacity claims.

## Which Stores Are Blocked/Deferred

Blocked or deferred stores are:

- `c0_slab_wip_buffer`
- `c1_slab_wip_buffer`
- `c0_hot_slab_transfer_buffer`
- `c1_hot_slab_transfer_buffer`
- liquid steel ladle and tundish storage
- coke sinter pellet and finished-goods flexibility

Cold slab or slab-`WIP` remains deferred because tonne grounding is incomplete. Hot slab transfer remains feasibility-only and not strategic.

## What Assumptions Are Used Per Asset

Main asset assumptions are:

- blast furnace and `BOF` rates are dev-only average placeholder translations from annual anchors
- `NG-DRP` and `EAF` rates in `C1` are dev-only placeholder translations
- metallic recipes use fixed provisional coefficients from the current minimal smoke pack
- first-buffer capacities use bounded dev-only tonne translations tied to one-hour-equivalent process flow logic
- liquid-steel targets use route-neutral horizon-total smoke targets

## What Assumptions Remain Provisional

The following remain provisional:

- all process bounds
- all conversion coefficients
- all smoke production targets
- all buffer capacities and initial inventories
- all weekly smoke interpretations

None of these assumptions has been promoted into approved thesis-usable input tables.

## What Each Asset Contributes To Flexibility Or Non-Flexibility

Asset roles in flexibility terms are:

- blast furnace: continuity-driven non-flexible upstream producer
- hot-metal buffer: short synchronisation only
- `BOF`: downstream consumer with minimal smoke-route flexibility only
- `NG-DRP`: continuous metallic producer in the hybrid route
- `DRI/HDRI` buffer: short-term surge and decoupling only
- `EAF`: main flexible metallic conversion unit in the hybrid route
- slab and downstream structures: deferred and not yet available for executable flexibility claims
- excluded bulk stocks: outside the `S2` flexibility claim entirely

This memo is thesis-readable but still governed by `thesis_usability=false`.
