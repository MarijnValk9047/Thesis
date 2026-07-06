# NL Incident Reserve Activation Data Source Audit v1

## 1. Purpose

This note records the repo-local source audit for a future Dutch incident-reserve / `mFRRda` activation tape. It is a planning and evidence-control document only. It does not certify any source as final activation truth, does not run API pulls, and does not implement optimisation logic.

The intended downstream layer is:

```text
accepted capacity obligation
-> historical activation request
-> physical delivery check
-> historical activation price applied only when delivery is successful
```

This is not an energy-bid strategy, merit-order, MARI, or activation-probability model.

## 2. Existing repo evidence inspected

Existing market-rule and capacity docs establish the boundary:

- `docs/market_rules/nl_incident_reserve_capacity_market_rules_v2.md` documents that accepted capacity creates a per-ISP energy-bid obligation, while activation, settlement, sanctions, and MARI are deferred.
- `docs/optimisation/nl_ir_capacity_milp_export_contract_v2.md` freezes the capacity-only export with `activation_modelling_in_scope = False`.
- `docs/forecasting/mfrr_capacity_forecasting_thesis_summary_v1.md` and `docs/forecasting/mfrr_capacity_metric_registry_v1.md` state that current mFRR work covers capacity average-price forecasting and accepted-threshold proxies, not activation modelling.
- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/mfrr_da_recourse.py` validates accepted/rejected capacity-result records, `contract_isp_count`, and hourly DA reserve obligations, and explicitly rejects rows with `activation_modelled = True`.

Existing data-import and cleaning surfaces also exist:

- `scripts/Data/00_data_imports/API_GETS.py`
- `scripts/Data/00_data_imports/README.md`
- `scripts/Data/01_cleaning/balancing_bid_document_a61_pipeline.py`
- `scripts/Data/01_cleaning/activated_balancing_energy_nl_a16_pipeline.py`

The existing local cleaned `IR Energy` artifacts are useful for schema inspection, but they are generated/local data artifacts and were not treated as Git-first thesis provenance in this audit.

## 3. Candidate source registry

| candidate | repo evidence | possible role | current audit status | main blocker before use |
|---|---|---|---|---|
| ENTSO-E `12_3_e_nl_ir_a61` | `API_GETS.py` defines `documentType=A24`, `processType=A61`, `area_Domain=10YNL----------L`; `balancing_bid_document_a61_pipeline.py` labels `A61` as `Direct_activation_mFRR` | candidate activation volume / bid-document source | candidate only | Need verify whether `quantity_maw` is realised system activation request, submitted/available energy bids, or another quantity concept; need prove incident reserve can be isolated. |
| ENTSO-E `17_1_f_nl_a16_realised` | `API_GETS.py` defines `documentType=A84`, `processType=A16`, `businessType=A97`; `activated_balancing_energy_nl_a16_pipeline.py` extracts `activation_price_eur_per_mwh` | candidate realised activation energy price source | candidate only | Need verify price concept, product filter, direction sign convention, missing-price behaviour, and whether it isolates Dutch incident reserve / `mFRRda`. |
| TenneT Developer API: Frequency restoration reserve activations | Mentioned by user as candidate; no repo-local endpoint metadata found in inspected files | candidate event/volume source | to_verify | Need identify endpoint, fields, authentication, product filter, direction convention, units, and date range. |
| TenneT Developer API: settlement prices | Mentioned by user as candidate; no repo-local endpoint metadata found in inspected files | candidate remuneration / settlement price source | to_verify | Need distinguish activation price, imbalance price, settlement price, and any sanction logic. |
| TenneT Developer API: Merit Order List Incident Reserve | Mentioned by user as candidate; no repo-local endpoint metadata found in inspected files | not primary for this tape; possible later validation of merit-order context | deferred | Merit-order strategy is out of scope for this tape. Use only if needed to understand source filtering or observed activation, not to optimise bid prices. |

## 4. ENTSO-E `12_3_E` activation-volume questions

Existing repo metadata:

- dataset key: `12_3_e_nl_ir_a61`;
- import runner: `scripts/Data/00_data_imports/API_GETS.py`;
- raw output subdir in runner: `data/00_Raw/ENTSOE/12_3_E_NL_IR_mFRRda`;
- cleaning script: `scripts/Data/01_cleaning/balancing_bid_document_a61_pipeline.py`;
- cleaning script raw subdir: `data/00_Raw/ENTSOE/12_3_E/12_3_E_NL_IR_A61`;
- process label in cleaning script: `Direct_activation_mFRR`;
- canonical resolution in cleaning script: `PT15M`;
- local cleaned schema observed under `data/01_cleaned/Balancing/IR Energy/12_3_e_nl_ir_a61/`.

Observed cleaned schema columns include:

- quarter-hour timestamps: `timestamp_utc`, `interval_end_utc`, `resolution_minutes`;
- direction fields: `flow_direction_code`, `flow_direction_label`;
- quantity fields: `quantity_maw`, `secondary_quantity_maw`, `unavailable_quantity_maw`;
- source fields: `source_block_id`, `source_file`, `business_type_code`, `business_type_label`, `market_product_type_code`.

Questions that must be answered before this source is used:

- Does `quantity_maw` represent realised activated balancing energy volume, requested activation volume, accepted bid volume, or available bid volume?
- Does `secondary_quantity_maw` or `unavailable_quantity_maw` carry emergency energy, unavailability, or a separate balancing concept?
- Can Dutch incident reserve / `mFRRda` be isolated from the `A61` process and product fields, or is it broader direct-activation mFRR?
- Are volumes system-level, BSP-level, bid-level, portfolio-level, or aggregated energy-data rows?
- Are directions `A01` and `A02` consistently `Up` and `Down` for the delivery interpretation used by the optimisation model?
- Is `MAW` in the parsed fields intended as MW for instantaneous ISP power, or a specific ENTSO-E unit label that needs conversion?
- Does the source publish rows only when there is activation, or also zero/no-activation rows?
- What is the publication delay and known-at status?

Until these are resolved, `12_3_E` should be treated as a candidate activation-volume source, not as final IR activation truth.

## 5. ENTSO-E `17.1_F` activation-price questions

Existing repo metadata:

- dataset key: `17_1_f_nl_a16_realised`;
- import runner: `scripts/Data/00_data_imports/API_GETS.py`;
- raw output subdir in runner: `data/00_Raw/ENTSOE/17.1 F - Prices of activated balancing energy/NL/A16 (Realised)`;
- cleaning script: `scripts/Data/01_cleaning/activated_balancing_energy_nl_a16_pipeline.py`;
- cleaning script known-at rule: `realised_a16_not_forecast_safe`;
- canonical resolution in cleaning script: `PT15M`;
- query variants in import runner: `Original_MarketProduct_A02`, `Original_MarketProduct_A04`, and `No_MarketProduct_Filter`;
- local cleaned schema observed under `data/01_cleaned/Balancing/IR Energy/17_1_f_nl_a16_realised/`.

Observed cleaned schema columns include:

- quarter-hour timestamps: `timestamp_utc`, `interval_end_utc`, `resolution_minutes`;
- direction fields: `flow_direction_code`, `flow_direction_label`;
- price field: `activation_price_eur_per_mwh`;
- price category fields: `imbalance_price_category_code`, `imbalance_price_category_label`;
- source fields: `source_block_id`, `source_file`, `curve_type_code`, `curve_type_label`.

Questions that must be answered before this source is used:

- Is `activation_price_eur_per_mwh` the correct remuneration price for incident-reserve activated energy?
- Does the price correspond to activated balancing energy, imbalance settlement, a settlement category, or another price concept?
- Which `Original_MarketProduct` filter corresponds to Dutch incident reserve / `mFRRda`, if any?
- Are prices published when no activation occurs, or only during activated intervals?
- Do missing prices mean no activation, unpublished price, zero price, or source gap?
- How should Up and Down price signs be interpreted for load-side reserve revenue?
- Are negative prices possible and should they be preserved exactly?
- Can emergency energy be excluded or identified separately?

Until these are resolved, `17.1_F` should be treated as a candidate activation-price source, not as final settlement truth.

## 6. TenneT Developer API questions

No repo-local endpoint definitions for TenneT Developer API activation datasets were found in the inspected files. A future source audit should check, at minimum:

- exact dataset name and endpoint for Frequency restoration reserve activations;
- endpoint for settlement prices, if separate;
- authentication requirements and whether a key is needed;
- timestamp timezone, interval duration, and publication delay;
- direction convention and reserve type;
- whether Dutch incident reserve / `mFRRda` is separable from standard mFRR, MARI, aFRR, and emergency energy;
- whether activation volumes are system-level, BSP-level, bid-level, or portfolio-level;
- whether prices are activation prices, imbalance prices, settlement prices, or energy-bid prices;
- units for volume, power, energy, and price;
- historical date range and missing-data behaviour.

No TenneT source should be used in the activation tape until these fields are verified by a small, governed source audit.

## 7. Source-use decision for v1 planning

For the first implementation phase, use the existing ENTSO-E import and cleaning surface as the lowest-friction audit route:

- candidate volume source: `12_3_e_nl_ir_a61`;
- candidate price source: `17_1_f_nl_a16_realised`;
- candidate raw root: `data/00_Raw/ENTSOE/`;
- candidate cleaned root: `data/01_cleaned/Balancing/IR Energy/`;
- candidate model-ready root: `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Activation/`.

This is not yet a source certification. The first future implementation must produce a one-month sample audit that proves product, direction, granularity, timestamp, volume, price, and missing-value semantics before any full-year activation tape is generated.

