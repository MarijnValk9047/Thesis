# DAM Reserve Availability Interface Design V1

## Purpose

This note decides how accepted `mFRR` reserve obligations should be represented in the existing day-ahead hydrogen bidding MILP without creating a second competing production model.

It is inspection and formulation guidance only. It does not implement the hook.

Real-world order to preserve:

```text
capacity bid -> capacity result -> DA bidding -> DA results -> energy bids -> activation
```

Methodological consequence:

- accepted reserve is known before DA bidding
- DA bid quantities remain first-stage decisions
- physical production and electricity use remain scenario-indexed DA recourse
- reserve obligations should therefore bind the DA recourse surface, not a fabricated deterministic production schedule

---

## 1. DAM model structure

### Core stack

- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/bidding_model.py`
  - Pyomo first, PuLP fallback
  - explicit hourly price-taking DA demand bidding MILP
- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/clearing.py`
  - deterministic actual-price clearing after bids are formed
- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/redispatch.py`
  - deterministic physical redispatch after actual clearing

### Horizon and scenario structure

- hourly time grid
- current dry-run path is one delivery day only
- default config is `D_only`
- default bid-price grid has 14 price blocks
- default scenario artifact is `hourly_lear_strict`
- inspected default artifact has 75 scenarios per forecast origin, constant across origins
- scenario probabilities are explicit and must sum to 1 per origin / model / lead-day block

### First-stage versus recourse

First-stage variables in `bidding_model.py`:

- `q[t,b]`: DA bid quantity by delivery hour and bid block

Scenario-indexed recourse variables in `bidding_model.py`:

- `P_el[s,t]`
- `u_el[s,t]`
- `H_prod[s,t]`
- `P_comp[s,t]`
- `H_comp[s,t]`
- `H_buf[s,t]`
- `used_energy[s,t]`
- `unused_cleared_energy[s,t]`
- optional `emergency_import[s,t]`
- `shortfall[s]`
- optional CVaR `xi[s]`, plus scalar `zeta`

### How bidding and clearing are represented

- DA bids are block bids on a fixed price grid through `q[t,b]`
- scenario clearing inside the stochastic MILP is represented by a fixed acceptance matrix `acceptance_lookup[(s,t,b)]`
- actual clearing later uses actual DA prices with `bid_price >= actual_price`
- physical production during stochastic bidding is already represented inside `bidding_model.py`; it is not delegated to `optimisation_model.py`

### Production, target, and inventory structure

- hydrogen production physics are modelled directly in `bidding_model.py`
- storage is `H_buf[s,t]` with lower reserve floor and upper storage cap
- current DAM bidding path uses daily target / shortfall logic
- current default config remains `legacy_daily_minimum`
- rolling production-credit / rolling-deadline logic exists elsewhere, but is not yet the live DAM bidding interface

### Redispatch role

- `redispatch.py` solves a separate deterministic physical model after actual clearing
- it reuses the same hydrogen physics family, but on the realised cleared-energy path
- this means accepted reserve obligations may eventually need to bind both:
  - DA scenario recourse in `bidding_model.py`
  - realised redispatch in `redispatch.py`

---

## 2. Computational size and feasibility

### Default inspected dry-run scale

Using current code and default config / artifact:

- hours `H ~= 24`
- scenarios `S ~= 75`
- bid blocks `B = 14`
- binary commitment variables `u_el[s,t] ~= 24 x 75 = 1800`

Approximate variable count in the risk-neutral Pyomo MILP, without emergency import:

- bid quantities: `H x B = 336`
- scenario-time physical variables:
  - `8 x H x S = 8 x 24 x 75 = 14400`
- scenario shortfall: `S = 75`
- total ~= `14811`

Additions if enabled:

- emergency import: `H x S = 1800`
- CVaR excess variables: `S = 75`
- CVaR threshold: `1`

Approximate constraint count in the risk-neutral soft-target case:

- bid-side hourly constraints: `2 x H = 48`
- scenario-time physics:
  - first hour: about `10 x S`
  - later hours: about `12 x S x (H - 1)`
- scenario target constraints: about `S`

This yields roughly:

- `48 + 75 x (10 + 12 x 23 + 1) = 21573`

Exact counts vary with:

- hard versus soft target mode
- emergency import
- CVaR

### Scaling of reserve constraints

If accepted reserve obligations are enforced against scenario-indexed recourse availability:

- one-direction hard reserve constraints scale as `O(H x S)`
- both Up and Down together also scale as `O(H x S)` with a larger constant
- no new binaries are required if reserve availability is expressed from existing continuous variables

For the default one-day, 75-scenario dry run, that means:

- Up only: about `24 x 75 = 1800` extra linear constraints
- Down only: about `1800` extra linear constraints
- both directions: about `3600` extra linear constraints

### Feasibility judgement

- for the current hourly one-day smoke scale, `O(H x S)` hard reserve constraints are computationally reasonable
- the incremental size is material but not structurally large relative to the existing MILP
- runtime risk rises much more from:
  - more scenarios
  - quarter-hour granularity
  - rolling-target extensions
  - additional reserve-feasibility proxy layers

This task did not run the dry run, so runtime is a code-inspection judgement, not a measured benchmark.

---

## 3. Candidate reserve-availability formulations

### Option A - Scenario-robust DA reserve preservation

For every delivery hour `t` and DA scenario `s`:

```text
available_up_reserve_mw[t,s] >= R_up[t]
available_down_reserve_mw[t,s] >= R_down[t]
```

Strength:

- respects the existing two-stage structure
- keeps accepted reserve fixed across DA scenarios
- avoids inventing a fake deterministic DA operating schedule
- directly constrains the scenario-recouse operating points that already exist

Cost:

- adds `O(H x S)` linear constraints
- no new binaries if availability uses existing variables

Feasibility risk:

- can become conservative when some DA scenarios clear much more or much less energy
- may expose that some accepted reserve volumes are not jointly supportable with current target assumptions

Thesis fit:

- strongest first implementation for a smoke test
- especially appropriate for mandatory accepted reserve obligations

### Option B - Selected-scenario or representative-scenario preservation

Enforce reserve only for a subset of scenarios, for example:

- central scenario
- low-price tail
- high-price tail

Strength:

- lower constraint count
- useful for diagnostics or stress slicing

Risk:

- leaves unprotected DA scenarios in the same optimisation
- weakens the meaning of accepted mandatory reserve
- can look feasible only because the worst unsupported scenarios are ignored

Thesis fit:

- acceptable as a diagnostic only
- not the preferred first operational formulation

### Option C - Soft or chance-style reserve preservation

Allow reserve violations with:

- slack penalties
- scenario-weighted violation terms
- chance-style thresholds

Strength:

- useful later for sensitivity analysis
- can help identify the cost of reserve robustness

Risk:

- dangerous for mandatory accepted reserve obligations
- can hide infeasibility behind penalties
- complicates interpretation before the hard-feasibility baseline is understood

Thesis fit:

- should be avoided for the first implementation

### Option D - Staged robust formulation with electrical availability first

Use Option A across all DA scenarios, but start with availability expressions that are already present in the DAM model:

```text
available_up_reserve_mw[t,s] = P_el[s,t] + P_comp[s,t]
available_down_reserve_mw[t,s] = site_max_load_mw - (P_el[s,t] + P_comp[s,t])
```

Strength:

- uses existing DAM recourse variables directly
- no duplicate production model
- computationally light enough for the one-day smoke scale

Risk:

- Up is a good electrical reducibility expression, but still not full later-activation economics
- Down is only electrical headroom; it is not yet full inventory / recovery-feasible Down reserve

Thesis fit:

- best staged first implementation if the note is explicit that this is DA electrical reserve preservation, not full activation-feasibility closure

---

## 4. Required DAM-side reserve-availability expressions

### Existing expressions that already exist safely

These can be defined from current scenario-indexed recourse variables in `bidding_model.py`:

```text
site_load_mw[t,s] = P_el[s,t] + P_comp[s,t]
available_up_reserve_mw[t,s] = site_load_mw[t,s]
electrical_down_headroom_mw[t,s] = site_max_load_mw - site_load_mw[t,s]
```

where:

```text
site_max_load_mw = electrolyser_nominal_mw + compressor_max_mw
```

This is methodologically consistent with the current DA MILP because:

- the model already chooses `P_el[s,t]` and `P_comp[s,t]`
- `used_energy[s,t]` is already linked to those decisions
- clearing enters through `acceptance_lookup[(s,t,b)]` and therefore shapes feasible recourse

### What is missing for full Down reserve availability

The current DAM bidding MILP does **not** yet contain a full scenario-indexed expression for:

- inventory-feasible Down absorption under later reserve activation
- recovery-feasible Up reserve after later activation
- rolling production-credit headroom inside the live bidding path

So the following is **not** available yet as a clean existing expression:

```text
full_available_down_reserve_mw[t,s]
```

if that expression is meant to include:

- storage absorption headroom
- future production-target consistency
- recovery after later activation

Those richer feasibility concepts currently live only in the older capacity-pilot logic and should not be copied blindly into the DAM stack.

### Practical interpretation

- Up reserve can be represented now as reducible scheduled site load on the scenario-recouse path
- Down reserve can be represented now only as electrical load-increase headroom unless a richer DAM-side proxy is added later

---

## 5. Non-anticipativity and timing

Correct timing in the current stack is:

1. capacity result is known
2. accepted reserve obligation `R[t]` is fixed
3. DA bid quantities `q[t,b]` are chosen before clearing
4. DA scenario clearing determines scenario-dependent available energy
5. physical dispatch adapts by scenario in `bidding_model.py`
6. actual clearing happens later
7. actual redispatch happens on the realised cleared path

Implications:

- reserve obligations should not be attached directly to `q[t,b]` because `q` is only a bid-quantity surface
- reserve obligations should bind the scenario-indexed DA recourse variables in `bidding_model.py`
- because recourse feasibility depends on first-stage `q`, those recourse constraints will indirectly shape the submitted DA bids
- later, the same accepted reserve obligation should also be visible in actual redispatch, but that does not need to be implemented in the first smoke step

So the right first binding location is:

- primary: DA scenario recourse in `bidding_model.py`
- later consistency layer: realised redispatch in `redispatch.py`

Not the right first binding location:

- a fabricated deterministic DA schedule outside the MILP
- the capacity adapter itself
- the old `optimisation_model.py` path

---

## 6. Recommended first implementation

### Recommended formulation

Implement Option A as the core structure, with Option D as the staged first expression set:

- accept optional hourly reserve obligations from `mfrr_da_recourse.py`
- add scenario-indexed reserve-availability expressions in `bidding_model.py`
- enforce accepted reserve obligations across all DA scenarios in the smoke test
- keep default behaviour unchanged when obligations are absent

Recommended first-stage expressions:

```text
available_up_reserve_mw[t,s] = P_el[s,t] + P_comp[s,t]
available_down_reserve_mw[t,s] = site_max_load_mw - (P_el[s,t] + P_comp[s,t])
```

Recommended hard constraints:

```text
available_up_reserve_mw[t,s] >= accepted_up_reserve_mw_for_da[t]
available_down_reserve_mw[t,s] >= accepted_down_reserve_mw_for_da[t]
```

for all scenarios `s`.

### Why this is the right first step

- it reuses the existing DAM MILP rather than introducing a second production formulation
- it respects non-anticipativity
- it is computationally feasible at the current one-day / 75-scenario scale
- it gives a clear hard-feasibility baseline before any softer or richer reserve logic is added

### Files to touch next

- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/bidding_model.py`
- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/mfrr_da_recourse.py` only for interface reuse if needed
- later, not in the same first step: `scripts/Data/03_Hydrogen_Test_Case/hydrogen/redispatch.py`

### Suggested input signature

Optional input in `bidding_model.py`:

```text
reserve_obligations_by_hour: pd.DataFrame | None = None
```

Expected aligned fields:

```text
delivery_timestamp
accepted_up_reserve_mw_for_da
accepted_down_reserve_mw_for_da
reserve_obligation_active
energy_bid_obligation_created
branch_id
capacity_contract_block_id
```

### Diagnostics to return

- whether reserve obligations were active
- min scenario Up reserve headroom by hour
- min scenario Down electrical headroom by hour
- reserve-binding hours by scenario count
- explicit flag that Down is electrical-headroom-only in the first implementation

### Explicitly out of scope

- energy-bid pricing
- activation modelling
- settlement or sanctions
- MARI
- 4-hour products
- stochastic accepted / rejected tree
- rolling production-credit reserve proxies inside the first DAM hook

---

## Bottom-line decision

The DAM bidding MILP is already a two-stage stochastic production model. Accepted reserve obligations should therefore be represented as hard scenario-indexed reserve-availability constraints on the existing DA recourse variables, not against a deterministic surrogate schedule.

For the first implementation, this is computationally feasible at the current one-day hourly scale. The clean staged choice is robust all-scenario enforcement with existing electrical load and headroom expressions, while keeping richer Down absorption and recovery-feasibility logic explicitly out of scope until the live DAM path has a justified proxy for it.

---

## Implementation status

- Optional hook path added in `scripts/Data/03_Hydrogen_Test_Case/hydrogen/bidding_model.py` via `reserve_obligations_by_hour=None`.
- Default no-reserve behaviour remains the default path; no reserve constraints are added when the input is absent.
- Current hard reserve constraints are:
  - `P_el[s,t] + P_comp[s,t] >= accepted_up_reserve_mw_for_da[t]`
  - `site_max_load_mw - (P_el[s,t] + P_comp[s,t]) >= accepted_down_reserve_mw_for_da[t]`
- Hourly reserve obligations are validated and aligned against the DA delivery-hour grid using the standalone adapter interface.
- This is **electrical reserve preservation only**.
- Still out of scope:
  - activation
  - energy-bid pricing
  - settlement / sanctions / MARI
  - rolling credit / recovery proxy logic inside the DAM stack
  - full Down absorption feasibility beyond electrical headroom

## Accepted/rejected smoke runner status

- Runner path: `scripts/Data/03_Hydrogen_Test_Case/run_mfrr_da_recourse_smoke_v1.py`
- Artifact scope: `hourly_lear_strict` only
- Current support logic:
  - use `real_aligned_support` only if the LEAR Strict artifact actually contains `2025-07-11`
  - otherwise run `synthetic_interface_support` on a supported LEAR Strict day
- Current implementation status:
  - adapter validation and hourly alignment are active
  - accepted branches pass nonzero reserve obligations into the DAM hook
  - rejected branches pass zero reserve obligations
- Still out of scope in the smoke runner:
  - activation
  - energy-bid pricing
  - settlement
  - redispatch reserve mirroring
  - full historical rolling-target recreation of the 2025 mFRR corner cases when LEAR Strict common support is absent
