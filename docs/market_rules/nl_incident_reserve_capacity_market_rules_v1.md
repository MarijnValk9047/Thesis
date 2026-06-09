# NL Incident Reserve Capacity Market Rules V1

## Purpose
This note is the repo-local fallback market-rules reference for later Dutch incident reserve / `mFRRda` capacity integration into a MILP.

It documents the product taxonomy, the first capacity-only integration scope, the timing correction that must be audited later, and the items that are explicitly deferred.

## Source Basis
Primary source:
- `docs/market_rules/source_documents/tennet_incident_reserves_bsp_manual_2026-01-13.pdf`
  - title extracted from the PDF front matter: product information / manual for incident reserves for BSPs

Secondary later-use source:
- `docs/market_rules/source_documents/tennet_imbalance_pricing_system_v6_1_2024-10-21.pdf`

Optional later-use source present:
- `docs/market_rules/source_documents/tennet_mari_standard_mfrr_handbook_2025.pdf`

## A. Product Taxonomy
### 1. Incident reserve / `mFRRda` capacity product
This is the current focus for the frozen threshold scenarios.

From the incident-reserve manual:
- incident reserve has both a balancing capacity product and a balancing energy product
- the capacity product is procured asymmetrically, either upward or downward
- a contract for balancing capacity obligates the BSP to offer a certain volume of balancing energy bids
- TenneT procures the capacity via daily capacity auctions

This is the correct scope for the current frozen threshold-scenario artifact.

### 2. Incident reserve energy product
This is a later extension, not the first capacity-only prototype.

From the incident-reserve manual:
- energy bids are submitted per ISP
- the bid is a volume / price combination for one ISP
- energy bids are valid for one ISP of 15 minutes
- BEGCT is 25 minutes before the validity period of the bid
- energy bids are asymmetric, either upward or downward
- bids are selected from the incident-reserve merit-order list
- upward volume is ordered price-ascending, downward volume price-descending

This energy layer should be preserved conceptually, but deferred from the first capacity-only MILP.

### 3. MARI / standard `mFRR` energy product
This is a separate later product.

From the standard `mFRR` / MARI handbook:
- the document explicitly refers to the standard `mFRR` product, also referred to as the MARI product
- the handbook distinguishes this from `mFRRda`
- it states that `mFRRda` is a specific capacity product for which TenneT has an exemption
- the MARI / standard `mFRR` product is an energy-bid product with its own delivery, settlement, and verification rules

Therefore:
- do not use MARI rules to redefine the current Dutch incident-reserve capacity scenario layer
- treat MARI as a separate future extension

### 4. `aFRR`
`aFRR` is not in scope for the first incident-reserve capacity MILP.

The incident-reserve manual discusses coexistence and allocation-point interaction with `aFRR`, but the current frozen threshold layer is not an `aFRR` product.

## B. Capacity Auction Rules Relevant For First MILP Integration
From the incident-reserve manual:
- auction timing: the capacity auction takes place daily on `D-1` at `09:00` Amsterdam time
- source text also indicates `UTC 01:00, Amsterdam time 09:00` in the extracted snippet; the operational conclusion for this project is the local-market cutoff `D-1 09:00 Europe/Amsterdam`
- contract duration: in principle one calendar day, `00:00` to `00:00`
- procurement is asymmetric: upward and downward capacity are separate
- minimum bid size: `1 MW`
- step size: `1 MW`
- remuneration: pay-as-bid
- accepted capacity creates an obligation to send in energy bids within the contracted period, for at least the contracted volume over the contracted period
- capacity / energy deliverability must be guaranteed from the BSP portfolio

Implication for v1:
- the first MILP should model capacity acceptance and capacity revenue only
- it should not yet model incident-reserve activation settlement

## C. Forecast / Scenario Artifact Implications
The frozen threshold scenario artifact should be interpreted as follows:
- `threshold_price_scenario` is an accepted-threshold proxy
- a simple bid-acceptance proxy can be represented as `bid_price <= threshold_price_scenario`
- threshold scenarios are not full submitted bid-ladder truth
- the `max` scenario is an optimistic upper-bound proxy, not a true market-clearing threshold
- pre-`2025-01-07` threshold scenarios are synthetic / proxy only
- scenario probabilities are optimisation weights, not empirical probabilities
- Down scenarios have weak stochastic richness because observed Down accepted stacks are mostly flat

