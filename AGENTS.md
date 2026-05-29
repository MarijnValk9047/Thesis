# AGENTS.md

## Current project stage and active goal

This repository is moving from the forecasting workstream into the **optimisation-model workstream** of the thesis.

The active goal is now to build a methodologically sound, reproducible optimisation framework that uses the already-developed Day-Ahead (DA) forecasts and scenario outputs to test the economic and operational value of industrial flexibility.

The first active implementation target is a **Badarinath-inspired green-hydrogen test case**. This test case should be simple enough to verify, but structured so it can later be extended toward a more complex multi-stage stochastic MILP for an electrified steel plant.

The optimisation framework should eventually support:

- DA-only bidding and scheduling;
- comparison of hourly vs quarter-hour DA granularity;
- comparison of D-only vs D+4 forecast/scenario horizons;
- comparison of forecast/scenario inputs from XGBoost FS3, LEAR FS3, and LEAR Strict;
- stochastic optimisation with scenario probabilities;
- CVaR-based risk aversion;
- price-insensitive and perfect-foresight benchmarks;
- later extension to mFRR capacity and activation modelling;
- later extension from the hydrogen test case to a steel-plant MILP.

The optimisation project should be treated as a downstream economic and methodological test bed. The key question is not only which forecast has the lowest error, but whether a given forecast/scenario input leads to better realised bidding, scheduling, risk, and feasibility outcomes.

## Relationship to the forecasting workstream

The existing forecasting instructions are **upstream context**, not the full governing scope of the optimisation workstream.

Earlier forecasting scope deliberately excluded:

- mFRR forecasting;
- probabilistic forecasting;
- optimiser integration;
- economic backtesting.

For this optimisation workstream, **optimiser integration and economic backtesting are now explicitly in scope**.

Do not unnecessarily redesign or rerun the forecasting work. Instead, consume its outputs as inputs:

- deterministic forecasts;
- scenario files;
- scenario probabilities;
- forecast origins;
- delivery timestamps;
- model identifiers;
- granularity labels;
- lead-day / horizon labels;
- scenario-generation diagnostics.

When using forecasting artifacts, preserve the upstream assumptions:

- Forecast origin: **08:00 on D-1** in Europe/Amsterdam time;
- Forecast horizon: **D through D+4** where applicable;
- Store timestamps internally in **UTC**;
- Convert to local time only for reporting and plots;
- No random splits;
- No data leakage;
- No tuning on the final test set;
- Validation-based model/scenario/CVaR selection;
- Observed-target-only scoring for quarter-hour data.

## Thesis-level research framing

The thesis investigates the risk-return performance of demand-side flexibility for energy-intensive industry, especially the steel sector, under volatile electricity markets.

The long-term thesis model should evaluate:

- whether operational flexibility improves economic performance;
- whether increased DA granularity from 60 minutes to 15 minutes changes the value of flexibility;
- whether scenario-based stochastic bidding outperforms simple benchmarks;
- whether CVaR risk aversion reduces downside exposure at acceptable opportunity cost;
- whether mFRR participation adds value beyond DA-only operation;
- whether the optimisation remains physically feasible under industrial constraints and uncertain market outcomes.

The project is inspired by `Master_Thesis_Mukunda_Badarinath.pdf`, especially its staged research design, hydrogen verification case, stochastic bidding model, CVaR formulation, Pyomo/Gurobi implementation, and benchmark logic. However, do not copy it blindly.

Important difference:

- Badarinath mainly compares bidding strategies, including exclusive group bids.
- This thesis currently focuses on comparing **forecast/scenario inputs, market granularity, and forecast horizon**.

Therefore:

- Do **not** implement exclusive group bids unless explicitly reopened later.
- Focus first on normal hourly or quarter-hour price-sensitive DA bidding and settlement.
- Treat bidding-strategy variation as secondary to forecast/scenario/granularity/horizon evaluation.

## Active implementation scope

Implement and maintain:

1. Hydrogen test-case optimisation stack.
2. Deterministic physical scheduling model.
3. Price-insensitive benchmark.
4. Perfect-foresight benchmark.
5. DA-only bidding and settlement logic.
6. Stochastic DA scenario optimisation.
7. CVaR risk-aversion formulation and parameter sweeps.
8. Standardised optimisation metrics and run reporting.
9. Experiment registry and reproducible run folders.
10. Scenario-input adapters for hourly and quarter-hour DA artifacts.

