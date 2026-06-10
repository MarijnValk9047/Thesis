# NL Incident Reserve Capacity Market Rules V2

## Purpose
This note is the repo-local market-rules reference for Dutch incident reserve / `mFRRda` capacity integration into a MILP.

It documents the product taxonomy, capacity-auction timing, capacity-price unit handling, the relation between ENTSO-E 17.1.B&C and GL EB 12.3.F data, the first capacity-only MILP scope, and the items explicitly deferred to later energy-activation modelling.

It also defines two modelling regimes used in this project:
- Regime A: a source-backed daily incident-reserve capacity baseline;
- Regime B: a counterfactual 4-hour flexible-block sensitivity.

Regime B is not treated as an observed Dutch mFRRda market regime unless later source data confirms such a product. It is included to test how shorter capacity-commitment blocks would affect industrial demand-side participation.

## Source Basis
Primary source:
- `docs/market_rules/source_documents/tennet_incident_reserves_bsp_manual_2026-01-13.pdf`
  - title extracted from the PDF front matter: product information / manual for incident reserves for BSPs
  - controlling source for incident reserve / `mFRRda` product mechanics

Secondary later-use source:
- `docs/market_rules/source_documents/tennet_imbalance_pricing_system_v6_1_2024-10-21.pdf`
  - settlement context only
  - not the controlling source for current incident-reserve energy-bid obligations

Optional later-use source present:
- `docs/market_rules/source_documents/tennet_mari_standard_mfrr_handbook_2025.pdf`
  - standard `mFRR` / MARI product reference only
  - not the controlling source for the incident-reserve capacity model

Additional ENTSO-E interpretation basis:
- ENTSO-E Transparency Platform documentation for TR 17.1.B&C indicates that balancing-reserve volumes and prices are published per ISP and that prices are expressed as `Currency/MW/ISP`.
- ENTSO-E Transparency Platform documentation for GL EB 12.3.F indicates that procured balancing-capacity offer volumes and prices are published per ISP and that prices are expressed as `Currency/MW/ISP`.

## A. Product Taxonomy

### 1. Incident reserve / `mFRRda` capacity product
This is the current focus for the frozen threshold scenarios and the first MILP integration.

From the incident-reserve manual:
- incident reserve is the specific Dutch directly activated `mFRRda` / noodvermogen product;
- incident reserve has both a balancing capacity product and a balancing energy product;
- the capacity product is procured asymmetrically, either upward or downward;
- a contract for balancing capacity obligates the BSP to offer a certain volume of balancing energy bids;
- TenneT procures the capacity via capacity auctions.

This is the correct scope for the current frozen threshold-scenario artifact.

### 2. Incident reserve energy product
This is a required obligation after capacity acceptance, but the first capacity-only MILP does not yet model activation settlement.

From the incident-reserve manual:
- energy bids are submitted per ISP;
- the bid is a volume / price combination for one ISP;
- energy bids are valid for one ISP of 15 minutes;
- BEGCT is 25 minutes before the validity period of the bid;
- at BEGCT the bid becomes firm and the BSP is obligated to deliver upon activation;
- energy bids are asymmetric, either upward or downward;
- bids are selected from the incident-reserve merit-order list;
- upward volume is ordered price-ascending;
- downward volume is ordered price-descending.

The energy-bid layer should be preserved conceptually. In V1 MILP it may be represented as an obligation / deliverability flag, while strategic energy-bid pricing, activation probability, and settlement are deferred.

### 3. MARI / standard `mFRR` energy product
This is a separate later product.

From the standard `mFRR` / MARI handbook:
- the document explicitly refers to the standard `mFRR` product, also referred to as the MARI product;
- the handbook distinguishes this product from `mFRRda`;
- it states that `mFRRda` is a specific capacity product for which TenneT has an exemption;
- the MARI / standard `mFRR` product is an energy-bid product with its own delivery, settlement, and verification rules.

Therefore:
- do not use MARI rules to redefine the current Dutch incident-reserve capacity scenario layer;
- treat MARI as a separate future extension.

### 4. `aFRR`
`aFRR` is not in scope for the first incident-reserve capacity MILP.

The incident-reserve manual discusses coexistence and allocation-point interaction with `aFRR`, but the current frozen threshold layer is not an `aFRR` product.

## B. Capacity Auction Rules Relevant For First MILP Integration