## D. Timing Metadata Alignment
A timing metadata issue is now explicitly frozen as a follow-up item.

Current project state:
- earlier project assumptions used `D-1 10:00 Europe/Amsterdam` for mFRR capacity timing metadata
- the incident-reserve manual indicates the capacity auction is on `D-1 09:00 Amsterdam time`

Implication:
- before any MILP export, `known_at_cutoff_utc` and related forecast-origin timing fields should be audited and aligned to the incident-reserve capacity cutoff at `D-1 09:00 Europe/Amsterdam`
- this note does not repair any artifact metadata
- the existing frozen scenario values are not changed here; the issue is a metadata-alignment and downstream-timing issue

## E. Minimal First Capacity-Only MILP Formulation Assumptions
The intended first integration is a capacity-only proxy, not a full energy-activation model.

Decision candidates:
- daily offered capacity in MW by direction
- daily capacity bid price by direction
- production schedule / flexibility reservation to keep the offered capacity deliverable

Scenario uncertainty:
- `threshold_price_scenario` by direction and scenario
- `scenario_probability`

Acceptance proxy:
- `accepted_scenario = (bid_price <= threshold_price_scenario)`

Capacity revenue proxy:
- `capacity_revenue = accepted_scenario * bid_price * offered_capacity_mw`

Availability / obligation rule:
- if capacity is accepted, enough upward or downward flexibility must be reserved across the contracted day
- a first v1 proxy may use `offered_capacity <= minimum available flexibility over relevant periods`
- capacity revenue should not be allowed without deliverability

Explicit v1 exclusions:
- no activation probability yet
- no 15-minute energy-bid optimisation yet
- no imbalance settlement yet
- no sanctions yet
- no MARI energy bidding yet

## F. Later Activation / Energy Extension Rules To Preserve
These rules should be preserved for a later extension, but remain out of scope for v1:
- incident-reserve energy bids are 15-minute ISP bids
- BEGCT is 25 minutes before the validity period
- energy bids are asymmetric
- activation uses the incident-reserve merit order
- upward and downward merit-order sorting differs
- activation and deactivation affect settlement volumes
- reference values and 5-minute measurements matter for delivery verification
- sanctions may apply for capacity / energy non-delivery or process failures

## G. Imbalance And Sign Convention Notes
From the imbalance-pricing document:
- positive prices for upward regulation result in a financial flow to the BSP; TenneT pays
- for downward regulation the sign is reversed: positive prices result in a financial flow to TenneT; the BSP pays
- the ISP is 15 minutes
- imbalance-pricing logic is a later-use settlement layer and should be deferred until activation / energy modelling is included

Priority rule for this project:
- if there is any tension between the older imbalance-pricing document and the newer incident-reserve manual on incident-reserve-specific mechanics, prefer the newer incident-reserve manual for incident-reserve product mechanics

## H. Out Of Scope For First MILP Integration
Explicitly out of scope for the first capacity-only integration:
- MARI standard `mFRR` energy product
- `aFRR`
- activation probability
- activation dispatch
- imbalance adjustment
- BRP settlement
- sanctions
- 5-minute measurement validation
- full submitted bid-ladder reconstruction
- rejected-bid inference
- 4-hour block products unless source-verified for the relevant product/regime

## I. Recommended Next Tasks
### 1. `MFRR_CAPACITY_TIMING_METADATA_ALIGNMENT_AUDIT_V1`
Purpose:
- inspect frozen `mFRR` capacity artifacts for `D-1 10:00` versus `D-1 09:00` metadata
- recommend whether a metadata-only repair is needed before MILP export

### 2. `MFRR_CAPACITY_MILP_EXPORT_CONTRACT_DAILY_V1`
Purpose:
- define and build a clean MILP input export from the frozen threshold scenario artifact
- no scenario recomputation

### 3. `MFRR_CAPACITY_ONLY_MILP_PILOT_V1`
Purpose:
- run a small test-period capacity-only integration
- no activation yet
