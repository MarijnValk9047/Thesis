# NL Incident Reserve Activation API Source Registry v1

## 1. Purpose

This registry identifies source and API candidates for historical Dutch Incident Reserve / `mFRRda` activation volume/event and activation price data before any full-year pull or optimisation use.

It is a source-semantics control document only. It does not certify a full activation tape, does not run a data pull, does not integrate with the MILP, and does not change hydrogen or steel model logic.

Related local CSV audit: `docs/market_rules/nl_ir_activation_local_csv_semantics_audit_v1.md` finds the local TenneT FRR activations CSV usable for an activation-volume sample, with activation-price and product-scope blockers still open. The frozen volume-only transform is documented in `docs/market_rules/nl_ir_activation_volume_tape_freeze_v1.md`; it creates `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Activation/nl_ir_activation_volume_tape_isp_v1.csv` from `scripts/Data/02_Forecasting/02_mFRR_IR_NL/build_nl_ir_activation_volume_tape_from_tennet_frr_v1.py`.

Default governance for later work:

- `output_policy = minimal`
- no root-level outputs
- no notebook outputs
- no generated CSVs in Git
- no full-year API pull before source semantics are certified
- no API keys or secrets in files, query templates, manifests, or logs

## 2. Product taxonomy

| product_family | reserve_type_label | activation_type_label | type_of_product_label | specific_or_standard | primary_use | include_in_current_IR_tape? | notes |
|---|---|---|---|---|---|---|---|
| Incident Reserve / `mFRRda` specific product | `mFRRda`, `Incident Reserve` | direct activation | source-level Incident Reserve label; explicit TypeOfProduct still to verify in ENTSO-E | specific | target product for historical IR activation tape | yes, after source field certification | Dutch market-rule docs define Incident Reserve as a specific directly activated mFRR product. TenneT FRR activation fields expose `mfrrda_volume_up/down`; source-level product mapping still needs manual confirmation before final model input. |
| standard `mFRRsa` | `mFRRsa` | scheduled activation | Standard / TO_VERIFY | standard | separate standard mFRR comparison or validation layer | no | Keep separate from Incident Reserve. Do not mix with `mFRRda` specific-product activation rows. |
| standard `mFRRda` / direct activation, if source distinguishes it | `mFRRda` | direct activation | Standard / TO_VERIFY | standard | separate direct-activation standard product layer, if public sources distinguish it | no | Include only if a source-backed product label separates standard from specific/direct Incident Reserve. |
| `aFRR` | `aFRR` | automatic FRR | TO_VERIFY | not IR | out of scope for this activation tape | no | TenneT FRR activation and merit-order families may expose aFRR fields. They must remain separate. |
| MARI | `mFRR` platform activation | MARI activation | Standard / platform-specific | not current IR | out of scope unless unavoidable in source metadata | no | Current thesis scope excludes MARI activation and settlement until DA-only and capacity-only work are stable. |
| emergency energy | emergency energy | emergency activation/accounting | not standard reserve product | separate | excluded diagnostic/accounting quantity | no | Do not merge into activation volume unless a later rule explicitly includes it and the field is source-backed. |

## 3. Source decision table

