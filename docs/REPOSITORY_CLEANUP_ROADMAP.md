# Repository Cleanup Roadmap

## 1. Purpose Of This Repository

This repository is the working record of a thesis pipeline that started with electricity-market data preparation and forecasting, and is now being used to support an optimisation workstream. At thesis level, it is trying to do five connected things.

First, it builds cleaned and structured input tables from raw ENTSO-E and DA market data. Second, it develops day-ahead electricity price forecasting models, mainly for the Dutch market, under a fixed split and rolling-origin methodology. Third, it extends that forecasting work into scenario generation, including diagnostics about scenario quality and support coverage. Fourth, it uses those forecasts and scenarios as inputs to a hydrogen optimisation test case with bidding, clearing, redispatch, benchmarks, and later risk aversion. Fifth, it is meant to evolve from that hydrogen case toward a more complex industrial flexibility model, ultimately including a steel-plant style MILP extension.

The repository therefore serves two roles at once: it is a source-code repository, and it is also a research lineage record. Cleanup should preserve both.

## 2. The Research Red Line

The main research progression in this repository is not random. It follows a fairly clear red line.

It begins with data import and cleaning. The cleaned hourly DA price, load, and generation tables are the upstream foundation for everything that follows. The cleaning layer also encodes important methodological choices such as UTC-internal timestamps, known-at logic, and the difference between observed truth and forecastable features.

From there, the work moves into hourly day-ahead forecasting. That work matured into a more standardised package under `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/`, with shared loading, scheduling, evaluation, and reporting logic.

Within hourly forecasting, the repository preserves an `FS0` to `FS3` ladder. `FS0` keeps the naive reference point. `FS1` establishes the endogenous benchmark layer. `FS2` is where more serious shortlisting starts. `FS3` expands the feature set and becomes the main place where exogenous-feature logic, pruning, and decision-relevant comparison work were developed. These stages matter historically because they explain how the final model shortlist emerged and why some model or feature families were dropped.

That leads into model comparison and model drop-out logic. The thesis did not simply search for the smallest MAE. It also asked which models remained competitive under the fixed split, which were robust enough to carry forward, and which should be demoted even if they were once plausible.

The LEAR Strict and Lago branch is an important side branch rather than junk. It covers LEAR Strict support questions, Lago-style six-year benchmark work, routing and support diagnostics, and a bounded May 2026 campaign that explains several later repository decisions. Even when this branch is not the canonical current path, it still documents why some comparison routes and quarter-hour extensions became awkward or non-default.

Quarter-hour and `D+4` attempts form another important branch. The repo contains both canonical quarter-hour runners and earlier phase-based exploration. This work matters because it preserves the observed-versus-counterfactual distinction, the quarter-hour truth-type caveat, and the practical limits of extending the thesis from hourly `D_only` work toward broader horizons and finer granularity.

Scenario generation then becomes the bridge between forecasting and optimisation. It is implemented in code and is methodologically in scope, but the repository also records a serious warning: scenario support mismatch and undercoverage are still active caveats. That means scenario work is part of the thesis red line, but final robust risk claims should remain cautious.

The downstream optimisation work is currently centred on the hydrogen bidding, clearing, and redispatch test case. That is now the strongest optimisation path, and it is where the forecasting artifacts are turned into an economic and operational test bed.

The CVaR branch matters as a later optimisation extension. It is not yet the hardened default path, but it is not junk. It preserves risk-aversion implementation, validation sweeps, anomaly diagnostics, and the methodological transition from risk-neutral operation toward downside-aware optimisation.

Finally, the command-centre and reporting governance layer is itself part of the thesis work. The repository is not only storing models. It is also trying to standardise run contracts, selected-week logic, reporting conventions, and optimisation governance.

The practical lesson is simple: failed, superseded, or non-default attempts are not automatically disposable. If they explain a methodological decision, a branch choice, or a known limitation, they are part of the thesis record.

## 3. Folder-By-Folder Interpretation

### `data/`