From the incident-reserve manual:
- auction timing: the capacity auction takes place daily on `D-1` at `09:00` Amsterdam time;
- operational conclusion for this project: local-market cutoff `D-1 09:00 Europe/Amsterdam`;
- contract duration in the inspected manual: in principle one calendar day, `00:00` to `00:00`;
- procurement is asymmetric: upward and downward capacity are separate;
- minimum bid size: `1 MW`;
- step size: `1 MW`;
- capacity remuneration: pay-as-bid;
- accepted capacity creates an obligation to send in energy bids within the contracted period, for at least the contracted volume over the contracted period;
- capacity and energy deliverability must be guaranteed from the BSP portfolio.

Implication for V1:
- the first MILP may model capacity acceptance and capacity revenue only;
- it should not yet model incident-reserve activation settlement;
- however, it must preserve the fact that accepted capacity creates a per-ISP energy-bid obligation.

## C. ENTSO-E Data-Use Distinction

### 1. TR 17.1.B&C: final aggregate market outcome
Use 17.1.B&C for final aggregate market outcomes:
- final procured capacity per ISP;
- average paid price per ISP for pay-as-bid schemes;
- marginal price per ISP where marginal pricing applies;
- validation of aggregate procured volume and average paid price.

For the Dutch incident-reserve / `mFRRda` pay-as-bid capacity product, 17.1.B&C should be interpreted as:
- `final_procured_capacity_mw`;
- `average_paid_price_eur_per_mw_isp`.

Do not use 17.1.B&C as an individual bid ladder.

### 2. GL EB 12.3.F: individual accepted / procured offers
Use GL EB 12.3.F for individual accepted offer information:
- accepted offer prices;
- accepted offer volumes;
- accepted-only bid ladder construction;
- accepted price distribution;
- max / p75 / p90 accepted price proxies;
- scenario generation for acceptance-threshold proxies.

Important caveats:
- 12.3.F contains only accepted/procured offers, not rejected offers;
- 12.3.F cannot reconstruct the full submitted bid ladder;
- 12.3.F cannot identify the true acceptance threshold or rejected-bid boundary;
- for divisible bids, the published offered volume of a procured bid may be larger than the actually procured volume.

Therefore:
- use 17.1.B&C as authoritative for final aggregate procured volume;
- use 12.3.F as authoritative for accepted-offer price structure;
- compare `sum_12_3_f_offered_volume_mw` with `17_1_bc_procured_volume_mw` as a reconciliation diagnostic.

## D. Capacity Price Unit And Revenue Scaling

### 1. Native ENTSO-E unit
For both 17.1.B&C and GL EB 12.3.F, ENTSO-E documents the capacity price unit as:

`Currency/MW/ISP`

For Dutch data this should be treated as:

`EUR/MW/ISP`

This means that `daily` in the auction/product context does not automatically mean that the price is already `EUR/MW/day`. A daily product is represented over multiple ISPs.

### 2. Correct revenue expression in native units
If the MILP keeps prices in ENTSO-E-native units, use:

`capacity_revenue = accepted_scenario * bid_price_eur_per_mw_isp * offered_capacity_mw * contract_isp_count`

Where:
- `accepted_scenario` is 0/1 or an expected acceptance probability depending on formulation;
- `bid_price_eur_per_mw_isp` is the BSP's candidate capacity bid price in `EUR/MW/ISP`;
- `offered_capacity_mw` is the offered capacity volume;
- `contract_isp_count` is the number of ISPs covered by the capacity contract.

For a normal full 15-minute delivery day:

`contract_isp_count = 96`

For a source-confirmed 4-hour 15-minute product:

`contract_isp_count = 16`

Do not hardcode either value. Compute `contract_isp_count` from `delivery_start` and `delivery_end` so that DST days and shorter products are handled correctly.

### 3. Alternative converted-unit formulation
A valid alternative is to convert prices before the MILP:

`bid_price_eur_per_mw_contracted_period = bid_price_eur_per_mw_isp * contract_isp_count`

Then revenue can be written as:

`capacity_revenue = accepted_scenario * bid_price_eur_per_mw_contracted_period * offered_capacity_mw`

This is only valid if all threshold prices, bid-price decision variables, units, documentation, and export columns are consistently converted.

### 4. Implementation rule
Preferred implementation for this project:
- keep the ENTSO-E-native unit `EUR/MW/ISP`;
- include `contract_isp_count` explicitly in the MILP export and objective;
- rename ambiguous unit labels such as `EUR_per_MW_per_period` unless `period = ISP` is explicitly documented.

Recommended fields:
- `acceptance_threshold_price_eur_per_mw_isp`;
- `candidate_bid_price_eur_per_mw_isp`;
- `offered_capacity_mw`;
- `contract_isp_count`;
- `capacity_revenue_rule_proxy = accepted_scenario_times_bid_price_eur_per_mw_isp_times_offered_capacity_mw_times_contract_isp_count`.

