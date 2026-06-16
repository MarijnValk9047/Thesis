# S2 Provisional Development Input Pack

## Purpose

This folder is a provisional deterministic `S2` development and smoke-testing input pack.

It exists to separate development-only scaffolding from the still-empty thesis-governed `s2_approved_model_input` surface.

## Status Boundary

This pack is not thesis-grade.

This pack is not approved.

This pack must not be cited as final model input.

This pack is separate from `s2_approved_model_input`.

Future LP outputs that consume this pack must report `thesis_usability=false`.

All values and structures in this folder require later review before any thesis use.

## What This Pack May Contain

- provisional development-only rows
- non-executable placeholders where required values are still unresolved
- explicit policy-derived formulas such as `CYC50` opening and terminal logic
- explicit translation formulas that remain non-executable until hourly review is complete
- validation anchors that remain outside executable constraints

## What This Pack Must Not Be Treated As

- an approved-input surface
- a thesis-grade numerical surface
- a silent promotion path into `s2_approved_model_input`
- evidence that annual public anchors may be used as hourly caps
- evidence that route-specific planning anchors may become base production constraints

## Governance Rules

- `approval_status=provisional_development_only` means development-only and not approved
- `approval_status=missing_required_dev_value` means a required value is still unresolved
- `executable_status=dev_executable_only` is allowed only for development-only rows with explicit reviewer-decision metadata
- `thesis_usability` must remain `false` for every row
- no row in this folder may have `approval_status=approved`
- no row in this folder may be copied into `s2_approved_model_input` without a separate later review and promotion decision

## Constraint And Translation Guards

Annual public anchors cannot become hourly caps without an explicit reviewed translation basis.

Validation targets must not drive constraints.

`CYC50` is endpoint policy only and not buffer-capacity approval.

Hot slab `WIP` must not be treated as a strategic multi-hour or multi-day flexibility store.

Production targets must remain route-neutral in the base case.
