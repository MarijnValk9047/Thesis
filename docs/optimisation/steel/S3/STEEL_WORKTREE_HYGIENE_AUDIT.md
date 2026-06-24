# Steel Worktree Hygiene Audit

## Audit Scope And Date

Date: 2026-06-18

Scope: audit-only review of the current dirty worktree for steel S2/S3 provenance risk. No cleanup, revert, delete, move, rename, archive, formatting, commit, source-code edit, input edit, generated-profile edit, or run-folder creation was performed.

The audit used only the command set authorised for this task. The command `git ls-files --others --exclude-standard` reported paths under `scripts/Data/04_Steel_Test_Case/runs/`; those entries were treated only as Git-reported untracked-path evidence. The run directory was not opened or inspected.

Follow-up remediation note: `STEEL_S2_S3_PROVENANCE_REMEDIATION.md` records the bounded S2/S3 provenance review performed after this audit. That report classifies the observed `liquid_steel_smoke_builder.py` change as a path/schema update, keeps S3 fixed profiles as snapshots, and blocks profile regeneration from S2 until the S2 layout migration is explicitly reviewed.

## Commands Run

| Command | Result | Notes |
|---|---:|---|
| `git status --short` | pass | Dirty tracked and untracked files present. |
| `git status --branch --short` | pass | Branch: `steel-milp-asset-config...origin/steel-milp-asset-config`. |
| `git diff --name-status` | pass | 208 tracked changed files. |
| `git diff --stat` | pass | 208 files changed, 2412 insertions, 6752 deletions. |
| `git diff --check` | fail | Whitespace errors: blank line at EOF in multiple steel docs, `steel/governance.py`, and `test_s2_promotion_protocol.py`; many line-ending warnings. |
| `git ls-files --others --exclude-standard` | pass | Large untracked set including current S2/S3 phase-layout files and run artifacts. |
| `python scripts/dev/check_portable_paths.py` | pass | Portable path and secret check passed. |
| `python scripts/Data/04_Steel_Test_Case/validate_s2_input_governance.py` | pass | Structural governance validation passed in candidate-review mode; approved S3 input shells remain empty. |
| `python -m pytest scripts/Data/04_Steel_Test_Case/tests/test_s3_downstream_accounting_closure.py -q` | pass | 6 passed. |
| `python -m pytest scripts/Data/04_Steel_Test_Case/tests/test_s3_wag_c1_route_energy_closure.py -q` | pass | 15 passed. |
| `python -m pytest scripts/Data/04_Steel_Test_Case/tests/test_s3_wag_plant_boundary_gate.py -q` | pass | 5 passed. |

The full test suite was not run because the audit found unresolved S2 frozen-surface drift that should be reviewed before relying on broad diagnostic provenance.

## Dirty-File Table

This table groups every dirty or untracked path pattern reported by the allowed Git commands. Individual entries within a group inherit the classification and recommendation.

