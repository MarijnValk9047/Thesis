# NL Incident Reserve Activation Tape Pipeline Plan v1

## 1. Purpose and scope

This plan designs a clean, reproducible pipeline for historical Dutch incident-reserve / `mFRRda` activation events and activation prices. The output is a model-ready historical activation tape for later optimisation evaluation.

Included:

- historical activation flags;
- historical activation volumes;
- historical activation prices;
- direction;
- ISP timestamps;
- source quality flags;
- model-ready activation tape fields.

Excluded:

- energy-bid strategy;
- energy-bid price optimisation;
- merit-order bidding;
- activation probability forecasting;
- MARI;
- MILP integration;
- activation redispatch;
- settlement or sanction implementation beyond preparing traceable price fields.

This plan does not run a large API pull and does not change the hydrogen, steel, or MILP code.

## 2. Market interpretation

The intended modelling chain is:

```text
capacity accepted
-> reserve obligation exists
-> historical activation event occurs
-> model is asked to deliver activation
-> model receives historical activation price only if delivery is successful
```

Terminology:

- a capacity bid is accepted or rejected;
- accepted capacity creates a reserve and per-ISP energy-bid obligation;
- real-time balancing energy activation creates a request to deliver upward or downward regulation;
- this activation tape is an ex-post realised evaluation input, not a forecast available before the capacity auction.

No-leakage rule:

- before capacity bidding, activation scenarios may only be based on historical training or validation distributions;
- for ex-post evaluation, the realised historical activation tape may be applied to the delivery day;
- same-day realised activation information must not enter the pre-auction, DA-bidding, or pre-delivery decision.

## 3. Source audit questions

The companion source audit is:

- `docs/market_rules/nl_ir_activation_data_source_audit_v1.md`

For each candidate source, the implementation must verify:

- exact dataset name;
- access method and API endpoint;
- authentication needs;
- timestamp timezone and interval;
- direction convention;
- reserve type and product type;
- whether Dutch incident reserve / `mFRRda` can be isolated;
- whether emergency energy is separate;
- whether volumes are system-level or BSP/bid-level;
- whether prices are activation prices, settlement prices, imbalance prices, or another concept;
- available date range;
- publication delay;
- missing-price behaviour;
- units.

Concepts that must not be mixed:

- capacity price;
- activation energy price;
- imbalance price;
- settlement price;
- energy-bid price;
- merit-order bid price.

Current repo-local candidate status:

| candidate | possible role | current status |
|---|---|---|
| ENTSO-E `12_3_e_nl_ir_a61` | activation volume / direct-activation mFRR quantity candidate | candidate only; volume semantics and IR isolation must be verified |
| ENTSO-E `17_1_f_nl_a16_realised` | realised activation price candidate | candidate only; product filter and price concept must be verified |
| TenneT Developer API Frequency restoration reserve activations | possible activation event / volume source | to_verify; no endpoint metadata inspected in repo |
| TenneT Developer API settlement prices | possible remuneration / settlement source | to_verify; no endpoint metadata inspected in repo |
| TenneT Merit Order List Incident Reserve | later source context only | not primary because merit-order strategy is out of scope |

## 4. Proposed repo pipeline

### Stage A - Source audit

Output:

- `docs/market_rules/nl_ir_activation_data_source_audit_v1.md`

Goal:

- prove which source fields can support activation flags, volumes, prices, direction, and ISP timestamps.

Rules:

- no source is final until product, direction, granularity, timestamp, price, and unit semantics are verified;
- do not claim incident-reserve isolation if only broader mFRR can be identified;
- do not use generated local artifacts as thesis truth without source-field verification.

### Stage B - Raw API retrieval

Use the existing raw import convention:

- `data/00_Raw/ENTSOE/12_3_E_NL_IR_mFRRda/`
- `data/00_Raw/ENTSOE/17.1 F - Prices of activated balancing energy/NL/A16 (Realised)/`

If a TenneT Developer API source is adopted later, use:

- `data/00_Raw/TenneT/IR_Activation/<dataset_key>/<retrieval_id>/`

Required manifest fields:

| field | meaning |
|---|---|
| `source_name` | ENTSO-E or TenneT Developer API |
| `dataset_name` | stable dataset key |
| `api_endpoint_or_source_reference` | endpoint or source reference |
| `query_start_utc` | query start |
| `query_end_utc` | query end |
| `retrieved_at_utc` | retrieval timestamp |
| `raw_file_path` | raw response path |
| `row_count` | parsed/raw row count if available |
| `response_hash` | hash of raw response |
| `api_version` | source API version if available |
| `notes` | caveats |

