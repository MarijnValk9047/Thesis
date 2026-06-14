# Steel S2 Configuration Tag Mapping

## Purpose

This note records `S2.6a`: the mapping layer between legacy steel configuration terminology and the frozen configuration set established in `STEEL_CONFIGURATION_SCOPE_FREEZE.md`.

The mapping is needed because older Waves `A` through `E`, `S2.5` candidate-review tables, source cards, and topology notes still contain broader labels such as:

- `Phase 1`
- `BF_BOF_plus_DRP_EAF`
- `DRP_EAF`
- `future_configuration`
- `transition_phase`
- route-suffix tags such as `PHASE1_DRP_EAF` or `BASELINE_BF_BOF`

Those legacy terms remain useful as historical or source-context labels, but they must not become uncontrolled implementation branches when `S2.6b` begins.

This memo creates a narrow interpretation rule:

- keep the historical labels visible where they help source traceability;
- map them explicitly to `C0`, `C1`, `C1S`, `C2`, or `postponed_or_blocked`;
- do not let legacy transition wording create new executable plant families.

## Frozen Configuration Targets

The only frozen thesis configuration targets are:

- `C0_current_BF_BOF_reference`
- `C1_phase1_hybrid_BF_BOF_NG_DRP_EAF`
- `C1S_phase1_sensitivity_variants`
- `C2_exogenous_hydrogen_sensitivity_optional_later`

Their roles stay exactly as defined in `STEEL_CONFIGURATION_SCOPE_FREEZE.md`.

## Why The Mapping Is Needed After S2.5e

`S2.5e` froze the configuration scope. `S2.6a` is the cleanup step that makes the older language safe to carry forward.

Without this mapping layer, the repository would still contain enough broad wording to create avoidable ambiguity such as:

- reading any `Phase 1` mention as permission for multiple future plant variants;
- treating `DRP_EAF` or `BF_BOF_plus_DRP_EAF` as separate top-level model branches;
- reviving `Phase 2`, `Phase 3`, hydrogen, CCS, or electrolysis pathway logic inside the structural implementation path;
- confusing topology support with numerical approval.

The mapping therefore protects the implementation path before any topology-skeleton coding starts.

## Allowed Historical Terms Versus Implementation Terms

The following types of older terms may remain in the repository:

- source-context terms taken directly from public material;
- candidate-review configuration labels from earlier Waves;
- route-fragment labels used to describe internal pieces of a frozen configuration;
- historical transition-pathway terms discussed only as blocked or postponed context.

These terms are allowed only for:

- traceability back to source cards or earlier memos;
- candidate-review interpretation;
- route-membership explanation;
- planning notes for future non-executable structural work.

They are not allowed to define new executable implementation branches by themselves.

## Mapping Rule For Legacy Terms

The machine-readable mapping table is:

- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_configuration_tag_mapping.csv`

The mapping rule is:

1. baseline or current-route legacy tags map to `C0_current_BF_BOF_reference`;
2. Phase 1 hybrid future-route legacy tags map to `C1_phase1_hybrid_BF_BOF_NG_DRP_EAF`;
3. legacy sensitivity flags that stay inside the same `C1` topology map to `C1S_phase1_sensitivity_variants`;
4. exogenous hydrogen later-sensitivity labels map to `C2_exogenous_hydrogen_sensitivity_optional_later`;
5. transition-pathway or out-of-scope technology labels map to `postponed_or_blocked`.

## How Common Legacy Terms Should Be Interpreted

### Terms That Map To `C0`

Examples:

- `baseline_bf_bof`
- `BASELINE_BF_BOF`
- `cfg_baseline_bf_bof`

Meaning:

- current-route reference or baseline context only;
- validation or contrast case;
- not the main future flexibility case.

### Terms That Map To `C1`

Examples:

- `phase1_hybrid_bf_bof_plus_dri_eaf`
- `BF_BOF_plus_DRP_EAF`
- `Phase 1`
- `future_configuration`
- `PHASE1_BF_BOF`
- `PHASE1_DRP_EAF`

Meaning:

- all of these are treated as legacy labels for the same frozen main thesis configuration;
- they must not create multiple future-case branches.

Important refinement:

- the frozen thesis term is `C1_phase1_hybrid_BF_BOF_NG_DRP_EAF`;
- older `DRI_EAF` or `DRP_EAF` wording is preserved only as historical shorthand for the Phase 1 route fragment;
- the base `C1` interpretation remains natural-gas-based `DRP`.

### Terms That Map To `C1S`

Examples:

- `flag_high_scrap_eaf_variant`
- `flag_slab_import_enabled`
- `flag_early_coke_closure_exogenous`

Meaning:

- these are sensitivity or variant controls inside the same `C1` topology;
- they do not authorise a separate transition pathway.

### Terms That Map To `C2`

Examples:

- `flag_h2_backbone_available`
- `exogenous_hydrogen_input`

Meaning:

- optional later exogenous-hydrogen sensitivity only;
- same `C1` topology;
- no endogenous hydrogen production, no on-site electrolysis, no hydrogen-storage optimisation.

### Terms That Map To `postponed_or_blocked`

Examples:

- `Phase 2`
- `Phase 3`
- `transition_phase`
- `full_hydrogen`
- `on_site_electrolysis`
- `hydrogen_production_optimisation`
- `hydrogen_storage`
- `hydrogen_infrastructure_optimisation`
- `SAF`
- `CCS`

Meaning:

- historical or strategy context only;
- blocked from the main `S2` to `S9` steel implementation path unless the methodology is reopened explicitly.

## Terms That Must Not Become Implementation Branches

The following must not become top-level executable branches in `S2.6b`:

- generic `Phase 1` versus `Phase 2` versus `Phase 3` pathway trees;
- `full_hydrogen` as a main plant case;
- on-site electrolyser plant variants;
- hydrogen production or storage optimisation branches;
- SAF or CCS pathway-comparison branches;
- generic `future_configuration` labels with no frozen-ID mapping.

The implementation branch keys must come from the frozen register, not from historical wording.

## How The Mapping Prevents Scope Creep

This mapping blocks the common failure mode where transition-pathway language gradually turns into implementation scope.

It does that by forcing every legacy tag into one of three categories:

- one of the frozen thesis configurations;
- a sensitivity-only interpretation inside a frozen configuration;
- postponed or blocked context.

That prevents drift into:

- Phase 2 or Phase 3 plant families;
- full-hydrogen pathway modelling;
- on-site electrolysis and hydrogen-system optimisation;
- broader Athanasiadis-style pathway-comparison logic.

## Topology Evidence Versus Numerical Approval

This mapping note is structural governance only.

It does not:

- approve numerical values;
- create executable topology tables;
- convert historical tags into approved model input rows;
- weaken `S2.5`, `S2.5b`, `S2.5c`, or `S2.5d` restrictions.

Topology evidence may justify:

- route presence;
- route-membership interpretation;
- buffer-class planning;
- implementation sequencing notes.

It does not justify:

- throughput bounds;
- yields;
- inventories;
- executable target values;
- any approved numerical promotion.

## How This Prepares S2.6b

`S2.6a` prepares `S2.6b` by giving the future topology-skeleton work a stable naming contract:

- `C0` and `C1` are the only main structural configurations to plan around;
- `C1S` is the only allowed internal sensitivity family;
- `C2` is later-only and exogenous-hydrogen-only;
- blocked pathway terms stay visible as historical context but cannot drive implementation branching.

That is enough to plan the structural topology skeleton. It is not permission to implement executable files yet.
