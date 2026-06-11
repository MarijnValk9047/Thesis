# mFRR-DA Recourse Interface Inspection V1

## Purpose

This note is an inspection-only interface design for how accepted or rejected Dutch incident-reserve / `mFRRda` capacity results should feed into the existing day-ahead hydrogen bidding and procurement stack.

It does not implement the integration.

Real-world order to preserve:

```text
capacity bid -> capacity result -> DA bidding -> DA results -> energy bids -> activation
```

Modelling correction to preserve:

- the capacity-bid model must look ahead to later DA procurement, production feasibility, reserve obligations, energy-bid obligations, activation feasibility proxies, and recovery limits before offering capacity

---

## 1. Existing DAM MILP inventory

### Main DA model surface

The current DA stack is split across three layers:

1. **Explicit DA bidding MILP**
   - `scripts/Data/03_Hydrogen_Test_Case/hydrogen/bidding_model.py`
   - framework: **Pyomo first**, with **PuLP fallback**
   - model type: explicit **price-taking DA demand bidding**
   - first-stage: bid quantities `q[t,b]` on a fixed bid-price grid
   - second-stage: scenario-dependent physical recourse after scenario clearing

2. **DA clearing utilities**
   - `scripts/Data/03_Hydrogen_Test_Case/hydrogen/clearing.py`
   - does deterministic price-taking bid acceptance with `bid_price >= actual_price`
   - aggregates submitted, cleared, and rejected energy

3. **Post-clearing deterministic redispatch**
   - `scripts/Data/03_Hydrogen_Test_Case/hydrogen/redispatch.py`
   - framework: **Pyomo first**, with **PuLP fallback**
   - consumes cleared DA energy and re-optimises physical operation

### Older schedule-first hydrogen MILP still in use

- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/optimisation_model.py`
- framework: **Pyomo first**, with **PuLP fallback**
- model type: stochastic **dispatch/procurement against scenario prices**, not explicit DA bid optimisation
- this is where the current `mfrr_capacity_pilot` logic is attached today

### Runners

- explicit DA bidding dry run:
  - `scripts/Data/03_Hydrogen_Test_Case/run_real_scenario_bidding_dry_run.py`
  - backed by `scripts/Data/03_Hydrogen_Test_Case/hydrogen/bidding_backtest.py`

- current mFRR capacity pilot diagnostics:
  - `scripts/Data/03_Hydrogen_Test_Case/run_mfrr_capacity_one_day_exact_comparison_refresh_v1.py`
  - `scripts/Data/03_Hydrogen_Test_Case/run_mfrr_capacity_rolling_target_overlay_smoke_v1.py`
  - `scripts/Data/03_Hydrogen_Test_Case/run_mfrr_capacity_rolling_target_stress_grid_v1.py`

### Configs and input adapters

- main config:
  - `scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml`

- scenario catalog / loader:
  - `scripts/Data/03_Hydrogen_Test_Case/configs/scenario_catalog.yaml`
  - `scripts/Data/03_Hydrogen_Test_Case/hydrogen/scenario_loader.py`

- DA + mFRR input slicing:
  - `scripts/Data/03_Hydrogen_Test_Case/hydrogen/optimisation/input_resolver.py`

### Inputs consumed

Current DA bidding path consumes:

- scenario tables with:
  - `forecast_origin_utc`
  - `delivery_start_utc`
  - `delivery_day`
  - `scenario_id`
  - `scenario_probability`
  - `scenario_price_eur_per_mwh`
  - `actual_price_eur_per_mwh`
  - `model_id`
  - `lead_day`
  - `granularity`
- hydrogen config and asset parameters from `base_hydrogen.yaml`

Current mFRR pilot path additionally consumes:

- repaired `mFRR` capacity export:
  - `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/milp_exports/nl_ir_capacity_milp_input_daily_direction_scenarios_v2.csv`

### Outputs written

Current DA dry run writes:

- `submitted_bids.parquet`
- `actual_clearing.parquet`
- `actual_clearing_by_hour.parquet`
- `actual_redispatch_timeseries.parquet`
- `actual_settlement_results.csv`
- `scenario_clearing.parquet`
- `scenario_dispatch.parquet`
- `scenario_settlement_results.csv`
- `scenario_objective_summary.csv`
- `metrics_summary.csv`
- `validation_checks.csv`
- manifests / model stats / README

### Granularity, market semantics, uncertainty, timing

- current explicit DA bidding MILP is **hourly**
- current real-scenario dry run is **D-only**
- current explicit DA market logic is **price-taking procurement via explicit DA demand bids**
- current older `optimisation_model.py` path is **stochastic price-taking procurement / dispatch**, but **not** explicit DA bid optimisation
- current DA bidding MILP uses **stochastic scenarios** with probabilities
- current loaders already preserve:
  - `forecast_origin_utc`
  - `delivery_day`
  - `lead_day`
  - UTC timestamps
  - D-only filtering logic

### Key inventory conclusion

There is **not** one single standalone “DAM MILP” file. The current DA implementation is a **stack**:

- `bidding_model.py` for DA bid optimisation
- `clearing.py` for price-taking DA clearing
- `redispatch.py` for post-clearing physical recourse

The older `optimisation_model.py` is still important because the current `mFRR` capacity pilot is attached there, but it is **not** the final DA bidding interface to extend if the goal is accepted/rejected reserve effects on DA bids.

---

## 2. Existing production model relation

### Relation between DA bidding MILP and hydrogen production model

- the DA bidding MILP is **separate from** the older stochastic dispatch model in `optimisation_model.py`
- both use the **same hydrogen asset assumptions**
  - electrolyser min/max
  - ramping
  - compressor power relation
  - storage balance
  - reserve floor
  - target / shortfall logic

### Reuse vs duplication

- physical logic is **partly duplicated**, not fully shared through one common model builder
- `bidding_model.py` defines its own scenario-indexed `P_el`, `P_comp`, `H_prod`, `H_comp`, `H_buf`, `shortfall`, `used_energy`, `unused_cleared_energy`
- `optimisation_model.py` defines a similar hydrogen schedule model, but without explicit DA bid variables
- `redispatch.py` defines another deterministic physical recourse model from cleared energy

### Time index and granularity

- current explicit DA bidding stack is **hourly**
- current `mFRR` capacity export and obligations are **ISP / 15-minute based**
- therefore the current DA stack and current `mFRR` obligation timing are already on **different grids**

### Production target logic

- older baseline config still defaults to `legacy_daily_minimum`
- rolling production target logic exists in:
  - `scripts/Data/03_Hydrogen_Test_Case/hydrogen/production_target.py`
- current `mFRR` capacity pilot in `optimisation_model.py` already uses rolling target and credit-headroom proxies
- current `bidding_model.py` does **not** yet consume the rolling target planner directly

### Inventory / credit concept

- rolling production-credit / inventory-cap logic is present on the `optimisation_model.py` side
- the current DA bidding MILP does **not** yet expose the same rolling-credit structure directly

### Reuse conclusion

- rolling production targets are **methodologically reusable**
- but they are **not plug-and-play reusable today** in the explicit DA bidding MILP
- an adapter is needed to translate accepted `mFRR` capacity obligations into DA-side procurement / reserve constraints without blindly copying the older proxy model

---

## DAM production model versus mFRR capacity-pilot production logic

- **Time granularity**: both current models are hourly on the DA side, but the accepted-capacity adapter now translates ISP / 15-minute `mFRR` blocks into hourly DA obligations with a conservative hourly max rule.
- **Solver / stage structure**: `bidding_model.py` is an explicit DA bidding MILP with first-stage bid quantities `q[t,b]` and scenario-indexed physical recourse, while `optimisation_model.py` is a schedule-first stochastic dispatch / procurement model with one physical operating point per time step.
- **Production and load variables**: both models use electrolyser, compressor, hydrogen production, buffer, and target / shortfall logic, but only `optimisation_model.py` exposes direct non-scenario load expressions like `P_el[t] + P_comp[t]` that the current `mFRR` pilot already binds against.
- **DA bidding / procurement surface**: `bidding_model.py` has explicit DA bid quantities and later clearing plus redispatch, while `optimisation_model.py` optimises electricity use against scenario prices without explicit DA bid blocks.
- **Scenario probabilities and timing metadata**: both paths preserve `forecast_origin_utc`, delivery timestamps, and scenario probabilities; the explicit DA bidding path is already structured around delivery-day bidding and later actual-price clearing.
- **Production target / inventory logic**: the capacity-pilot path already consumes rolling production-target logic and reserve-feasibility proxies; the explicit DA bidding path still uses duplicated physical logic and does not yet expose the same rolling-credit interface cleanly at the bidding stage.
- **Redispatch relation**: the explicit DA stack already has a separate deterministic redispatch model after clearing; this exists in DAM but not in the older capacity-pilot path and must not be duplicated inside the adapter.
- **Reserve-expression conclusion**: accepted reserve obligations cannot yet be enforced safely in `bidding_model.py` using an existing shared scheduled-load or load-headroom expression, because its physical variables are scenario-indexed recourse variables rather than one scenario-independent DA operating-point interface.

### What must not be duplicated

- Do not copy the `optimisation_model.py` hydrogen physics into the adapter.
- Do not add a second production MILP beside `bidding_model.py` to manufacture reserve headroom.
- Do not reinterpret scenario-indexed recourse variables as a clean DA scheduled-load commitment without an explicit modelling decision.

### Hook status

- The standalone adapter now exists at `scripts/Data/03_Hydrogen_Test_Case/hydrogen/mfrr_da_recourse.py`.
- A DAM reserve-obligation hook was **not** added in Phase G/H.1 continuation, because the current bidding MILP does not expose a safe existing interface for:
  - scenario-independent scheduled reducible load for accepted Up reserve; or
  - scenario-independent available load-increase headroom for accepted Down reserve.
- The next clean implementation step is to define that DAM-side operating-point interface explicitly before adding reserve-preservation constraints.

---

## 3. Required mFRR -> DAM recourse interface

### Minimal branch logic

For accepted capacity:

```text
accepted_capacity_mw[t, direction] > 0
reserved_flexibility_mw[t, direction] >= accepted_capacity_mw[t, direction]
energy_bid_obligation[t, direction] = true
```

For rejected capacity:

```text
accepted_capacity_mw[t, direction] = 0
reserved_flexibility_mw[t, direction] = 0
energy_bid_obligation[t, direction] = false
```

unless flexibility is deliberately retained for another explicit reason.

### Where the interface should enter

Recommended insertion point is **between capacity result and DA bidding**, as a compact adapter that prepares DA-side reserve constraints for the explicit bidding stack.

It should feed at least two DA-side effects:

1. **Bid formation effect**
   - accepted Up/Down reserve changes what DA procurement is allowed or required to preserve
   - this should shape the feasible DA bid curve before clearing

2. **Physical recourse effect**
   - accepted reserve must remain visible during post-clearing redispatch
   - rejected reserve must not bind DA redispatch

### Recommended interface payload

Use a compact normalized table with these fields:

```text
forecast_origin
delivery_date
delivery_timestamp
isp_start
isp_end
direction
capacity_contract_block_id
capacity_product_structure
offered_capacity_mw
accepted_capacity_mw
accepted_flag
capacity_price_eur_per_mw_isp
contract_isp_count
energy_bid_obligation_if_accepted
activation_modelled
model_stage
scenario_id
scenario_probability
```

### Recommended DA-side derived fields

The adapter should derive, at minimum:

```text
reserved_up_mw_hour[h]
reserved_down_mw_hour[h]
energy_bid_obligation_up_hour[h]
energy_bid_obligation_down_hour[h]
accepted_capacity_revenue_eur
capacity_branch_label
```

For the current hourly DA model, `ISP` obligations should be aggregated conservatively into hourly envelopes, not silently ignored.

### Recommended implementation boundary

Do **not** feed accepted/rejected capacity straight into raw bid-price logic first.

Instead:

1. normalize accepted/rejected capacity results
2. convert ISP obligations to the DA model time grid
3. produce hourly reserve obligations / reserve masks
4. pass those as exogenous constraints into DA bid formation and actual redispatch

### Why a wrapper is preferred

This avoids coupling the current capacity-only proxy inside `optimisation_model.py` directly into the explicit DA bidding MILP before the timing and branch semantics are frozen.

---

## 4. Minimal smoke-test design

### Candidate positive-reserve corners

Use the already surviving corners:

```text
Up case:
tight_tomorrow_40000 + credit_20000

