# S4/C5 Selective Recovery Plan

## 1. Protection status

- Stash preserved: `stash@{0}` was not popped, dropped, or cleared.
- Protective branch: `backup/stash-s4-c5-activation`.
- Protective tag: `backup/stash-s4-c5-activation-20260707`.
- Bundle backup: external recovery backup folder, file `stash_s4_c5_activation.bundle`.

## 2. Selective worktree

- Worktree: external selective recovery worktree `Thesis_s4_c5_selective`.
- Branch: `recovery/s4-c5-selective`.
- Base: `steel-milp-asset-config`.
- Restore method: selected paths only from `backup/stash-s4-c5-activation` and `backup/stash-s4-c5-activation^3`.
- Extra dependency policy: restored compact S4.4b/S4.4c/S3.4 code dependencies needed for C5 test import closure; no bulky run outputs restored.

## 3. Final selected counts by category

| category | count |
|---|---:|
| source cards and parameter markdowns | 11 |
| S4 governance/recovery docs | 7 |
| C5 model modules | 31 |
| S4 shared code dependencies | 16 |
| C5 runners | 30 |
| S4 shared runners | 14 |
| C5 tests | 31 |
| S4 shared tests | 8 |
| compact S4 input/report artifacts | 836 |
| total status entries after restore | 984 |

## 4. Exclusions, exclusive counts

| excluded group | count |
|---|---:|
| bulky generated run artifacts | 675 |
| solver/cache/raw/figure outputs | 8 |
| old S2/S3 deletes or legacy material | 158 |
| unrelated forecasting/notebook paths | 386 |
| relative paths >= 220 chars | 0 |
| other excluded paths | 0 |
| excluded total | 1227 |

## 5. High-priority file presence

| path | present |
|---|---:|
| $p | true |
| $p | true |
| $p | true |
| $p | true |
| $p | true |
| $p | true |
| $p | true |
| $p | true |
| $p | true |

## 6. Checks

``text
portable_paths	0	external selective recovery backup: check_final_portable_paths.txt
git_diff_check	0	external selective recovery backup: check_final_git_diff_check.txt
pytest_c5p_a	0	external selective recovery backup: check_final_pytest_c5p_a.txt
pytest_anchor_route	0	external selective recovery backup: check_final_pytest_anchor_route.txt
``

## 7. Proposed commit batches, no commits made

| batch | content | rationale | caveat |
|---|---|---|---|
| Batch 1 | source cards and parameter markdowns | source evidence and candidate parameter governance | review thesis usability labels |
| Batch 2 | S4/C5 governance docs | stage context, audits, decision registers | exclude generated-heavy docs if any |
| Batch 3 | S4 shared dependencies and C5 model modules | executable implementation | keep S4 shared deps separate from plant stages if preferred |
| Batch 4 | S4/C5 runners | reproduction entrypoints | verify no broad output side effects |
| Batch 5 | S4/C5 tests | regression protection | keep passing targeted tests with modules |
| Batch 6 | compact input/report artifacts only if approved | compact provenance | review output policy before committing 836 artifacts |

## 8. Explicit exclusions

- Do not commit bulky generated artifacts.
- Do not commit long-path outputs or generated run folders.
- Do not commit old S2/S3 deletions without review.
- Do not commit unrelated activation-module, forecasting, or notebook changes.
- Do not commit all recovered files blindly.

## 9. Risks and next action

- This selective recovery is intentionally not a full stash apply.
- Compact S4 artifacts are numerous and need output-policy review.
- Next action: review batches, then commit selectively only after user approval.