## E. Forecast / Scenario Artifact Implications

The frozen threshold scenario artifact should be interpreted as follows:
- `threshold_price_scenario` is an accepted-threshold proxy;
- a simple bid-acceptance proxy can be represented as `bid_price_eur_per_mw_isp <= threshold_price_scenario_eur_per_mw_isp` if the scenario artifact has not been converted;
- threshold scenarios are not full submitted bid-ladder truth;
- the `max` scenario is an optimistic upper-bound proxy, not a true market-clearing threshold;
- pre-`2025-01-07` threshold scenarios are synthetic / proxy only;
- scenario probabilities are optimisation weights, not empirical probabilities;
- Down scenarios have weak stochastic richness because observed Down accepted stacks are mostly flat.

Before MILP export, the pipeline must verify whether the threshold scenario values are still ENTSO-E-native `EUR/MW/ISP` or were already converted to `EUR/MW/contracted_period` upstream.

## F. Timing Metadata Alignment

A timing metadata issue is explicitly frozen as a follow-up item.

Current project state:
- earlier project assumptions used `D-1 10:00 Europe/Amsterdam` for `mFRR` capacity timing metadata;
- the incident-reserve manual indicates the capacity auction is on `D-1 09:00 Amsterdam time`.

Implication:
- before any MILP export, `known_at_cutoff_utc` and related forecast-origin timing fields should be audited and aligned to the incident-reserve capacity cutoff at `D-1 09:00 Europe/Amsterdam`;
- this note does not repair any artifact metadata;
- the existing frozen scenario values are not changed here; the issue is a metadata-alignment and downstream-timing issue.

## G. Minimal First Capacity-Only MILP Formulation Assumptions

The intended first integration is a capacity-only proxy, not a full energy-activation model.

Decision candidates:
- offered capacity in MW by direction and contract block;
- capacity bid price by direction and contract block;
- production schedule / flexibility reservation to keep the offered capacity deliverable.

Scenario uncertainty:
- `threshold_price_scenario_eur_per_mw_isp` by direction and scenario;
- `scenario_probability` or scenario weight.

Acceptance proxy:
- `accepted_scenario = (bid_price_eur_per_mw_isp <= threshold_price_scenario_eur_per_mw_isp)`

Capacity revenue proxy:
- `capacity_revenue = accepted_scenario * bid_price_eur_per_mw_isp * offered_capacity_mw * contract_isp_count`

Availability / obligation rule:
- if capacity is accepted, enough upward or downward flexibility must be reserved across the contracted period;
- a first V1 proxy may use `offered_capacity_mw <= minimum_available_flexibility_mw_over_contract_period`;
- capacity revenue should not be allowed without deliverability;
- accepted capacity should create an obligation flag for per-ISP energy bids, even if activation settlement is deferred.

Explicit V1 exclusions:
- no activation probability yet;
- no strategic 15-minute energy-bid optimisation yet;
- no imbalance settlement yet;
- no sanctions yet;
- no MARI energy bidding yet.

## H. Later Activation / Energy Extension Rules To Preserve

These rules should be preserved for a later extension, but remain out of scope for V1:
- incident-reserve energy bids are 15-minute ISP bids;
- BEGCT is 25 minutes before the validity period;
- energy bids are asymmetric;
- energy bid volume must cover at least the contracted capacity volume for accepted capacity periods;
- activation uses the incident-reserve merit order;
- upward and downward merit-order sorting differs;
- activation and deactivation affect settlement volumes;
- reference values and 5-minute measurements matter for delivery verification;
- sanctions may apply for capacity / energy non-delivery or process failures.

## I. Imbalance And Sign Convention Notes

From the imbalance-pricing document:
- positive prices for upward regulation result in a financial flow to the BSP; TenneT pays;
- for downward regulation the sign is reversed: positive prices result in a financial flow to TenneT; the BSP pays;
- the ISP is 15 minutes;
- activated balancing energy is settled through balancing-energy / imbalance-pricing logic;
- imbalance-pricing logic is a later-use settlement layer and should be deferred until activation / energy modelling is included.

Priority rule for this project:
- if there is any tension between the older imbalance-pricing document and the newer incident-reserve manual on incident-reserve-specific mechanics, prefer the newer incident-reserve manual for incident-reserve product mechanics.

## J. Market Regimes Used In This Project

This project supports two incident-reserve capacity regimes.

### Regime A: Source-backed daily incident-reserve capacity baseline

