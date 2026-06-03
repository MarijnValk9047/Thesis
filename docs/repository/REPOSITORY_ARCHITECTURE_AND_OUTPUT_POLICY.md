# Repository Architecture And Output Policy

## Purpose
This document defines the repository classification model and output-governance rules for future work.

It is a policy and classification layer, not an immediate filesystem migration plan. It does not require active paths to be moved now, and it does not authorize creating new broad output trees outside the governed locations already used by the repository.

Use [docs/RESEARCH_LINEAGE.md](../RESEARCH_LINEAGE.md) as the main lineage anchor. This document references that lineage instead of duplicating it.

## Core Principle
Keep source, compact methodology, and compact governance in Git.

Keep bulky generated outputs, run bundles, notebook artifacts, plots, and large intermediate data out of Git by default unless they are explicitly classified as small thesis-critical provenance.

## Classification Model

### Source Code
Includes reusable modules, runners, tests, command-centre logic, visual-style helpers, and scenario or optimisation logic.

Default treatment:
- Git-eligible
- protected from broad cleanup

### Configs
Includes YAML and comparable config files, supported-options registries, selected-week configs, and experiment-control configs.

Default treatment:
- Git-eligible
- part of the controlled execution surface

### Raw Data
Includes raw market inputs, external benchmark data, local balancing data, and imported source datasets.

Default treatment:
- local or externally managed
- not Git-first

### Cleaned Data
Includes baseline cleaned thesis inputs, derived cleaned tables, and diagnostics mixed into cleaned-data trees.

Default treatment:
- mixed-policy area
- not safe for bulk cleanup
- requires baseline-versus-derived review

Special warning:
- `data/01_cleaned/` remains a separate tracked-data policy problem
- do not treat `data/01_cleaned/` as ordinary generated output
- do not bulk-clean, bulk-restore, or broadly reclassify it without a separate review

### Features
Includes engineered model-input tables and feature-family derivatives used by forecasting or downstream scenario work.

Default treatment:
- generated output by default
- not Git-eligible unless explicitly classified as small thesis-critical provenance

### Forecasts
Includes deterministic forecast outputs, evaluation exports, and downstream support tables such as frozen actual-path layers.

Default treatment:
- generated output
- not Git-first by default

### Scenarios
Includes scenario files, scenario probabilities, scenario diagnostics, support checks, and containment audits.

Default treatment:
- source code, configs, and compact audit summaries may be Git-eligible
- bulk scenario artifacts are not Git-first by default

### Optimisation Inputs
Includes optimisation-ready market inputs, scenario manifests or adapters, and test-case asset inputs.

Default treatment:
- compact manifests may be Git-eligible
- bulky generated payloads are not Git-first by default

### Run Outputs
Includes run folders, solver logs, metric exports, time-series outputs, bid results, dispatch results, settlement results, and evaluation bundles.

Default treatment:
- not Git-eligible by default
- governed by the run registry and output contract

### Diagnostics And Audits
Includes support checks, undercoverage diagnostics, anomaly runs, comparability audits, routing checks, and other review-focused outputs.

Default treatment:
- compact explanations belong in stable docs
- bulky generated diagnostics stay local or archived

### Notebooks
Includes interpretation notebooks, exploratory notebooks, and thesis-facing narrative notebooks.

Notebook policy:
- source-clean notebooks may stay in Git after review
- notebook execution outputs belong local-only or archive-only
- notebooks are interpretation surfaces, not the preferred home for core implementation

### Thesis Figures And Tables
Includes selected thesis-facing plots and compact reporting tables.

Plot policy:
- default is no plots
- selected thesis plots should be created only when requested or explicitly required
- diagnostic plots stay local or ignored
- do not generate figure floods by default

### Local Archives
Includes local bundles of bulky run outputs, archived exports, and reproducibility support that should not live in Git.

Default treatment:
- local-only
- archive locations should be recorded, not tracked in bulk

## Allowed Output Locations
Generated outputs should be written only to governed locations such as:
- existing established forecasting run-output roots
- existing established optimisation run-output roots
- existing audit or export roots that are already local-only or ignored
- explicit local archive locations
- `workspace_triage/` for local planning material only

If an output does not clearly belong to a governed location, pause and choose an output root before writing files.

## No-Root-Output Rule
Do not create generated outputs at repository root.

This includes:
- result CSVs
- JSON manifests
- plot directories
- export bundles
- scratch reports
- ad hoc diagnostics

## Git Eligibility Rule
Generated data and run outputs are not Git-eligible unless explicitly classified as small thesis-critical provenance.

Default pattern:
- keep methodology and lineage in compact docs
- keep run meaning in manifests and registry entries
- keep bulk output outside Git

## One-Off Script Policy
Bounded campaigns or one-off scripts should live in a dated folder pattern inside an appropriate source surface, following the existing `one_off` style where relevant.

Each such folder should have a short README covering:
- purpose
- reason it is one-off rather than canonical
- expected output location
- expiry or review condition
- whether it is preserved as lineage or still operational

## Domain Rules

### Day-Ahead
- keep canonical source and compact methodology in Git
- keep bulky forecast outputs, evaluation trees, and exports outside Git by default

### Quarter-Hour
- preserve observed-versus-counterfactual separation explicitly
- do not mix synthetic downstream support paths with observed truth
- keep bulky generated quarter-hour outputs local or archived

### `D+4`
- treat `D+4` as a governed extension path rather than an ad hoc output exception
- preserve compact applicability and support explanations even if full output bulk is not retained

### Scenario Generation
- preserve source, configuration, compact caveat docs, and undercoverage summaries
- keep bulk scenario trees outside Git by default
- do not erase support-mismatch or containment caveats through cleanup

### Hydrogen Optimisation
- preserve the selected-week command-centre path as the current canonical downstream route
- keep code, configs, tests, and compact governance docs in Git
- keep bulky run outputs and diagnostics outside Git by default

### CVaR
- preserve CVaR as implemented and methodologically relevant
- do not treat it as failed clutter
- do not describe it as the command-centre default unless that status changes explicitly

### Balancing
- balancing work must reuse this same classification and output-governance layer
- do not let balancing create a second parallel artifact structure
- preserve future-scope balancing preparation material unless explicitly deprecated later

## Lineage Rule
Use [docs/RESEARCH_LINEAGE.md](../RESEARCH_LINEAGE.md) as the main lineage anchor.

Repository governance must preserve compact explanations of:
- canonical current path
- important historical or methodological branches
- generated artifacts versus source-level progress
- local-only bulky outputs

Preserve the explanation of important attempts in stable docs. Do not preserve full redundant output bulk in Git just to preserve lineage.