| Path or status pattern | Git status | Classification | Likely source/task | Touches frozen S2 behaviour | Affects C0/C1 diagnostics | Safe pending review | Recommendation |
|---|---|---|---|---:|---:|---:|---|
| `data/03_Optimisation/inputs/assets/steel/s2_*` root-level tracked deletions | `D` | `s2_frozen_surface_risk` | Likely S2 phase-layout migration into `steel/S2/` | yes | yes, through S2 provenance and loader expectations | no | Investigate first; commit only with matching migration review. |
| `data/03_Optimisation/inputs/assets/steel/S2/**` untracked phase-layout files | `??` | `s2_frozen_surface_risk` | Likely current S2 governed phase-layout source | yes | yes, if loaders/readiness checks now depend on these paths | conditional | Review with root-level deletions as one S2 migration package. |
| `docs/optimisation/steel/STEEL_S2_*.md` tracked deletions | `D` | `s2_frozen_surface_risk` | Likely doc migration to `docs/optimisation/steel/S2/` | yes, freeze documentation | indirect | no | Pair with new S2 docs and review before commit. |
| `docs/optimisation/steel/S2/**` untracked docs | `??` | `s2_frozen_surface_risk` | S2 freeze / S3-entry documentation migration | yes, freeze documentation | indirect | conditional | Commit only after confirming old/new doc migration is intentional. |
| `scripts/Data/04_Steel_Test_Case/steel/liquid_steel_smoke_builder.py` | `M` | `s2_frozen_surface_risk` | Unknown small tracked edit to frozen S2 builder surface | yes | yes, if C0/C1 profiles derive from smoke outputs | no | Highest-priority review before more diagnostics or commit. |
| `scripts/Data/04_Steel_Test_Case/steel/liquid_steel_smoke_runner.py` | clean in reported status | not dirty | n/a | no dirty runner detected | no | yes | No action from this audit. |
| `scripts/Data/04_Steel_Test_Case/configs/*.yaml` S2 config edits | `M` | `s2_frozen_surface_risk` | S2 smoke/config governance updates | yes | possible | no | Review with S2 migration and smoke-builder change. |
| `scripts/Data/04_Steel_Test_Case/validate_s2_input_governance.py` and S2 governance tests | `M` / `??` | `test_or_validator_change` | S2 governance and phase-layout validation work | not physical behaviour, but validates frozen inputs | indirect | conditional | Commit with S2 governance migration after review. |
| `scripts/Data/04_Steel_Test_Case/steel/governance.py` | `M` | `test_or_validator_change` | Large governance expansion | not direct physical model, but loader/governance-critical | yes, via validation/readiness semantics | conditional | Review carefully; whitespace issue also present. |
| `docs/optimisation/steel/*.md` non-S2 tracked modifications | `M` | `s3_source_or_input_change` | Steel roadmap, freeze, parameter, stage-gate, thesis docs | no direct S2 behaviour | indirect | conditional | Commit as documentation/governance bundle after resolving whitespace. |
| `docs/optimisation/steel/S3/**` untracked S3 docs | `??` | `expected_current_s3_work` / `s3_source_or_input_change` | Recent S3 WAG, C1, evidence, boundary, downstream tasks | no | yes, documents current C0/C1 interpretation | yes | Commit with matching S3 registers/tests after S2 risk review. |
| `docs/optimisation/steel/research_memos/**` additions/modifications | `M` / `??` | `s3_source_or_input_change` | WAG/source-evidence research support | no | indirect; should remain non-primary unless canonicalised | conditional | Commit separately or with evidence bundle; do not treat memos as primary evidence. |
| `data/03_Optimisation/inputs/assets/steel/source_evidence/**` untracked/changed files | `??` / tracked CSV changes | `s3_source_or_input_change` | Canonical source-card and candidate-evidence integration | no | yes, selected coefficients/evidence provenance | conditional | Commit with evidence policy/tests, not alone. |
| `data/03_Optimisation/inputs/assets/steel/S3/**` untracked S3 candidate review, provisional inputs, profiles | `??` | `expected_current_s3_work` / `s3_source_or_input_change` | S3 WAG/C1/DRP-EAF/downstream/boundary work | no direct S2 behaviour | yes | conditional | Commit as S3 data/profile bundle after confirming generated profiles were not produced from risky S2 drift. |
| `data/03_Optimisation/inputs/assets/steel/S3/s3_provisional_dev_input/fixed_profiles/**` | `??` | `s3_source_or_input_change` | Governed fixed profiles for C0/C1/downstream drivers | no direct S2 behaviour | yes, primary diagnostic inputs | conditional | Review provenance; avoid regenerating from dirty S2 until builder risk is resolved. |
| `scripts/Data/04_Steel_Test_Case/steel/wag_*.py` untracked S3 WAG code | `??` | `expected_current_s3_work` / `s3_source_or_input_change` | S3 WAG/profile/diagnostic implementation | no | yes | conditional | Commit with S3 tests and registers after review. |
| `scripts/Data/04_Steel_Test_Case/tests/test_s3_*.py` untracked S3 tests | `??` | `test_or_validator_change` | S3 WAG/C1/boundary/downstream tests | no | yes, safeguards diagnostics | yes | Commit with corresponding S3 implementation and data. |
| `scripts/Data/04_Steel_Test_Case/tests/test_steel_*phase_layout.py` and related phase-layout tests | `??` | `test_or_validator_change` | S2/S3 phase-layout migration tests | yes indirectly | indirect | conditional | Commit with S2/S3 path migration review. |
| `scripts/Data/04_Steel_Test_Case/runs/**` reported by untracked listing | `??` | `generated_or_run_artifact` | Generated run folders/artifacts | no source behaviour | no canonical provenance role | no | Do not commit; cleanup only after explicit user approval. |
| No dirty forecasting/hydrogen/market/stochastic/DA/mFRR/settlement paths observed in allowed output | n/a | `unrelated_project_area` | n/a | no | no | yes | No action from this audit. |
| Any individual file not explicitly named above but under the reported steel S2/S3/doc/data/code/test path groups | `M` / `D` / `??` | covered by nearest group above | Mostly current steel S2/S3 work | depends on group | depends on group | depends on group | Review by grouped commit package. |

## Classification Summary

The dirty worktree appears dominated by an unfinished steel S2/S3 path and governance migration plus recent S3 WAG/C1/downstream implementation artifacts.

