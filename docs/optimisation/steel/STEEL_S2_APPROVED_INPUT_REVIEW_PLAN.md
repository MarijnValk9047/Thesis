# Steel S2 Approved Input Review Plan

## Purpose

This document defines the `S2.3` governance step for future deterministic steel `S2` inputs.

It does not approve any steel value table. It defines:

- the difference between `toy_scaffold`, `candidate_review`, and `approved_model_input` modes;
- the future deterministic `S2` input-table schema surface;
- how candidate evidence categories map into that future schema;
- why validation targets must stay distinct from executable constraints;
- what remains postponed until `S3` or later.

Read this together with:

- `STEEL_IMPLEMENTATION_FREEZE_V1.md`
- `STEEL_STAGE_GATE_VALIDATION_PLAN.md`
- `STEEL_S2_S3_IMPLEMENTATION_SCOPE.md`
- `STEEL_TRACTABILITY_AND_CHANGE_CONTROL.md`
- `STEEL_PARAMETER_UNIVERSE.md`

## Input Modes

### `toy_scaffold`

Use this only for the current governed toy tables under:

- `data/03_Optimisation/inputs/assets/steel/s2_toy_scaffold/`

Rules:

- toy values may drive structural smoke runs;
- thesis usability stays `no`;
- outputs must state that values are scaffold, not approved, and not Tata-specific quantitative evidence.

### `candidate_review`

Use this only for structural parsing, schema checks, mapping checks, and non-thesis dry runs.

Rules:

- candidate, toy, validation-only, sensitivity-only, or otherwise not-approved rows may be read;
- thesis usability stays `no`;
- no quantitative thesis claim may be made from such runs;
- validation targets remain external checks and must not silently become active constraints.

### `approved_model_input`

This mode is reserved for a later governed state.

Rules:

- every executable row required by the active model configuration must have `approval_status = approved_model_input`;
- toy, candidate, validation-only, sensitivity-only, and `approved_later` rows are forbidden;
- if any required row is not approved, configuration loading must fail before solving.

## Future S2 Input Tables

The future deterministic `S2` approved-input surface is represented in:

- `data/03_Optimisation/inputs/assets/steel/s2_schema/`

The current schema scaffold covers:

- `process_units.csv`
- `carriers.csv`
- `stores.csv`
- `conversion_coefficients.csv`
- `process_bounds.csv`
- `production_targets.csv`
- `initial_inventories.csv`
- `terminal_inventory_rules.csv`
- `topology_routes.csv`
- `validation_targets.csv`

These schema files are governance contracts only. They are not approved value tables.

## Minimum Governance Fields

Future approved rows should carry, where relevant:

- `input_id` or `parameter_id`
- `process_id`, `carrier_id`, `store_id`, or `route_id`
- `value`
- `unit`
- `time_resolution` or `horizon_applicability`
- `configuration`
- `source_id` or `source_class`
- `source_status`
- `approval_status`
- `intended_use`
- `required_phase`
- `scenario_tag`
- `notes`

This is the minimum surface needed to stop category discovery, validation anchors, and executable model inputs from being mixed together.

## Candidate Mapping Layer

The mapping scaffold now lives under:

- `data/03_Optimisation/inputs/assets/steel/s2_candidate_mapping/`

It records:

- which candidate evidence categories are required for deterministic `S2`;
- which future input table each category would feed;
- which categories are validation-only;
- what is still missing before approval;
- which categories are postponed until `S3` or later.

This layer is a review scaffold only. It must not be treated as approved numerical input.

## Validation Targets Versus Constraints

Validation targets are external plausibility anchors.

They may support:

- annual reconciliation checks;
- route-level plausibility checks;
- diagnostics and stage-gate evidence.

They may not:

- become active production, capacity, or inventory constraints by default;
- be translated into hourly caps without explicit translation methodology and approval;
- be used as approved model-input rows while still labelled validation-only.

## Promotion Requirements Before Approval

Before a candidate category can become `approved_model_input`, the following must be explicit:

1. reviewed source support;
2. unit basis and sign convention;
3. configuration applicability;
4. hourly or horizon translation method where relevant;
5. distinction from validation targets and sensitivity-only assumptions;
6. freeze-compatible phase scope;
7. review decision recorded in the steel governance documents.

## Explicitly Postponed Beyond S2

`S2.3` does not reopen:

- `S3` WAG and internal-energy layers;
- emissions and ETS objective terms;
- network tariffs;
- DA prices or DA bidding;
- stochastic scenarios;
- `mFRR`;
- 15-minute granularity;
- `D_plus_4`;
- `CVaR`;
- product revenue or order-book logic.

Those remain postponed in line with the frozen implementation sequence.

## Thesis Claim Boundary After S2.3

After `S2.3`, thesis-grade quantitative claims are still not allowed for the steel runs because:

- the executable runs still use toy scaffold values;
- candidate evidence is only mapped and reviewed, not promoted;
- approved deterministic `S2` value tables do not yet exist.

`S2.3` improves governance and misuse prevention. It does not create approved steel operating inputs.
