# mFRR/DAM Integration Handoff v1

## 1. Purpose of this handoff

This note freezes the current hydrogen `mFRR` / incident-reserve and DAM sandbox before the thesis moves to the steel-plant deterministic DAM model.

The hydrogen sandbox was useful for validating market timing, capacity-result handling, reserve-obligation mapping, and the DAM reserve-preservation hook. It should now be treated as an interface and methodology sandbox, not as the place to finish a full activation-feasible `mFRR` model before the steel process model exists.

Core message:

> The hydrogen case validated market timing, capacity price-unit handling, accepted/rejected capacity-result records, ISP-to-hourly reserve-obligation mapping, and the DAM reserve-obligation hook. Future steel work should reuse the market interfaces and validation logic, but should not copy hydrogen-specific production or activation physics.

## 2. Real-world market order preserved

The implemented interface design preserves the real market order:

```text
capacity bid -> capacity result -> DA bidding -> DA results -> energy bids -> activation
```

This ordering matters because the model must already look ahead from the capacity-bid stage. A capacity offer is only meaningful if later DA procurement, reserve preservation, energy-bid obligation, and eventual activation feasibility can still be respected. The hydrogen sandbox corrected this sequencing at the interface level even though the full activation model is intentionally deferred.

## 3. What has been implemented

The current sandbox has implemented the following completed items:

- `mFRR` capacity price-unit repair to `EUR/MW/ISP`
- explicit `contract_isp_count` logic computed from delivery start and end rather than hardcoded assumptions
- integer MW capacity bid handling with the `1 MW` minimum / step logic
- rolling production target / production-credit sandbox diagnostics
- no unlimited above-target sales in rolling mode
- Down absorption proxy using rolling production-credit / inventory headroom
- Up recovery proxy using rolling future recoverable production headroom
- double-ISP and four-ISP stress diagnostics on top of the rolling-target overlay
- `mFRR` capacity-result adapter via `CapacityResultRecord`
- accepted/rejected branch representation
- ISP/block-to-hourly DA obligation mapping using conservative hourly max aggregation
- DAM reserve-obligation hook in the stochastic hourly DA bidding MILP
- all-scenario electrical reserve preservation in the stochastic DAM bidding MILP
- synthetic accepted/rejected DAM smoke test on `hourly_lear_strict`

In practical terms, the DAM-side reserve hook now accepts `reserve_obligations_by_hour`, aligns them to the hourly delivery grid, and enforces scenario-indexed electrical reserve preservation across all DA scenarios.

## 4. What is intentionally not implemented

The following items are intentionally deferred:

- real aligned historical `mFRR`-DAM smoke test
- mandatory per-ISP energy-bid volume / deadline output layer
- energy-bid price logic
- activation probability or merit-order proxy
- activation redispatch
- `5`-minute response validation
- settlement, imbalance, sanctions, or non-delivery logic
- full accepted/rejected/activation stochastic tree
- steel-specific reserve feasibility
- `MARI`
- source-backed `4`-hour incident-reserve product

These are deferred for two reasons:

1. the remaining layers depend on the final steel process and buffer model, because activation feasibility is asset- and process-specific; and
2. a real historical `mFRR`-DAM smoke test still requires common DAM / `mFRR` support dates, which the current sandbox does not have.

## 5. Reusable market/interface logic

The following parts should be reused later for the steel model:

- `CapacityResultRecord`
- accepted/rejected branch concept
- `energy_bid_obligation_created` flag
- `contract_isp_count`
- observed daily product structure
- ISP-to-model-grid reserve aggregation
- `reserve_obligations_by_hour` input
- all-scenario reserve preservation concept
- common-support guards
- explicit support status labels:
  - `real_aligned_support`
  - `synthetic_interface_support`
  - `no_support_stop`

These are the stable interface assets from the hydrogen sandbox. They capture the market chain and the obligation handoff cleanly enough to survive the move to steel.

## 6. Hydrogen-specific sandbox logic

The following hydrogen-specific logic should not be copied blindly into the steel model:

