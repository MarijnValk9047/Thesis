# S3 Evidence Use And Thesis Assumption Policy

## Purpose

This policy revises the S3 evidence rules for the steel test case.

The previous S3 source-card and candidate-evidence governance was intentionally strict while the project was still defining the S3 accounting boundary. That strictness correctly blocked unsourced values, redacted values, research-memo-only values, and hidden placeholders. It also made the implementation stage too narrow: public, traceable, reasonable secondary or generic technology values could not be used even when no more specific public Tata Steel IJmuiden data is expected.

The revised policy keeps the blocking rules, but separates:

- source evidence existence;
- development-model usability;
- final thesis model usability as a declared assumption;
- thesis validation or claim usability;
- eligibility for a Tata-exact claim.

The key rule is:

```text
final thesis model assumption != exact Tata Steel IJmuiden truth
final thesis model assumption != validation target
final thesis model assumption != approved empirical fact
```

Legacy `thesis_usability=false` remains valid for rows that are not thesis-grade facts or validation claims. A row may later become eligible as a `thesis_model_assumption` only through the separate fields and policy files introduced for S3 assumption use. This policy does not promote or select any DRP, EAF, WAG, cost, emissions, route-share, or tariff coefficient.

## Governed Policy Files

The controlled vocabulary and acceptance rules are stored in:

- `data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review/s3_evidence_use_tier_vocabulary.csv`
- `data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review/s3_model_input_use_status_vocabulary.csv`
- `data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review/s3_thesis_assumption_acceptance_policy.csv`
- `data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review/s3_material_parameter_sensitivity_mandate.csv`

## Evidence Tiers

### Tier A - primary_public_site_specific

Examples include public permits, environmental documents, official Tata or project documents, government documents, annual reports, and public sources with direct site-specific values.

Allowed use:

- development model;
- final thesis model assumption;
- possible validation or calibration target if the boundary matches.

Requirements:

- source card;
- complete locator;
- unit and basis;
- limitations.

Tier A is the only tier that can ever support a Tata-exact public claim, and only when the boundary, unit, and basis match the claim.

### Tier B - public_secondary_literature_derived

Examples include public thesis tables, peer-reviewed values summarised in a public thesis, and literature-derived parameters in public reports.

Allowed use:

- development model;
- final thesis model assumption with caveat;
- sensitivity review if material.

Requirements:

- source card for the immediate public source;
- page, table, or section locator;
- original unit and basis;
- explicit caveat if the underlying source is not independently source-carded;
- `tata_exact_claim_allowed=false`.

Tier B values must never be presented as exact Tata operation or validation truth.

### Tier C - generic_technology_public

Examples include JRC BREF, IEA, worldsteel, MIDREX or ENERGIRON public documents, vendor literature, peer-reviewed technology references, and public technology ranges.

Allowed use:

- development model;
- final thesis model assumption;
- sensitivity review if the range is broad or the parameter is materially important.

Requirements:

- source card;
- locator;
- technology applicability note;
- original unit and basis.

Tier C values can support a defensible technology assumption, not a Tata-exact fact.

### Tier D - user_selected_scenario_policy

Examples include C1 route-share scenarios inside a feasible envelope, central/low/high policy assumptions, and scenario design choices.

Allowed use:

- development model;
- final thesis model scenario or sensitivity;
- not empirical validation.

Requirements:

- explicit user decision record;
- scenario or policy basis;
- feasible-envelope or modelling rationale where applicable;
- `tata_exact_claim_allowed=false`;
- `technical_source_required=false` only for the scenario choice itself.

Tier D can define what scenario is tested. It cannot prove that the selected scenario is real plant operation.

### Tier E - derived_from_source_backed_inputs

Examples include pellets per tonne steel derived from pellets-to-DRI and DRI-to-steel efficiencies, or MWh per tonne steel derived from MWh per tonne DRI.

Allowed use:

- same use permission as the weakest input used in the derivation.

Requirements:

- formula;
- input parameter IDs;
- unit conversion;
- no hidden assumptions;
- tests for conversion.

