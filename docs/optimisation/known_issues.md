# Known Issues

## Purpose

This file centralises the main optimisation caveats and blockers that are currently documented across the repository.

It is not a run-by-run failure log. It is a stable register of issues that materially affect method interpretation, fairness of comparison, or cleanup policy.

## 1. Scenario Support Mismatch Across Hourly Artifacts

This is the main current thesis blocker.

At present, the repository documentation indicates that the desired three-model hourly comparison cannot yet be completed cleanly because the available thesis-grade scenario artifacts do not expose the same delivery support window.

Implication:

- the blocker is upstream support mismatch, not lack of optimisation code or solver infrastructure;
- any final hourly three-model result must first resolve support alignment.

## 2. Scenario Quality Is Still Caveated

Scenario generation is implemented and can support exploratory optimisation work, but the current doc layer still treats scenario quality as methodologically caveated.

Known caveat themes:

- undercoverage;
- tail weakness;
- incomplete robustness for final downside-risk claims.

Implication:

- exploratory stochastic optimisation and CVaR work can proceed with explicit warnings;
- final robust-risk claims should not ignore scenario-quality limitations.

## 3. LEAR Strict Support Mismatch

LEAR Strict remains methodologically important, but it also appears in the current documentation as a source of support-window mismatch and quarter-hour anchor/routing complexity.

Implication:

- LEAR Strict should not be treated as a disposable side branch;
- at the same time, comparisons involving LEAR Strict require explicit support checks and careful interpretation.

## 4. Quarter-Hour Truth-Type Caveat

Quarter-hour work is split between:

- observed-market quarter-hour evaluation;
- counterfactual / synthetic quarter-hour path support for downstream work.

This is not a cosmetic distinction.

Implication:

- observed-market quarter-hour results must be reported as observed-target evidence;
- counterfactual quarter-hour results must stay labelled synthetic or counterfactual;
- hourly-vs-quarter-hour claims are not clean if period support and truth type differ.

## 5. CVaR Branch Versus Command-Centre Default

CVaR exists in the repository as a serious implementation branch, but it is not yet the hardened command-centre default.

Current default:

- risk-neutral selected-week hydrogen path.

Implication:

- future documentation and cleanup must preserve the difference between implemented branch and hardened default execution surface;
- users should not assume command-centre CVaR is already the standard path.

## 6. Selected-Week Governance Caveat

Selected-week governance is now split cleanly into validation and test files, but legacy mixed-file runs still exist.

Implication:

- mixed-file runs remain useful as exploratory or development evidence;
- they are not official validation/test evidence unless rerun under the split-policy workflow;
- `winter_proxy` must not be presented as a real winter seasonal result.

## 7. Tracked Cleaned-Data Policy Is Still Unresolved

`data/01_cleaned/` is still a mixed tree of:

- baseline input candidates;
- generated derivatives;
- diagnostics.

Implication:

- tracked cleaned-data changes should not be batch-restored or batch-cleaned;
- a family-by-family policy is still required before any destructive cleanup decisions are made there.

## 8. Documentation Placement Is Not Fully Consolidated

The repository already has a strong optimisation governance layer, but some expected central docs were missing until this cleanup/documentation pass, and some high-value hydrogen reports still live outside `docs/optimisation/`.

There is also a current path mismatch around the visual policy:

- active file: `VISUALISATION.md`
- expected optimisation-doc path in `AGENTS.md`: `docs/optimisation/VISUALISATION.md`

Implication:

- cleanup should not remove or destabilise those documents before the placement question is resolved cleanly.
