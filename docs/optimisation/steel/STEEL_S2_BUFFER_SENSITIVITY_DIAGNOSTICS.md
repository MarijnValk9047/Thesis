# Steel S2 Buffer Sensitivity Diagnostics

## Purpose Of S2.10d

`S2.10d` tests whether the first buffer-aware `24h` scaffold depends strongly on the assumed `50%` initial inventory and the provisional first-buffer capacity sizes.

This is a diagnostic sensitivity step only.

It does not change the base input tables, the restricted LP scope, or the non-thesis status of the runs.

## Sensitivity Cases Tested

Tested groups:

- `C0` initial inventory: `0%`, `25%`, `50%`, `75%`
- `C1` initial inventory: `0%`, `25%`, `50%`, `75%`
- `C0` hot metal capacity: `0.5x`, `1.0x`, `2.0x`
- `C1` hot metal capacity: `0.5x`, `1.0x`, `2.0x`
- `C1` `DRI/HDRI` capacity: `0x_no_surge`, `0.5x`, `1.0x`, `2.0x`, `4.0x`
- permissive stress regressions for `C0` and `C1`

All cases remained:

- `inventory_mode=first_buffers`
- hard target
- no shortfall slack
- `minimise_overproduction_dev_only`
- `thesis_usability=false`

## Whether Feasible Operation Depends On 50% Initial Inventory

In the current restricted `24h` scaffold, feasible operation does not depend strongly on the `50%` initial inventory assumption.

Observed result:

- all `C0 feasible_smoke` initial-inventory cases from `0%` through `75%` solved `optimal`
- all `C1 feasible_smoke` initial-inventory cases from `0%` through `75%` solved `optimal`
- all solved exactly on target with zero overproduction

That means the present `24h` restricted scope can meet the mechanics target even with `0%` initial stock.

This is a useful diagnostic, but it does not prove multi-day physical credibility.

## Whether Hot Metal Buffer Size Matters

In the current restricted `24h` scaffold, hot metal buffer size does not change `24h` feasibility for the tested `0.5x`, `1.0x`, and `2.0x` range.

Observed result:

- `C0` remained `optimal` in all hot metal size cases
- `C1` remained `optimal` in all hot metal size cases
- all solved exactly on target with zero overproduction

That means the current `24h` scaffold is not strongly sensitive to the tested hot metal buffer size range.

This does not upgrade hot metal into strategic flexibility. Hot metal remains synchronisation only.

## Whether DRI/HDRI Buffer Size Matters

In the current restricted `24h` scaffold, `DRI/HDRI` buffer size does not change `24h` feasibility for the tested `0x`, `0.5x`, `1.0x`, `2.0x`, and `4.0x` range.

Observed result:

- all tested `C1 DRI/HDRI` size cases solved `optimal`
- even the `dri_hdri_0x_no_surge` case remained feasible
- all solved exactly on target with zero overproduction

This means the current restricted `24h` scaffold does not require a positive `DRI/HDRI` surge buffer to achieve the guarded mechanics target.

That is an important limitation signal: the present scope does not yet demonstrate that `DRI/HDRI` storage is necessary for `24h` feasibility.

## Whether Any Case Breaks CYC50

No tested feasible case breaks `CYC50`.

All feasible sensitivity runs returned terminal inventory to the overridden beginning inventory.

## Whether Stress Targets Remain Infeasible

Stress targets remain infeasible.

This was checked under permissive inventory settings:

- `C0`: `75%` initial inventory and `2.0x` hot metal capacity
- `C1`: `75%` initial inventory, `2.0x` hot metal capacity, and `4.0x` `DRI/HDRI` capacity

Both stress cases remained infeasible.

That is a positive safeguard: more permissive first-buffer settings did not make the public-scale stress targets look feasible.

## Whether Zero-Inventory Hits Persist

Zero-inventory hits persist.

All feasible sensitivity runs still touched zero inventory on at least one active store.

That means the restricted scaffold still uses the buffers as boundary-touching synchronisation or surge devices rather than as comfortably interior stores.

In the special `dri_hdri_0x_no_surge` case, the disabled `DRI/HDRI` store also hit capacity because the capacity was explicitly `0`.

## Why No Thesis-Use Claim Is Made

No thesis-use claim is made because:

- these are dev-only sensitivity overrides
- the scope is still `24h` only
- downstream remains inactive
- no economics are active
- no stochastic, `CVaR`, or `mFRR` logic is active
- the runs remain strictly non-thesis

## One-Week Buffer-Aware Runs

One-week buffer-aware runs remain blocked.

They are not conditionally approved by `S2.10d`.

Reason:

- `24h` feasibility is robust to the tested initial-inventory and buffer-size changes
- but zero-inventory hits persist in all feasible cases
- and the current restricted scope still does not validate longer-horizon physical credibility or flexibility value

The current interpretation is therefore:

- `24h` first-buffer mechanics are robust inside the tested range
- one-week buffer-aware scope is still blocked pending explicit longer-horizon review

The corresponding plan is recorded in `s2_buffer_sensitivity_plan.csv`.

The frozen run outcomes are recorded in `s2_buffer_sensitivity_result_summary.csv`.

The subsequent zero-hit attribution gate and any later weekly opening decision are recorded separately in `STEEL_S2_ZERO_HIT_ATTRIBUTION_AND_WEEK_GATE.md`.
