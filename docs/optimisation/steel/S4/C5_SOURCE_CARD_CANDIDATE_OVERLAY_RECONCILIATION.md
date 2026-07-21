# C5 Source-Card Candidate Overlay Reconciliation

Status: development-only diagnostic report.

Thesis usability: false.

This report summarizes `S4.4c5p_i_source_card_candidate_overlay_reconciliation`.
The stage applies repaired source-card candidate values to current annualized
C5 activity outputs as post-processing diagnostics only. It does not migrate
values into executable inputs, add residual loads, change model equations,
create CO2 costs, or activate economics/DA behaviour.

## Electricity overlay

- C0 current gross modelled demand: 1.742724 TWh/y.
- C0 expanded generic overlay gross demand: 2.268025 TWh/y.
- C0 expanded pre-floor exposure after internal offsets: 0.200360 TWh/y.
- C1 current gross modelled demand: 3.033750 TWh/y.
- C1 expanded generic overlay gross demand: 3.441266 TWh/y.
- C1 expanded pre-floor exposure after internal offsets: 2.505989 TWh/y.

The expanded electricity overlay reduces the C0 over-offset but does not solve
the residual electricity boundary. The 3 TWh/y and 360 MW context anchors remain
validation/context only.

## NG and fuel overlay

- C1 current modelled NG: 31.783675 PJ/y.
- C1 expanded HSM NG-equivalent fuel stress: 38.694953 PJ/y.

The HSM fuel overlay is a fuel-scale stress diagnostic. It is not an active NG
load because the HSM carrier split between WAG and NG is not source-frozen.
BOF volume-fuel candidates are not converted to PJ without verified LHV and
normalization.

## CO2 overlay

CO2 remains component-diagnostic only. Aggregate process-counter mode and
fuel-explicit WAG/NG mode are separated. Fuel-explicit WAG/NG CO2 is not
computed because official factors are not source-carded as active factors.
ETS readiness remains false.

## Migration recommendations

Source review required before migration:

- `HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC_KHALID`
- `BOF_ELECTRICITY_MWH_PER_T_LS_BIEDA`
- `BOF_NG_M3_PER_T_LS_BIEDA`
- `KGF_ELECTRICITY_PURCHASED_GJ_PER_T_COKE`

Sensitivity-only:

- `HSM_REHEAT_FUEL_GJ_PER_T_HRC_KHALID`
- `KGF_COG_FOR_HEATING_GJ_PER_T_COKE`
- `BOILER_EFFICIENCY_BASE`

## Gate decision

- Migration proposal to executable development inputs: NO-GO until source
  locators, duplicate-boundary checks and sensitivity decisions are complete.
- Residual electricity/NG implementation: NO-GO.
- Consolidated CO2 implementation: NO-GO until WAG carbon policy and official
  factors are frozen.
- Economics and DA readiness: NO-GO.
