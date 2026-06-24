# S3.0e Site Static Energy Emissions Economic Accounting

## Purpose

This layer creates a static accounting ledger for the represented S3 steel-site boundary. It is a bridge between component diagnostics and later cost or DA optimisation, not a plant-truth model.

It exists to make C0 and C1 comparable on the current governed fixed-profile snapshots while keeping four claims separate:

- component diagnostics;
- proxy site-wide diagnostics;
- full plant truth;
- DA/cost optimisation.

No S2 rebuild is used. The current C0 and C1 fixed profiles are treated as accounting snapshots because the worktree hygiene audit still records unresolved frozen-S2 provenance risk.

S3.0e-b adds the explicit emissions non-double-counting policy documented in `STEEL_S3_0E_EMISSIONS_BOUNDARY_AND_NON_DOUBLE_COUNTING_POLICY.md`. The selected policy is `current_partial_direct_proxy_policy`.

## Included

The static ledger includes:

- WAG generation by carrier: BFG, COG, and BOFG/LDG;
- WAG power-offset potential after the existing WAG allocation mechanics;
- DRP natural-gas demand for C1;
- DRP and EAF electricity demand for C1;
- downstream/end-processing throughput drivers as accounting drivers;
- Tier D proxy gross electricity-boundary cases;
- WAG oxidation CO2 by carrier;
- DRP direct CO2 proxy for C1;
- formula hooks for future electricity, natural-gas, WAG avoided-import, CO2/ETS, and tariff accounting.

## Excluded

The layer does not implement:

- DA prices;
- WAG price response;
- route optimisation;
- bidding, clearing, settlement, stochastic scenarios, CVaR, or mFRR;
- product revenue;
- tariff logic;
- gross ETS cost;
- full HSM, slab-yard, reheating, or downstream scheduling;
- complete direct-emissions accounting;
- actual plant import or Vattenfall dispatch.

## Electricity Boundary Cases

The proxy electricity-boundary sensitivity register uses Tier D user-selected scenario policy:

| boundary case | annual MWh | average MW | 24h MWh |
|---|---:|---:|---:|
| low proxy site electricity boundary | 2,250,000 | 256.849315 | 6,164.383562 |
| central proxy site electricity boundary | 3,000,000 | 342.465753 | 8,219.178082 |
| high proxy site electricity boundary | 3,750,000 | 428.082192 | 10,273.972603 |

These are proxy exposure cases only. They are not Tata-exact, not validation-claim eligible, and not cost/DA ready.

## Physical Accounting Results

Central physical results from `s3_site_static_accounting_result_register.csv`:

| scenario | total WAG GJ/24h | DRP NG m3/24h | DRP electricity MWh/24h | EAF electricity MWh/24h | component electricity MWh/24h |
|---|---:|---:|---:|---:|---:|
| C0 reference | 57,391.510570 | 0.000000 | 0.000000 | 0.000000 | n/a |
| C1 high DRP/EAF | 31,565.330813 | 1,017,385.383073 | 521.736094 | 1,930.423547 | 2,452.159641 |
| C1 central | 35,008.821447 | 881,733.998663 | 452.171281 | 1,673.033741 | 2,125.205023 |
| C1 low DRP/EAF | 39,026.227187 | 723,474.050185 | 371.012334 | 1,372.745634 | 1,743.757967 |

C0 has more WAG than all C1 route scenarios because C1 retains only part of the BF/BOF/coking WAG drivers. C1 DRP gas and electricity rise with the DRP/EAF share.

## Proxy Import Exposure

The ledger caps WAG offset by the proxy gross electricity boundary and reports residual proxy import exposure:

| scenario | WAG offset MWh/24h | residual low boundary MWh/24h | residual central boundary MWh/24h | residual high boundary MWh/24h |
|---|---:|---:|---:|---:|
| C0 reference | 3,945.448968 | 2,218.934594 | 4,273.729114 | 6,328.523635 |
| C1 high DRP/EAF | 3,257.366777 | 2,907.016785 | 4,961.811305 | 7,016.605826 |
| C1 central | 3,612.715880 | 2,551.667682 | 4,606.462202 | 6,661.256723 |
| C1 low DRP/EAF | 4,027.289833 | 2,137.093728 | 4,191.888249 | 6,246.682769 |

This residual is a proxy exposure measure only. It is not actual plant import, settlement volume, avoided cost, WAG revenue, or a DA market result.

## Emissions Proxy Results

Partial direct-emissions proxy results:

| scenario | WAG CO2 t/24h | DRP direct CO2 proxy t/24h | partial direct CO2 proxy t/24h |
|---|---:|---:|---:|
| C0 reference | 10,480.316497 | 0.000000 | 10,480.316497 |
| C1 high DRP/EAF | 5,764.174073 | 2,608.680469 | 8,372.854542 |
| C1 central | 6,392.993063 | 2,260.856407 | 8,653.849470 |
| C1 low DRP/EAF | 7,126.615218 | 1,855.061667 | 8,981.676885 |

Natural-gas combustion CO2 is not added on top of the DRP direct CO2 proxy because a non-double-counting policy for that combination is not selected. Electricity scope-2 emissions are also not computed because no explicit factor is selected.

Under `current_partial_direct_proxy_policy`, WAG emissions are counted at represented point of oxidation/use and not at WAG generation. C1 DRP direct CO2 is counted as a proxy, while separate DRP natural-gas combustion CO2 remains blank because it is policy-blocked while the direct proxy is active, not because the physical value is assumed zero. Electricity scope-2 and downstream emissions remain blank because selected factors or coefficients are missing.

## Economic Formula Readiness

Formula hooks exist for:

- electricity import cost: `residual_proxy_grid_import_mwh_24h * electricity_price`;
- natural-gas cost: `drp_natural_gas_m3_24h * natural_gas_price_or_converted_energy_price`;
- WAG avoided import value: `wag_offset_mwh_24h * selected_static_valuation_price`;
- CO2/ETS proxy: `eligible_co2_t * selected_co2_price`;
- tariff/network costs: blocked until a tariff policy is selected.

All monetary result columns remain blank and `monetary_values_ready=false` because no selected static price inputs, tariff policy, complete emissions boundary, or cost-ready site boundary exists.

## Downstream Representation

Downstream/end-processing is represented only through accounting drivers in the fixed profiles:

- secondary metallurgy;
- continuous casting;
- slab handling/transfer;
- reheating or hot-charge throughput;
- hot-strip-mill throughput;
- finished-product boundary proxy;
- ASU/oxygen auxiliary driver;
- residual downstream auxiliary boundary driver.

These drivers preserve throughput continuity. They do not schedule downstream processes, create slab storage flexibility, create HSM logic, or supply hidden zero energy coefficients.

## Readiness Flags

Current readiness remains:

- `plant_level_claim_allowed=false`;
- `complete_site_energy_ready=false`;
- `complete_direct_emissions_ready=false`;
- `cost_result_allowed=false`;
- `da_market_result_allowed=false`;
- `cost_da_ready=false`;
- `monetary_values_ready=false`.

## Remaining Blockers

Before monetary cost, ETS, or DA integration, the model still needs:

- downstream electricity coefficients;
- ASU/oxygen electricity coefficient;
- heat/steam/reheating coefficient;
- residual boundary review;
- natural-gas, electricity, and CO2 price inputs;
- complete direct-emissions ledger policy;
- non-double-counting policy for DRP direct CO2 versus natural-gas combustion CO2;
- DA/market integration after the static boundary is reviewed.

The non-double-counting convention is now recorded, but the complete direct-emissions ledger remains blocked until retained BF/BOF non-WAG process emissions, coking non-WAG process emissions, downstream/reheating emissions, oxygen/ASU emissions, residual site emissions, and any later scope-2 treatment are reviewed.