- `s2_frozen_surface_risk`: high. Root-level S2 source/input/doc deletions, new untracked S2 phase-layout files, S2 configs, S2 governance tests, and a tracked edit to `liquid_steel_smoke_builder.py` are all present.
- `expected_current_s3_work`: high volume. S3 WAG/C1/evidence/downstream docs, registers, profiles, code, and tests are present and likely correspond to recent tasks.
- `s3_source_or_input_change`: high volume. Source evidence, S3 provisional inputs, fixed profiles, and candidate-review registers affect C0/C1 diagnostic provenance.
- `test_or_validator_change`: substantial. Governance, S2/S3 layout, C1, plant-boundary, and downstream tests exist or changed.
- `generated_or_run_artifact`: present. Git reports untracked entries under `scripts/Data/04_Steel_Test_Case/runs/**`.
- `unrelated_project_area`: none observed from the allowed outputs.
- `unknown_needs_review`: no broad unknown group was required, but individual S2 migration details still need review before commit.

## S2 Freeze-Risk Assessment

Risk status: elevated.

The strongest S2 freeze-risk indicators are:

1. Tracked deletion of old root-level S2 files and docs.
2. Untracked replacement-looking files under `data/03_Optimisation/inputs/assets/steel/S2/**` and `docs/optimisation/steel/S2/**`.
3. Tracked modification of `scripts/Data/04_Steel_Test_Case/steel/liquid_steel_smoke_builder.py`.
4. S2 config and governance-validator/test changes.

This may be a legitimate phase-layout migration rather than physics drift, but it is not safe to classify as harmless without a focused S2 migration review. `liquid_steel_smoke_runner.py` was not dirty in the reported status.

## C0/C1 Diagnostic Provenance Risk Assessment

Risk status: moderate to elevated until S2 drift is reviewed.

The focused S3 tests passed:

- downstream accounting closure: 6 passed;
- C1 route/energy closure: 15 passed;
- plant-boundary gate: 5 passed.

However, C0/C1 diagnostic provenance remains review-sensitive because fixed profiles and S3 diagnostics may have been produced while S2 builder/config/governance surfaces were dirty. The S3 fixed profiles and S3 WAG/C1 registers appear intentional, but they should be committed only after confirming that their source basis did not depend on unintended S2 physical changes.

## Generated-Artifact Risk Assessment

Risk status: high for commit hygiene, low for source behaviour if left untracked.

`git ls-files --others --exclude-standard` reports untracked paths under `scripts/Data/04_Steel_Test_Case/runs/**`. These are generated run artifacts and should not be committed. No run-folder contents were opened by this audit. Cleanup or ignore-file changes should happen only after explicit user approval and a separate review.

No root-level generated outputs were identified from the allowed command summaries, but the untracked list was large and truncated, so commit staging should be explicit and path-scoped.

## Recommended Action Plan

Safe to continue: yes for documentation and audit planning; no for new provenance-sensitive C0/C1 diagnostic claims until S2 frozen-surface changes are reviewed.

Recommended commit grouping:

1. S2 phase-layout and freeze-governance migration: old S2 deletions, new `S2/**` files, S2 docs, S2 configs, S2 governance validator/tests, and any approved `liquid_steel_smoke_builder.py` change.
2. S3 WAG/C1/downstream implementation package: S3 docs, S3 candidate-review registers, provisional S3 inputs, fixed profiles, S3 WAG code, and S3 tests.
3. Source-evidence and evidence-policy package: source-card/candidate-evidence files, Tier-B review files, evidence-use docs, and matching tests.
4. Documentation-only steel roadmap/stage-gate cleanup: broad steel docs with whitespace fixes, if not already included in the above packages.
5. Generated run artifacts: do not commit. Remove or ignore only after explicit user approval.

Files needing user review before commit:

- `scripts/Data/04_Steel_Test_Case/steel/liquid_steel_smoke_builder.py`
- `scripts/Data/04_Steel_Test_Case/steel/governance.py`
- all root-level tracked deleted `data/03_Optimisation/inputs/assets/steel/s2_*` files
- all untracked `data/03_Optimisation/inputs/assets/steel/S2/**` replacements
- all deleted `docs/optimisation/steel/STEEL_S2_*.md` files and untracked `docs/optimisation/steel/S2/**` replacements
- S2 config files under `scripts/Data/04_Steel_Test_Case/configs/`
- generated run artifacts under `scripts/Data/04_Steel_Test_Case/runs/**`

Files that should not be committed:

- `scripts/Data/04_Steel_Test_Case/runs/**`
- any generated diagnostics or notebooks if present in the untracked set

Checks to run after cleanup or commit staging:

1. `git diff --check`
2. `python scripts/dev/check_portable_paths.py`
3. `python scripts/Data/04_Steel_Test_Case/validate_s2_input_governance.py`
4. focused S2 smoke/freeze tests after the S2 migration review
5. focused S3 WAG/C1/downstream tests
6. full steel test suite only after the S2 frozen-surface review is resolved

No cleanup, revert, delete, move, rename, archive, formatting, commit, or run-folder inspection was performed.
