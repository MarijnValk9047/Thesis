# NL Incident Reserve Capacity MILP Export Contract V2

## Purpose

This note freezes the repaired daily MILP export contract for Dutch incident reserve / `mFRRda` capacity:

- export path: `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/milp_exports/nl_ir_capacity_milp_input_daily_direction_scenarios_v2.csv`
- builder: `scripts/Data/02_Forecasting/02_mFRR_IR_NL/export_mfrr_capacity_milp_input_daily_v2.py`

Use `v2` for downstream MILP work. Keep `v1` frozen for lineage only.

## Why V2 Supersedes V1

`v1` under-specified the price unit by exporting threshold prices as `EUR_per_MW_per_period` and omitted the contract-length multiplier needed for capacity remuneration.

`v2` repairs that contract by:

- keeping the ENTSO-E-native capacity price unit as `EUR/MW/ISP`;
- exporting `acceptance_threshold_price_eur_per_mw_isp`;
- exporting explicit delivery interval metadata in both local time and UTC;
- computing `contract_isp_count` from `delivery_start` and `delivery_end` instead of hardcoding `96`;
- freezing the timing assumption explicitly as `D-1 09:00 Europe/Amsterdam`.

## Timing Rule

For this incident-reserve capacity export, decision timing is:

- capacity auction timing: `D-1 09:00 Europe/Amsterdam`
- `forecast_origin_local`: aligned to `D-1 09:00 Europe/Amsterdam`
- `known_at_cutoff_utc`: UTC equivalent of that local cutoff
- `known_at_assumption`: `assumed_nl_incident_reserve_capacity_auction_d_minus_1_09am_europe_amsterdam`

This is a metadata-alignment repair only. Forecast values and threshold-scenario values are preserved from the frozen upstream artifacts.

## Capacity Unit And Revenue Rule

`v2` keeps threshold prices in the ENTSO-E-native unit:

- `capacity_price_unit = EUR_per_MW_per_ISP`

Revenue must therefore scale by the number of ISPs covered by the accepted contract:

`capacity_revenue = accepted * bid_price_eur_per_mw_isp * offered_capacity_mw * contract_isp_count`

Hard validation example:

- `2.22 EUR/MW/ISP * 35 MW * 96 ISP = 7459.20 EUR`
- `2.22 * 35 = 77.70 EUR` is only one-ISP remuneration and is incomplete for a full-day product.

## Current Scope

`v2` is still the source-backed daily product only:

- `capacity_product_structure = observed_daily`
- no 4-hour counterfactual block is included in this contract
- accepted capacity still implies a per-ISP energy-bid obligation, but that obligation is only flagged in the export
- activation, balancing-energy settlement, sanctions, and MARI remain out of scope for this export contract

Relevant scope flags in `v2`:

- `energy_bid_obligation_if_accepted = True`
- `activation_modelling_in_scope = False`
- `mari_modelling_in_scope = False`

## Downstream MILP Consumer

The first downstream hydrogen mFRR-capacity smoke path now consumes `v2` instead of `v1`.

Implementation interpretation:

- threshold and candidate capacity bid prices are handled as `EUR/MW/ISP`
- expected capacity revenue coefficients include `contract_isp_count`
- capacity volume is enforced as integer MW inside the MILP
- bid selection implies at least `1 MW` and otherwise `0 MW`
- any previous `v1` interpretation that treated the exported price as full-day `EUR/MW/day` would undercount revenue magnitude
- the current smoke path remains capacity-only and does not prove activation feasibility
- the mandatory energy-bid obligation remains a metadata/reporting flag, not an optimised energy-bid layer
- source-backed 4-hour products remain out of scope until separately evidenced

This aligns the pilot formulation with the incident-reserve `1 MW` minimum size and `1 MW` step-size rule. Positive capacity or production changes in optional mFRR runs remain diagnostic signals only, not final economic conclusions.
