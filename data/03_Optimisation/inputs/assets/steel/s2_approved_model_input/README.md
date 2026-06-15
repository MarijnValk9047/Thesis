# S2 Approved Model Input

## Purpose

This folder is the future deterministic `S2` approved-input surface for the steel test case.

It exists so the deterministic `S2` builder contract has a governed destination for future approved rows. It does not contain approved rows yet.

## Current State

All CSV files in this folder are currently empty shell tables with headers only.

They are empty because:

- candidate-review values have not been promoted;
- unit, sign, endpoint, and annual-to-hourly blockers are still open;
- no deterministic `S2` numerical row has passed the required approval gates.

These tables are therefore not yet thesis-usable or executable.

## Promotion Rule

Candidate-review rows must be reviewed before promotion.

No value may be copied from Deepsearch F, any candidate-review CSV, or any other candidate source into this folder without explicit approval.

## Minimum Metadata For Any Future Approved Row

Any future non-empty row must include at least:

- `source_ids`;
- explicit units;
- approval metadata;
- explicit `approval_status`;
- explicit `executable_status`;
- explicit `thesis_usability`;
- reviewer traceability fields such as `approved_by` and `approval_date`.

## Constraint And Translation Guards

Validation targets cannot be used as constraints.

Annual values cannot become hourly caps without an explicitly approved annual-to-hourly translation method.

That applies to public annual anchors, target anchors, downstream sink anchors, and any annual throughput reference that might otherwise be mistaken for a live hourly cap.

## Folder Meaning

This folder creates table surfaces only. It does not approve content, does not create executable model parameters, and does not reopen later-stage scope.

## Promotion Governance

No approved-input table may be populated without the promotion protocol in `docs/optimisation/steel/STEEL_S2_APPROVED_INPUT_PROMOTION_PROTOCOL.md`.

Codex cannot approve values. Explicit user or thesis-reviewer promotion is required before any row enters this folder.

Approved and executable statuses are separate. A reviewed row may only become executable after a separate executable gate is cleared.

Promotion decision records must be retained in `s2_promotion_decision_template.csv` or its future populated successor.