| source_id | source_name | candidate_role | actual_spec_or_url_reference | repo_script_or_source_key | data_access_method | can_identify_mFRRda_specific? | can_identify_mFRRsa_standard? | can_identify_specific_vs_standard? | activation_volume_event_field | activation_price_field | direction_field | timestamp_field | unit | status | main_blocker | recommended_next_step |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `tennet_frr_activations` | TenneT Frequency Restoration Reserve Activations | primary candidate for activation events and volumes | `https://developer.tennet.eu/specs/v1/frequency-restoration-reserve-activations` | not yet implemented in repo | TenneT Developer API, `apikey` header, bounded by `date_from`/`date_to` | partial: explicit `mfrrda_volume_up/down` and CSV label `Incident Reserve Up/Down`; source-level mapping to specific IR still to confirm | partial: has `aFRR_up/down`; no `mFRRsa` field visible in inspected OpenAPI point schema | no explicit TypeOfProduct field in inspected OpenAPI point schema | `mfrrda_volume_up`, `mfrrda_volume_down`; `total_volume`, `absolute_total_volume` for cross-check | none | separate up/down fields | `timeInterval_start`, `timeInterval_end`, `isp` | kWh in spec response metadata | `usable_for_sample` | TenneT API key required for data; OpenAPI says activations/settled reserve/emergency energy, but inspected point schema does not expose separate settled-reserve or emergency-energy fields. Product-specific status is source-level, not a per-row TypeOfProduct field. | Run a one-day or one-month bounded metadata-controlled sample only after TenneT API access is available; verify zero/nonzero sparsity and whether `mfrrda_volume_*` is activated balancing energy or settlement/accounting volume. |
| `tennet_mol_ir` | TenneT Merit Order List Incident Reserve | later energy-bid / merit-order validation for Incident Reserve | `https://developer.tennet.eu/specs/v1/merit-order-list-bid-prices-incident-reserve` | not yet implemented in repo | TenneT Developer API, `apikey` header, `x-conversation_id` header, bounded by `date_from`/`date_to` | yes at source level: spec states incident reserve (`mFRRda`) bids | no | yes at source level for IR only, not as activation truth | none; bid ladder only | bid `price_up`, `price_down` | separate up/down bid-price fields | `time_interval_start`, `time_interval_end`, `isp` | `MAW`, `EUR/MWh` from spec metadata | `not_usable` | Merit-order bid prices and capacity thresholds are not historical activation events and are not activation remuneration prices. | Keep for later bid-stack validation only; do not use as activation truth. |
| `tennet_mol_afrr_mfrrsa` | TenneT Merit Order List aFRR & mFRRsa | later energy-bid / merit-order validation for standard products | `https://developer.tennet.eu/specs/v1/merit-order-list` | not yet implemented in repo | TenneT Developer API, `apikey` header, bounded by `date_from`/`date_to` | no | to_verify: source description covers aFRR and mFRRsa, but inspected point schema does not expose a reserve-type field | no explicit specific/standard field in inspected OpenAPI point schema | none; bid ladder only | bid `price_up`, `price_down` | separate up/down bid-price fields | `timeInterval_start`, `timeInterval_end`, `isp` | `MAW`, `EUR/MWh` from spec metadata | `not_usable` | It is a bid-stack source, not activation truth; reserve-type separation between aFRR and mFRRsa was not visible in the inspected OpenAPI point schema. | Keep separate from IR. Use only after a field-level reserve-type separation is verified. |
| `entsoe_12_3_e_a61` | ENTSO-E 12.3.E Aggregated Balancing Energy Bids, NL A61 | diagnostic fallback / cross-check for direct activation volumes | local repo key `12_3_e_nl_ir_a61`; ENTSO-E Transparency Platform API | `scripts/Data/00_data_imports/API_GETS.py`; `balancing_bid_document_a61_pipeline.py` | ENTSO-E TP API with `securityToken`; bounded sample already implemented in one-off runner | no final certification: repo labels `processType=A61` as direct activation mFRR; local `market_product_type_code=A02` exists but product meaning is not certified | no | no certified TypeOfProduct mapping | `quantity_maw` is parsed, but not certified as activated volume/event; `secondary_quantity_maw` and `unavailable_quantity_maw` parsed when present | none | `flow_direction_code`, `flow_direction_label` | `point_timestamp_utc`, `series_period_start_utc`, `series_period_end_utc` | `MAW` / MW-equivalent quantity field | `diagnostic_only` | Previous July sample had positive `quantity_maw` for every ISP in both directions after block expansion, so it is not credible as a direct activation flag without source mapping. | Do not use for final activation flags. Use only as cross-check after TenneT FRR activation sample is verified. |
| `entsoe_12_3_e_a60` | ENTSO-E 12.3.E Aggregated Balancing Energy Bids, NL A60 | possible standard `mFRRsa` diagnostic source | local repo key `12_3_e_nl_ir_a60`; ENTSO-E Transparency Platform API | `scripts/Data/00_data_imports/API_GETS.py` | ENTSO-E TP API with `securityToken` | no | to_verify: repo key labels `processType=A60` as `mFRRsa` | no certified TypeOfProduct mapping | TO_VERIFY | none | TO_VERIFY | TO_VERIFY | TO_VERIFY | `to_verify_external` | No listed local cleaner/sample certifies field semantics for A60 in this audit. | Verify ENTSO-E 12.3.E process/product mapping before any bounded sample. |
| `entsoe_12_3_e_a47` | ENTSO-E 12.3.E Aggregated Balancing Energy Bids, NL A47 | broad mFRR cross-check only | local repo key `12_3_e_nl_ir_a47`; ENTSO-E Transparency Platform API | `scripts/Data/00_data_imports/API_GETS.py` | ENTSO-E TP API with `securityToken` | no | no | no | TO_VERIFY | none | TO_VERIFY | TO_VERIFY | TO_VERIFY | `not_usable` | Broad `mFRR` process does not isolate IR / `mFRRda` specific product. | Do not use for current IR tape. |
| `entsoe_17_1_f_a16_realised` | ENTSO-E 17.1.F Prices of Activated Balancing Energy, NL A16 realised | diagnostic activation-price candidate | local repo key `17_1_f_nl_a16_realised`; ENTSO-E Transparency Platform API | `scripts/Data/00_data_imports/API_GETS.py`; `activated_balancing_energy_nl_a16_pipeline.py` | ENTSO-E TP API with `securityToken`; prior sample tested `Original_MarketProduct=A02`, `Original_MarketProduct=A04`, and no market-product filter | no | no | no: A02/A04 product-filter variants returned no matching support in prior sample; no-filter variant was diagnostic only | none | `activation_Price.amount` parsed as `activation_price_eur_per_mwh`; `imbalance_Price.category` parsed separately | `flowDirection.direction` mapped to Up/Down | `point_timestamp_utc`, `series_period_start_utc`, `series_period_end_utc` | `EUR/MWh` from `currency_Unit.name` and `price_Measure_Unit.name` | `diagnostic_only` | Product scope and remuneration concept are unresolved. Missing price must not be treated as zero. | Verify ENTSO-E 17.1.F / 17.2.E parameter mapping and price concept before activation revenue use. |
| `entsoe_17_2_e_prices_to_verify` | ENTSO-E 17.2.E prices source, if applicable | possible price-source cross-check | ENTSO-E Transparency Platform API | no repo source key identified in listed files | ENTSO-E TP API with `securityToken` | TO_VERIFY | TO_VERIFY | TO_VERIFY | none | TO_VERIFY | TO_VERIFY | TO_VERIFY | TO_VERIFY | `to_verify_external` | No repo source key or local cleaner was identified in the allowed inspection scope. | Verify whether 17.2.E is relevant to activated balancing energy remuneration for NL and whether it has product labels. |

