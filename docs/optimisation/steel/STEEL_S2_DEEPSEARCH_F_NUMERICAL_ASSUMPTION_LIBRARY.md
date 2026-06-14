# Steel S2 Deepsearch F Numerical Assumption Library

## Purpose

This note records `S2.5d`: the integration of Deepsearch F into the existing steel `S2` governance surface.

Deepsearch F adds a source-backed assumption and sensitivity library for the deterministic hourly metallic material-flow LP. It does not approve Tata Steel IJmuiden operating values. It does not create executable `S2` rows. It does not reopen `S3`, DA, stochastic, `mFRR`, `15-minute`, `D+4`, or `CVaR` layers.

Read this together with:

- `STEEL_IMPLEMENTATION_FREEZE_V1.md`
- `STEEL_S2_S3_IMPLEMENTATION_SCOPE.md`
- `STEEL_S2_APPROVED_INPUT_REVIEW_PLAN.md`
- `STEEL_S2_STRUCTURAL_NUMERICAL_SEPARATION.md`
- `STEEL_S2_UNIT_SIGN_AND_ENDPOINT_CONVENTIONS.md`

## What Deepsearch F Adds Beyond Waves A-E

Waves A-E established structure, topology, validation anchors, technology ranges, WAG and energy boundaries, and later economic-policy layers. Deepsearch F adds a narrower `S2` numerical-governance function:

- a source-indexed assumption library for first-pass metallic coefficients and operating classes;
- stronger support for cyclic inventory policy and anti-gaming terminal rules;
- stronger support for bounded internal buffers, especially slab-yard and HDRI decoupling classes;
- a clearer distinction between strong assumption-backed candidates and weak sensitivity-only categories.

The strongest Deepsearch F categories are:

- `CYC50` inventory policy;
- BF and DRP continuity classes;
- BOF and EAF batch-equivalent treatment;
- hot-metal, HDRI, and slab/WIP buffer classes;
- casting yield;
- route-average BF-BOF raw-material coefficients;
- DRP ore-to-DRI coefficient;
- target-basis methodology.

The weakest categories remain:

- internal coke product storage;
- sinter and pellet intermediate storage;
- exact BF minimum stable load;
- modern slab-to-HRC yield for a Tata-inspired integrated flat route;
- site-transferable slab-yard quantitative caps beyond order-of-magnitude use.

## Integrated Structures Updated

Deepsearch F was integrated into existing governance structures instead of creating a parallel system.

Updated or reused:

- `data/03_Optimisation/inputs/assets/steel/source_cards/`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_deepsearch_f_source_index.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_deepsearch_f_candidate_assumption_register.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_deepsearch_f_assumption_sensitivity_matrix.csv`
- `scripts/Data/04_Steel_Test_Case/steel/governance.py`
- `scripts/Data/04_Steel_Test_Case/tests/test_s2_toy_smoke.py`

Not duplicated:

- no second source-card system;
- no second candidate-review bundle;
- no second schema layer;
- no separate executable input surface;
- no alternative S2 promotion checklist.

## F01-F20 Mapping to S2 Categories

The `F01-F20` source cards and source index cover the following `S2` categories:

- `F01`, `F17`: Tata-inspired topology, public annual anchors, and route framing
- `F02`: cyclic inventory policy, anti-fake-flexibility endpoint logic, and annual-to-effective-hours reasoning
- `F03`: hot-metal ladles, mixers, and BF-to-BOF coupling
- `F04`, `F07`: DRP continuity, ore-to-DRI coefficients, and vendor-context DRI properties
- `F05`, `F06`: HDRI transfer, feed-bin classes, HTV classes, and DRI/EAF decoupling
- `F08`, `F10`, `F11`: EAF batch-equivalent logic, tap-to-tap ranges, heat-size context, and DRI/HBI handling caveats
- `F09`: BOF batch-equivalent logic and hot-metal or scrap share support
- `F12`: BF-BOF route-average raw-material coefficients
- `F13`: casting yield and continuous-casting context
- `F14`, `F15`: slab-yard, hot-slab, and downstream WIP treatment
- `F16`: coke-oven continuity and the weakness of public coke-buffer evidence
- `F18`, `F19`, `F20`: governance and modelling precedent only, not numerical approval sources

## Why Deepsearch F Does Not Approve Numerical Inputs

Deepsearch F remains candidate-only because the sources are still mixed in character:

- public topology and route-framing sources;
- peer-reviewed studies and theses;
- vendor brochures and technical notes;
- governance and thesis-precedent materials.

That is strong enough for an assumption library. It is not strong enough for approved Tata-like executable rows. In particular:

- vendor technical values remain vendor-context evidence;
- route-average industry coefficients remain non-site-specific;
- annual public values remain validation anchors, not hourly caps;
- downstream slab-yard evidence remains order-of-magnitude and sensitivity support, not Tata truth.

## CYC50 Policy

The current `S2` inventory policy direction is `CYC50`:

- initial inventory = `50%` of explicit buffer capacity;
- terminal inventory = initial inventory;
- cyclic terminal inventory prevents fake flexibility from net depletion across the optimisation horizon.

Deepsearch F strengthens that policy by adding direct literature support for equal initial and terminal inventories. It does not, by itself, approve executable opening or terminal quantity rows.

## Internal Buffers Versus External Supplies

Deepsearch F also sharpens the boundary between internal bounded buffers and external raw-material supplies.

Best candidates for explicit internal bounded buffers:

- hot-metal transport or mixer class;
- HDRI or DRI surge and feed-bin class;
- hot slab WIP;
- cold slab yard or WIP.

Best treated as exogenous supply plus throughput limits unless stronger evidence appears:

- coke product stock;
- sinter internal stock;
- pellet internal stock;
- finished steel or commercial inventory.

This matters because public evidence is much stronger for process continuity and downstream slab handling than for dispatchable intra-plant stock of coke, sinter, or pellets.

## What Must Happen Before Any Candidate Becomes Executable

Before any Deepsearch F candidate can support executable `S2` assumptions later, the following still need to happen:

1. source review confirming the intended use is not overstated;
2. unit and sign review against the shared `S2` conventions;
3. explicit separation between validation anchors and constraint-driving rows;
4. explicit annual-to-hourly approval where any annual anchor is translated;
5. promotion into the existing `approved_model_input` governance path;
6. a decision that the row is usable as a Tata-inspired thesis assumption rather than only as a sensitivity range.

Until that happens, all Deepsearch F candidate rows remain:

- `non_executable`
- not approved
- not thesis-grade numerical inputs

## Why D-Only Versus D+4 Is Not Part of S2.5d

`S2.5d` is a numerical assumption-library governance step for deterministic `S2`. It is not a forecast-horizon comparison stage.

Therefore this integration does not add:

- `D-only` versus `D+4` comparison artifacts;
- rolling-lookahead comparison tables;
- market-sequence logic;
- forecast-origin experiment design.

Rolling lookahead may matter later as operational design context, but it is outside this Deepsearch F integration step.
