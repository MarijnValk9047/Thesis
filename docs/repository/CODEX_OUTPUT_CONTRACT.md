# Codex Output Contract

## Purpose
This document defines the operational rules Codex must follow before creating files or running pipelines in this repository.

Use [docs/RESEARCH_LINEAGE.md](../RESEARCH_LINEAGE.md) as the lineage anchor when deciding how outputs should be classified, summarised, retained, or kept local-only.

## Output Policy Labels
Use exactly these `output_policy` labels:
- `minimal`
- `diagnostics`
- `full`
- `thesis_report`

## Default Rule
Default `output_policy = minimal`.

Codex should use the smallest output surface that is sufficient for the task.

## Approval Rule
Broad diagnostics or heavy output require explicit user approval.

Operationally:
- `minimal` is the default
- `diagnostics` is allowed when the user clearly needs inspection output
- `full` requires explicit approval
- `thesis_report` should be used only for selected thesis-facing reporting outputs

## Required Pre-Run Statement For Broad Output Creation
Before generating many files or starting a nontrivial pipeline, Codex must state:
- `output_root`
- expected file count
- expected approximate size
- `output_policy`
- `run_class`
- `lineage_role`
- retention status
- whether outputs are Git-eligible

If any of those items are unclear, pause and ask or propose defaults before proceeding.

## Mandatory Rules
- no root-level generated outputs
- no broad run folders without config, manifest, and registry metadata
- no notebook outputs in Git
- no large generated data in Git
- no hardcoded personal paths, licence paths, API keys, WLS keys, or secrets
- no broad destructive cleanup commands such as `git clean -fdX` without a reviewed archive-first manifest

## Git Eligibility Rule
Generated data and run outputs are not Git-eligible unless explicitly classified as small thesis-critical provenance.

Prefer:
- compact docs
- manifests
- registry entries
- warnings summaries

Do not default to committing bulky generated artifacts.

## Commit-Time Validation Rule
Before committing source or docs after Codex-generated edits, run `python scripts/dev/check_portable_paths.py` or use the configured pre-commit hook.

This guard blocks personal absolute paths and obvious secrets. It complements the output contract, but does not replace it.

## Run-Folder Rule
If Codex creates a meaningful run folder, it must include or explicitly plan for:
- `resolved_config.yaml`
- `input_manifest.json`
- `code_version.json`
- `run_summary.json`
- `warnings_and_limitations.md`
- `registry_entry.json`

If applicable, it should also produce `metrics_summary.csv`.

## Notebook Rule
If notebook work is requested:
- keep notebook source clean where feasible
- route execution outputs to local or archive locations only
- do not treat notebook cell output as the default run record

## Plot Rule
Default behaviour is no plots.

Plots should be created only when:
- the user requests them
- the governed run purpose requires them
- the output is a selected `thesis_report` deliverable

Diagnostic plots should stay local or ignored.

## Lineage Preservation Rule
Codex must preserve the distinctions anchored in [docs/RESEARCH_LINEAGE.md](../RESEARCH_LINEAGE.md):
- canonical current path
- important historical branches
- diagnostic work
- generated artifacts
- local-only bulky outputs

Codex must not flatten methodologically important branches into generic clutter when proposing cleanup, output rules, archive decisions, or run classifications.

## Balancing Warning
Balancing pipeline work must reuse this same output contract.

It must not create:
- a second parallel artifact structure
- a second output-policy vocabulary
- undocumented root-level exports or run trees

## Acceptable Output Behaviour
### Acceptable Example 1
Codex proposes a smoke run and states:
- output root in an existing governed run location
- expected files: 6 to 8
- expected size: under 5 MB
- `output_policy = minimal`
- `run_class = smoke`
- `lineage_role = diagnostic`
- local retention only
- metadata may be Git-eligible, bulk output is not

### Acceptable Example 2
Codex creates a compact methodology note in `docs/` and keeps bulky diagnostic artifacts in a local ignored output root.

### Acceptable Example 3
Codex refuses to write generated CSVs, plots, or scratch manifests at repository root and instead proposes a governed output root.

## Unacceptable Output Behaviour
### Unacceptable Example 1
Creating `results/`, `figures/`, `exports/`, or `debug_output/` at repository root.

### Unacceptable Example 2
Running a pipeline that creates many files without first stating output root, expected file count, expected approximate size, `output_policy`, `run_class`, and `lineage_role`.

### Unacceptable Example 3
Writing notebook outputs, large scenario files, or full run bundles into Git-tracked locations by default.

### Unacceptable Example 4
Using broad destructive cleanup commands against ignored trees without archive-first review and manifesting.