Down case:
loose_tomorrow_20000 + credit_5000 or credit_20000
```

### Branches

For each corner, run two deterministic branch inputs:

```text
accepted branch:
  accepted reserve obligation > 0
  DA/prod plan must preserve reserve

rejected branch:
  accepted reserve = 0
  DA/prod plan has no reserve obligation
```

### Minimal scope

- one day only
- deterministic branch inputs only
- no stochastic accepted/rejected tree
- no activation settlement
- no energy-bid price optimisation

### Required smoke-test outputs

```text
DA procurement cost
production fulfilled
end inventory_or_credit
accepted reserve MW
reserved Up MW
reserved Down MW
reserve feasibility slack
capacity revenue if accepted
net objective
energy_bid_obligation_created
```

### Recommended comparison rule

Accepted vs rejected branches must use the **same production requirement and same realised DA path**. Only reserve acceptance should differ.

---

## 5. Integration risks

- **Hourly vs ISP mismatch**: current DA bidding MILP is hourly, while accepted `mFRR` obligations are ISP-based and conceptually later in the market chain.
- **Forecast-origin leakage**: the capacity-result branch must not use DA actuals or later information when generating accepted/rejected inputs.
- **False free revenue**: accepted capacity revenue must never be added without binding DA procurement and reserve-preservation consequences.
- **Lost obligation chain**: after capacity acceptance, DA scheduling must remember both reserve preservation and the later energy-bid obligation flag.
- **Comparability failure**: accepted and rejected branch comparisons are invalid if production target, inventory start, or realised DA path changes.
- **Penalty masking**: reserve infeasibility must not disappear into generic penalties without explicit reserve-feasibility reporting.
- **Truth-type confusion**: do not treat synthetic quarter-hour support paths as observed market truth.
- **Hydrogen lock-in**: do not hard-code electrolyser-specific reserve semantics into the long-term DA recourse interface intended for later steel transfer.

---

## 6. Recommended next implementation step

### Recommendation

Keep the standalone adapter and add a **small DAM-side operating-point interface** before introducing reserve-preservation constraints.

### Why

- the current `mFRR` pilot sits in the older dispatch-first model
- the actual DA bidding surface now lives in `bidding_model.py` + `clearing.py` + `redispatch.py`
- the accepted/rejected reserve branch now has a schema boundary, but the explicit DA bidding MILP still lacks a clean existing scheduled-load / headroom interface for reserve preservation

### Files to touch next

Primary next-touch candidates:

- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/bidding_model.py`
- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/redispatch.py`
- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/optimisation/input_resolver.py`
- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/mfrr_da_recourse.py`

### What the next implementation should do

- add a normalized accepted/rejected capacity-result adapter
- use the existing adapter to map ISP obligations to the DA model grid conservatively
- define a DAM-side operating-point / reserve-preservation interface before binding accepted Up or Down obligations
- inject hourly reserve-preservation inputs into DA bid optimisation and actual redispatch only after that interface exists
- keep smoke-test scope to accepted vs rejected deterministic branches only

### What not to touch yet

- no accepted/rejected stochastic tree
- no activation redispatch
- no energy-bid price optimisation
- no settlement / sanctions / MARI
- no 4-hour product logic
- no full-week scaling
- no command-centre expansion yet

---

## Bottom-line conclusion

The current `mFRR` capacity pilot is attached to the older stochastic dispatch MILP, but the DA interface that should eventually receive accepted/rejected reserve obligations is the newer explicit bidding stack. The correct next move is therefore an adapter layer that converts accepted capacity results into DA-side reserve-preservation and energy-bid-obligation inputs, rather than a direct merge of the existing capacity proxy into the older dispatch-first model.