- electrolyser and compressor equations
- hydrogen production conversion factors
- hydrogen buffer and inventory assumptions
- hydrogen production-credit logic
- hydrogen Up recovery proxy
- hydrogen Down absorption proxy
- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/optimisation_model.py` as the final integration path

Explicit rule:

```text
Reuse the interfaces, not the hydrogen physics.
```

The hydrogen production and reserve-feasibility proxies were useful for sandboxing, but they are not the final plant-feasibility layer for steel.

## 7. File map

### Reusable / interface layer

- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/mfrr_da_recourse.py`
  - accepted/rejected capacity-result schema, validation, ISP counting, and ISP-to-hourly obligation mapping
- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/bidding_model.py`
  - DAM reserve-obligation hook and all-scenario electrical reserve preservation
- `scripts/Data/03_Hydrogen_Test_Case/run_mfrr_da_recourse_smoke_v1.py`
  - accepted/rejected DAM smoke runner with `real_aligned_support` vs `synthetic_interface_support`
- `docs/optimisation/dam_reserve_availability_interface_design_v1.md`
  - DAM hook design and staged reserve-preservation interpretation
- `docs/optimisation/mfrr_da_recourse_interface_inspection_v1.md`
  - interface inventory and accepted/rejected branch design
- `docs/optimisation/nl_ir_capacity_milp_export_contract_v2.md`
  - repaired export contract, `EUR/MW/ISP`, `contract_isp_count`, and integer MW interpretation

### Hydrogen sandbox / diagnostics

- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/optimisation_model.py`
  - older schedule-first hydrogen model used by the sandbox capacity pilot
- `scripts/Data/03_Hydrogen_Test_Case/run_mfrr_capacity_one_day_exact_comparison_refresh_v1.py`
  - exact one-day unit / revenue / integer-MW diagnostic
- `scripts/Data/03_Hydrogen_Test_Case/run_mfrr_capacity_rolling_target_overlay_smoke_v1.py`
  - rolling-target overlay with absorption and recovery proxy diagnostics
- `scripts/Data/03_Hydrogen_Test_Case/run_mfrr_capacity_rolling_target_stress_grid_v1.py`
  - stress grid over targets, credit caps, and activation durations
- `docs/optimisation/generic_reserve_feasibility_interface_design_v1.md`
  - generic reserve-feasibility abstraction for future steel extension
- `docs/optimisation/production_first_rolling_target_envelope_design_v1.md`
  - production-first rolling target design and its hydrogen implementation status

### Market rules

- `docs/market_rules/nl_incident_reserve_capacity_market_rules_v2.md`

Important warning:

```text
Do not treat scripts/Data/03_Hydrogen_Test_Case/hydrogen/optimisation_model.py as the final DAM integration path. The live DAM stack is bidding_model.py -> clearing.py -> redispatch.py.
```

## 8. Validation and smoke tests

The current sandbox supports the following compact conclusions:

- capacity unit and revenue repair was validated
- integer MW diagnostics passed
- rolling target smoke diagnostics passed
- reserve-feasibility stress grid completed
- DAM hook default no-reserve dry run path passed
- synthetic interface support smoke passed with `hourly_lear_strict`
- real aligned `2025` `mFRR`-DAM smoke was not run because common support was missing

Key interpretation:

```text
The synthetic smoke test proves the interface chain works technically, but it is not a historical mFRR value result.
```

## 9. Known limitations and red flags

- Do not report hydrogen `mFRR` results as final steel results.
- Do not claim activation feasibility from electrical reserve preservation only.
- Do not mix `2025` `mFRR` cases with `2026` DAM scenario artifacts.
- Do not average ISP reserve obligations into hourly DAM obligations; use conservative max aggregation.
- Do not use scenarios without probabilities.
- Do not hide infeasibility with penalties.
- Do not add `mFRR` to the steel model before deterministic DAM-only steel is stable.
- Do not hardcode hydrogen-specific reserve logic into steel.
- Do not treat accepted bids as a full submitted bid ladder.

## 10. How to resume later

Recommended continuation point after the steel deterministic DAM model exists and is stable:

1. define steel process and buffer reserve availability
2. add deterministic reserve-availability diagnostics
3. reintroduce `CapacityResultRecord` and the accepted/rejected obligation interface
4. map ISP obligations to the steel model grid
5. add DAM reserve preservation
6. only then add energy-bid obligations and activation redispatch

Before any real historical `mFRR`-DAM smoke test is attempted, the DAM artifacts must have common support with the chosen `mFRR` test date.

## 11. Suggested next branch after freeze

Recommended next major implementation branch:

```text
steel-dam-deterministic-core
```