## 4. Exact API/query templates

### TenneT `tennet_frr_activations`

```text
source_id: tennet_frr_activations
spec_url: https://developer.tennet.eu/specs/v1/frequency-restoration-reserve-activations
operation_path: /publications/v1/frequency-restoration-reserve-activations
server_template: https://api.tennet.eu
required_query_params: date_from, date_to
required_headers: apikey, Accept
timestamp_format: DD-MM-YYYY HH:MM:SS per OpenAPI example; response timestamps appear as interval start/end fields
maximum_range: 1 day per OpenAPI parameter description
rate_limits_visible: 1 request/second, 60 requests/minute, 1500 requests/day
example_template_without_secrets:
  GET https://api.tennet.eu/publications/v1/frequency-restoration-reserve-activations?date_from=<DD-MM-YYYY%20HH:MM:SS>&date_to=<DD-MM-YYYY%20HH:MM:SS>
  headers: apikey=<TENNET_API_KEY>, Accept=application/json
```

### TenneT `tennet_mol_ir`

```text
source_id: tennet_mol_ir
spec_url: https://developer.tennet.eu/specs/v1/merit-order-list-bid-prices-incident-reserve
operation_path: /publications/v1/merit-order-list-incident-reserve
server_template: https://api.acc.tennet.eu in inspected OpenAPI; production host TO_VERIFY
required_query_params: date_from, date_to
optional_query_params: response_format=json|csv
required_headers: apikey, x-conversation_id
timestamp_format: UTC timestamp ending with Z, e.g. 2024-01-01T00:00:00Z
maximum_range: 1 hour per operation description
rate_limits_visible: 1 request/second, 10 requests/minute, 600 requests/day
example_template_without_secrets:
  GET https://api.acc.tennet.eu/publications/v1/merit-order-list-incident-reserve?date_from=<YYYY-MM-DDTHH:MM:SSZ>&date_to=<YYYY-MM-DDTHH:MM:SSZ>&response_format=json
  headers: apikey=<TENNET_API_KEY>, x-conversation_id=<UUID>
```

