# Production-First Rolling Target Envelope Design V1

## Purpose

This note defines the smallest safe path from the current hydrogen production-target logic toward a production-first rolling delivery-target envelope.

It is a design note only. It does not change the Pyomo model yet.

## 1. Current Production-Target Logic

### 1.1 Active one-day and small-week `mFRR` diagnostic path

The current capacity-only `mFRR` smoke diagnostics do **not** use a hard daily minimum. They run the hydrogen dispatch model in a soft daily target mode:

- config source:
  - `scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml`
- runner entry points:
  - `scripts/Data/03_Hydrogen_Test_Case/run_mfrr_capacity_one_day_exact_comparison_refresh_v1.py`
  - `scripts/Data/03_Hydrogen_Test_Case/run_mfrr_capacity_integer_week_diagnostic_v1.py`
- model implementation:
  - `scripts/Data/03_Hydrogen_Test_Case/hydrogen/optimisation_model.py`

Observed config keys:

- `production.target_semantics = lower_bound_reference`
- `production.allow_above_target_production = true`
- `production.allow_above_target_sales = true`
- `economics.daily_target_kg = 19000.0`
- `economics.shortfall_penalty_eur_per_kg = 20.0`
- `economics.terminal_inventory_location = before_compression`
- `hydrogen_system.storage_initial_kg = 5000.0`
- `hydrogen_system.storage_capacity_kg = 10000.0`

Observed runner behaviour:

- both `mFRR` diagnostic runners call `solve_stochastic_dispatch(...)` with:
  - `production_target_mode = "current_soft_target"`
  - `daily_target_kg = config.economics.daily_target_kg`
  - `apply_terminal_value = True`
  - `terminal_reference_start_kg = config.hydrogen_system.storage_initial_kg`

### 1.2 Current Pyomo production constraint and objective logic

In `hydrogen/optimisation_model.py`, the current stochastic dispatch model:

- creates one nonnegative scalar shortfall variable: `m.shortfall`
- computes total compressed hydrogen over the horizon:
  - `sum_h_comp = sum(m.H_comp[t] for t in horizon)`
- interprets target mode through `_is_hard_target_mode(...)`

Current hard-mode behaviour:

- if `production_target_mode in {"hard_daily_target", "weekly_hard_band_target"}`:
  - `sum_h_comp >= target_hydrogen_min_kg`
  - optional `sum_h_comp <= target_hydrogen_max_kg`
  - `m.shortfall == 0.0`

Current soft-mode behaviour:

- otherwise:
  - `sum_h_comp + m.shortfall >= target_hydrogen_min_kg`

Current objective terms relevant to production:

- hydrogen revenue on all compressed hydrogen:
  - `revenue_expr = h2_sale_price_eur_per_kg * sum_h_comp`
- shortfall penalty:
  - `shortfall_penalty_expr = effective_shortfall_penalty * m.shortfall`
- terminal inventory value:
  - `terminal_value_expr = terminal_value_per_kg * (m.H_buf[t_max] - terminal_reference_start_kg)`

Interpretation:

- the current `mFRR` smoke path uses a **soft lower bound** plus shortfall penalty;
- production above the nominal daily target is allowed and economically rewarded;
- terminal inventory is also valued;
- there is no explicit future delivery calendar or future-feasibility reservation.

### 1.3 Legacy production-target modules already in the repo

The repo already contains a second, stricter production-target path outside the current `mFRR` smoke tests:

- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/production_target.py`
- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/weekly_hard_band_target.py`

Existing target modes found:

- `current_soft_target`
- `high_shortfall_penalty`
- `hard_daily_target`
- `weekly_hard_band_target`

The weekly hard-band path already carries a cumulative-style tracker, but only at the weekly band level:

- `WeeklyHardBandSettings`
- `compute_weekly_target_day_bounds(...)`
- `compute_weekly_target_day_bounds_for_variant(...)`

That logic computes daily lower and upper bounds from:

- remaining weekly target;
- remaining included days;
- `daily_min_fraction`;
- `daily_max_fraction`;
- optional physical daily max in the `weekly_hard_band_off` variant.

This is useful precedent, but it is not the same as a delivery-deadline calendar.

### 1.4 Where production-target logic is and is not defined

