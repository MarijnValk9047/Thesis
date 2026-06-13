# Hourly D-only DA Model Selection Handoff v1

## Purpose and scope

This note freezes the hourly `D_only` day-ahead forecasting and model-selection stage that feeds the downstream optimisation work. Its purpose is to make the selected hourly scenario input easy to understand, defend, and reuse when the thesis moves into the steel-plant MILP stage.

This is a downstream input-selection record for the current hydrogen DAM-only test bed. It is not a claim that the selected model is universally the best electricity-price model across all settings, horizons, markets, or plant configurations.

## Final decision

- Selected model: `LEAR Strict D-only 1092 repaired anchor`
- Main scenario count: `30`
- Main comparison support: `307` common observed delivery days
- Support period: `2024-10-01` to `2025-09-25`
- Main economic comparison setting: hourly, `D_only`, DAM-only, common observed support, `cvar_gamma = 0.0`, emergency import enabled at `3000 EUR/MWh`

This freeze applies to the three-model common-support ranking only. It does not reopen model ranking based on later within-model sensitivity results.

## Candidate models

- `LEAR Strict D-only 1092 repaired anchor`
- `LEAR FS3 promoted`
- `XGBoost FS3 pruned candidate`

## Evidence summary

The frozen comparison uses five evidence layers plus support and reproducibility checks:

1. Classical forecast accuracy:
   LEAR Strict has the best MAE (`20.39`), RMSE (`34.78`), and p90 absolute error (`43.03`) on the common support.
2. Timing and shape:
   LEAR FS3 leads daily Spearman (`0.861`), Bottom-6 hit rate (`0.800`), and Top-6 hit rate (`0.768`). LEAR Strict remains close. XGBoost is weaker across these timing indicators.
3. Scenario quality:
   All three models pass probability non-null and sum-to-one checks on all `307` model-origin-day groups. LEAR Strict has the strongest empirical coverage on the common 30-scenario layer: p90 coverage `0.801` and p95 coverage `0.872`.
4. Economic backtest:
   In the governed hourly DAM-only hydrogen run, LEAR Strict records the highest realised adjusted profit (`EUR 20.010 million`), the lowest emergency import (`46.5 MWh`), and full stochastic-optimal and redispatch-feasible completion on all `307` days. LEAR FS3 remains economically close at `EUR 19.996 million`. XGBoost is materially weaker at `EUR 19.708 million`.
5. Computational time:
   The common-support scenario layer runtime is `2363.35 s`. In the governed DAM-only run, LEAR Strict is also the slightly fastest model profile, with mean solve time `0.850 s` versus `0.863 s` for LEAR FS3 and `0.888 s` for XGBoost.
6. Support and reproducibility:
   Ranking uses only the `307` common observed days. `model_max_supported` was recorded for reproducibility but not used for ranking.

## Final model-selection rationale

### Why LEAR Strict is selected

LEAR Strict is selected because it provides the strongest overall combination of:

- best classical point accuracy on common support;
- best p90 and p95 scenario coverage on the 30-scenario common layer;
- highest realised adjusted profit in the governed DAM-only hydrogen backtest;
- lowest emergency-import reliance among the three models;
- full stochastic-optimal and redispatch-feasible completion on all `307` days;
- slightly fastest computational profile;
- high interpretability and transparent repair lineage.

The selection is cumulative. It is not based on expected profit alone, and it is not based on a single headline metric.

### Why LEAR FS3 remains a close robustness comparator

LEAR FS3 remains close and should stay in scope as the main robustness comparator because it still has:

- best Daily Spearman;
- best Bottom-6 hit rate;
- best Top-6 hit rate;
- more daily economic wins (`116` vs `110`);
- lower total shortfall (`13,927.62 kg` vs `17,985.77 kg`).

The realised adjusted profit gap versus LEAR Strict is only `EUR 14,093.76`. That margin is too small to describe as a decisive economic separation on its own.

### Why XGBoost remains the ML comparator but is not selected

XGBoost remains important as the machine-learning comparator, but it is not selected because on the frozen common-support comparison it has:

- weaker realised economics;
- highest emergency import (`66.0 MWh`);
- highest shortfall (`27,515.22 kg`);
- lower interpretability and transparency than the LEAR candidates.

## Scenario-count decision

The main workflow remains fixed at `30` scenarios per model-origin-day.

