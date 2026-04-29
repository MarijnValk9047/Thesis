# FS3 Feature Families

## Goal
This note freezes the current **design policy** for `FS3` without authorizing a new feature-family run yet.

The design stays consistent with the thesis methodology:
- same train / validation / test split
- same daily rolling-origin evaluation
- same `08:00` on `D-1` forecast origin
- same `D` through `D+4` horizon
- same long-format forecast storage and evaluation metrics

Critical stage rule:
- `FS3` happens only after the cross-model shortlist at `FS2`
- the first real shortlist is **not** after `FS1`
- `FS3` should continue only with the models that survived `FS2`

## Candidate scope

The next `FS3` families should be added gradually, not as one large buffet.

The actual current code-defined experiment inventory is more specific than the literature shorthand:

Full-horizon candidates:
- `wa_load_domestic`
- `wa_load_crossborder`
- `installed_capacity_crossborder`

Explicit `D`-only branch candidates:
- `da_load_day1_domestic`
- `da_load_day1_crossborder`
- `da_generation_day1_domestic`
- `da_generation_day1_crossborder`

Historical lagged-only candidates:
- `load_history_domestic`
- `load_history_crossborder`
- `generation_history_domestic`
- `generation_history_crossborder`
- `neighbor_price_weekly`

Machine-readable inventory:
- [fs3_taxonomy_inventory.csv](C:/Users/marijnvalk/PycharmProjects/Thesis/scripts/Data/02_Forecasting/01_DA_prices/docs/fs3_taxonomy_inventory.csv)
- [fs3_taxonomy_inventory.json](C:/Users/marijnvalk/PycharmProjects/Thesis/scripts/Data/02_Forecasting/01_DA_prices/docs/fs3_taxonomy_inventory.json)

Important naming rule:
- keep these code-level bundle names as the repo truth for now
- do not relabel them into generic literature families until a later phase introduces an explicit mapping layer

The cleaned feature manifest remains:
- [entsoe_feature_family_manifest.csv](C:/Users/marijnvalk/PycharmProjects/Thesis/data/01_cleaned/entsoe_feature_family_manifest.csv)

## Availability Rules
Each cleaned family stores `known_at_utc` explicitly.

Practical categories:
- future-known across the required horizon
- future-known only for the `D` branch
- historical-only and therefore lagged-only

Important implication:
- causal availability must be checked per family, not assumed
- a family that is only known for `D` should not be silently reused for `D+1..D+4`
- lagged-only families must stay leak-free across the recursive horizon
- current inventory should distinguish between experiments defined in code and experiments fully available in the current feature store

## Gradual implementation policy

`FS3` is a grouped feature-family workflow:
- test one causal family or one compact family bundle at a time
- keep the same shared rolling-origin evaluation pipeline
- preserve the same storage schema and metrics
- retune because `FS3` changes the feature space materially

Current implementation guidance:
- begin with the cleanest causal families first
- keep coverage comparability explicit
- document the closest fair comparable setup when a model cannot use the exact same inputs

## Model scope

Default expectation for `FS3`:
- `XGBoost`
- `LEAR`

Conditional:
- `Prophet` only if it survives `FS2` and the regressor set stays compact and causal

## Execution boundary

This note is structural only.

It does **not** certify that `FS3` has already been rerun under the finalized methodology.

The next valid `FS3` execution should happen only after:
- the `FS2` shortlist is frozen
- the chosen feature family is causally documented
- the `FS3` retuning plan is fixed on validation