Current logic exists in multiple places:

- config values:
  - `scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml`
- config dataclasses and parser:
  - `scripts/Data/03_Hydrogen_Test_Case/hydrogen/plant_parameters.py`
- target-mode helpers:
  - `scripts/Data/03_Hydrogen_Test_Case/hydrogen/production_target.py`
- weekly hard-band accounting:
  - `scripts/Data/03_Hydrogen_Test_Case/hydrogen/weekly_hard_band_target.py`
- Pyomo/PuLP production constraints:
  - `scripts/Data/03_Hydrogen_Test_Case/hydrogen/optimisation_model.py`
- benchmark duplicate target logic:
  - `scripts/Data/03_Hydrogen_Test_Case/hydrogen/benchmarks.py`
- runner-level mode selection for the current `mFRR` smoke path:
  - `run_mfrr_capacity_one_day_exact_comparison_refresh_v1.py`
  - `run_mfrr_capacity_integer_week_diagnostic_v1.py`

No current production-target logic was found in:

- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/optimisation/input_resolver.py`

That resolver is not the first place to change unless the future target calendar is loaded from an external governed file instead of from YAML config.

### 1.5 How production currently interacts with `mFRR`

Current `mFRR` capacity variables reserve flexibility against the operating point:

- Up reserve is bounded by current site load:
  - `offered_up <= P_el[t] + P_comp[t]`
- Down reserve is bounded by headroom:
  - `offered_down <= max_site_load - (P_el[t] + P_comp[t])`

This means optional `mFRR` changes production through:

1. the corrected capacity-revenue incentive;
2. the fact that hydrogen production is rewarded above the nominal target;
3. the terminal inventory value term;
4. the absence of a rolling future-delivery feasibility guard.

So the recent positive Up-capacity result is not evidence that future delivery obligations are protected. It only shows that the current soft-target capacity-only formulation can afford to reserve load while still looking attractive within the one-day objective.

## 2. Proposed Rolling Target Envelope

### 2.1 Design objective

Replace the implicit instruction:

- "produce at least X today"

with:

- "meet cumulative known delivery obligations by their deadlines, while keeping future delivery feasible."

This should become the default production-first interpretation for later `mFRR` work.

### 2.2 Proposed target calendar input

Add a new config-supported production target calendar with rows such as:

- `delivery_id`
- `due_date`
- `required_quantity_kg`
- optional `earliest_production_date`
- optional `product_type`
- optional `priority`
- optional `inventory_allowed`
- optional `maximum_inventory_or_credit_kg`

For the first implementation, only these should be binding:

- `delivery_id`
- `due_date`
- `required_quantity_kg`

The others can be parsed and validated without being fully active yet.

### 2.3 Proposed linear state and constraints

Minimal conceptual objects:

- `initial_inventory_or_credit_kg`
- cumulative production by each modelled day or period
- cumulative required delivery by each known due date
- optional bounded production-credit / inventory stock

Core constraint family:

- `initial_inventory_or_credit_kg + cumulative_production_by_due_date >= cumulative_required_delivery_by_due_date`

Optional cap:

- `inventory_or_credit_kg <= max_inventory_or_credit_kg`

Interpretation:

- production can move freely across the horizon;
- the model is not told to hit a fixed daily minimum unless that is explicitly selected as a legacy mode;
- feasibility is enforced at delivery deadlines, not by rigid same-day quotas.

### 2.4 Terminal feasibility protection

#### D-only

For D-only runs, the model still needs protection against "borrowing from the future."

Minimal rule:

- after the model chooses today’s production, the remaining unmet cumulative obligations up to each future known due date must still be coverable by the maximum physically feasible production remaining before that due date.

This should be implemented as a linear preprocessing-based guard:

1. compute maximum feasible future hydrogen production for each remaining day before each due date;
2. derive a required minimum cumulative production by the end of today;
3. enforce that minimum inside the D-only optimisation.

This is the production-first envelope for the current one-day `mFRR` smoke structure.

#### D+4

For D+4 runs:

- optimise directly across the five-day horizon;
- apply the same cumulative deadline constraints inside the horizon;
- still add a terminal feasibility guard if known targets extend beyond the five-day window.

### 2.5 Inventory / production-credit interpretation

For the first implementation, treat the existing hydrogen buffer plus any terminal production-credit concept conservatively:

- do not redesign product settlement;
- do not add a separate commercial inventory system unless needed;
- allow one linear "delivery credit" interpretation that can be mapped to existing buffer/terminal accounting.

The first implementation can start with:

- `initial_inventory_or_credit_kg = storage_initial_kg` or an explicit configured value;
- a separate configurable cap if needed.

The later implementation should be explicit about whether deadline satisfaction is measured using:

- compressed hydrogen only;
- end-of-day deliverable inventory;
- or another delivery-ready quantity.

The current code uses `H_comp` as the sold/delivered quantity, so the first refactor should stay aligned with that unless there is a strong reason to change the commercial meaning.

## 3. Minimal Implementation Plan

### Phase 1: config and parser only

Add config support for a simple production target calendar.

Files to change:

- `scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml`
- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/plant_parameters.py`
- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/production_target.py`

Requirements:

- preserve existing scalar daily target mode as legacy fallback;
- add a new target mode name for the rolling envelope;
- add parser and validation only;
- do not change optimisation behaviour yet if legacy mode is selected.

### Phase 2: Pyomo delivery-deadline constraints

Add rolling cumulative target logic to the main optimisation model.

Files to change:

- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/optimisation_model.py`
- likely `scripts/Data/03_Hydrogen_Test_Case/hydrogen/benchmarks.py` for parity or explicit guardrails