Rules:

- no API keys in Git;
- raw pulls are immutable;
- start with one month, not a full-year pull;
- do not overwrite raw files;
- do not create root-level outputs;
- generated raw files are not Git-first artifacts.

### Stage C - Clean activation volume table

Preferred cleaned location:

- `data/01_cleaned/Balancing/IR Energy/nl_ir_activation_volume_isp_long_v1.csv`

Existing related local artifacts:

- `data/01_cleaned/Balancing/IR Energy/12_3_e_nl_ir_a61/quarterhour/12_3_e_nl_ir_a61_quarterhour_long.csv`
- `data/01_cleaned/Balancing/IR Energy/12_3_e_nl_ir_a61/hourly/12_3_e_nl_ir_a61_hourly_long.csv`

Minimum columns:

| column | notes |
|---|---|
| `delivery_start_utc` | ISP start in UTC |
| `delivery_end_utc` | ISP end in UTC |
| `delivery_start_local` | Europe/Amsterdam reporting timestamp |
| `delivery_date_local` | local delivery date |
| `isp_index_local` | local ISP index within delivery day |
| `direction` | `Up` or `Down` |
| `reserve_type` | e.g. `mFRR` |
| `product_type` | e.g. `mFRRda` or `to_verify` |
| `activation_scope` | e.g. system-level, BSP-level, bid-level, to_verify |
| `system_activated_volume_mw` | source-backed system activation volume if verified |
| `settled_reserve_mw` | separate field if source provides settlement volume |
| `emergency_energy_mw` | separate field if source identifies emergency energy |
| `activation_flag` | true only under verified nonzero activation rule |
| `source_dataset` | source key |
| `data_quality_flag` | source quality / ambiguity |

Design rules:

- keep Up and Down explicit;
- keep emergency energy separate unless explicitly included by a source-backed rule;
- do not silently combine FRR products;
- if Incident Reserve cannot be isolated, set `data_quality_flag = product_scope_ambiguous` and do not use as final IR truth.

### Stage D - Clean activation price table

Preferred cleaned location:

- `data/01_cleaned/Balancing/IR Energy/nl_ir_activation_price_isp_long_v1.csv`

Existing related local artifacts:

- `data/01_cleaned/Balancing/IR Energy/17_1_f_nl_a16_realised/quarterhour/17_1_f_nl_a16_realised_quarterhour_long.csv`
- `data/01_cleaned/Balancing/IR Energy/17_1_f_nl_a16_realised/hourly/17_1_f_nl_a16_realised_hourly_long.csv`

Minimum columns:

| column | notes |
|---|---|
| `delivery_start_utc` | ISP start in UTC |
| `delivery_end_utc` | ISP end in UTC |
| `delivery_start_local` | Europe/Amsterdam reporting timestamp |
| `delivery_date_local` | local delivery date |
| `isp_index_local` | local ISP index within delivery day |
| `direction` | `Up` or `Down` |
| `reserve_type` | e.g. `mFRR` |
| `product_type` | e.g. `mFRRda` or `to_verify` |
| `activation_price_eur_per_mwh` | source-backed price field |
| `price_type` | activation, settlement, imbalance, or to_verify |
| `price_available` | boolean |
| `source_dataset` | source key |
| `data_quality_flag` | source quality / ambiguity |

Design rules:

- do not interpret missing prices as zero;
- distinguish activation price from imbalance price and energy-bid price;
- preserve negative prices if present;
- keep source units traceable.

### Stage E - Joined model-ready activation tape

Preferred model-input location:

- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Activation/nl_ir_activation_tape_isp_v1.csv`

Minimum columns:

| column | notes |
|---|---|
| `delivery_start_utc` | ISP start in UTC |
| `delivery_end_utc` | ISP end in UTC |
| `delivery_start_local` | Europe/Amsterdam reporting timestamp |
| `delivery_date_local` | local delivery date |
| `isp_index_local` | local ISP index within delivery day |
| `direction` | `Up` or `Down` |
| `activation_flag` | realised activation flag |
| `system_activated_volume_mw` | verified system volume |
| `activation_price_eur_per_mwh` | verified price |
| `price_available` | boolean |
| `activation_duration_hours` | normally `0.25` for one ISP |
| `activation_volume_source` | source key/path |
| `activation_price_source` | source key/path |
| `activation_scope` | system-level, BSP-level, bid-level, or to_verify |
| `data_quality_flag` | combined quality flag |

Optional columns for later model use:

- `activation_cluster_id`;
- `activation_cluster_length_isps`;
- `activation_assignment_rule_default`;
- `historical_realised_flag`;
- `usable_for_training`;
- `usable_for_validation`;
- `usable_for_test`.

Generated tape files are not Git-first by default. Commit only compact docs, manifests, and contracts unless a small thesis-critical provenance exception is explicitly approved.

## 5. Activation assignment rules for later modelling

These rules define future model interfaces only. They are not implemented by this plan.

### Rule 1 - full call if system activated

```text
if historical system activation in direction d:
    requested_activation_mw = accepted_capacity_mw
```

Use as a conservative stress test.

### Rule 2 - volume capped historical activation

```text
requested_activation_mw = min(accepted_capacity_mw, system_activated_volume_mw)
```

Recommended first default once system volume is source-backed. It avoids assuming a plant is fully activated whenever a small system activation occurs.

### Rule 3 - pro-rata activation

```text
activation_fraction = system_activated_volume_mw / reference_available_volume_mw
requested_activation_mw = accepted_capacity_mw * activation_fraction
```

Use later only if `reference_available_volume_mw` is source-backed.

Without energy-bid merit-order modelling, plant-specific activation is not directly observed. These rules are assignment assumptions for historical tape simulation, not observed plant activation truth.

## 6. Revenue logic for later model use

Future accounting should use:

```text
requested_activation_energy_mwh =
    requested_activation_mw * activation_duration_hours

delivered_activation_energy_mwh =
    delivered_activation_mw * activation_duration_hours

if delivery_ok:
    activation_revenue =
        delivered_activation_energy_mwh * activation_price_eur_per_mwh
else:
    activation_revenue =
        0 or partial, depending on later source-backed settlement rule
