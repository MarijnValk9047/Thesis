# mFRR Capacity Only MILP Pilot Design V1

## A. Current Input Contract Summary

Primary input contract for the pilot:
- path: `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/milp_exports/nl_ir_capacity_milp_input_daily_direction_scenarios_v1.csv`
- row count: `2190`
- horizon: `2024-10-01` to `2025-09-30`
- grain: `delivery_date_local x direction x scenario_id`
- directions: `Up`, `Down`
- scenario IDs:
  - `threshold_conservative_p75`
  - `threshold_central_p90`
  - `threshold_optimistic_max`
- scenario probabilities:
  - `0.25`, `0.50`, `0.25`
- timing:
  - repaired `forecast_origin_local = D-1 09:00 Europe/Amsterdam`
  - repaired `known_at_cutoff_utc` preserved
- key fields for the pilot:
  - `acceptance_threshold_price`
  - `scenario_probability`
  - `direction`
  - `delivery_date_local`
  - `threshold_source_scope`
  - `threshold_observed_overlap_flag`
  - `average_price_forecast_threshold_anchor`
  - `average_price_forecast_primary`
  - `average_price_forecast_comparator`
- out-of-scope flags already embedded:
  - `activation_included = false`
  - `imbalance_settlement_included = false`
  - `mari_energy_included = false`
  - `afrr_included = false`

## B. Current Optimisation Structure

Inspected current optimisation surface:
- stable user-facing entry point:
  - `scripts/Data/03_Hydrogen_Test_Case/run_from_command_centre.py`
  - delegates to `hydrogen.command_centre.run_from_command_centre`
- current hardened backend:
  - hourly
  - `D_only`
  - hydrogen
  - `DA_only`
  - risk-neutral
  - selected-regime / selected-week fast path
- input resolution contract:
  - large market/scenario artifacts are supposed to flow through `hydrogen/optimisation/input_resolver.py`
  - resolver returns filtered scenario slices, market actuals, origin registry, and fingerprints
- run/reporting contract:
  - command-centre and optimisation run contract already exist
  - current framework expects resolved inputs, fingerprints, runtime profiling, and governed output policy

Inspected model layers:
- `hydrogen/optimisation_model.py`
  - Pyomo or PuLP physical stochastic dispatch model
  - time-indexed variables include `P_el`, `u_el`, `H_prod`, `P_comp`, `H_comp`, `H_buf`, `shortfall`
  - scenario set `S` is used in the objective and scenario cost bookkeeping
  - physical schedule variables in the inspected Pyomo formulation are shared across scenarios, so this file already represents a non-anticipative shared schedule pattern
- `hydrogen/bidding_model.py`
  - Pyomo stochastic hourly DA bidding model
  - first-stage bid-grid quantities `q[t,b]` are scenario-independent
  - scenario-indexed physical recourse variables include `P_el[s,t]`, `H_buf[s,t]`, and related quantities
  - acceptance is handled through a deterministic lookup from scenario price versus bid-price block
  - expected profit uses scenario probabilities and optional CVaR terms
- `hydrogen/clearing.py`
  - realised DA clearing against actual prices
  - acceptance rule is price-grid based and deterministic once actual price is known
- `hydrogen/redispatch.py`
  - physical redispatch after clearing
  - enforces physical balance, ramping, storage, and shortfall accounting

Interpretation:
- the current hydrogen stack already separates:
  - pre-uncertainty bid decisions;
  - scenario-dependent acceptance / clearing logic;
  - physical feasibility;
  - realised ex-post redispatch and settlement.
- this is a good structural fit for a future `mFRR` capacity pilot.

## C. Proposed Capacity-Only Integration Design

Recommended integration point:
- do not touch forecasting or scenario-generation code
- do not create a separate optimisation pipeline outside the hydrogen package
- add a narrow `mFRR` capacity pilot backend inside `scripts/Data/03_Hydrogen_Test_Case/hydrogen/`
- make it consume the existing MILP-facing export through the existing optimisation input-resolution pattern

Recommended architectural placement:
- use `hydrogen/optimisation/input_resolver.py` to load and filter the daily `mFRR` capacity export for the requested pilot week
- implement the pilot as a sibling backend module inside the hydrogen package, not inside forecasting
- reuse existing:
  - `plant_parameters.py`
  - run registry / output policy infrastructure
  - runtime profiling
  - solver wrappers from `optimisation_model.py`
- do not force the first pilot into the hourly DA bid-curve backend in `bidding_model.py`
  - reason: `mFRRda` capacity is daily x direction, not hourly DA block bidding
  - forcing it into the hourly bid-curve abstraction immediately would widen scope unnecessarily

Recommended first pilot structure:
- deterministic physical schedule with daily reserve-capacity decision variables
- stochastic daily capacity acceptance and revenue over the 3 threshold scenarios
- no activation dispatch
- no imbalance settlement
- no MARI / `aFRR`

## D. New Inputs, Variables, Constraints, Objective Terms