The completed LEAR Strict `30` versus `75` scenario sensitivity on the same `307`-day support shows that `75` scenarios improves robustness:

- p95 coverage: `0.872` -> `0.923`
- tail-miss days: `226` -> `159`
- realised adjusted profit: `+EUR 587,897.54` (`about +2.94%`)
- emergency import: `46.5 MWh` -> `22.0 MWh`
- shortfall: `17,985.77 kg` -> `9,515.54 kg`

The same sensitivity also shows the tractability cost:

- total wall time multiplier: `2.94x`
- total solve time multiplier: `3.50x`

Decision:

- `30` scenarios are retained as the main thesis workflow setting.
- `75` scenarios are preserved as robustness evidence.
- The `75`-scenario result must not be used to rerank the three candidate models, because it is a within-model sensitivity for LEAR Strict only.
- The `30`-scenario choice is a tractability decision, not an economically neutral simplification.

This matters for the next stages because the model will likely become heavier through quarter-hour granularity, `D+4` horizon, additional assets, plant buffers, steel-process constraints, and later reserve layers.

## Methodological safeguards

- No random splits.
- Common observed support used for ranking.
- No unequal-support ranking via `model_max_supported`.
- No quarter-hour bridge in the hourly `D_only` ranking.
- No `mFRR`, reserve, intraday, or `MARI` layers in the DAM-only comparison run.
- No retuning on test economic results.
- Expected profit not used as the primary ranking metric.
- Realised settlement, shortfall, feasibility, and emergency import were checked alongside forecast metrics.
- DST non-24h days are excluded under the fixed 24-hour hourly policy.

## Technical fixes and lessons

- LEAR Strict sparse support was artefactual, not methodological.
- The repaired hourly LEAR Strict anchor resolved the support blocker and restored fair common-support comparison.
- The 2026 QH-anchor artifact was not suitable for the hourly `D_only` comparison and should not be reused for this ranking.
- Fair ranking for this stage uses common observed support, not each model's unequal maximum support.
- Progress logging was hardened after an `[Errno 22]` issue encountered during the `75`-scenario sensitivity workflow.
- Cache writing required safe parent-directory handling before nested cache writes.
- Validation-fail rows should not be treated as solver failures by default. In the three-model 30-scenario economic run, all model-day stochastic solves and redispatch solves completed successfully; failure logs mostly record `solver_status = Optimal` with `validation_fail_count = 1`.

## Official evidence map

