# Steel S2 Model-Builder Interface Contract

## Purpose

This note defines the contract that a future deterministic `S2` metallic material-flow LP builder must satisfy before any executable steel LP work is allowed.

It is an interface-design artifact only. It does not approve numerical values, create solver inputs, define Pyomo equations, or permit executable model behaviour.

## Contract Position In The Steel Chain

The current steel chain is:

- source evidence;
- candidate assumption library;
- configuration scope freeze;
- configuration-tag mapping;
- topology registry;
- topology loader and validator;
- in-memory topology objects;
- topology query and assembly views;
- deterministic model-builder interface contract.

The future deterministic `S2` model builder must sit after these structural gates, not bypass them.

## What The Future Builder Will Consume Structurally

The future deterministic `S2` builder is expected to consume validated structural views from:

- `scripts/Data/04_Steel_Test_Case/steel/topology_queries.py`

Those structural views must supply, at minimum:

- configuration ID;
- route IDs;
- process-unit membership;
- carrier membership;
- store membership;
- topology arcs;
- source-like and sink-like nodes;
- bounded buffer/store nodes;
- shared downstream handling in `C1`;
- endpoint-policy metadata such as `CYC50_candidate_only`.

The builder must not reconstruct topology ad hoc from raw CSV files or free-text assumptions.

## What The Future Builder Will Require Numerically

No numerical input is approved by this contract.

Before executable `S2.7` LP work is allowed, the future builder will require approved numerical inputs for at least:

- process bounds;
- conversion coefficients;
- store capacities;
- initial inventories;
- terminal inventory rules;
- production targets.

These inputs may only be consumed after they exist as approved numerical tables under the steel governance system.

## What Remains Blocked

At this stage, the following remain blocked from executable use:

- candidate-review numerical values;
- validation targets as live constraints;
- annual public anchors as hourly caps;
- any hidden conversion of structural candidates into executable parameters.

The contract therefore separates four layers explicitly:

1. topology structure;
2. numerical input approval;
3. model construction;
4. solver execution and run reporting.

Structural presence is not numerical approval. Numerical approval is not model construction. Model construction is not solver execution.

## Configuration Handling

The future deterministic `S2` builder may treat only these as main configurations:

- `C0_current_BF_BOF_reference`
- `C1_phase1_hybrid_BF_BOF_NG_DRP_EAF`

`C1S_phase1_sensitivity_variants` may later appear only as sensitivity-overlay metadata inside `C1`. It must not create a separate pathway branch or topology branch.

`C2_exogenous_hydrogen_sensitivity_optional_later` may later appear only as optional-later exogenous-hydrogen sensitivity metadata. It must not create a main implementation branch, endogenous hydrogen production, on-site electrolysis, or hydrogen infrastructure optimisation.

## Buffer And Boundary Contract

The future builder must preserve the structural distinction between:

- external raw-material boundaries; and
- internal flexibility buffers.

External raw-material supplies such as ore, pellets, coal or coke, scrap, and fluxes are supply boundaries. They are not to be treated as internal flexibility buffers.

Internal buffers remain bounded structural candidates only. The future builder may later consume approved capacities and inventory rules for:

- hot-metal buffers;
- `DRI` or `HDRI` buffers;
- slab or `WIP` buffers;
- tiny feasibility-only transfer buffers where justified.

## CYC50 Contract Logic

`CYC50` is part of the interface contract only as endpoint-policy logic.

For future executable work, the contract meaning is:

- initial inventory is linked to an explicit buffer-capacity rule;
- terminal inventory returns to the same reference level;
- cyclic treatment prevents false flexibility through net depletion.

At this stage, `CYC50` is not an approved executable numerical value. It is only a contract requirement for how future approved endpoint rules must behave.

## Required Builder Refusal Rules

The future deterministic `S2` builder must refuse:

- candidate-review values unless explicitly approved later;
- validation targets as constraints;
- annual public anchors as hourly caps;
- `S3` WAG, internal-energy, emissions-economics, tariff, DA bidding, stochastic, `mFRR`, `CVaR`, product-revenue, and order-book logic inside `S2`;
- `D-only` versus `D+4` comparison logic;
- Phase 2, Phase 3, full-hydrogen, on-site electrolysis, `SAF`, `CCS`, hydrogen production, and hydrogen storage or infrastructure optimisation as `S2` builder branches.

## Required Future Run And Reporting Outputs

When executable deterministic `S2` work is eventually opened, the builder and runner must report at least:

- solver status;
- objective value;
- runtime;
- variable count;
- constraint count;
- infeasibility diagnostics when failed;
- resolved configuration and input manifests;
- production and inventory summaries;
- warnings and limitations.

Those reporting obligations are part of the builder contract even though the executable runner does not exist yet.

## What Must Happen Before S2.7

Executable `S2.7` LP work is not allowed until all of the following are true:

- the frozen `C0` and `C1` structural path remains intact;
- approved numerical input tables exist for the required deterministic quantities;
- unit, sign, and endpoint conventions are reviewed for those approved inputs;
- validation targets remain separated from live constraints;
- annual public anchors remain blocked from hourly-cap use;
- the deterministic builder interface is implemented without reopening blocked scope;
- run and reporting outputs are specified and testable.

Until those gates pass, the steel work remains structural and governance-only.