Requirements:

- add cumulative production / delivery-deadline constraints;
- preserve current `mFRR` capacity-only logic unchanged;
- keep integer MW `mFRR` bids unchanged;
- keep v2 `EUR/MW/ISP x contract_isp_count` revenue scaling unchanged.

### Phase 3: terminal feasibility protection

Add D-only and D+4 terminal feasibility protection.

Files to change:

- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/optimisation_model.py`
- optionally a small helper module if the preprocessing becomes noisy

Requirements:

- prevent hidden underproduction that only becomes visible after the optimisation horizon;
- report any computed production-feasibility margins explicitly;
- do not hide infeasibility behind penalties.

### Phase 4: diagnostic rerun

Re-run the current integer `mFRR` capacity diagnostics after the production-first envelope is active.

Expected files to touch only if needed:

- `run_mfrr_capacity_one_day_exact_comparison_refresh_v1.py`
- `run_mfrr_capacity_integer_week_diagnostic_v1.py`

Goal:

- test whether positive Up-capacity still survives after future delivery feasibility is protected.

## 4. Proposed Config Schema

### 4.1 New rolling-envelope mode

```yaml
production_targets:
  mode: rolling_deadline_envelope
  initial_inventory_kg: 0
  max_inventory_kg: 50000
  targets:
    - delivery_id: target_2025_07_14
      due_date: 2025-07-14
      required_quantity_kg: 80000
    - delivery_id: target_2025_07_18
      due_date: 2025-07-18
      required_quantity_kg: 100000
```

### 4.2 Legacy fallback mode

```yaml
production_targets:
  mode: legacy_daily_minimum
```

### 4.3 Recommended compatibility rule

Keep the existing fields during transition:

- `economics.daily_target_kg`
- `economics.shortfall_penalty_eur_per_kg`
- `production.target_semantics`

Recommended interpretation:

- if `production_targets.mode = legacy_daily_minimum`, current scalar target logic remains active;
- if `production_targets.mode = rolling_deadline_envelope`, the new calendar becomes authoritative and scalar daily target values become legacy-only compatibility inputs.

## 5. Acceptance Criteria For The Later Implementation

- old one-day and one-week `mFRR` diagnostics still run under legacy mode;
- rolling mode has no fixed daily minimum unless explicitly configured;
- no hidden shortfall is absorbed silently by penalties without reporting;
- D-only runs have terminal feasibility protection;
- D+4 runs can optimise directly across the full five-day horizon;
- `mFRR` capacity remains integer MW with the existing 1 MW minimum linkage;
- v2 capacity revenue scaling remains unchanged:
  - `EUR/MW/ISP x contract_isp_count`
- no activation, energy-bid optimisation, settlement, sanctions, `MARI`, accepted/rejected branching, or 4-hour products are introduced.

## 6. Exact Next File-Level Change Set

The smallest safe next implementation prompt should target:

1. `scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml`
2. `scripts/Data/03_Hydrogen_Test_Case/hydrogen/plant_parameters.py`
3. `scripts/Data/03_Hydrogen_Test_Case/hydrogen/production_target.py`
4. `scripts/Data/03_Hydrogen_Test_Case/hydrogen/optimisation_model.py`
5. `scripts/Data/03_Hydrogen_Test_Case/hydrogen/benchmarks.py`

Legacy runners to keep stable during the refactor:

6. `scripts/Data/03_Hydrogen_Test_Case/run_mfrr_capacity_one_day_exact_comparison_refresh_v1.py`
7. `scripts/Data/03_Hydrogen_Test_Case/run_mfrr_capacity_integer_week_diagnostic_v1.py`

Not first-place changes for the next prompt:

- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/optimisation/input_resolver.py`
  - no current production-target logic there