This is the broad storage layer for raw inputs, cleaned tables, forecasting outputs, and related artifacts. It mixes baseline inputs, reproducible derivatives, and large generated outputs. In future cleanup, it should be treated as a mixed zone rather than a single thing.

### `data/01_cleaned/`

This is a special case. It contains cleaned data that may function as baseline thesis inputs, but it also contains diagnostics, derivative tables, and churn-heavy outputs. It is not safe to treat this folder as ordinary generated data, and it is not safe to restore or remove it in bulk. It is a manual-review area with a separate policy problem.

### `data/02_Forecasting/`

This folder contains forecasting outputs and related result artifacts. Much of it belongs outside Git in the long term: run folders, frozen results, repair runs, scenario-evaluation artifacts, exports, and other generated result trees. At the same time, the folder structure itself helps explain the research progression, so cleanup should archive large artifacts rather than treating them as meaningless clutter.

### `docs/`

This is the stable documentation layer and should increasingly hold the human-readable explanation of the repository. It is canonical and should remain in Git. It now includes lineage and optimisation-governance docs that are meant to survive later cleanup.

### `docs/forecasting/`

This is the right long-term home for stable forecasting summaries, campaign writeups, and promoted root-level methodology notes. It is part of the canonical documentation surface, although some forecasting knowledge is still scattered elsewhere and needs consolidation.

### `docs/optimisation/`

This is the central governance and methodology surface for the optimisation workstream. It should keep project decisions, known issues, model-equation roadmaps, result-table definitions, retention policy, run contracts, selected-week governance, and other compact thesis-facing docs.

### `notebooks/`

This folder is mainly an interpretation and exploratory layer, not the preferred home for core implementation. Some notebooks may be thesis-facing and worth retaining. Others are likely output noise, generator-managed artifacts, or transitional scratch work. This is a manual-review area rather than a keep-or-delete-by-default area.

### `scripts/Data/01_cleaning/`

This is canonical source code. It contains the main cleaning pipelines that feed the forecasting and optimisation workstreams. It should stay in Git and should be protected from broad cleanup.

### `scripts/Data/02_Forecasting/01_DA_prices/`

This is the main forecasting work surface. It contains canonical runners, historical runners, documentation, one-off campaigns, quarter-hour extensions, and support scripts. It is mixed, but much of the source layer is thesis-relevant and should not be treated as disposable.

### `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/`

This is the standardised canonical hourly forecasting package. It contains shared modules, model logic, evaluation and reporting functions, and the main code-level implementation of the fixed forecasting methodology. This is canonical source and should stay in Git.

### `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/`

This is the quarter-hour source branch. It is methodologically important because it preserves the observed-versus-counterfactual split, phase workflow history, and the quarter-hour extension logic. Even where it is not the thesis-default path, it is source-level lineage and should be protected.

### `scripts/Data/02_Forecasting/01_DA_prices/one_off/2026-05_campaign/`

This is a bounded historical campaign bundle rather than random script sprawl. It preserves the May 2026 campaign, including LEAR Strict, Lago, support/routing checks, `D+4` applicability scans, and scenario-quality diagnostics. It is a historical attempt to preserve, not a junk drawer.

### `scripts/Data/03_Hydrogen_Test_Case/`

This is the main optimisation workstream folder. It contains runners, configs, support scripts, docs, tests, and the implementation surface for the hydrogen case and related optimisation experiments. This folder is central to the current thesis direction and should be treated as protected source, apart from run folders and other clearly generated artifacts.

### `scripts/Data/03_Hydrogen_Test_Case/hydrogen/`

This is the core hydrogen optimisation code. It represents the current strongest downstream test case and includes bidding, clearing, redispatch, metrics, CVaR-related logic, and command-centre integration. It is canonical source and should stay in Git.

### `scripts/Data/03_Hydrogen_Test_Case/docs/`

This contains hydrogen-specific methodology notes, audits, and readiness/support documentation. It is part source material and part governance support. Some of it may later be promoted into `docs/optimisation/`, but it should be preserved until that consolidation is done.