```

First conservative default:

```text
revenue_paid_only_if_delivery_ok = true
non_delivery_reported_explicitly = true
no hidden penalty-only feasibility
```

Do not decide final sanction logic here. Needed evidence:

- source-backed non-delivery settlement rule;
- sign convention for Up and Down settlement;
- whether partial delivery receives partial energy remuneration;
- whether capacity non-delivery penalties interact with activation non-delivery;
- whether imbalance settlement applies separately.

## 7. Diagnostics to produce after a future sample pull

Do not run these diagnostics until a governed one-month sample exists.

Required diagnostics:

| diagnostic | purpose |
|---|---|
| `number_of_ISPs` | support size |
| `activation_ISP_count` | realised activation frequency count |
| `activation_frequency_by_direction` | Up/Down frequency |
| `mean_activation_volume_by_direction` | magnitude check |
| `max_activation_volume_by_direction` | spike / outlier check |
| `activation_cluster_count` | event clustering |
| `mean_cluster_length` | duration structure |
| `max_cluster_length` | stress duration |
| `price_available_share` | price support |
| `mean_activation_price_by_direction` | price magnitude check |
| `missing_price_when_activated_count` | source consistency |
| `emergency_energy_rows_excluded` | exclusion audit |
| `product_filter_ambiguous_count` | source ambiguity |

## 8. Human-readable repo locations

Recommended locations:

| artifact type | location |
|---|---|
| source audit doc | `docs/market_rules/nl_ir_activation_data_source_audit_v1.md` |
| pipeline plan doc | `docs/optimisation/nl_ir_activation_tape_pipeline_plan_v1.md` |
| raw ENTSO-E pulls | `data/00_Raw/ENTSOE/` existing dataset subdirs |
| raw TenneT pulls, if adopted | `data/00_Raw/TenneT/IR_Activation/<dataset_key>/<retrieval_id>/` |
| raw manifests | next to raw response files under the governed retrieval folder |
| cleaned activation volume | `data/01_cleaned/Balancing/IR Energy/nl_ir_activation_volume_isp_long_v1.csv` |
| cleaned activation price | `data/01_cleaned/Balancing/IR Energy/nl_ir_activation_price_isp_long_v1.csv` |
| model-ready activation tape | `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Activation/nl_ir_activation_tape_isp_v1.csv` |
| diagnostics | `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Activation/diagnostics/` |
| future input contract | `docs/optimisation/nl_ir_activation_tape_input_contract_v1.md` |

Implementation note:

- Existing cleaning scripts currently define output subdirs under `02_Balancing_mFRR_IR/IR Energy`, while inspected local cleaned artifacts were under `data/01_cleaned/Balancing/IR Energy/`. Reconcile this path convention before implementation; do not move existing data during the planning step.

## 9. Relation to existing mFRR capacity work

Existing capacity-side layer:

- `17.1_BC` daily by direction average capacity price forecasting;
- `12.3_F` accepted-threshold proxies;
- capacity revenue unit repair to `EUR/MW/ISP` plus `contract_isp_count`;
- accepted/rejected reserve-obligation interface;
- DAM reserve-preservation smoke interface.

Key references:

- `docs/forecasting/mfrr_capacity_forecasting_thesis_summary_v1.md`
- `docs/forecasting/mfrr_capacity_metric_registry_v1.md`
- `docs/optimisation/mfrr_dam_integration_handoff_v1.md`
- `docs/optimisation/nl_ir_capacity_milp_export_contract_v2.md`

New future addition:

- historical activation request and activation price tape;
- applied after accepted capacity and after a DA/dispatch baseline exists;
- used for ex-post delivery and revenue evaluation;
- not a replacement for capacity forecasting.

## 10. Relation to future steel model

Build the activation tape now as market data infrastructure.

Do not hardcode hydrogen or steel physics into the tape.

Reusable for steel:

- timestamps;
- direction;
- activation flag;
- system activated volume;
- activation price;
- assignment rule metadata;
- revenue accounting fields.

Steel-specific later:

- whether the steel plant can deliver Up or Down regulation;
- EAF, DRP, BOF, HSM, and buffer redispatch;
- production shortfall;
- downstream blockage;
- recovery after activation;
- delivery quality.

## 11. Recommended implementation phases

### Phase 1 - Source audit

Goal:

- prove the exact volume and price fields before any model-ready tape is generated.

Files to create or modify:

- update `docs/market_rules/nl_ir_activation_data_source_audit_v1.md`;
- optionally add `docs/optimisation/nl_ir_activation_tape_input_contract_v1.md` once fields are verified.

Inputs:

- existing market-rule docs;
- `scripts/Data/00_data_imports/API_GETS.py`;
- `scripts/Data/01_cleaning/balancing_bid_document_a61_pipeline.py`;
- `scripts/Data/01_cleaning/activated_balancing_energy_nl_a16_pipeline.py`;
- optional source documentation/API metadata.

Outputs:

- source decision table with `usable`, `usable_with_caveat`, or `rejected` status per field.

Checks:

- dataset name, endpoint, product, direction, granularity, units, date range, and missing-value semantics documented.

Risks:

- `12_3_E` may not be realised system activation volume;
- `17.1_F` may not isolate incident reserve;
- price field may be settlement or imbalance price rather than activation remuneration.

Acceptance criteria:

- no `to_verify` remains for activation flag, volume, price, timestamp, direction, and unit fields selected for the one-month sample.

### Phase 2 - Small one-month API sample pull

Goal:

- retrieve a bounded sample without committing raw or bulky generated data.

Files to create or modify:

- raw response files under governed raw source folders;
- one manifest per source retrieval.

Inputs:

- source-audit-approved dataset keys;
- local API credentials via environment only.

Outputs:

- raw sample responses;
- retrieval manifest with hashes and row counts.

Checks:

- no API key stored;
- raw file hashes recorded;
- query window one month only;
- no overwrite of existing raw files.

Risks:

- source unavailable;
- API pagination or product filter mismatch;
- publication delay creates apparent missing data.

Acceptance criteria:

- each raw response has a manifest and can be traced to a source query.

### Phase 3 - Clean activation volume table

Goal:

- convert source volume/event records into a canonical ISP-long volume table.

Files to create or modify:

- future cleaning script or adapter;
- `data/01_cleaned/Balancing/IR Energy/nl_ir_activation_volume_isp_long_v1.csv`.

Inputs:

- one-month raw activation/volume sample.

Outputs:

- cleaned ISP-long volume table.

Checks:

- timestamps UTC and local;
- `Up` and `Down` explicit;
- no silent product mixing;
- emergency energy excluded or flagged;
- activation flag rule documented.

Risks:

- source rows are sparse event rows rather than full ISP support;
- volumes are not system activation requests;
- direction sign interpretation wrong.

Acceptance criteria:

- every row has source dataset, quality flag, direction, ISP interval, and volume semantics.

### Phase 4 - Clean activation price table

Goal:

- convert price records into a canonical ISP-long price table.

Files to create or modify:

- future cleaning script or adapter;
- `data/01_cleaned/Balancing/IR Energy/nl_ir_activation_price_isp_long_v1.csv`.

Inputs:

- one-month raw activation-price sample.

Outputs:

- cleaned ISP-long price table.

Checks:

- missing price is not converted to zero;
- negative prices preserved;
- price type labelled;
- source units traceable.

Risks:

- price source does not publish no-activation rows;
- price concept is not activation remuneration;
- product filter ambiguous.

Acceptance criteria:

- every activated ISP can be checked for price availability or an explicit missing-price reason.

### Phase 5 - Joined activation tape

Goal:

- join event/volume and price tables into one model-ready historical tape.

Files to create or modify:

- future tape builder;
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Activation/nl_ir_activation_tape_isp_v1.csv`.