Later, after DA-only test case is stable:

1. mFRR capacity bidding.
2. mFRR activation / MARI energy settlement.
3. Multi-market co-optimisation.
4. Steel-plant process and material-buffer extension.

Do not add mFRR before the DA-only hydrogen test case is explainable, verified, and reportable.

## Out of scope unless explicitly requested

Do not implement yet:

- exclusive group bids;
- full EUPHEMIA market clearing;
- price-making or bi-level market equilibrium;
- intraday market participation;
- long-term investment planning;
- deep reinforcement learning;
- full steel-plant MILP before the hydrogen test case is stable;
- new forecasting-model research unless required to consume existing artifacts.

## Optimisation implementation phases

Develop the model in phases. Each phase should have validation checks and saved outputs before moving on.

### Phase 1 — deterministic hydrogen scheduling

Goal: verify physical logic without stochasticity.

Include at minimum:

- electrolyser power limits;
- hydrogen production efficiency;
- hydrogen storage/buffer state;
- production target or product revenue;
- electricity consumption;
- optional compressor if already present in the test-case design;
- clear units for MW, MWh, kg H2, €/MWh, €/kg.

Outputs:

- dispatch profile;
- storage trajectory;
- production total;
- electricity use;
- objective value;
- feasibility status.

### Phase 2 — benchmarks

Implement two benchmark strategies:

1. **Price-insensitive benchmark**
   - Fixed or simple production logic.
   - Does not react to DA price variation.
   - Settled against realised DA prices.

2. **Perfect-foresight benchmark**
   - Optimises with realised future prices known.
   - Used only as an upper-bound benchmark.
   - Never describe as a realistic operating strategy.

### Phase 3 — DA bidding and settlement

Add DA market participation.

The model should represent bidding and settlement, not just dispatch against known prices.

For the initial simplified version:

- assume price-taking behaviour;
- use hourly or quarter-hour price-sensitive bids;
- simulate whether bids clear against realised market prices;
- translate cleared bids into available electricity / realised procurement;
- report bid clearing and realised settlement separately from forecast-stage objective value.

Be explicit whether the model is choosing:

- quantities only;
- bid prices and quantities;
- or an approximate cleared-consumption policy based on scenario optimisation.

### Phase 4 — stochastic scenario optimisation

Add scenario-indexed uncertainty.

Required:

- scenario IDs;
- scenario probabilities;
- scenario prices;
- coherent trajectories over time;
- non-anticipative first-stage decisions;
- scenario-dependent second-stage dispatch only where information would realistically be available.

Do not sample each hour/quarter independently in a way that destroys temporal structure.

### Phase 5 — CVaR risk aversion

Add CVaR on scenario net cost or downside profit.

Use a transparent linear formulation with:

- VaR threshold variable;
- excess-loss variables per scenario;
- confidence level alpha;
- CVaR weight / risk-aversion parameter.

Perform sensitivity sweeps over the CVaR weight. Select preferred settings using validation-like periods, not final test performance.

### Phase 6 — forecast/scenario comparison experiments

Use the hydrogen test case to compare:

- XGBoost FS3 scenarios;
- LEAR FS3 scenarios;
- LEAR Strict scenarios;
- hourly vs quarter-hour DA granularity;
- D-only vs D+4 horizon, if tractable and meaningful.

The output should show whether better forecast/scenario inputs improve economic performance, not only statistical forecast accuracy.

### Phase 7 — mFRR extension

Only after DA-only works:

- distinguish capacity bids, capacity clearing, activation, energy settlement, and penalties;
- model reserve deliverability as a physical feasibility constraint;
- be careful with sign conventions for load-side upward/downward regulation;
- keep activation scenarios tractable;
- report DA-only vs DA + mFRR incremental value.

### Phase 8 — steel-plant extension

Only after the hydrogen test case is stable:

- add process units stepwise;
- add material balances;
- add process buffers as storage-like components;
- add production targets and penalties;
- add ramping and minimum/maximum operating constraints;
- preserve the same run, reporting, and benchmark structure.

## Scenario undercoverage and stochastic validity