| Evidence item | Path | Purpose | Compact / large artifact | Recommended to commit |
|---|---|---|---|---|
| Three-model model-selection bundle root | `data/02_Forecasting/01_DA_prices/hourly_da/model_selection_evidence/model_selection_3model_common_observed_20260611_150137/` | Frozen compact evidence bundle for hourly `D_only` common-support ranking | mixed | no |
| Master comparison table | `data/02_Forecasting/01_DA_prices/hourly_da/model_selection_evidence/model_selection_3model_common_observed_20260611_150137/model_selection_master_table.csv` | Single-table summary of ranking inputs and outcomes | compact | no |
| Forecast accuracy table | `data/02_Forecasting/01_DA_prices/hourly_da/model_selection_evidence/model_selection_3model_common_observed_20260611_150137/forecast_accuracy_metrics.csv` | MAE, RMSE, bias, p90 AE | compact | no |
| Timing and shape table | `data/02_Forecasting/01_DA_prices/hourly_da/model_selection_evidence/model_selection_3model_common_observed_20260611_150137/timing_shape_metrics.csv` | Daily Spearman, Bottom-6, Top-6 | compact | no |
| Scenario quality table | `data/02_Forecasting/01_DA_prices/hourly_da/model_selection_evidence/model_selection_3model_common_observed_20260611_150137/scenario_quality_metrics.csv` | Probability validity, p90/p95 coverage, tail misses | compact | no |
| Economic backtest table | `data/02_Forecasting/01_DA_prices/hourly_da/model_selection_evidence/model_selection_3model_common_observed_20260611_150137/economic_backtest_metrics.csv` | Realised economics, shortfall, emergency import, feasibility | compact | no |
| Pairwise economic differences | `data/02_Forecasting/01_DA_prices/hourly_da/model_selection_evidence/model_selection_3model_common_observed_20260611_150137/pairwise_economic_differences.csv` | Direct model-to-model deltas | compact | no |
| Support and reproducibility table | `data/02_Forecasting/01_DA_prices/hourly_da/model_selection_evidence/model_selection_3model_common_observed_20260611_150137/support_reproducibility_metrics.csv` | Support window, max support, runtime, interpretability | compact | no |
| Bundle summary | `data/02_Forecasting/01_DA_prices/hourly_da/model_selection_evidence/model_selection_3model_common_observed_20260611_150137/model_selection_summary.md` | Human-readable model-selection summary | compact | no |
| Bundle decision log | `data/02_Forecasting/01_DA_prices/hourly_da/model_selection_evidence/model_selection_3model_common_observed_20260611_150137/model_selection_decision_log.md` | Ranking logic and caveats | compact | no |
| Bundle assumptions note | `data/02_Forecasting/01_DA_prices/hourly_da/model_selection_evidence/model_selection_3model_common_observed_20260611_150137/unavailable_metrics_or_assumptions.md` | Scope boundaries and excluded artifacts | compact | no |
| Thesis-facing tables and wording | `data/02_Forecasting/01_DA_prices/hourly_da/model_selection_evidence/model_selection_3model_common_observed_20260611_150137/final_tables/` | Thesis-ready comparison table files and wording block | compact | no |
| Common observed scenario layer | `data/02_Forecasting/01_DA_prices/hourly_da/scenario_recreation_runs/full_testperiod_donly_3model_30scen_20260611_101630/common_observed_comparison/` | Authoritative three-model common-support scenario layer | mixed; includes large CSV payloads | no |
| Three-model DAM-only economic run | `scripts/Data/03_Hydrogen_Test_Case/runs/20260611_135643_common_observed_3model_30scen_dam_only/` | Governed hydrogen economic comparison run used for model ranking | mixed | no |
| Economic run summary metrics | `scripts/Data/03_Hydrogen_Test_Case/runs/20260611_135643_common_observed_3model_30scen_dam_only/model_summary_metrics.csv` | Per-model realised economics and solve counts | compact | no |
| Economic feasibility summary | `scripts/Data/03_Hydrogen_Test_Case/runs/20260611_135643_common_observed_3model_30scen_dam_only/feasibility_summary.csv` | Feasibility and validation-fail counts | compact | no |
| Emergency import summary | `scripts/Data/03_Hydrogen_Test_Case/runs/20260611_135643_common_observed_3model_30scen_dam_only/emergency_import_summary.csv` | Emergency import burden by model | compact | no |
| Runtime diagnostics | `scripts/Data/03_Hydrogen_Test_Case/runs/20260611_135643_common_observed_3model_30scen_dam_only/per_model_runtime_diagnostics.csv` | Per-model runtime scalability | compact | no |
| Runtime summary | `scripts/Data/03_Hydrogen_Test_Case/runs/20260611_135643_common_observed_3model_30scen_dam_only/runtime_summary.csv` | Run-level timing breakdown | compact | no |
| Failure log | `scripts/Data/03_Hydrogen_Test_Case/runs/20260611_135643_common_observed_3model_30scen_dam_only/failure_log.csv` | Validation-fail and solve-status trace | compact | no |
| Scenario-count sensitivity parent | `data/03_Hydrogen_Test_Case/dam_only_sensitivity/lear_strict_scenario_count_sensitivity_20260611_172625/` | Parent folder for LEAR Strict `30` vs `75` sensitivity evidence | mixed | no |
| Final 30-vs-75 comparison bundle | `data/03_Hydrogen_Test_Case/dam_only_sensitivity/lear_strict_scenario_count_sensitivity_20260611_172625/final_30_vs_75_comparison/` | Compact sensitivity summary tables | compact | no |
| Completed 75-scenario retry run | `scripts/Data/03_Hydrogen_Test_Case/runs/20260612_090310_lear_strict_scenario_count_sensitivity_75scen_full_retry/` | Full rerun behind the sensitivity summary | mixed | no |

Note on path verification:

- The expected `thesis_three_model_comparison_long.csv`, `thesis_three_model_comparison_wide.csv`, `thesis_three_model_comparison.md`, and `thesis_model_selection_text.md` were not present at the model-selection bundle root.
- They do exist under the bundle subfolder `final_tables/`, which should be treated as the authoritative location for those thesis-facing files.

