# Steel Data And Parameter Plan

## Goal

Define how steel-model facts move from public sources into approved model inputs without hiding assumptions in Python code or notebooks.

The objective is reproducible parameter governance, not early completeness.

## Promotion Ladder

Every steel fact should move through four layers:

| Layer | Purpose | Git Role | May Drive Model Directly |
|---|---|---|---|
| Raw sources | Preserve original evidence such as reports, papers, decks, and public disclosures. | Usually local or externally managed | No |
| Source cards | Compact structured notes per source. | Yes, if compact and clean | No |
| Candidate parameter register | Working table of possible parameters, ranges, and confidence. | Yes | No |
| Approved model input tables | Frozen inputs used by model configs and loaders. | Yes | Yes |

This prevents a thesis from drifting from "I saw a number in a report" to "that number silently became model truth."

## Storage Recommendation

Recommended future location:

```text
data/03_Optimisation/inputs/assets/steel/
  source_cards/
  parameter_register.csv
  process_units.csv
  carriers.csv
  stores.csv
  conversion_factors.csv
  emissions_factors.csv
  costs.csv
  configurations.csv
  validation_targets.csv
```

This matches the current optimisation direction better than placing steel inputs under the hydrogen code tree. It also keeps asset inputs separate from run outputs.

The current task does not create these files. It only freezes the contract.

## Source Hierarchy

Use this hierarchy when promoting data:

1. site-specific public sources and annual reports;
2. Athanasiadis and Badarinath for topology and modelling logic;
3. technology literature for generic ranges;
4. calibrated or assumed values only when flagged and paired with sensitivity tests.

Rules:

- do not treat prior theses as confidential site truth;
- do not treat redacted values as exact plant values;
- do not fill gaps with guessed single-point values when a range or assumption flag is more honest;
- do not promote values straight from notes into approved tables without a candidate-register step.

## Parameter Statuses

Each candidate parameter must have one status:

- `candidate`
- `approved`
- `rejected`
- `sensitivity_only`

Interpretation:

- `candidate`: plausible but not yet frozen for model use;
- `approved`: allowed for model input tables;
- `rejected`: explicitly not used, usually due to weak evidence or contradiction;
- `sensitivity_only`: not a base assumption, but allowed for robustness tests.

## Minimum Fields Per Parameter

Every parameter row must contain:

| Field | Requirement |
|---|---|
| `parameter_id` | Stable machine-readable identifier |
| `parameter_name` | Human-readable name |
| `unit` | Explicit unit |
| `process_id` | Linked process unit if applicable |
| `carrier_id` | Linked carrier if applicable |
| `configuration_id` | Baseline, phase1, or other explicit configuration |
| `value` | Preferred point value if one exists |
| `value_min` | Lower bound if a range is known |
| `value_max` | Upper bound if a range is known |
| `source_id` | Link to source card or source reference |
| `source_location` | Page, table, figure, appendix, or URL fragment |
| `confidence` | High, medium, low, or explicit numeric convention |
| `public_confidential_status` | Public, redacted_public, confidential_unknown, or derived_assumption |
| `status` | Candidate, approved, rejected, or sensitivity_only |
| `notes` | Short explanation or caveat |

If `value` is blank and only a range exists, that is acceptable. The model can later choose a base point from an approved rule, but the uncertainty must stay visible.

## Required Source-Card Fields

Each source card should capture:

| Field | Purpose |
|---|---|
| `source_id` | Stable identifier |
| `title` | Source title |
| `author_or_org` | Origin of the source |
| `year` | Publication year |
| `source_type` | Annual report, thesis, paper, technical note, etc. |
| `site_specificity` | Site-specific, route-specific, technology-generic, or unclear |
| `configuration_relevance` | Baseline BF-BOF, Phase 1 hybrid, both, or unclear |
| `key_claims` | Short bullet summary |
| `known_limits` | Redaction, ambiguity, marketing language, missing units, etc. |
| `promotion_recommendation` | Allow candidate extraction, sensitivity only, or do not promote |

## Approved Model Input Tables

The approved input layer should use small, explicit tables.

### `process_units`

Purpose:

- define unit identity and operating envelope.

Suggested columns:

- `process_id`
- `process_name`
- `configuration_id`
- `route_role`
- `carrier_in_primary`
- `carrier_out_primary`
- `capacity_min`
- `capacity_max`
- `ramp_up_limit`
- `ramp_down_limit`
- `binary_commitment_required`
- `notes`

### `carriers`

Purpose:

- define material and energy carriers consistently.

Suggested columns:

- `carrier_id`
- `carrier_name`
- `carrier_type`
- `unit`
- `aggregation_level`
- `is_storable`
- `notes`

### `stores`

Purpose:

- define explicit buffers rather than implicit free inventory.

Suggested columns:

- `store_id`
- `carrier_id`
- `configuration_id`
- `capacity_min`
- `capacity_max`
- `initial_policy`
- `terminal_policy`
- `charge_limit`
- `discharge_limit`
- `loss_factor`
- `notes`

### `conversion_factors`

Purpose:

- hold process conversion coefficients separately from code.

Suggested columns:

- `conversion_id`
- `process_id`
- `input_carrier_id`
- `output_carrier_id`
- `coefficient`
- `coefficient_unit`
- `configuration_id`
- `status`
- `source_id`

### `emissions_factors`

Purpose:

- track emissions consistently and transparently.

Suggested columns:

- `emission_factor_id`
- `process_id`
- `carrier_id`
- `emission_scope`
- `co2e_factor`
- `unit`
- `configuration_id`
- `source_id`
- `status`

### `costs`

Purpose:

- separate cost assumptions from physics.

Suggested columns:

- `cost_id`
- `cost_name`
- `applies_to`
- `configuration_id`
- `value`
- `unit`
- `indexation_rule`
- `scenario_link`
- `source_id`
- `status`

### `configurations`

Purpose:

- define named asset-policy bundles.

Suggested columns:

- `configuration_id`
- `configuration_name`
- `description`
- `route_scope`
- `active_from_stage`
- `benchmark_role`
- `notes`

### `validation_targets`

Purpose:

- hold external plausibility targets for validation.

Suggested columns:

- `target_id`
- `metric_name`
- `configuration_id`
- `expected_value`
- `expected_min`
- `expected_max`
- `unit`
- `source_id`
- `validation_use`

## Parameter Governance Rules

1. Approved model input parameters must not be hardcoded in Python.
2. Unit conversion should happen in loaders or schema validation, not ad hoc inside optimisation constraints.
3. If public sources disagree, represent the disagreement as:
   - a candidate range;
   - a frozen assumption;
   - or a sensitivity set.
4. If a parameter materially affects flexibility value, it needs:
   - a confidence label;
   - a source link;
   - and a sensitivity decision.
5. Confidential or unknown values must never be backfilled with invented precision.

## Minimum Promotion Checklist

Promote a parameter to approved input only if:

- the unit is explicit;
- the configuration context is explicit;
- the process or carrier context is explicit;
- the source is recorded;
- contradictions are noted;
- confidence is assigned;
- the value is not a hidden personal estimate;
- sensitivity need is declared.

If any of these are missing, keep the parameter in the candidate register.