### `scripts/Data/03_Hydrogen_Test_Case/runs/`

This is a generated output area for optimisation runs. It is useful evidence, but it is not Git-first material. It should stay outside Git, be archived where valuable, and be described by manifests or compact summary docs rather than versioned in bulk.

### `workspace_triage/`

This is a local triage and cleanup-planning workspace. It is useful for operational cleanup work, but it is not the permanent home of thesis meaning. Its durable conclusions should be promoted into `docs/`. Old triage folders are likely later deletion candidates once the stable docs exist.

## 4. What Should Stay In Git

Git should keep the compact, explanatory, reproducible part of the repository.

That includes source code, reusable configs, tests, stable docs, methodology notes, run contracts, selected-week registries where they function as governance artifacts, and compact audit summaries that preserve a meaningful decision or caveat.

In this repository, the clearest examples are the cleaning pipelines in `scripts/Data/01_cleaning/`, the canonical hourly forecasting package in `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/`, the quarter-hour source layer in `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/`, the hydrogen optimisation code in `scripts/Data/03_Hydrogen_Test_Case/hydrogen/`, the hydrogen configs and tests, and the stable docs under `docs/`.

Git should also keep the compact governance layer: `AGENTS.md`, `CHATGPT_PROJECT_CONTEXT.md`, project decisions, known issues, run-contract docs, selected-week policy, and methodology summaries such as the campaign and lineage docs.

Final or thesis-relevant notebooks may stay in Git after review, but only if they are genuinely part of the interpretation layer and not just bulky execution noise.

## 5. What Should Stay Outside Git But Be Archived

Some repository material can still be useful evidence without being a good Git citizen.

That includes large run folders, scenario artifacts, `frozen_results`, `repair_runs`, exports, parquet outputs, solver logs, full metric time series, and large generated CSV result tables. These may document important experiments, support audits, or reproducibility of a particular run, but they should normally live outside Git and be archived locally or externally.

In this repository, examples include forecasting run folders under `data/02_Forecasting/.../runs/`, scenario-evaluation outputs, large result trees under `hourly_da/frozen_results/`, repair runs, quarter-hour run outputs, and optimisation run folders under `scripts/Data/03_Hydrogen_Test_Case/runs/`.

The point is not to throw these away casually. Some of them are still methodologically useful. The better pattern is to archive them with a manifest or compact summary so that the thesis can still refer to them without forcing Git to carry the bulk.

## 6. What Can Later Be Deleted

Likely deletion candidates exist, but they should be treated conservatively.

The safest candidates are accidental or local-only files such as `--config`, temporary debug folders, cache folders, bytecode directories, virtual-environment folders, and similar machine-local clutter already recognised by `.gitignore`.

Duplicate copy files are also plausible candidates, such as copy-named cleaned-data files that were not intended as stable inputs.

Generated next-action JSONs and root-level CSV diagnostics may later be deleted after their conclusions are summarised into stable docs. The same applies to old triage folders under `workspace_triage/` once permanent documentation exists elsewhere.

What should not happen is bulk deletion before archive or summarisation where needed. If a file is the only place where a methodological conclusion still lives, it should not be treated as junk just because it is inconvenient.

## 7. What Might Need To Be Moved Or Consolidated

Several things in this repository probably belong in more stable places conceptually, even if no file operations are done yet.

The root-level LEAR Strict, routing, and support reports conceptually belong under `docs/forecasting/`. Their knowledge is forecasting methodology, not top-level repo clutter.

Hydrogen support and readiness docs that currently live under `scripts/Data/03_Hydrogen_Test_Case/docs/` may eventually need to be consolidated into `docs/optimisation/`, especially where they now substitute for missing central governance docs.

`VISUALISATION.md` is still a placement question. It currently functions as an active governance surface, but the long-term expectation is that this visual policy belongs conceptually with the optimisation docs.

There is also a broader consolidation problem around central optimisation governance: experiment registry, selected-week registries, and related run-level reporting references should be easy to locate in a single documentation surface rather than scattered across source folders and local reports.