Current DA scenarios are not fully satisfactory: on many days, the realised price path falls partly or fully outside the generated scenario spread.

This is a serious methodological warning, but not automatically fatal.

The optimisation project should explicitly test whether scenario undercoverage materially affects:

- realised net profit or cost;
- downside risk;
- CVaR;
- production fulfilment;
- bid clearing behaviour;
- feasibility;
- reserve deliverability once mFRR is added;
- value captured relative to perfect foresight;
- uplift relative to price-insensitive operation.

Always report scenario diagnostics together with optimisation outcomes.

At minimum, for each scenario input used by the optimiser, record:

- scenario source/model;
- number of scenarios;
- probability convention;
- delivery horizon;
- granularity;
- p50/p90/p95 coverage diagnostics where available;
- realised-path containment diagnostics where available;
- whether stress/tail scenarios are included;
- known limitations.

Do not claim robust risk performance if the scenario tails are known to be poorly calibrated and this has not been tested.

## Fixed time and split methodology

For hourly DA artifacts, preserve the existing thesis split policy unless explicitly changed:

- Train: `2022-01-01` to `2023-09-30`;
- Validation: `2023-10-01` to `2024-09-30`;
- Test: `2024-10-01` to `2025-09-30`.

Forecasting assumptions to preserve:

- daily rolling-origin evaluation;
- forecast origin at `08:00` on `D-1`;
- horizon `D` through `D+4`;
- UTC internally;
- Europe/Amsterdam only for local reporting;
- no random splits;
- no leakage;
- no test-set tuning.

Quarter-hour data rules:

- score observed targets only;
- do not treat interpolated, synthetic, gap-filled, or flagged 15-minute target rows as realised truth;
- keep `y_true = NaN` for non-observed target rows in forecasting evaluation;
- when using frozen synthetic quarter-hour paths for downstream bidding experiments, label them clearly as experiment inputs, not observed-market scoring truth.

DST rule:

- A 5-day local delivery horizon is not always exactly 120 hours or 480 quarter-hours.
- Do not hard-code horizon length without checking DST windows.

## Non-anticipativity and information timing

The optimisation model must respect information release.

First-stage decisions are made before uncertain prices and activation outcomes are realised. These decisions must be identical across scenarios sharing the same information set.

Second-stage decisions may adapt only if the model’s timeline allows that information to be known.

Red flags:

- using realised DA prices to set DA bids;
- using test-set actuals for scenario calibration;
- letting scenario-specific bid decisions differ before uncertainty is revealed;
- using future storage states or future prices in earlier decisions;
- choosing CVaR parameters based on final test performance.

## Technical stack

Use Python in PyCharm.

Default optimisation stack:

- **Pyomo** for model formulation;
- **Gurobi** as solver.

Hydrogen optimisation config default:

- `scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml`

Local Gurobi licence handling:

- use `solver.grb_license_file` to point to the local `gurobi.lic` path;
- runtime may set `GRB_LICENSE_FILE` from that path;
- never commit licence contents, WLS keys, API keys, or secrets.

Prefer readable and modular Pyomo code over compact but opaque formulations.

## Tractability rules

Start small and scale only after validation.

Default progression:

1. 1 asset before multiple assets;
2. 1 day before 1 week;
3. 3 scenarios before 30 scenarios;
4. hourly before quarter-hour if debugging logic;
5. deterministic before stochastic;
6. DA-only before DA + mFRR;
7. continuous relaxation before binary-heavy MILP where possible.

Always report:

- solver status;
- objective value;
- solve time;
- MIP gap;
- number of variables;
- number of binary variables;
- number of constraints;
- infeasibility diagnostics when failed.

Avoid:

- loose Big-M values without justification;
- unnecessary binaries;
- repeated full hyperparameter/model searches inside rolling-origin optimisation;
- overlarge scenario counts before validating basic model logic.

## Directory structure

Keep optimisation work separate from forecasting work.

Recommended structure:

