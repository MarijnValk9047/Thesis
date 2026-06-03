# Run And Artifact Registry Schema

## Purpose
This document defines the minimum registry contract for meaningful runs and artifact bundles so outputs can be understood, classified, retained, archived, or deleted consistently.

Use [docs/RESEARCH_LINEAGE.md](../RESEARCH_LINEAGE.md) as the source of the lineage narrative. The registry captures lineage status through compact fields rather than rewriting that narrative.

## Output Policy Labels
Use exactly these `output_policy` labels:
- `minimal`
- `diagnostics`
- `full`
- `thesis_report`

## Required Registry Fields
| Field | Purpose |
|---|---|
| `run_id` | Stable unique identifier for the run or artifact bundle. |
| `timestamp` | ISO timestamp for run creation or registration. |
| `domain` | Forecasting, optimisation, balancing, cleaning, or audit domain. |
| `market` | Market context such as `DA`, `mFRR`, or mixed. |
| `pipeline_stage` | Stage label such as cleaning, forecasting, scenario generation, settlement, or audit. |
| `granularity` | `hourly`, `quarter_hour`, or another explicit label. |
| `horizon` | `D_only`, `D_plus_4`, selected week, or another explicit horizon label. |
| `model_family` | Main model, benchmark, or strategy family. |
| `feature_set` | Feature set or comparable input-family label. |
| `scenario_source` | Scenario model, deterministic source, or `none`. |
| `input_artifacts` | Manifest or list of key input artifact identifiers and paths. |
| `output_root` | Root path where outputs were written. |
| `output_policy` | One of `minimal`, `diagnostics`, `full`, `thesis_report`. |
| `run_class` | Governance class for the run. |
| `lineage_role` | How the run relates to the research lineage. |
| `status` | Planned, running, completed, failed, partial, archived, or deprecated. |
| `thesis_usable` | `yes`, `no`, or `conditional`, with justification. |
| `key_result` | One-line main outcome. |
| `limitations` | Main caveats, warnings, or blockers. |
| `archive_location` | Local archive path or bundle reference if moved. |
| `delete_after` | Review or deletion-eligibility date. |
| `git_commit` | Commit hash used for the run. |

## `lineage_role` Values
- `canonical`: part of the current canonical path
- `extension`: meaningful extension of the canonical path
- `diagnostic`: created to inspect caveats, anomalies, or support questions
- `historical`: methodologically important but not current default path
- `deprecated`: preserved only to explain why it is no longer active
- `local_artifact`: local-only artifact with no Git-first role

## Run Classes
### `debug`
Short-lived local debugging runs.

### `smoke`
Very small verification runs for pathing, schema, or runner health.

### `diagnostic`
Runs used to inspect anomalies, caveats, comparability, or support issues.

### `benchmark`
Runs representing defined comparison baselines such as price-insensitive or perfect foresight.

### `candidate_best`
Serious candidate runs not yet frozen as thesis evidence.

### `thesis_evidence`
Frozen runs whose results may be used in thesis reporting.

### `deprecated`
Runs or bundles preserved only to document why an approach is no longer used.

### `redundant_full_run`
Large reruns or duplicates that add little or no new methodological evidence.

## Minimum File Set For Meaningful Runs
Every meaningful run should include at least:
- `resolved_config.yaml`
- `input_manifest.json`
- `code_version.json`
- `run_summary.json`
- `metrics_summary.csv`, when applicable
- `warnings_and_limitations.md`
- `registry_entry.json`

## File Intent
- `resolved_config.yaml`: exact config used
- `input_manifest.json`: key inputs, paths, IDs, and hashes where feasible
- `code_version.json`: commit hash, runner identity, and environment hints
- `run_summary.json`: status, runtime, compact metrics, and top-level interpretation
- `metrics_summary.csv`: compact metrics table where metrics exist
- `warnings_and_limitations.md`: caveats, blocked claims, truth-type warnings, or support issues
- `registry_entry.json`: machine-readable copy of the registry entry

## Minimum Registry Rules
- if a run is large enough to matter, it is large enough to need a registry entry
- `lineage_role` must preserve the distinction between canonical, historical, diagnostic, and local artifact status
- `output_policy` must use only the four approved labels
- `candidate_best` and `thesis_evidence` runs should not exist without clear limitations and archive or retention fields
