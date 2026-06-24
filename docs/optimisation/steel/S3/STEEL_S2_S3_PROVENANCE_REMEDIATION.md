# Steel S2/S3 Provenance Remediation

## Purpose And Date

Date: 2026-06-18

Purpose: document the controlled review of the dirty S2 frozen-surface state after S3.0e-a static accounting. This remediation records what can be safely classified, what remains user-review risk, and which git safety governance rule was strengthened.

This task did not stage, commit, push, reset, restore, checkout, clean, delete, revert, move, archive, or inspect run-folder contents.

## Commands Run

Allowed summary and validation commands:

| Command | Result | Notes |
|---|---:|---|
| `git status --short` | pass | Dirty S2/S3/docs/code/test files and untracked run artifacts still present. |
| `git status --branch --short` | pass | Branch remains `steel-milp-asset-config...origin/steel-milp-asset-config`. |
| `git diff --name-status` | pass | Confirms root-level S2 deletions plus replacement-looking untracked `S2/` layout. |
| `git diff --stat` | pass | 208 tracked files changed before this remediation. |
| `git diff --check` | fail before remediation | Reported new blank line at EOF in steel docs, `steel/governance.py`, and `test_s2_promotion_protocol.py`; line-ending warnings also appeared. |
| `git ls-files --others --exclude-standard` | pass | Confirms untracked S2/S3 layout files and `scripts/Data/04_Steel_Test_Case/runs/` paths; run contents were not inspected. |

Targeted bounded diffs were inspected for:

- `scripts/Data/04_Steel_Test_Case/steel/liquid_steel_smoke_builder.py`;
- `scripts/Data/04_Steel_Test_Case/configs/*.yaml` S2 smoke configs;
- `scripts/Data/04_Steel_Test_Case/validate_s2_input_governance.py`;
- `scripts/Data/04_Steel_Test_Case/tests/test_s2_approved_input_governance.py`;
- `scripts/Data/04_Steel_Test_Case/steel/governance.py`.

## S2 Dirty-File Classification

| File or group | Classification | Assessment |
|---|---|---|
| Root-level tracked deletions under `data/03_Optimisation/inputs/assets/steel/s2_approved_model_input/`, `s2_candidate_mapping/`, `s2_candidate_review/`, `s2_provisional_dev_input/`, `s2_schema/`, `s2_toy_scaffold/`, and S2/S3 candidate CSVs | `accepted_s2_layout_migration_candidate` | Pattern matches migration from root-level `steel/s2_*` folders into `steel/S2/s2_*`. Treat as migration candidate, not automatically approved. |
| Untracked replacements under `data/03_Optimisation/inputs/assets/steel/S2/**` | `accepted_s2_layout_migration_candidate` | Replacement-looking phase-layout source. User review still required before commit because files are untracked and not byte-reviewed here. |
| Root-level tracked deletions of `docs/optimisation/steel/STEEL_S2_*.md`, S2 packets, S2 memos, and matching untracked replacements under `docs/optimisation/steel/S2/**` | `accepted_s2_layout_migration_candidate` plus `s2_documentation_or_register_change` | Looks like S2 documentation phase-layout migration. No executable physical model effect, but freeze documentation should be reviewed as one migration package. |
| `scripts/Data/04_Steel_Test_Case/configs/base_s2_toy_smoke.yaml` and related S2 smoke configs | `s2_builder_path_or_schema_update` | Diff only changes `table_root` from root-level `steel/s2_toy_scaffold` to `steel/S2/s2_toy_scaffold`. No target, bound, route, solver, or model setting change observed. |
| `scripts/Data/04_Steel_Test_Case/validate_s2_input_governance.py` | `s2_builder_path_or_schema_update` | Diff only changes default S2 schema/mapping/review/approved input roots to the `steel/S2/` layout. |
| `scripts/Data/04_Steel_Test_Case/tests/test_s2_approved_input_governance.py` | `s2_builder_path_or_schema_update` | Path constants move to `steel/S2/`; expected governance row counts expand to include S2.12/S3 accounting checks. No physical model logic. |
| Other dirty S2 tests under `scripts/Data/04_Steel_Test_Case/tests/test_s2_*.py` | `s2_builder_path_or_schema_update` | `git diff --stat` indicates small path/count changes across tests. Not fully line-reviewed here; user review still required before commit. |
| `scripts/Data/04_Steel_Test_Case/steel/governance.py` | `s2_builder_path_or_schema_update` | Bounded diff shows new S2.12/S3 register schema specifications and governance validation surfaces. This is loader/governance-critical but not physical MILP logic. |
| `scripts/Data/04_Steel_Test_Case/steel/liquid_steel_smoke_runner.py` | not dirty | No review needed in this task. |
| `scripts/Data/04_Steel_Test_Case/runs/**` | generated/run artifact | Exists as untracked output. Not source evidence and not commit-eligible by default. Contents were not inspected. |