### TenneT `tennet_mol_afrr_mfrrsa`

```text
source_id: tennet_mol_afrr_mfrrsa
spec_url: https://developer.tennet.eu/specs/v1/merit-order-list
operation_path: /publications/v1/merit-order-list
server_template: https://api.tennet.eu or https://api.acc.tennet.eu per OpenAPI server variables
required_query_params: date_from, date_to
required_headers: apikey, Accept
timestamp_format: DD-MM-YYYY HH:MM:SS per OpenAPI example
maximum_range: 1 hour per OpenAPI parameter description
rate_limits_visible: production 1 request/second, 10 requests/minute, 600 requests/day; acceptance 1 request/second, 60 requests/minute, 600 requests/day
example_template_without_secrets:
  GET https://api.tennet.eu/publications/v1/merit-order-list?date_from=<DD-MM-YYYY%20HH:MM:SS>&date_to=<DD-MM-YYYY%20HH:MM:SS>
  headers: apikey=<TENNET_API_KEY>, Accept=application/json
```

### ENTSO-E `entsoe_12_3_e_a61`

```text
source_id: entsoe_12_3_e_a61
api_base_url: https://web-api.tp.entsoe.eu/api
documentType: A24
processType: A61
businessType: not passed by repo downloader; cleaned XML has A14 Aggregated_energy_data
domain_parameter: area_Domain=10YNL----------L
periodStart/periodEnd format: YYYYMMDDHHMM
example_template_without_token:
  https://web-api.tp.entsoe.eu/api?documentType=A24&processType=A61&area_Domain=10YNL----------L&periodStart=<YYYYMMDDHHMM>&periodEnd=<YYYYMMDDHHMM>&securityToken=<TOKEN>
```

### ENTSO-E `entsoe_12_3_e_a60`

```text
source_id: entsoe_12_3_e_a60
api_base_url: https://web-api.tp.entsoe.eu/api
documentType: A24
processType: A60
businessType: TO_VERIFY
domain_parameter: area_Domain=10YNL----------L
periodStart/periodEnd format: YYYYMMDDHHMM
example_template_without_token:
  https://web-api.tp.entsoe.eu/api?documentType=A24&processType=A60&area_Domain=10YNL----------L&periodStart=<YYYYMMDDHHMM>&periodEnd=<YYYYMMDDHHMM>&securityToken=<TOKEN>
```

### ENTSO-E `entsoe_12_3_e_a47`

```text
source_id: entsoe_12_3_e_a47
api_base_url: https://web-api.tp.entsoe.eu/api
documentType: A24
processType: A47
businessType: TO_VERIFY
domain_parameter: area_Domain=10YNL----------L
periodStart/periodEnd format: YYYYMMDDHHMM
example_template_without_token:
  https://web-api.tp.entsoe.eu/api?documentType=A24&processType=A47&area_Domain=10YNL----------L&periodStart=<YYYYMMDDHHMM>&periodEnd=<YYYYMMDDHHMM>&securityToken=<TOKEN>
```

