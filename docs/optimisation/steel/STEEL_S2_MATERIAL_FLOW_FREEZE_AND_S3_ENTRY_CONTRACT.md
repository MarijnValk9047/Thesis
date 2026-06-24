# STEEL_S2_MATERIAL_FLOW_FREEZE_AND_S3_ENTRY_CONTRACT

## S2 Purpose And Scope

`S2` exists to freeze a governed material-flow scaffold before any `S3` energy cost or emissions layer is opened.

The frozen `S2` scope is:

- deterministic
- hourly
- `24h` and guarded `168h` smoke horizons only
- provisional development-only metallic material-flow LP
- `C0_current_BF_BOF_reference`
- `C1_phase1_hybrid_BF_BOF_NG_DRP_EAF`
- route-neutral liquid-steel horizon-total smoke targets
- bounded first-buffer inventory activation only for `c0_hot_metal_buffer`, `c1_hot_metal_buffer`, and `c1_dri_hdri_buffer`

The frozen `S2` scope does not include:

- downstream `HSM` or slab production logic
- energy cost or emissions accounting
- `DA` bidding
- stochastic scenarios
- `CVaR`
- `mFRR`
- `15-minute` resolution
- `D-only` or `D+4` comparison logic
- product revenue or order-book logic

## C0 And C1 Configuration Definitions

`C0_current_BF_BOF_reference` is the current-route reference configuration with a retained blast furnace and retained `BOF` route.

`C1_phase1_hybrid_BF_BOF_NG_DRP_EAF` is the Phase 1 hybrid configuration with:

- a retained `BF-BOF` route
- a parallel `NG-DRP-EAF` route
- a shared liquid-steel sink boundary

`C0` is the reference route. `C1` is the first hybrid route intended to expose bounded metallic decoupling through `DRI/HDRI` and hot-metal synchronisation.

## What S2 Has Implemented

`S2` has implemented:

- governed topology and route skeletons for `C0` and `C1`
- provisional development-only process bounds and conversion coefficients
- a restricted liquid-steel smoke LP with hard targets and no shortfall slack
- explicit overproduction accounting under `minimise_overproduction_dev_only`
- guarded first-buffer inventory activation for the three approved dev-only stores
- zero-hit attribution diagnostics
- a gated one-week buffer-aware smoke run after benign attribution evidence

## What S2 Has Explicitly Not Implemented

`S2` has explicitly not implemented:

- approved thesis-grade numerical inputs
- downstream `HSM` or slab-flow execution
- cold slab or slab-`WIP` activation
- hot slab `WIP` strategic flexibility
- liquid steel ladle or tundish strategic storage
- coke sinter pellet or finished-goods flexibility
- energy cost emissions accounting
- `DA` bidding
- stochastic scenarios
- `CVaR`
- `mFRR`

## S2 Smoke/Buffer/One-Week Results Summary

Restricted liquid-steel smoke status:

- `C0` `24h feasible_smoke`: optimal
- `C1` `24h feasible_smoke`: optimal
- `C0` `24h stress_infeasible_original`: infeasible
- `C1` `24h stress_infeasible_original`: infeasible

First-buffer-aware `24h` status:

- `C0` `24h first_buffers feasible_smoke`: optimal
- `C1` `24h first_buffers feasible_smoke`: optimal
- `C0` `24h first_buffers stress_infeasible_original`: infeasible
- `C1` `24h first_buffers stress_infeasible_original`: infeasible

Zero-hit attribution gate:

- default feasible runs could hit zero inventory
- zero-hits disappeared under the diagnostic inventory-preserving objective
- stress safeguards remained infeasible
- the weekly gate therefore passed as benign and non-thesis

Guarded one-week status:

- `C0` `168h feasible_smoke_168h`: optimal under the diagnostic inventory-preserving objective
- `C1` `168h feasible_smoke_168h`: optimal under the diagnostic inventory-preserving objective
- one-week evidence remains development-only and diagnostic

## Why S2 Results Remain Non-Thesis

`S2` results remain non-thesis because:

- all executable numerical rows are still provisional development-only
- approved-input tables remain zero-row
- smoke targets are mechanics targets and not Tata executable production truth
- one-week smoke runs are guarded diagnostics and not plant validation
- no downstream material closure or energy accounting is active

Every `S2` artifact remains `thesis_usability=false`.

## What S3 May Consume

`S3` may consume the frozen `S2` scaffold only in the following guarded sense:

- topology for `C0` and `C1`
- process activity variables and route membership
- carrier balances and sink definitions
- process bounds as read-only dev-only placeholders
- conversion coefficients as read-only dev-only placeholders
- the three activated first-buffer inventory structures
- `CYC50` as endpoint-neutrality policy only
- the smoke and weekly run results as diagnostic context only

`S3` may add energy cost and emissions accounting only after reading this contract and preserving all frozen `S2` assumptions.

## What S3 Must Not Reinterpret

`S3` must not silently change production targets, process bounds, conversion coefficients, stores, `CYC50` policy, or topology.

`S3` must not reinterpret:

- `feasible_smoke` or `feasible_smoke_168h` as public annual validation targets
- public annual anchor translations as executable truth
- first-buffer activation as proof of economic flexibility value
- generated run folders as canonical source artifacts
- approved-input shells as populated approved data

`S3` must not introduce `DA` bidding, stochastic scenarios, `CVaR`, `mFRR`, `15-minute` resolution, product revenue, or order-book logic.

## Remaining S2 Limitations

Remaining `S2` limitations are material:

- downstream slab and `HSM` logic is still blocked
- cold slab or slab-`WIP` tonne grounding is unresolved
- hot slab transfer remains feasibility-only and non-strategic
- liquid steel ladle and tundish storage is omitted or tiny only
- one-week credibility is still diagnostic and not thesis-grade
- zero approved numerical rows exist

## S3 Entry Conditions

`S3` entry is conditional rather than automatic.

Before `S3.0` begins:

- the `S2` topology freeze must remain intact
- the `C0` and `C1` configuration definitions must remain intact
- the liquid-steel LP and first-buffer inventory runs must remain reproducible
- the weekly gate evidence must remain tied to the benign zero-hit result
- no hidden shortfall slack may appear
- no fake free buffers may appear
- blocked stores must remain blocked
- `S3.0` must be limited to energy cost and emissions accounting first

## Red Flags That Must Block S3 If Violated

The following red flags must block `S3` immediately if violated:

- any silent change to frozen `S2` targets bounds coefficients stores or topology
- any attempt to use public annual targets as executable truth
- any activation of blocked stores without a new governed gate
- any hidden shortfall slack or target relaxation
- any reinterpretation of weekly smoke runs as thesis validation
- any attempt to use `S3` to backfill unresolved `S2` physical issues implicitly
- any attempt to add `DA` stochastic `CVaR` `mFRR` or product logic inside `S3.0`

Cross-reference summary:

- restricted liquid-steel smoke baseline: `STEEL_S2_LIQUID_STEEL_SMOKE_BASELINE_FREEZE.md`
- first buffer-aware baseline: `STEEL_S2_FIRST_BUFFER_AWARE_BASELINE_FREEZE.md`
- zero-hit gate and weekly opening: `STEEL_S2_ZERO_HIT_ATTRIBUTION_AND_WEEK_GATE.md`
- asset-level summary: `STEEL_S2_CONFIGURATION_ASSET_AND_ASSUMPTION_SUMMARY.md`