```text
data/
  03_Optimisation/
    inputs/
      market/
      scenarios/
      assets/
      test_cases/
    runs/
      <YYYYMMDD_HHMMSS_experiment_slug>/
        config_resolved.yaml
        input_manifest.json
        model_stats.json
        solver_log.txt
        solution_dispatch.parquet
        submitted_bids.parquet
        settlement_results.parquet
        metrics_summary.csv
        metrics_timeseries.parquet
        figures/
        README_run.md

scripts/
  Data/
    03_Hydrogen_Test_Case/
      configs/
        base_hydrogen.yaml
        experiments/
      src/
        optimisation/
          data_io.py
          config_schema.py
          scenario_adapter.py
          model_builder.py
          variables.py
          constraints/
          objectives.py
          cvar.py
          settlement.py
          metrics.py
          reporting.py
          plotting.py
      run_hydrogen_test_case.py
      run_experiment_batch.py
      create_results_notebook.py
      tests/

docs/
  optimisation/
    PROJECT_DECISIONS.md
    methodology_notes.md
    model_equations.md
    experiment_registry.md
    result_table_definitions.md
    known_issues.md
```

Do not create uncontrolled copies of scripts. Prefer configs and run folders over duplicated code.

## Run folder contract

Every meaningful run must create a self-contained run folder containing:

- resolved config;
- input manifest with paths and file hashes where feasible;
- scenario source metadata;
- model version or git commit if available;
- solver settings;
- model-size statistics;
- solver log;
- dispatch output;
- submitted bids;
- settlement results;
- metric summary;
- time-series metrics;
- plots;
- run-level README with plain-language interpretation;
- warnings and known limitations.

Run folders should make it possible to understand what was run without relying on memory.

## Experiment registry

Maintain a central experiment registry, preferably:

- `docs/optimisation/experiment_registry.md`, or
- `docs/optimisation/experiment_registry.csv`.

Each entry should include:

- run ID;
- date;
- purpose;
- model version;
- scenario source;
- forecast model;
- granularity;
- horizon;
- number of scenarios;
- CVaR settings;
- benchmark type;
- solver status;
- runtime;
- key result;
- whether thesis-usable;
- notes / warnings.

## PROJECT_DECISIONS.md

Create and maintain:

- `docs/optimisation/PROJECT_DECISIONS.md`

Use it to freeze decisions such as:

- no exclusive group bids;
- DA-only before mFRR;
- hydrogen test case before steel-plant MILP;
- Pyomo + Gurobi;
- D-only first;
- D+4 later if tractable;
- scenario probabilities required;
- validation-based CVaR/model/scenario selection;
- perfect foresight is only an upper bound;
- price-insensitive benchmark is required;
- quarter-hour observed-target caveats.

Update this file when a methodological decision is changed.

## Required optimisation metrics

Report results in layers.

### Economic metrics

- realised net profit or net cost;
- expected objective value at optimisation time;
- profit/cost uplift vs price-insensitive benchmark;
- value captured vs perfect foresight;
- DA electricity cost;
- average electricity price paid;
- product revenue;
- production margin;
- imbalance, unused-energy, or non-delivery penalties where relevant;
- later: mFRR capacity revenue;
- later: mFRR activation revenue/cost.

### Risk metrics

- VaR;
- CVaR;
- worst-scenario profit/cost;
- downside-tail mean;
- risk-return frontier over CVaR weights;
- realised outcome vs forecast scenario distribution.

### Reliability and feasibility metrics

- production target fulfilment;
- hydrogen or steel production volume;
- unmet demand or shortfall;
- storage/buffer boundary hits;
- infeasible periods;
- grid-capacity violations if modelled;
- reserve non-delivery once mFRR is added;
- penalty activations.

### Operational metrics

- electrolyser load profile;
- compressor load profile if included;
- storage state trajectory;
- ramping behaviour;
- number of starts/stops if binaries are introduced;
- price responsiveness;
- consumption shifted from high-price to low-price periods.

### Computational metrics

- solve time;
- MIP gap;
- variable count;
- binary variable count;
- constraint count;
- scenario count;
- horizon length;
- memory/runtime warnings.

## Reporting standards

For thesis reporting, produce at least:

1. **Compact thesis-body table**
   - strategy/model;
   - granularity;
   - horizon;
   - net profit/cost;
   - production;
   - average price paid;
   - CVaR or downside-risk indicator;
   - value vs price-insensitive;
   - value captured vs perfect foresight.

2. **Appendix-level detailed table**
   - full metric definitions;
   - units;
   - interpretation;
   - why each metric is used;
   - impact on model/scenario choice.