- `docs/optimisation/nl_ir_capacity_milp_export_contract_v2.md`
  - export contract is already correct and should stay unchanged

## 7. Main Risks And Open Questions

1. **Delivery quantity definition**
   - the current model rewards `H_comp` directly;
   - the rolling envelope must decide whether due-date fulfilment is measured on `H_comp`, inventory drawdown, or another deliverable quantity.

2. **Terminal inventory value overlap**
   - the current objective values terminal inventory;
   - once delivery deadlines are introduced, this value term must not double-count commercial value already embedded in the delivery-credit logic.

3. **Legacy weekly hard-band coexistence**
   - the repo already has `weekly_hard_band_target`;
   - the next implementation should preserve it as a legacy option or explicitly wall it off, not half-merge it with the new envelope.

4. **Benchmark parity**
   - `hydrogen/benchmarks.py` duplicates target logic;
   - leaving that file unchanged while changing the main model would create interpretation drift.

5. **D-only feasibility preprocessing**
   - the terminal-feasibility guard should stay linear and light;
   - it should be based on conservative physical max production, not on optimistic future redispatch assumptions.

## 8. Phase 1 Schema Status

Implemented in the repository in the first parser-only step:

- a new explicit `production_targets` config branch in `base_hydrogen.yaml`;
- parser support in `hydrogen/plant_parameters.py`;
- schema-mode validation helpers in `hydrogen/production_target.py`.

Implemented schema:

```yaml
production_targets:
  mode: legacy_daily_minimum
  initial_inventory_kg: 0.0
  max_inventory_kg: null
  terminal_inventory_value_mode: legacy
  targets: []
```

Supported modes:

- `legacy_daily_minimum`
- `rolling_deadline_envelope`

Implemented validation rules:

- `delivery_id` required and unique;
- `due_date` required and ISO-date parseable;
- `required_quantity_kg` required and nonnegative;
- optional `earliest_production_date` must be parseable if present;
- optional `product_type` is normalized to string if present;
- optional `priority` accepts numeric or string values;
- optional `inventory_allowed` accepts boolean-style YAML input;
- optional `maximum_inventory_or_credit_kg` must be nonnegative if present;
- `rolling_deadline_envelope` fails if `targets` is empty.

Legacy fallback behaviour intentionally preserved:

- existing scalar keys such as `economics.daily_target_kg` and `economics.shortfall_penalty_eur_per_kg` remain in place;
- existing runners still pass `production_target_mode="current_soft_target"`;
- the optimiser does not consume `production_targets.targets` yet;
- terminal inventory value logic is unchanged and `terminal_inventory_value_mode` is schema-only for now.

Intentionally not changed yet:

- no Pyomo cumulative deadline constraints;
- no terminal feasibility guard;
- no production-first flexibility envelope;
- no change to `mFRR` v2 export consumption, integer MW bidding, or capacity revenue scaling.

Next implementation step:

- add cumulative deadline constraints and D-only terminal-feasibility protection inside the Pyomo model while preserving the legacy mode as a runnable fallback.

## 9. Phase 2 Implementation Status

Implemented in the second model-side step:

- `hydrogen/optimisation_model.py` now consumes the parsed `production_targets` settings;
- `hydrogen/production_target.py` now preprocesses rolling cumulative deadline bounds and terminal-feasibility guard bounds;
- `hydrogen/benchmarks.py` now respects the rolling branch for optimisation-based benchmark solves and fails clearly for the legacy heuristic path.

