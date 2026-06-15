# Steel S2 Approved Input Promotion Protocol

## Purpose

This memo defines the governance protocol for moving future rows from `s2_candidate_review` into `s2_approved_model_input`.

It creates review and approval rules only. It does not approve any numerical value, populate any approved-input table, create executable model behaviour, or reopen later steel stages.

## Status Boundary

The current status remains:

- approved rows = `0`;
- thesis-grade numerical rows = `0`;
- executable candidate/input rows = `0`;
- all approved-input shell tables remain empty;
- approval and executable status are both still blocked for steel `S2` numerical inputs.

## Four Distinct Row States

These states must stay separate:

1. `candidate-review`:
   row is evidence-normalised, reviewable, and non-executable.
2. `approved assumption`:
   row has an explicit reviewer decision recorded for thesis use, but is still not automatically executable.
3. `thesis-grade numerical input`:
   row is accepted for thesis-grade quantitative use within stated limits.
4. `executable model input`:
   row has passed a separate executable gate and may later be consumed by a controlled builder.

Structural support is not numerical approval. Numerical approval is not executable status.

## Approval Authority

Codex may prepare review packets but may not approve rows.

Codex may also check completeness, validate metadata, and surface blockers. Codex may not select final values, decide promotions, or populate `s2_approved_model_input` without an explicit user or thesis-review decision.

Explicit user/thesis-review approval is required before any row may enter `s2_approved_model_input`.

Every promoted row requires an explicit user/thesis-review approval record. No silent promotion is allowed.

## Approval Gate And Executable Gate

Approval and executable status are separate gates.

- A row may be approved for thesis use and still remain `non_executable`.
- A row may not become executable merely because it appears plausible or has strong evidence.
- Executable use requires a later, separate gate confirming scope, consistency, and implementation readiness.

## Minimum Metadata For Any Future Promoted Row

Any future promoted row must carry, at minimum:

- stable row or parameter ID;
- target approved-input table;
- configuration applicability for `C0` and or `C1`;
- `C1S` overlay applicability where relevant;
- unit and basis;
- sign convention or explicit direction convention;
- source IDs;
- source label such as `public`, `confidential`, `vendor`, `academic`, or `assumption_only`;
- evidence-strength label;
- sensitivity classification;
- approval decision metadata;
- thesis-use status;
- executable status;
- conditions, caveats, and blockers if any remain.

Rows missing this metadata must not be promoted.

## Source-Card Requirement

Promotion requires traceable source support through the governed source-card system. A future row must not be promoted unless its supporting source cards are complete enough to identify origin, scope, public-reportability status, and intended modelling use.

If the only support is weak, indirect, vendor-context, annual-anchor, or assumption-only evidence, the row must be deferred, rejected, or promoted only with an explicit sensitivity requirement.

## Evidence-Strength Requirement

Evidence must be classified deliberately. Stronger evidence is needed for rows that directly shape flexibility value, feasibility, or target fulfilment.

Evidence labels should distinguish at least:

- public source support;
- academic support;
- vendor-context support;
- confidential or internal support if later available;
- assumption-only support.

Deepsearch F candidates may be used as review evidence only. They may not be copied into approved-input tables as direct executable or thesis-grade inputs without explicit reviewer approval.

## Unit, Sign, And Convention Requirement

No row may be promoted unless its unit basis and sign or direction convention are explicit and consistent with `STEEL_S2_UNIT_SIGN_AND_ENDPOINT_CONVENTIONS.md`.

This includes:

- throughput bounds;
- coefficient direction;
- inventory state semantics;
- endpoint-rule semantics;
- horizon-total versus per-hour target basis.

## Configuration Applicability

Promotion must state where a row applies:

- `C0_current_BF_BOF_reference`;
- `C1_phase1_hybrid_BF_BOF_NG_DRP_EAF`;
- `C1S_phase1_sensitivity_variants` as an overlay only;
- `C2_exogenous_hydrogen_sensitivity_optional_later` only where explicitly allowed later.

`C1S` may modify reviewed assumptions inside `C1`, but must not create a separate pathway family. `C2` remains optional later and exogenous only. It must not silently approve on-site electrolysis, hydrogen storage, or endogenous hydrogen production.

## Validation Targets Stay Separate

Validation targets must remain separate from live constraints.

- A validation target may be approved as a reporting or plausibility anchor.
- It may not become a process bound, production target, inventory rule, or other live constraint without reclassification and fresh review.
- Annual public anchors must not be used as hourly constraints by default.

## Annual Public Anchors

Any annual public anchor that could influence hourly steel behaviour requires explicit annual-to-hourly translation approval before hourly use.

That approval must identify:

- the translation method;
- the operating-envelope logic;
- why the translation is suitable for the specific category;
- which uncertainty remains and whether sensitivity treatment is required.

Without this, annual anchors remain validation-only or evidence-only.

## CYC50 Boundary

`CYC50` may be reviewed as endpoint-policy logic without silently approving buffer capacities.

Allowed interpretation:

- initial inventory linked to an explicit policy basis;
- terminal inventory returns to the same policy basis;
- anti-fake-flexibility endpoint logic is preserved.

Not allowed:

- treating endpoint-policy support as approval of a numerical capacity;
- treating policy review as approval of exact opening or closing inventory quantities.

## Uncertainty And Sensitivity

If evidence is uncertain, indirect, or materially affects flexibility value, the row must be marked `sensitivity_required` unless the reviewer explicitly decides otherwise.

High-uncertainty rows should be deferred or approved only with narrow applicability and explicit caveats.

## Rejection And Deferral

Rejection and deferral are valid outcomes and must be recorded.

Typical reasons include:

- incomplete source cards;
- ambiguous unit or sign basis;
- annual anchor with no approved hourly translation;
- configuration ambiguity;
- weak vendor transferability;
- uncertainty too high for thesis-grade base use;
- category still better treated as validation-only or sensitivity-only.

## Future Promotion Packets

Future promotion packets should be generated per category and should contain:

- candidate row IDs under review;
- source-card links;
- unit and sign review summary;
- configuration applicability summary;
- validation-only versus live-input distinction;
- annual-to-hourly blocker status where relevant;
- reviewer questions;
- recommended decision options such as approve non-executable, defer, reject, or sensitivity-only.

Codex may prepare those packets and completeness checks. Codex may not decide the final promotion outcome.

## Recommended Review Order

Use a cautious order:

1. inventory endpoint policy / `CYC50`;
2. terminal inventory rules;
3. initial inventory rules;
4. strong conversion coefficients;
5. process bounds;
6. store capacities;
7. production targets.

This order keeps endpoint logic ahead of high-impact flexibility parameters.

## Safer Early Categories

Safer early review categories are:

- endpoint-policy logic;
- terminal-rule type logic;
- opening-state rule basis;
- strong, directionally clear conversion-coefficient candidates with explicit source traceability;
- run-reporting requirements.

These are still non-executable until separately gated.

## High-Risk Categories

Do not promote early:

- store capacities with major flexibility-value impact;
- process bounds derived from annual public anchors without approved hourly translation;
- production targets with unclear target basis;
- values supported only by weak vendor transfer or order-of-magnitude public anchors;
- any row that mixes validation-anchor logic with live-constraint use.

## Decision Recording

Every future promotion decision must be recorded in the governed decision template. Promotion records must be retained even for rejected or deferred rows so that later reviewers can see what was considered and why it was not promoted.

## Operating Rule

Until an explicit reviewer decision is provided, `s2_approved_model_input` remains empty and non-executable.
