# Scenario Real Integration Readiness

## Scope

This Phase 6a audit checks whether the hydrogen stochastic bidding stack can move from toy scenarios to real hourly thesis-grade scenario artifacts.

This phase does not run real stochastic optimisation. It only audits artifact discovery, schema compatibility, probability mass, and catalog readiness.

## Update: May 16, 2026

Support and readiness map update:

- a new machine-readable inventory now exists at:
  - [forecast_scenario_support_inventory.csv](/scripts/Data/03_Hydrogen_Test_Case/docs/forecast_scenario_support_inventory.csv)
- experiment-level readiness is now tracked at:
  - [optimisation_experiment_readiness_matrix.csv](/scripts/Data/03_Hydrogen_Test_Case/docs/optimisation_experiment_readiness_matrix.csv)
- the human-readable support separation is now documented at:
  - [optimisation_data_support_map.md](/scripts/Data/03_Hydrogen_Test_Case/docs/optimisation_data_support_map.md)

New readiness finding:

- the intended final hourly D-only comparison period is:
  - `2024-10-01` to `2025-09-30`
- that comparison is still **blocked**
- reason:
  - current thesis-grade LEAR Strict hourly support is `2026-02-05` to `2026-04-30`
  - current thesis-grade LEAR FS3 hourly support on the intended period is only `2024-10-01` to `2025-09-26`
  - current thesis-grade XGBoost hourly support on the intended period is only `2024-10-01` to `2025-09-26`
- there is therefore:
  - no three-model common support inside the intended hourly test year

Quarter-hour track separation is now explicit:

- observed-market quarter-hour work is a separate `2025/2026` track and must use observed targets only
- counterfactual quarter-hour work is the frozen synthetic `2024-10-01` to `2025-09-30` track and must stay labelled counterfactual/synthetic
- hourly versus quarter-hour is **not** a clean granularity comparison unless support and truth type are matched

Selected-week integration status update:

- all three hourly thesis-grade catalog entries now pass hydrogen-loader validation:
  - `hourly_lear_strict`
  - `hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate`
  - `hourly_xgboost_fs3_pruned_tail_stress_v1_thesis_candidate`
- however, the current thesis-grade LEAR Strict hourly artifact has valid delivery support only on:
  - `2026-02-05` to `2026-04-29`
- the LEAR FS3 and XGBoost thesis-grade hourly artifacts currently share valid delivery support on:
  - `2023-10-05` to `2025-09-26`
- there is therefore no three-model common-support week for a clean thesis-grade selected-week comparison

What this means for optimisation:

- the hydrogen stochastic bidding chain is ready for thesis-grade selected-week runs on the common LEAR FS3 / XGBoost subset
- the selected-week three-model comparison remains blocked upstream by artifact support mismatch, not by the MILP chain or hydrogen loader
- any three-model selected-week notebook must either:
  - stop with an explicit common-support failure, or
  - degrade intentionally to a two-model thesis-grade comparison and report the LEAR Strict blocker

Hourly LEAR Strict regeneration has now completed successfully from:

- `data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly_with_lear_strict/20260516_002902/`

Observed run status from `scenario_generation_run_summary.json`:

- `status = completed`
- `horizon_mode = D_ONLY`
- `granularity = hourly`
- `scenario_variant = tail_stress_v1`
- `n_raw = 400`
- `n_final = 75`
- `forecast_origin_reconstruction_used = false`
- probability validation in the upstream run summary: `pass`

The regenerated long-format artifact contains exactly these hourly candidate/model IDs:

- `lear_strict_hourly_anchor_export`
- `lear_fs3_combo_pruned_candidate`

It does not contain:

- `lear_fs3_combo_promoted`
- `xgboost_fs3_combo_pruned_candidate`
- `xgboost_fs3_combo_promoted`

Hydrogen loader validation status after catalog alignment:

1. `hourly_lear_strict`
   - catalog path updated to the regenerated `20260516_002902/scenario_prices_long.csv`
   - thesis-grade validation: `pass`

2. `hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate`
   - promoted from the same regenerated run using exact model id `lear_fs3_combo_pruned_candidate`
   - thesis-grade validation: `pass`

3. XGBoost hourly
   - no XGBoost rows are present in the regenerated artifact
   - existing XGBoost hourly availability remains the legacy-derived `base_plus_b` integration candidate only
   - thesis-grade promotion was not applied

## Commands

Inventory and probability diagnosis:

```powershell
.venv\Scripts\python.exe scripts/Data/03_Hydrogen_Test_Case/audit_scenario_artifacts.py `
  --config scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml `
  --output-dir scripts/Data/03_Hydrogen_Test_Case/docs
```

Catalog validation preflight:

```powershell
.venv\Scripts\python.exe scripts/Data/03_Hydrogen_Test_Case/validate_scenario_catalog.py `
  --config scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml
```

Selected-artifact validation:

```powershell
.venv\Scripts\python.exe scripts/Data/03_Hydrogen_Test_Case/validate_scenario_catalog.py `
  --config scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml `
  --artifacts hourly_lear_fs3_promoted_legacy_available