Derived values inherit the weakest evidence tier, sensitivity obligation, and limitations from their inputs.

### Tier F - validation_target_only

Examples include public annual production anchors, public emissions reduction targets, WAG-to-Vattenfall reduction statements, and plant-scale electricity anchors with boundary mismatch.

Allowed use:

- validation or plausibility context;
- not executable hourly input unless translated through a separate assumption row.

Tier F is not a shortcut for constraints, hourly caps, or executable coefficients.

### Tier X - blocked

Examples include:

- research memo only;
- AI-generated value;
- generated run output used as source evidence;
- missing locator where a locator is required;
- confidential-only value;
- redacted value treated as exact public truth;
- hidden zero or placeholder;
- incompatible unit or basis without conversion.

Allowed use:

- none.

## Model Use Statuses

The S3 policy recognises:

- `blocked`
- `development_only`
- `thesis_model_assumption`
- `thesis_model_sensitivity`
- `validation_target_only`
- `derived_assumption`

`thesis_model_assumption` and `thesis_model_sensitivity` allow executable final-thesis use only when the evidence tier, source-card requirements, locator requirements, unit and basis requirements, limitation fields, and sensitivity rules are satisfied.

## Required Use-Status Fields

S3 assumption review surfaces should use the following fields when a row is being considered for final thesis model use:

- `evidence_tier`
- `source_locator_quality`
- `model_use_status`
- `development_model_eligible`
- `thesis_model_assumption_eligible`
- `thesis_validation_claim_eligible`
- `tata_exact_claim_allowed`
- `sensitivity_required`
- `sensitivity_class`
- `basis_conversion_required`
- `limitations_required`

These fields supplement legacy `thesis_usability`. They do not automatically convert legacy rows to thesis-grade facts.

## Sensitivity Mandate

Central values may be used in the final thesis model if they are source-backed, labelled, and accepted under this policy. Material uncertain values must also be included in a sensitivity plan, or have an explicit documented deferral reason before final thesis use.

The sensitivity mandate applies at minimum to:

- C1 route share;
- DRP natural-gas consumption;
- DRP electricity consumption;
- EAF electricity consumption;
- DRI, pellets, and yield conversion;
- scrap share;
- WAG generation yields;
- WAG LHV values;
- coking and coke coefficients;
- WAG allocation or conversion efficiency;
- site or component electricity boundary;
- natural-gas CO2 factor;
- WAG CO2 factors;
- energy price assumptions;
- ETS cost assumptions when later introduced.

No single secondary or generic value may be presented as exact Tata operation.

## Application To C1 DRP/EAF And WAG Assumptions

The C1 DRP/EAF energy coefficients may later be accepted as final thesis model assumptions if they are Tier A, B, C, or E and satisfy locator, unit, basis, limitation, conversion, and sensitivity requirements. Tier B and Tier C DRP/EAF values must be labelled as public secondary or generic technology assumptions, not Tata-exact validation facts.

The C1 route-share scenarios may later be treated as Tier D scenario policy assumptions if they remain explicitly user selected, inside or near the governed feasible envelope, and not empirical validation claims.

WAG generation, LHV, demand, allocation, conversion-efficiency, and emissions assumptions may later use Tier A, B, C, or E evidence as central thesis assumptions with caveats and sensitivity review. Research memos, redacted source snippets, generated diagnostics, or missing-locator values remain blocked.

## What Remains Forbidden

This policy does not allow:

- unsourced values;
- AI-generated parameters;
- research-memo-only numerical values;
- generated run folders as source evidence;
- hidden zero or placeholder values;
- confidential or redacted values treated as exact public truth;
- public secondary or generic values labelled as Tata-exact validation;
- material Tier B, C, D, or E assumptions without sensitivity review or explicit deferral;
- missing units or basis;
- incompatible basis conversions without a formula and conversion note;
- automatic population of approved final input rows;
- day-ahead, bidding, stochastic, CVaR, mFRR, route-optimisation, revenue, ETS-cost, or tariff logic.