### ENTSO-E `entsoe_17_1_f_a16_realised`

```text
source_id: entsoe_17_1_f_a16_realised
api_base_url: https://web-api.tp.entsoe.eu/api
documentType: A84
processType: A16
businessType: A97
domain_parameter: controlArea_Domain=10YNL----------L
market_product_variants_tested_by_repo: Original_MarketProduct=A02; Original_MarketProduct=A04; no market-product filter
periodStart/periodEnd format: YYYYMMDDHHMM
example_template_without_token:
  https://web-api.tp.entsoe.eu/api?documentType=A84&processType=A16&businessType=A97&controlArea_Domain=10YNL----------L&periodStart=<YYYYMMDDHHMM>&periodEnd=<YYYYMMDDHHMM>&Original_MarketProduct=<A02_OR_A04_OR_TO_VERIFY>&securityToken=<TOKEN>
diagnostic_no_filter_template_without_token:
  https://web-api.tp.entsoe.eu/api?documentType=A84&processType=A16&businessType=A97&controlArea_Domain=10YNL----------L&periodStart=<YYYYMMDDHHMM>&periodEnd=<YYYYMMDDHHMM>&securityToken=<TOKEN>
```

### ENTSO-E `entsoe_17_2_e_prices_to_verify`

```text
source_id: entsoe_17_2_e_prices_to_verify
api_base_url: https://web-api.tp.entsoe.eu/api
documentType: TO_VERIFY
processType: TO_VERIFY
businessType: TO_VERIFY
domain_parameter: TO_VERIFY
periodStart/periodEnd format: YYYYMMDDHHMM
example_template_without_token:
  https://web-api.tp.entsoe.eu/api?documentType=<TO_VERIFY>&processType=<TO_VERIFY>&businessType=<TO_VERIFY>&<DOMAIN_PARAM>=10YNL----------L&periodStart=<YYYYMMDDHHMM>&periodEnd=<YYYYMMDDHHMM>&securityToken=<TOKEN>
```

## 5. Decision rules

- No product-type filter or source-level product isolation means no final model input.
- No source-backed activated-volume field means no activation flag.
- No verified activation remuneration price concept means no activation revenue.
- Missing price is not zero.
- Negative prices must be preserved.
- Emergency energy is separate unless explicitly included later.
- `mFRRda` specific and `mFRRsa` standard must not be mixed.
- Standard `mFRRda` direct activation, if present, must remain separate from Incident Reserve specific-product activation.
- Merit-order bid prices are not activation remuneration prices.
- ENTSO-E A61 `quantity_maw > 0` is not an activation event flag until the field meaning is externally verified.
- A source may be `usable_for_sample` while still being ineligible for final optimiser input.

## 6. Recommended next action

Recommendation: `blocked_until_ENTSOE_parameter_mapping_verified`.

TenneT FRR Activations is the recommended bounded-sample source for activation volumes/events, subject to TenneT API access and a sample check of `mfrrda_volume_up/down` sparsity and units. It is not enough to complete the activation tape because the activation remuneration price source is not certified.

External/manual source checks needed before implementation:

1. In ENTSO-E Transparency Platform documentation or Data View, verify the exact 17.1.F / 17.2.E parameter mapping for Dutch activated balancing energy prices:
   - `documentType`
   - `processType`
   - `businessType`
   - `Original_MarketProduct`
   - `Standard_MarketProduct`
   - product labels for `mFRR DA`, `mFRR SA`, `Specific`, `Standard`, and `Standard Local`
   - whether `activation_Price.amount` is the activation remuneration price for load-side activation
2. In TenneT balancing-publication documentation, check whether a public settlement or activation remuneration price endpoint exists that is separate from the merit-order bid-price endpoints.
3. In TenneT FRR Activations documentation or a bounded sample, confirm whether `mfrrda_volume_up/down` are activated balancing energy volumes only, or whether settled reserve and emergency energy require additional fields not visible in the inspected OpenAPI point schema.
