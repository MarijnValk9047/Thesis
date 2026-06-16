# Steel S2 Store-Capacity Translation Review

## Purpose

This memo records the `S2.10a` dev-only store-capacity translation review for the first buffer-aware `S2` extension.

It prepares governed numeric and formula-only store rows for later guarded inventory activation without activating any inventory dynamics in this task.

## What Was Translated

The first dev-only tonne translations were limited to the two bounded short-term buffers that already have the strongest structural support in the current `S2` scope:

- `c0_hot_metal_buffer`
- `c1_hot_metal_buffer`
- `c1_dri_hdri_buffer`

Those rows now have explicit provisional tonne values derived from existing dev-only process bounds and dev-only conversion rows.

## Which Buffers May Be Activated First

The first candidate buffers for `S2.10b` are:

- hot metal as a small synchronisation-only buffer on the retained `BF-BOF` route
- `DRI/HDRI` surge as the main short-term `DRP-EAF` decoupling buffer

Both remain development-only and non-thesis.

## Which Buffers Remain Excluded Or Deferred

- cold slab or slab-`WIP` remains formula-only and non-executable until downstream throughput is translated into tonnes
- hot slab `WIP` remains omitted or tiny thermal-transfer only
- liquid steel, ladle, and tundish remain omitted or tiny feasibility-only
- coke, sinter, pellet, and finished goods remain excluded from `S2` base flexibility

## Why CYC50 Is Not Capacity Evidence

`CYC50` is endpoint policy only.

It supports `initial inventory = 50% of capacity` and `terminal inventory = beginning inventory` once a capacity row already exists, but it does not justify a capacity value by itself.

## Why Hot Slab WIP Is Not Strategic Flexibility

Hot slab `WIP` is thermally constrained transfer or local `WIP`, not a multi-hour or multi-day arbitrage store.

The dev pack therefore keeps hot slab rows non-executable and refuses strategic activation.

## Why Coke, Sinter, Pellet, And Finished Goods Are Excluded

Those categories are outside the intended first buffer-aware `S2` extension and would create fake flexibility if introduced as internal freely deployable stores.

They remain excluded unless a later explicit scope change is approved.

## Why Outputs Remain Non-Thesis-Usable

- no row in `s2_approved_model_input` was populated
- no row was marked approved
- no row was marked thesis-usable
- all translated values remain `provisional_development_only`

This review prepares later guarded builder work only.

## What S2.10b May Activate

`S2.10b` may consider activating only:

- `c0_hot_metal_buffer`
- `c1_hot_metal_buffer`
- `c1_dri_hdri_buffer`

and only under explicit guards that prevent multi-day carry, fake market-arbitrage interpretation, or downstream leakage.

## What S2.10b Must Still Refuse

`S2.10b` must still refuse:

- slab or downstream `WIP` activation
- hot slab strategic activation
- liquid steel, ladle, and tundish strategic activation
- coke, sinter, pellet, and finished-goods inventory activation
- any claim that these store rows are thesis-grade or approved

The resulting guarded activation boundary and first inventory-balance interpretation are recorded in `STEEL_S2_FIRST_BUFFER_INVENTORY_ACTIVATION.md`.