Regime A is the historical/source-backed baseline. It follows the inspected TenneT incident-reserve manual and models the Dutch incident reserve / `mFRRda` capacity product as a daily capacity product with a normal contract period from `00:00` to `00:00`.

Configuration:

* `regime_id = IR_daily_source_backed`
* `source_status = source_backed`
* `block_duration_hours = 24`
* `blocks_per_day = 1`
* `bidding_mode = daily_all_or_nothing`
* `quantity_mode = uniform_daily_capacity`
* `price_construction = observed_daily`
* `contract_isp_count` is computed from `delivery_start` and `delivery_end`, normally `96` for a full 15-minute delivery day.

This regime may be used for historical/source-backed backtesting.

### Regime B: Counterfactual 4-hour flexible-block sensitivity

Regime B is a counterfactual sensitivity. It is not treated as an observed Dutch incident-reserve / `mFRRda` market regime unless later TenneT, APFAS, or ENTSO-E source data confirms 4-hour contract blocks for the relevant product.

Regime B splits each delivery day into six 4-hour capacity blocks and allows the model to decide participation and capacity volume per block. Its purpose is to test how shorter capacity-commitment blocks would affect the ability of an industrial site to participate in reserve-capacity markets under production and flexibility constraints.

Configuration:

* `regime_id = IR_4h_counterfactual_flexible`
* `source_status = counterfactual`
* `block_duration_hours = 4`
* `blocks_per_day = 6`
* `bidding_mode = optional_per_block`
* `quantity_mode = block_specific_capacity`
* `price_construction = daily_price_repeated_to_blocks` unless a separate synthetic block-price construction is explicitly documented
* `contract_isp_count` is computed from `delivery_start` and `delivery_end`, normally `16` for a 4-hour 15-minute block.

Regime B must not be described as a historical observed 4-hour mFRRda backtest if no source-confirmed 4-hour mFRRda capacity data is used. It should be reported as a counterfactual market-design sensitivity.

### Shared implementation rule

Do not hardcode `contract_isp_count = 96` or `contract_isp_count = 16`. Always compute `contract_isp_count` from `delivery_start`, `delivery_end`, and ISP duration, so that daily products, 4-hour blocks, DST days, and any later source-confirmed shorter products are handled consistently.


## K. In- and Out Of Scope For First MILP Integration

Explicitly out of scope for the first capacity-only integration:
- MARI standard `mFRR` energy product;
- `aFRR`;
- activation probability;
- activation dispatch;
- strategic energy-bid price optimisation;
- imbalance adjustment;
- BRP settlement;
- sanctions;
- 5-minute measurement validation;
- full submitted bid-ladder reconstruction;
- rejected-bid inference;
- source-backed historical 4-hour incident-reserve capacity modelling unless source-verified for the relevant product/regime;
- observed 4-hour mFRRda price or contract-period claims unless supported by TenneT, APFAS, or ENTSO-E source data.

Explicitly in scope as a counterfactual sensitivity:
- Regime B: 4-hour flexible-block incident-reserve capacity modelling, provided it is clearly labelled as counterfactual and does not claim to use observed 4-hour mFRRda capacity prices or source-confirmed 4-hour contract periods.

## L. Recommended Next Tasks

### 1. `MFRR_CAPACITY_TIMING_METADATA_ALIGNMENT_AUDIT_V2`
Purpose:
- inspect frozen `mFRR` capacity artifacts for `D-1 10:00` versus `D-1 09:00` metadata;
- recommend whether a metadata-only repair is needed before MILP export.

### 2. `MFRR_CAPACITY_PRICE_UNIT_AND_REVENUE_SCALING_AUDIT_V1`
Purpose:
- inspect whether threshold scenario artifacts and MILP exports use ENTSO-E-native `EUR/MW/ISP` or converted `EUR/MW/contracted_period` values;
- update ambiguous labels such as `EUR_per_MW_per_period`;
- add `contract_isp_count` to the export if native prices are retained;
- prevent undercounting capacity revenue by omitting the ISP multiplier.

### 3. `MFRR_CAPACITY_MILP_EXPORT_CONTRACT_BLOCK_V2`
Purpose:
- define and build a clean MILP input export from the frozen threshold scenario artifact;
- preserve scenario values unless a deliberate unit conversion is applied;
- include `delivery_start`, `delivery_end`, `contract_isp_count`, and explicit price units;
- avoid hardcoded daily-only assumptions.

### 4. `MFRR_CAPACITY_ONLY_MILP_PILOT_V2`
Purpose:
- run a small test-period capacity-only integration;
- include corrected capacity revenue scaling;
- include deliverability constraints and energy-bid obligation flags;
- no activation settlement yet.