## `liquid_steel_smoke_builder.py` Assessment

Bounded diff review found only default path-root changes:

- `steel/s2_provisional_dev_input` to `steel/S2/s2_provisional_dev_input`;
- `steel/s2_approved_model_input` to `steel/S2/s2_approved_model_input`;
- `steel/s2_candidate_review` to `steel/S2/s2_candidate_review`.

No changes were observed to:

- physical constraints;
- route topology;
- objective;
- process bounds;
- conversion coefficients;
- inventory equations;
- terminal inventory policy;
- production target logic;
- solver settings.

Classification: `s2_builder_path_or_schema_update`.

## S2 Physical Logic Decision

Based on the bounded inspected diffs, S2 physical logic does not appear changed by the reviewed dirty builder/config/governance surfaces.

Residual caveat: this is a remediation classification, not a full byte-for-byte approval of every untracked replacement file under `data/03_Optimisation/inputs/assets/steel/S2/**` and `docs/optimisation/steel/S2/**`.

Follow-up decision: `docs/optimisation/steel/S2/STEEL_S2_LAYOUT_MIGRATION_ACCEPTANCE_AND_REFREEZE.md` accepts the migration as a non-physical layout/schema migration, re-freezes S2 under `steel/S2/**`, and allows S3 profile regeneration only after rerunning the S2/S3 validation checks.

## S3 Fixed Profile Treatment

S3 fixed profiles may continue to be treated as current governed snapshots for downstream S3 accounting and diagnostics, with caveats.

Profile regeneration from S2 remains blocked until the S2 layout migration and governance changes are explicitly reviewed and accepted. The current S3 snapshots should not be regenerated from S2 during the unresolved migration state.

## Whitespace And EOF Remediation

`git diff --check` initially reported blank-line-at-EOF issues in steel documentation, `steel/governance.py`, and `test_s2_promotion_protocol.py`.

Safe remediation policy:

- safe to fix documentation EOF whitespace;
- safe to fix EOF whitespace in governance loader/test files;
- no physical S2 model logic may be changed for whitespace cleanup.

Line-ending warnings from Git are noted separately and are not treated as physical-model risk.

## Git Safety Policy Update

`AGENTS.md` now states that Codex must not stage, commit, or push unless the user explicitly asks for that exact git operation in the current prompt.

The policy also requires:

- proposed commit grouping and confirmation before commits unless the prompt explicitly says to commit immediately;
- no push unless the current prompt explicitly says to push;
- explicit user approval for cleanup, revert, delete, reset, restore, checkout, clean, and `git rm`;
- generated run folders and bulky artifacts must not be committed by default.

## Remaining User-Review Items

Before any commit:

1. Review and approve the S2 phase-layout migration as one package: root-level `s2_*` deletions plus `steel/S2/**` replacements.
2. Review `steel/governance.py` schema expansion because it is governance-critical.
3. Review all changed S2 tests and validator row-count expectations as a migration package.
4. Confirm S3 fixed-profile provenance remains acceptable as snapshot evidence and is not regenerated from S2 yet.
5. Keep `scripts/Data/04_Steel_Test_Case/runs/**` uncommitted unless a separate explicit generated-artifact policy exception is approved.

## Explicit No-Git-Operation Statement

No `git add` was run.
No `git commit` was run.
No `git push` was run.
No `git reset`, `git restore`, `git checkout --`, `git clean`, `git rm`, cleanup, delete, revert, move, or archive operation was performed.