Inputs:

- cleaned volume table;
- cleaned price table.

Outputs:

- model-ready activation tape.

Checks:

- one row per `delivery_start_utc x direction`;
- activation duration hours computed;
- source and quality flags preserved;
- split usability flags assigned without leakage.

Risks:

- price and volume support do not align;
- sparse rows make no-activation inference ambiguous;
- DST days create non-96 ISP days.

Acceptance criteria:

- sample tape can be interpreted without reading source XML or API responses.

### Phase 6 - Diagnostics

Goal:

- quantify source support, activation frequency, volume, price support, and ambiguity.

Files to create or modify:

- compact diagnostics under `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Activation/diagnostics/`;
- optional compact markdown summary in `docs/market_rules/`.

Inputs:

- sample activation tape.

Outputs:

- compact diagnostic CSV or JSON summaries;
- no figure flood.

Checks:

- diagnostics listed in section 7 produced;
- activated-without-price cases flagged.

Risks:

- diagnostics reveal source not usable for IR-specific tape.

Acceptance criteria:

- source support is clear enough to decide whether to scale beyond one month.

### Phase 7 - Model input contract

Goal:

- freeze the schema before any MILP consumption.

Files to create or modify:

- `docs/optimisation/nl_ir_activation_tape_input_contract_v1.md`.

Inputs:

- sample tape schema and diagnostics.

Outputs:

- input contract for later optimiser integration.

Checks:

- no activation forecast claim;
- assignment rules separated from observed data fields;
- revenue logic and sign caveats documented.

Risks:

- premature coupling to hydrogen or steel physics.

Acceptance criteria:

- future optimiser code can consume the tape without guessing source semantics.

### Phase 8 - Later steel integration

Goal:

- apply the asset-neutral tape to steel reserve-delivery checks after deterministic DA-only steel is stable.

Files to create or modify:

- future steel-specific activation adapter;
- future steel dispatch/recovery constraints;
- future run contracts.

Inputs:

- model-ready activation tape;
- accepted capacity records;
- steel process and buffer model.

Outputs:

- steel activation feasibility and ex-post activation revenue results.

Checks:

- no hidden infeasibility;
- delivered activation energy reported;
- production shortfall and recovery reported.

Risks:

- activation feasibility becomes process-specific and cannot be inferred from the tape alone.

Acceptance criteria:

- activation tape remains asset-neutral; steel physics lives in the steel model.

## 12. Open questions

Unresolved before implementation:

- Can Dutch incident reserve / `mFRRda` activation be isolated from candidate API sources?
- Is ENTSO-E `12_3_E` a realised activation-volume source, an energy-bid source, or another aggregated energy-data source?
- Which price is the correct activation remuneration price?
- Are prices published when no activation occurred?
- How are Up and Down activation prices signed for load-side revenue?
- Are system volumes sufficient, or is BSP/bid-level activation needed?
- How should emergency energy be excluded?
- What is the publication delay for each candidate source?
- What date range is available?
- Can the source support the same dates as the capacity and DAM artifacts?
- Do the existing cleaned local `IR Energy` outputs match current repo architecture, or should future scripts repair the output path convention first?
- Are local cleaned `IR Energy` artifacts complete, partial, or exploratory?