## 8. The `data/01_cleaned/` Problem

`data/01_cleaned/` is special because it mixes different kinds of artifacts under one name.

Some files may be baseline thesis inputs that a clean clone should still have available. Some appear to be generated derivatives that are reproducible from smaller upstream baselines plus code. Some are diagnostics and parse summaries that should probably not live next to baseline data long-term. Some changes may be accidental formatting or regeneration churn rather than meaningful data updates.

That is why this folder should not be cleaned in bulk. It needs a representative diff review and a family-by-family policy decision first. The sensible distinction is between baseline inputs, derivatives, diagnostics, and accidental churn. Until that review is done, broad restore or broad cleanup is methodologically risky.

## 9. The Notebook Problem

Notebooks require manual review because they are not one thing.

Some notebooks are interpretation layers that may be thesis-facing. Some contain output noise from reruns. Some may be generator-managed scaffolds or late-stage support notebooks. Some may capture conclusions that are not yet written into stable markdown docs.

The key modified notebooks that need review are:

- `04_fs0_naive_models.ipynb`
- `14_fs2_feature_value_results.ipynb`
- `20_fs3_xgboost_ablation.ipynb`
- `23_fs3_decision_relevant_forecast_evaluation.ipynb`
- `24_final_conclusion_and_best_model.ipynb`

The key late-stage untracked notebooks that also need review include:

- `25_lago_lear_six_year_benchmark.ipynb`
- `26_three_candidate_model_comparison_new_metrics.ipynb`
- `27_qh_three_model_comparison_new_metrics.ipynb`
- `28_qh_scenario_generation_review.ipynb`
- `29_scenario_distribution_evaluation_all_models.ipynb`
- the `15min_extension/` notebook set
- quarter-hour notebook subfolders under the forecasting notebooks tree

These should not be judged only by file size or by whether Git currently tracks them. They need human review for role: thesis interpretation, exploratory scratch work, generator output, or historical reference.

## 10. The Hydrogen Test Case Status

The current strongest optimisation path is the hydrogen test case running through the command centre, using an hourly, `D_only`, `DA_only`, selected-week, risk-neutral path as the hardened default.

The optimisation workstream already has meaningful infrastructure around bidding, clearing, redispatch, metrics, benchmarks, selected-week governance, and reporting. In other words, the main issue is not that optimisation is missing. The issue is that the optimisation stack is now constrained by upstream forecasting and scenario quality.

The command-centre selected-week risk-neutral path is currently the most stable operational route. CVaR exists as an implemented and methodologically relevant branch, but it is not yet the command-centre default. That distinction matters and should be preserved in cleanup and documentation.

The current blocker is scenario support mismatch rather than lack of MILP infrastructure. Scenario undercoverage and tail weakness are also active caveats. That means the hydrogen code, configs, tests, governance docs, and support diagnostics should be preserved before any cleanup of surrounding artifacts happens.

## 11. Proposed Cleanup Sequence

The cleanup sequence should be human-led and path-specific.

First, preserve the lineage and governance docs so the reasoning is no longer trapped in local triage folders or scattered reports.

Second, take a snapshot and backup before any destructive thought process. That includes Git status summaries, diff summaries, manifests, and a tracked worktree patch. Dry-run commands are appropriate here; broad destructive commands are not.

Third, decide the tracked deleted forecasting runners. Several top-level runner deletions appear to have same-name replacements under `one_off/2026-05_campaign/`, but this should be confirmed as intentional relocation rather than assumed automatically.

Fourth, review representative samples from `data/01_cleaned/` before deciding whether any tracked data changes are real updates, churn, or diagnostics.

Fifth, review notebooks manually, especially the modified late-stage forecasting notebooks and the untracked late-stage campaign notebooks.

Sixth, explicitly protect untracked source trees. This repository has already shown that broad cleanup previews can accidentally treat untracked source as disposable.