New inputs:
- the frozen `mFRR` MILP export
- one explicit one-week pilot window in the observed-overlap period
- optional daily bid-price candidate grid
- optional daily offered-capacity upper bound per direction

New decision variables by day and direction:
- `offered_capacity_up_day`
- `offered_capacity_down_day`
- `bid_price_choice_up_day_b`
- `bid_price_choice_down_day_b`
- `offered_capacity_up_day_b`
- `offered_capacity_down_day_b`
- optional reporting variable:
  - `accepted_capacity_up_day_scenario`
  - `accepted_capacity_down_day_scenario`

Recommended meaning:
- choose one bid-price candidate per day and direction
- choose offered capacity per day and direction
- capacity acceptance per scenario is implied by threshold lookup, not by scenario-specific free bid decisions

Core constraints:
- offered capacity nonnegative
- offered capacity bounded by site capability and any configured commercial max
- one bid-price candidate chosen per day and direction
- offered capacity assigned to the selected price candidate only
- 1 MW step size:
  - if tractable, use integer MW offered-capacity variables
  - if not, use continuous MW for the first pilot and record the approximation explicitly
- acceptance lookup:
  - use export `acceptance_threshold_price`
  - do not use `average_price_forecast_primary` or `average_price_forecast_comparator` as thresholds
- expected capacity revenue:
  - scenario probability weighted
  - based on accepted capacity and selected bid price
- deliverability reservation:
  - bind offered capacity directly, not accepted capacity only
  - this prevents earning revenue without reserving physical flexibility

Objective addition:
- add expected `mFRRda` capacity revenue to the existing operational objective
- keep production fulfilment and physical feasibility hard-constrained
- do not allow revenue to exploit missing feasibility constraints

## E. Acceptance Linearisation Recommendation

### Option 1: discretised bid-price candidates
Recommended for `v1`.

Reason:
- the current hydrogen bidding stack already uses a discrete bid-price grid plus deterministic acceptance lookup
- this avoids introducing a bilinear `accepted * bid_price * offered_capacity` term
- it is easier to debug and closer to the existing repository pattern

Recommended formulation:
- define a small fixed daily bid-price candidate grid in config
- choose one candidate per day and direction
- precompute acceptance indicator parameter:
  - `accepted_param[d,dir,s,b] = 1 if bid_price_candidate_b <= acceptance_threshold_price[d,dir,s] else 0`
- define continuous capacity-by-price variables:
  - `offered_capacity_day_dir_b`
- enforce:
  - sum over `b` of `offered_capacity_day_dir_b` equals offered capacity
  - each `offered_capacity_day_dir_b <= M * choose_price_day_dir_b`
- expected capacity revenue becomes linear:
  - sum over `d, dir, s, b` of `prob[s] * bid_price_candidate_b * accepted_param[d,dir,s,b] * offered_capacity_day_dir_b`

### Option 2: continuous bid price with binary acceptance and Big-M
Not recommended for `v1`.

Reason:
- acceptance then requires binary comparison logic
- revenue introduces extra bilinear structure unless auxiliary variables are added carefully
- this is unnecessary complexity for the first pilot when the repository already has a working discrete bid-grid pattern

Recommendation:
- use discretised bid-price candidates for the first capacity-only pilot
- revisit continuous price variables only after the pilot is stable

## F. Deliverability Design

Recommended first deliverability proxy:
- attach the `mFRR` capacity layer to the existing time-indexed physical load schedule
- define total flexible site load at time `t` as:
  - `site_load_t = P_el_t + P_comp_t`

For load-side upward reserve:
- interpretation: ability to reduce electricity consumption on request
- constraint:
  - `offered_capacity_up_day <= site_load_t` for every `t` in the contracted day
- stricter later refinement may subtract a must-run floor if needed

For load-side downward reserve:
- interpretation: ability to increase electricity consumption on request
- conservative headroom constraint:
  - `offered_capacity_down_day <= electrolyser_nominal_mw + compressor_max_mw - site_load_t` for every `t` in the contracted day

Why this is the preferred `v1` proxy:
- it is directly compatible with the currently inspected hydrogen physical variables
- it does not require activation modelling
- it guarantees no capacity revenue without a physically reserved envelope across the full contracted day

Important rule:
- reserve against offered capacity itself, not only accepted capacity
- otherwise the model could offer nondeliverable volume and only test deliverability after acceptance, which is not defensible for a capacity-obligation product

## G. Stage And Non-Anticipativity Design

Recommended stage sequence:

Stage 0:
- before the `D-1 09:00` incident-reserve capacity auction
- choose daily offered capacity by direction
- choose daily bid-price candidate by direction

Stage 1:
- threshold scenario resolves accepted or rejected capacity by day and direction
- expected capacity revenue is computed over the fixed scenario probabilities

Stage 2:
- no activation stage in `v1`
- no 15-minute energy-bid recourse in `v1`
- no imbalance settlement in `v1`

Non-anticipativity rule:
- daily offered capacity and bid-price choice must be identical across threshold scenarios for the same day and direction
- in the recommended discrete-price design, this is automatic because the decision variables are not scenario-indexed

