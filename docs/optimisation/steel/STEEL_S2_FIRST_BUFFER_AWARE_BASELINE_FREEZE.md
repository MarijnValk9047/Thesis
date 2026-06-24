# Steel S2 First Buffer-Aware Baseline Freeze

## Purpose

This memo freezes the first buffer-aware `S2.10b` smoke baseline before any one-week, downstream, energy, cost, `DA`, stochastic, or `mFRR` scope increase.

It records what the guarded first-buffer inventory scaffold proves, what it does not prove, and which checks remain blocked.

It is not a thesis-result memo.

## S2.10b Scope And Non-Scope

In scope:

- deterministic `24h` restricted liquid-steel smoke LP
- `inventory_mode=first_buffers`
- `C0` and `C1`
- activated hot metal and `DRI/HDRI` buffers only
- hard route-neutral liquid-steel target
- `minimise_overproduction_dev_only`
- no shortfall slack

Out of scope:

- cold slab or slab-`WIP`
- hot slab `WIP` or strategic hot transfer
- liquid steel, ladle, or tundish inventory
- downstream `HSM` or slab scope
- one-week runs
- energy, cost, emissions, `DA`, stochastic, `CVaR`, `mFRR`
- product or order-book logic

## Activated Stores And Refused Stores

Activated stores:

- `c0_hot_metal_buffer`
- `c1_hot_metal_buffer`
- `c1_dri_hdri_buffer`

Refused stores:

- cold slab or slab-`WIP`
- hot slab `WIP` or hot transfer
- liquid steel, ladle, or tundish
- coke, sinter, pellet, and finished goods
- downstream `HSM`

## Feasible And Stress Run Outcomes

- `C0 feasible_smoke`, `24h`, `first_buffers`: optimal
- `C1 feasible_smoke`, `24h`, `first_buffers`: optimal
- `C0 stress_infeasible_original`, `24h`, `first_buffers`: infeasible
- `C1 stress_infeasible_original`, `24h`, `first_buffers`: infeasible

This means the small bounded inventories did not break the restricted smoke mechanics, and they did not make impossible public-scale `24h` targets look feasible.

## Model Size Summary

- `C0`: `73` variables, `171` constraints, `0` binaries
- `C1`: `145` variables, `340` constraints, `0` binaries

## Inventory Capacity/Initial/Min/Max/Terminal Summary

`C0` active store:

- `c0_hot_metal_buffer`
- capacity `319.6344 t`
- initial inventory `159.8172 t`
- minimum inventory `0.0 t`
- maximum inventory `159.8172 t`
- terminal inventory `159.8172 t`
- terminal rule satisfied under `CYC50=true`

`C1` active stores:

- `c1_hot_metal_buffer`
  - capacity `319.6344 t`
  - initial inventory `159.8172 t`
  - minimum inventory `0.0 t`
  - maximum inventory `159.8172 t`
  - terminal inventory returned to `159.8172 t`
- `c1_dri_hdri_buffer`
  - capacity `418.568847032 t`
  - initial inventory `209.284423516 t`
  - minimum inventory `0.0 t`
  - maximum inventory `209.284423516 t`
  - terminal inventory returned to `209.284423516 t`

## Interpretation Of Buffers Hitting Zero

Buffers hitting zero is a warning, not an automatic invalidation.

The relevant signal is that zero inventory was reached within the horizon while the terminal rule still forced the model to return to the beginning inventory. That means the model did not borrow net material across the `24h` horizon, but it did use the initial stock aggressively during the day.

## Why CYC50 Prevents Net Horizon Borrowing But Does Not Prove Physical Credibility

`CYC50` prevents net horizon borrowing but does not prove physical credibility.

It proves only that the model ended where it started. It does not prove that the path, operating cadence, or repeated multi-day use of the same buffers would remain physically credible.

## Why Hot Metal Remains Only A Synchronisation Buffer

Hot metal remains only a synchronisation buffer.

Draining hot metal to zero may be acceptable as a narrow `24h` synchronisation diagnostic between `BF` and `BOF`, but it is not evidence for long-duration operational flexibility and must not be used to justify one-week or thesis-level flexibility claims.

## Why DRI/HDRI Remains Only A Short-Term Surge Buffer

`DRI/HDRI` remains only a short-term surge buffer.

Draining `DRI/HDRI` to zero may be plausible as short-term `DRP-EAF` decoupling, but it still needs initial-inventory sensitivity, size sensitivity, and longer-horizon checks before any stronger interpretation is allowed.

## Why Cold Slab/Slab-WIP Remains Blocked/Deferred

Cold slab/slab-`WIP` remains blocked/deferred because tonne grounding and downstream sink scope are still not ready.

No activation signal from `S2.10b` changes that gate.

## Why No Economic Flexibility Value Is Claimed Yet

No economic flexibility value is claimed yet.

These runs prove guarded mechanics only:

- bounded inventory balance works
- `CYC50` terminal neutrality works
- stress infeasibility remains visible

They do not prove economic value, arbitrage value, or thesis-grade operational flexibility.

## Why Outputs Remain `thesis_usability=false`

All consumed rows remain provisional development-only and non-approved.

All outputs remain `thesis_usability=false`.

## Decision On Whether S2.10b Is Acceptable As A 24h Smoke Baseline

`S2.10b` is acceptable as a `24h` smoke baseline.

That acceptance is narrow:

- acceptable for guarded mechanics checks
- acceptable for buffer-balance diagnostics
- not acceptable as evidence for one-week credibility
- not acceptable as evidence for economic flexibility value

## Required Next Gates Before One-Week Buffer-Aware Runs

- interpret `24h` inventory minima and maxima explicitly
- test sensitivity to initial inventory assumptions
- decide whether a zero-initial-stock diagnostic may be run later
- test `DRI/HDRI` buffer-size sensitivity
- test hot metal buffer-size sensitivity
- preserve the block on cold slab/slab-`WIP` until tonne grounding is complete

## Required Next Gates Before S3

- complete one-week buffer-aware gate review
- complete downstream `HSM` activation gate review
- keep liquid-steel-side, hot slab, and excluded bulk stocks inactive unless reopened by policy
- preserve separation between dev-only scaffolds and approved thesis inputs
- keep any future energy, cost, and emissions scope behind an explicit `S3` entry gate

The governed inventory-use interpretation is recorded in `s2_inventory_use_interpretation_register.csv`.

The frozen first buffer-aware case summary is recorded in `s2_first_buffer_aware_baseline_summary.csv`.

The blocked follow-up checks are recorded in `s2_buffer_aware_next_check_register.csv`.

The first guarded initial-inventory and buffer-size sensitivity evidence built on top of this baseline is recorded in `STEEL_S2_BUFFER_SENSITIVITY_DIAGNOSTICS.md`.

The later zero-hit attribution gate and conditional weekly decision are recorded in `STEEL_S2_ZERO_HIT_ATTRIBUTION_AND_WEEK_GATE.md`.

The consolidated `S2.11` freeze and `S3` entry contract built on top of this buffer-aware baseline are recorded in `STEEL_S2_MATERIAL_FLOW_FREEZE_AND_S3_ENTRY_CONTRACT.md`.