Seventh, archive large outputs that are useful evidence but not suitable for Git: run folders, frozen results, repair runs, scenario evaluation outputs, and optimisation runs.

Eighth, delete only confirmed junk such as caches, temporary local files, and generated support artifacts whose conclusions are already preserved elsewhere.

Ninth, re-run `git status` and only then consider a clean commit of actual code/doc changes. Any restore or delete action should follow review, not precede it.

If commands are used at any point, they should be dry-run or inspection commands until the relevant path lists are explicitly approved.

## 12. Open Decisions

Several decisions remain unresolved.

The `data/01_cleaned/` tracking policy is still open and needs a family-by-family decision. Root-level report consolidation is not finished. Notebook retention is unresolved. `VISUALISATION.md` still has a final placement question. Hydrogen support/readiness docs may need promotion into the central optimisation docs. The long-term archive location for large forecasting and optimisation artifacts still needs agreement. And the repository still needs a final decision on whether the deleted top-level forecasting runners should remain replaced by `one_off/2026-05_campaign/` or be restored at their old surface.

## 13. Practical Rule Of Thumb

Git should keep source, config, tests, and compact reasoning.

Git should not keep large generated outputs.

Important failed or superseded attempts should be summarised, not erased.

Preserve evidence of why alternatives were rejected.

Do not confuse noncanonical with worthless.

Archive large evidence before deleting it.

Protect future-scope work such as balancing markets unless explicitly deprecated.

Cleanup should be path-specific, not broad.

Never run broad clean or broad restore logic before snapshot and review.

## 14. Explicit Preservation Guards

Future cleanup should treat the following categories as protected research lineage, even when they are not part of the current default execution path. These are not cleanup junk and should not be deleted, de-tracked, or flattened without separate review.

### LEAR FS1 / FS2 / FS3 progression

Preserve the scripts, configs, notebooks, docs, and compact result summaries that explain LEAR's role across the FS ladder. The repository should keep enough evidence to show how LEAR evolved from one forecasting stage to the next, how it was compared against alternatives, and why particular LEAR variants were retained, modified, or dropped. It is not necessary to keep every large run artifact, but the methodological chain should stay legible.

### Prophet / ARIMA / SARIMA attempts

Preserve the methodological record of Prophet-, ARIMA-, and SARIMA-related attempts even when they are not final thesis models. These branches explain what was tried, how it was compared, and why it was not carried forward. That means source scripts, comparison summaries, and compact explanations should remain discoverable. Large generated outputs do not need to remain in Git by default, but the reasoning for model rejection should not disappear.

### Balancing market / mFRR / IR preparation

Do not delete balancing-market data folders, scripts, assumptions, or notes without separate review. Even though `DA_only` is the current active scope, balancing-market and mFRR preparation material belongs to the future extension path described in the thesis framing. Large balancing data may remain outside Git or be archived, but it should not be treated as disposable merely because the current default workflow does not use it yet. Preserve future extension material for mFRR capacity and activation modelling unless it is explicitly deprecated later.

### Visual / reporting framework

Preserve `VISUALISATION.md`, visual-style helpers, reporting conventions, run table definitions, and thesis plotting policy. Final placement may still change, but the reporting framework is part of the thesis infrastructure, not decoration. Cleanup should not separate figures from the policies that explain how they are supposed to be produced and interpreted.

### Command-centre and execution framework

Preserve command-centre scripts, supported-options registries, run contracts, selected-week configs, experiment-registry logic, progress reporting, and reproducible run-folder contracts. These are architecture, not temporary helper scripts. Even when the underlying model logic is still evolving, this framework captures how experiments are controlled, validated, documented, and compared.

### Large artifacts

Large files are not automatically junk. They should be classified in one of three ways. Keep them in Git only if they are small enough and clearly canonical. Archive them outside Git if they are important evidence, reproducibility support, or thesis-relevant result history. Delete them only if they are reproducible, redundant, and not cited by stable docs. Any deletion decision should follow a snapshot and dry-run review rather than size-based cleanup.