Operational implication:
- the first pilot should keep the physical schedule shared across threshold scenarios
- the threshold scenarios affect expected revenue, not scenario-specific physical dispatch
- this is simpler and methodologically consistent because activation is not modelled yet

## H. Pilot Period Recommendation

Recommended first pilot window:
- one explicit calendar week inside the observed-overlap period
- preferred window: `2025-07-07` to `2025-07-13`
- include both `Up` and `Down`
- use all 3 threshold scenarios
- no activation

Recommendation on selected-week machinery:
- avoid reusing the current selected-week regime mechanism for `v1`
- reason:
  - the current selected-week path is specialized to hourly DA scenario artifacts and would widen scope unnecessarily
  - the `mFRRda` capacity pilot is daily and should start from one explicit fixed week
- use a narrow custom date filter inside the new capacity-pilot resolver/backend instead

## I. Metrics And Reporting For The Pilot

Recommended pilot outputs:
- offered capacity MW by day and direction
- chosen bid-price candidate by day and direction
- scenario acceptance indicator by day, direction, and threshold scenario
- expected capacity revenue
- objective decomposition:
  - baseline production economics
  - added expected `mFRR` capacity revenue
- daily minimum upward reserve margin
- daily minimum downward reserve margin
- production fulfilment
- storage boundary hits and reserve-envelope binding diagnostics
- infeasibility diagnostics if the reserve envelope conflicts with production requirements
- comparison to a no-`mFRR` baseline run over the same week

## J. Implementation Boundaries

The next implementation should:
- modify only a small set of files inside the existing hydrogen package and command-centre governance layer
- not touch forecasting or scenario-generation pipelines
- not regenerate the `mFRR` export
- not add activation, MARI, `aFRR`, or imbalance settlement
- not hide infeasibility behind soft penalties unless explicitly approved

Recommended exact files for the next implementation prompt:
- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/optimisation/input_resolver.py`
  - add narrow resolver support for the frozen `mFRR` capacity export and a fixed custom weekly slice
- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/plant_parameters.py`
  - add bounded config fields for capacity bid-price candidate grid and any explicit commercial bounds needed by the pilot
- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/optimisation_model.py`
  - either extend the shared physical schedule model with daily reserve-capacity variables and expected capacity revenue, or factor the shared physical constraints into a helper used by the new pilot backend
- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/command_centre.py`
  - only if the pilot is wired into the command-centre path immediately
- `scripts/Data/03_Hydrogen_Test_Case/configs/optimisation_supported_options.yaml`
  - if market-scope or backend status changes
- `docs/optimisation/RUN_COMMAND_CENTRE_GUIDE.md`
  - if the command-centre surface changes
- `docs/optimisation/PROJECT_DECISIONS.md`
  - if the repository formally opens a first `mFRRda` capacity pilot branch

Preferred implementation boundary for `v1`:
- add one narrow hydrogen-package capacity pilot backend first
- wire it into the broader command-centre surface only if the patch stays small and traceable

## K. Draft Next Implementation Prompt

### `MFRR_CAPACITY_ONLY_MILP_PILOT_IMPLEMENTATION_V1`

Goal:
- implement the first capacity-only Dutch incident-reserve / `mFRRda` pilot inside the existing hydrogen optimisation package
- consume the frozen MILP-facing export without recomputing any forecast or scenario artifact
- add daily `Up` / `Down` capacity bid-price and offered-capacity decisions with scenario-weighted accepted-capacity revenue
- enforce physical deliverability across the contracted day
- no activation, no MARI, no `aFRR`, no imbalance settlement

Files to inspect and modify:
- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/optimisation/input_resolver.py`
- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/plant_parameters.py`
- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/optimisation_model.py`
- `scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml`
- if command-centre wiring is included:
  - `scripts/Data/03_Hydrogen_Test_Case/hydrogen/command_centre.py`
  - `scripts/Data/03_Hydrogen_Test_Case/configs/optimisation_supported_options.yaml`
  - `docs/optimisation/RUN_COMMAND_CENTRE_GUIDE.md`
  - `docs/optimisation/PROJECT_DECISIONS.md`

Required input:
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/milp_exports/nl_ir_capacity_milp_input_daily_direction_scenarios_v1.csv`

Pilot window:
- fixed custom week `2025-07-07` to `2025-07-13`

Required design choices:
- use discretised daily bid-price candidates for `mFRRda` capacity
- keep offered capacity daily by direction
- bind offered capacity to time-indexed physical reserve headroom across the full day
- keep bid-price and offered-capacity decisions non-anticipative across threshold scenarios
- use expected scenario-weighted capacity revenue only

Acceptance criteria:
- no forecasting/scenario artifact modified
- no `mFRR` export recomputed
- no activation logic added
- no MARI / `aFRR` logic added
- offered capacity and bid-price decisions are daily and direction-specific
- threshold scenario probabilities are consumed exactly as exported
- deliverability constraints prevent capacity revenue without reserved flexibility
- objective decomposition reports the added expected capacity revenue separately
- one compact governed pilot output surface only