```

## Artifacts inspected

The audit inspected:

- scenario catalog entries from `configs/scenario_catalog.yaml`
- hourly discovery rows from `data/02_Forecasting/01_DA_prices/scenario_evaluation/20260513_102807/tables/scenario_load_registry.csv`
- direct filesystem matches for:
  - `scenario_prices_long.csv`
  - `scenario_prices_long.parquet`
  - `scenarios_long.csv`
  - `scenarios_long.parquet`

Machine-readable outputs:

- [scenario_artifact_inventory.csv](/scripts/Data/03_Hydrogen_Test_Case/docs/scenario_artifact_inventory.csv)
- [probability_mass_by_origin.csv](/scripts/Data/03_Hydrogen_Test_Case/docs/probability_mass_by_origin.csv)

## Hourly D-only target findings

First-integration target:

- hourly
- D-only / `lead_day = 0`
- one model first
- explicit probabilities required
- explicit `forecast_origin_utc` preferred

Observed hourly candidates before Phase 6a-2 repair:

1. `hourly_lear_strict`
   - catalog default
   - expected path does not exist
   - current status: missing export

2. `hourly_lear_fs3__20260513_073251`
   - referenced by discovery registry
   - expected path does not exist
   - current status: missing export

3. `hourly_xgboost_fs3__20260511_212611`
   - referenced by discovery registry
   - expected path does not exist
   - current status: missing export

4. `hourly_lear_fs3_promoted_legacy_available`
   - file exists
   - current status: schema-mapping repair required
   - blockers:
     - no explicit `forecast_origin_utc`
     - four `scenario_variant` groups bundled into one artifact
     - current optimisation contract has no variant selector

## Phase 6a-2 repair outcome

Phase 6a-2 created clean one-variant integration-candidate exports from the legacy hourly bundled artifact:

1. `hourly_lear_fs3_promoted_base_plus_b_integration_candidate`
2. `hourly_xgboost_fs3_pruned_base_plus_b_integration_candidate`

Export basis:

- source file:
  `data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly/20260429_193206/scenario_prices_long.csv`
- selected variant:
  `base_plus_b`
- selection support:
  - `final_scenario_recommendation.json`
  - `final_scenario_model_comparison.csv`

Important status:

- probability mass validates at `1.0` per forecast origin after variant selection
- no silent probability normalisation was used
- `forecast_origin_utc` was reconstructed using:
  `D-1 08:00 Europe/Amsterdam converted to UTC`
- these exports are **integration candidates**, not thesis-grade artifacts

Derived artifact locations:

- `data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/legacy_variant_integration_candidates/hourly_lear_fs3_promoted_base_plus_b_integration_candidate/`
- `data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/legacy_variant_integration_candidates/hourly_xgboost_fs3_pruned_base_plus_b_integration_candidate/`

## Probability diagnosis

The legacy hourly fallback does not fail because long-format rows repeat the same probabilities over timestamps. That false-failure mode was checked explicitly.

The actual issue is different:

- each `scenario_variant` block has probability mass `1.0` per forecast origin
- the file bundles four variants together
- the current loader contract sees all four at once
- that yields about `4.0` probability mass per origin on a unique-scenario basis

This is therefore a **schema/selection issue**, not a case for silent probability normalisation.

After selecting exactly one scenario variant per derived artifact, the exported integration-candidate artifacts pass per-origin probability validation.

## Catalog and config status

Catalog update applied in Phase 6a:

- `hourly_lear_strict.model_id` was corrected from `lear_fs3_combo_pruned_candidate` to `lear_strict_hourly_anchor_export`

Catalog status after the May 16 alignment:

- default artifact `hourly_lear_strict` now points to the regenerated thesis-grade file under `20260516_002902`
- a second thesis-grade hourly entry now exists for:
  - `hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate`
- legacy integration-candidate entries remain in place for:
  - hourly LEAR FS3 `base_plus_b`
  - hourly XGBoost FS3 `base_plus_b`

`base_hydrogen.yaml` status:

- still defaults to `hourly_lear_strict` in `models.include`
- now catalog-resolvable for thesis-grade hourly LEAR Strict scenario loading
- not yet sufficient for a clean three-model thesis-grade comparison because hourly XGBoost is still mixed-provenance

## Can real stochastic bidding proceed?

Partially.

What is now ready:

- thesis-grade hourly LEAR Strict scenario loading through the hydrogen loader
- thesis-grade hourly LEAR FS3 pruned-candidate scenario loading through the hydrogen loader

What is still not ready:

1. a clean thesis-grade three-model comparison is not yet possible because hourly XGBoost has not been regenerated/promoted to the same standard
2. scenario-quality diagnostics still show coverage weaknesses even before optimiser use
3. this document still concerns artifact readiness only; no optimiser, bidding, or CVaR runs have been approved here

However, Phase 6b may now proceed as an **integration dry run** using the derived LEAR FS3 or XGBoost FS3 integration-candidate artifacts.

## Remaining blockers

1. regenerate or otherwise promote hourly XGBoost to thesis-grade if a clean three-model comparison is required
2. keep explicit `forecast_origin_utc` in all thesis-grade exports
3. preserve nonnegative probabilities summing to `1.0` per forecast origin and scenario set
4. keep actual-price linkage available for later realised-clearing backtests
5. carry scenario coverage diagnostics into the first real optimisation phase

## Phase 6b gate

Phase 6b real scenario integration may proceed only after:

- at least one hourly D-only artifact passes catalog validation in thesis-grade mode
- probability mass is valid without silent renormalisation
- the artifact has explicit or formally justified forecast-origin provenance
- the readiness blocker in `known_issues.md` is resolved

Current gate status:

- LEAR Strict: satisfied
- LEAR FS3 pruned candidate: satisfied
- XGBoost: not yet satisfied for thesis-grade comparison parity
