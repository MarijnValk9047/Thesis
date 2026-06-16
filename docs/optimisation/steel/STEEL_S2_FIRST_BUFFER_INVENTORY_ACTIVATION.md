# Steel S2 First Buffer Inventory Activation

## Purpose Of S2.10b

`S2.10b` activates the first bounded inventory dynamics inside the restricted liquid-steel smoke scaffold.

The purpose is to test whether small, governed store balances work without introducing fake flexibility, free material sources, or downstream leakage.

This remains a development-only model extension.

## Which Stores Are Activated

Only the three `S2.10a` readiness-approved stores may activate:

- `c0_hot_metal_buffer`
- `c1_hot_metal_buffer`
- `c1_dri_hdri_buffer`

These are consumed only from `s2_provisional_dev_input` rows that remain `provisional_development_only`, `dev_executable_only`, and `thesis_usability=false`.

## Which Stores Remain Refused

The builder and runner still refuse:

- cold slab or slab-`WIP`
- hot slab `WIP` or strategic hot transfer
- liquid steel, ladle, or tundish inventory
- coke, sinter, pellet, and finished-goods stocks
- any formula-only or non-executable store row

## Capacity, Initial, And Terminal Policy

Activated stores use only the translated dev-only rows from `S2.10a`:

- `c0_hot_metal_buffer = 319.6344 t`
- `c1_hot_metal_buffer = 319.6344 t`
- `c1_dri_hdri_buffer = 418.568847032 t`

Initial inventory is fixed at `50%` of capacity.

Terminal inventory is fixed to beginning inventory.

## How Store Flows Are Coupled To Process Flows

Store balances are not driven by free inflow or outflow variables.

They are coupled directly to the existing restricted process flows:

- hot metal inventory sits between `BF` hot metal production and `BOF` hot metal consumption
- `DRI/HDRI` inventory sits between `DRP` production and `EAF` metallic input consumption

This means the store can only shift already-modelled internal carrier flow in time.

## How CYC50 Is Applied

`CYC50` is applied only as endpoint neutrality:

- beginning inventory fixed from the dev input table
- ending inventory forced back to the same level

It prevents net depletion from masquerading as flexibility value over the `24h` horizon.

## Why CYC50 Is Not Capacity Evidence

`CYC50` is an endpoint rule only.

It does not justify a tonne capacity and it does not permit any store to become active unless the translated dev-only capacity row already exists.

## Why Hot Slab/Slab/WIP And Downstream Are Still Inactive

Hot slab `WIP` remains thermally constrained transfer only and must not become strategic multi-hour or multi-day flexibility.

Cold slab or slab-`WIP` remains deferred because downstream sink scope and tonne translation are still not ready.

Downstream `HSM` and slab modelling therefore remain outside `S2.10b`.

## Why Outputs Remain Non-Thesis

The activated rows remain:

- provisional development only
- non-approved
- non-thesis

All run metadata must continue to report `thesis_usability=false`.

## How To Interpret Feasible/Stress Runs

`feasible_smoke` with `inventory_mode=first_buffers` checks whether the guarded store balances preserve the restricted mechanics baseline under bounded inventory carry.

`stress_infeasible_original` remains the regression case for transparent infeasibility.

If a stress case becomes feasible under these small bounded buffers, that is a red flag rather than a success signal.

## What Must Be Checked Before One-Week S2 Or S3

Before any one-week `S2` or later `S3` extension:

- verify that buffer carry does not create fake flexibility
- review whether terminal inventory neutrality remains physically interpretable over longer horizons
- finish cold slab/slab-`WIP` tonne translation before any downstream inventory activation
- keep hot slab, liquid steel, ladle, tundish, and excluded bulk stocks inactive
- preserve the separation between provisional dev inputs and approved thesis inputs