### 9.1 Legacy mode behaviour

Legacy mode remains unchanged:

- `production_targets.mode = legacy_daily_minimum` keeps the existing daily target and shortfall logic;
- existing soft-target and hard-target semantics remain in place;
- `mFRR` capacity logic, integer MW bidding, and v2 `EUR/MW/ISP x contract_isp_count` scaling are unchanged.

### 9.2 Implemented rolling constraints

When `production_targets.mode = rolling_deadline_envelope`:

- the legacy fixed daily minimum constraint is not used;
- the legacy shortfall slack is not used to satisfy rolling targets;
- the model enforces hard cumulative delivery-deadline constraints on `H_comp`.

Implemented due-date interpretation:

- `due_date` is treated as due by the **end of that local Europe/Amsterdam delivery day**;
- there are no intra-day delivery times in this first implementation.

Implemented in-horizon constraint form:

- `initial_inventory_kg + cumulative_H_comp_until_due >= cumulative_required_kg_by_due`

where:

- `initial_inventory_kg` comes from `production_targets.initial_inventory_kg`;
- `cumulative_H_comp_until_due` is summed through the last optimisation interval of the due date;
- cumulative required quantity is aggregated over all targets due on or before that date.

### 9.3 Implemented terminal-feasibility guard

Implemented as preprocessing in `hydrogen/production_target.py`, then added as linear lower-bound constraints in the model.

For targets due after the optimisation horizon:

- the model computes a conservative future maximum deliverable quantity after the horizon and before each due date;
- then enforces a minimum production requirement by horizon end only if needed.

Implemented lower bound:

- `sum_H_comp_over_horizon >= max(0, cumulative_required_by_due - initial_inventory_kg - conservative_future_max_production_after_horizon_before_due)`

Conservative future daily maximum formula:

- per local day, future deliverable hydrogen is bounded by:
  - a zero-start electrolyser ramp-up profile using the model timestep size and configured ramp rate;
  - compressor throughput over the DST-aware local day length;
  - the daily cap is the minimum of those two limits.

This is intentionally conservative:

- it does not assume a favourable post-horizon starting power level;
- it uses the local-day duration directly, so DST 23-hour and 25-hour days are handled explicitly.

### 9.4 Inventory / production-credit cap

Implemented in linear form when `production_targets.max_inventory_kg` is not null:

- `initial_inventory_kg + cumulative_H_comp_until_t - cumulative_required_due_by_t <= max_inventory_kg`

with `cumulative_required_due_by_t` jumping only at the end of due dates, consistent with the date-only deadline interpretation.

### 9.5 Terminal inventory value handling

Implemented:

- if `production_targets.terminal_inventory_value_mode = disabled`, the terminal inventory value term is disabled in rolling mode;
- if `production_targets.terminal_inventory_value_mode = legacy`, the legacy terminal inventory value term remains active.

Important caveat:

- `legacy` terminal inventory value may still double count economic value relative to delivery-credit logic;
- this is preserved only as an explicit transitional mode.

### 9.6 Benchmark behaviour

Implemented:

- optimisation-based benchmark paths now pass the parsed `production_targets` settings into the shared dispatch solver;
- the legacy `price_insensitive_heuristic` benchmark fails clearly in rolling mode instead of silently ignoring the target calendar.

### 9.7 Still out of scope

Still not implemented here:

- activation, settlement, sanctions, `MARI`, or accepted/rejected branching;
- energy-bid optimisation;
- production-first `mFRR` flexibility reservation beyond the cumulative delivery-target logic;
- a redesign of the broader economics layer;
- explicit product delivery times inside a day.

## 10. Rolling Economics Note

Rolling mode now uses a more conservative economics interpretation than legacy mode:

- legacy mode still values all `H_comp` with the configured hydrogen sales revenue;
- rolling mode no longer treats all `H_comp` as unlimited sellable output;
- in rolling mode, delivery targets are enforced as constraints and extra production is only meaningful as bounded production credit / inventory;
- meaningful rolling diagnostics should therefore use a finite `max_inventory_kg` instead of leaving production credit unbounded.