3. **Diagnostic figures**
   - price/scenario fan vs realised price;
   - dispatch profile;
   - storage trajectory;
   - bid clearing visualisation;
   - profit/cost distribution;
   - CVaR sensitivity curve;
   - benchmark comparison plot.

4. **Run-level README**
   - what was tested;
   - which inputs were used;
   - whether the run is valid;
   - main result;
   - methodological warnings.

## Visual reporting policy

For every plot, table, notebook output, report figure, or thesis-ready visualisation, follow:

- docs/optimisation/VISUALISATION.md

This file defines the chart-selection rules, figure taxonomy, semantic colour mappings, support-statement requirements, thesis-body versus appendix guidance, and anti-patterns for forecast, scenario, bidding, clearing, redispatch, settlement, optimisation, and solver reporting.

Use the shared Python style module:

- src/reporting/visual_style.py

In Python scripts and notebooks, import and apply the project style before plotting:

    from src.reporting.visual_style import (
        COLORS,
        MODEL_COLORS,
        STRATEGY_COLORS,
        MARKET_CHAIN_COLORS,
        apply_visual_style,
        save_figure,
    )

    apply_visual_style()

Do not use default Matplotlib, Pandas, Seaborn, Excel, or notebook colour cycles unless explicitly justified.

Before creating a new recurring plot type, check docs/optimisation/VISUALISATION.md. If the required figure type is not covered, add the chart-selection rule or figure contract there first.

## Forecasting metrics carried into optimisation context

Do not rely only on MAE/RMSE to choose optimisation inputs.

When available, use forecasting diagnostics to interpret optimisation results:

- MAE;
- RMSE;
- bias;
- rMAE;
- tail MAE;
- top/bottom-k hit rates;
- daily Spearman rank correlation;
- contiguous operating-window regret;
- high-low spread error;
- scenario coverage;
- realised-path containment.

The optimiser may prefer a forecast with slightly worse MAE if it better identifies cheap operating windows or avoids extreme downside events.

## Code structure rules

- Put reusable logic in shared modules.
- Keep notebooks focused on interpretation, not core implementation.
- Use configs instead of hardcoded experiment settings.
- Inspect existing files before creating new ones.
- Archive outdated artifacts instead of deleting blindly.
- Keep functions small and named by modelling role.
- Prefer explicit units and comments for constraints.
- Use clear constraint names to help infeasibility diagnosis.
- Avoid unused imports.

## Command-centre maintenance contract

Whenever an agent adds or changes any of the following:

- scenario model;
- artifact ID;
- selected period or selected-week policy;
- split definition;
- granularity;
- horizon;
- market scope;
- asset configuration;
- risk mode;
- output mode;
- method version;
- runner/backend;
- benchmark policy;
- methodological approximation option;

it must update:

1. `scripts/Data/03_Hydrogen_Test_Case/configs/optimisation_supported_options.yaml`
2. `docs/optimisation/RUN_COMMAND_CENTRE_GUIDE.md`
3. command-centre validation and doctor checks
4. relevant tests
5. any affected run contract docs

If one of these items changes without updating the registry and guide, the task is incomplete.

## Methodological red flags

Warn explicitly if any of the following occur:

- test-set tuning;
- scenario selection based on test performance;
- comparing hourly and quarter-hour cases while changing other assumptions;
- treating synthetic quarter-hour paths as observed truth;
- using scenario files without probabilities;
- independent per-time-step scenario sampling;
- missing non-anticipativity;
- reporting expected profit without realised settlement;
- reporting profit without production fulfilment;
- hiding infeasibility behind penalties without reporting violations;
- adding mFRR before DA-only is stable;
- implementing full steel-plant complexity before the hydrogen case is verified;
- using perfect foresight as anything other than an upper bound;
- silently changing units between MW, MWh, €/MWh, kg H2, and €/kg.

## Documentation style

Be beginner-friendly but methodologically strict.

When writing prompts or implementation plans, include:

- goal;
- files to inspect;
- files to modify;
- assumptions;
- model equations or pseudocode;
- required outputs;
- validation checks;
- methodological warnings;
- acceptance criteria.

Prefer transparency, reproducibility, and comparability over unnecessary model complexity.