## Future task guide

| Future task | Start from | Do not use | Notes |
|---|---|---|---|
| Recreate 30-scenario common layer | `data/02_Forecasting/01_DA_prices/hourly_da/scenario_recreation_runs/full_testperiod_donly_3model_30scen_20260611_101630/common_observed_comparison/` and its `layer_run_summary.json` | Any quarter-hour bridge artifact | Preserve hourly `D_only`, common observed support, and 30-scenario cap. |
| Extend support beyond `2025-09-25` | LEAR Strict repaired-anchor lineage plus common-support diagnostics in the model-selection bundle | Current frozen `307`-day ranking as if it already covers more days | Treat this as new support work, not a silent continuation of the frozen ranking. |
| Make all days work / repair support gaps | LEAR Strict repair lineage referenced in `forecast_accuracy_metrics.csv` and support notes | The unsuitable 2026 QH-anchor artifact | Recheck support logic before touching ranking logic. |
| Rerun three-model comparison | Three-model model-selection bundle plus economic run `20260611_135643_common_observed_3model_30scen_dam_only` | `model_max_supported` as ranking basis | Keep common observed support and risk-neutral DAM-only controls fixed for fair reruns. |
| Rerun selected-model 75-scenario sensitivity | `data/03_Hydrogen_Test_Case/dam_only_sensitivity/lear_strict_scenario_count_sensitivity_20260611_172625/` and run `20260612_090310_lear_strict_scenario_count_sensitivity_75scen_full_retry/` | Cross-model reinterpretation of the within-model result | Use it to study tractability and robustness, not to rerank LEAR FS3 or XGBoost. |
| Move to quarter-hourly granularity | This handoff plus quarter-hour forecasting lineage in `docs/RESEARCH_LINEAGE.md` | Mixing synthetic quarter-hour paths with observed hourly truth | Keep truth-type separation explicit. |
| Add `D+4` horizon | This handoff plus the existing forecasting horizon governance | Assuming the `D_only` result automatically transfers | Recheck support, scenario coverage, and runtime with the longer horizon. |
| Add `mFRR` or reserve layer | Current hydrogen DAM-only path and `docs/optimisation/PROJECT_DECISIONS.md` | Using this handoff as if it already includes reserve deliverability evidence | DAM-only should remain the baseline reference. |
| Build steel-plant MILP integration | This handoff for upstream hourly input choice and the hydrogen optimisation governance docs | Reopening model selection from scratch before integration needs it | Use LEAR Strict 30-scenario input as the default upstream feed, retain LEAR FS3 as robustness comparator. |
| Compare 30 vs 75 scenarios | `final_30_vs_75_comparison/lear_strict_30_vs_75_master_table.csv` and `lear_strict_30_vs_75_difference_table.csv` | Directly comparing 75-scenario LEAR Strict against 30-scenario other models | Keep the sensitivity framed as within-model. |
| Inspect runtime scalability | `per_model_runtime_diagnostics.csv`, `runtime_summary.csv`, and `lear_strict_30_vs_75_runtime_metrics.csv` | Reading folder size alone as the main practicality metric | Use solve time and wall time first; output size is secondary. |

## Thesis wording block

For the hourly `D_only` day-ahead input-selection stage, LEAR Strict D-only 1092 repaired anchor is retained as the main downstream scenario model because on the common observed support from `2024-10-01` to `2025-09-25` it combines the strongest overall forecast accuracy, the best empirical scenario coverage, the highest realised adjusted profit in the governed hydrogen DAM-only test, and the lowest emergency-import reliance. The main thesis workflow retains `30` scenarios per day as a tractability setting rather than as an economically neutral simplification. A completed LEAR Strict `75`-scenario sensitivity on the same `307`-day support shows materially better tail coverage, lower emergency import, lower shortfall, and about `EUR 0.588 million` higher realised adjusted profit, but at roughly `2.94x` wall time and `3.50x` solve time. Accordingly, the `75`-scenario result is kept as robustness evidence rather than as a basis to rerank models, and the frozen three-model comparison remains the hourly `30`-scenario common-support benchmark. Key caveats are that LEAR FS3 remains a close robustness comparator, XGBoost remains the machine-learning comparator, and the economic ranking is specific to the current hydrogen DAM-only setup rather than a universal claim about price-model superiority.
