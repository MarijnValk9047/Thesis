# S3.0e-b Emissions Boundary And Non-Double-Counting Policy

## Purpose

This policy hardens the static S3 site-accounting layer created in S3.0e-a. The goal is to make the partial emissions proxy explicit enough for C0/C1 comparison without allowing it to become a complete plant emissions, ETS, or cost result.

The current ledger uses governed S3 fixed profiles as accounting snapshots. It does not rebuild S2 and does not regenerate S3 profiles from S2 while the S2 layout migration remains under user review.

## Current Selected Policy

Selected policy ID: `current_partial_direct_proxy_policy`.

The current policy counts:

- WAG oxidation/use emissions for BFG, COG, and BOFG/LDG at represented use or oxidation sinks;
- the C1 DRP direct CO2 proxy from the selected Tier B NG-DRP assumption.

The current policy does not count:

- WAG generation as a separate emissions event;
- separate DRP natural-gas combustion CO2 while the DRP direct CO2 proxy is active;
- electricity scope-2 emissions;
- downstream/reheating emissions;
- retained BF/BOF non-WAG process emissions;
- coking non-WAG process emissions;
- residual site direct emissions;
- gross ETS cost.

The output is therefore `partial_direct_emissions_proxy`, not a complete direct-emissions ledger.

## WAG Point-Of-Oxidation Logic

BFG, COG, and BOFG/LDG carbon is counted at point of oxidation/use: process use, boiler or steam use, power-interface use, or flare/spill if represented.

WAG generation alone is not counted as a separate emissions event. This avoids counting the same carbon once when gas is generated and again when it is burned or flared.

WAG-to-power offset remains an internal direct-emissions accounting choice. It is not external zero-emission electricity generation, export revenue, settlement, or an avoided-cost result.

## DRP Direct CO2 Versus Natural-Gas Combustion

The selected Athanasiadis NG-DRP assumptions include both:

- natural-gas consumption in `m3_NG/t_pellets`;
- direct CO2 proxy in `t_CO2/t_pellets`.

For the current S3 static ledger:

- DRP natural-gas volume is retained for physical fuel accounting and future fuel-cost accounting;
- `ng_drp_direct_co2_factor` is used as the C1 DRP direct CO2 proxy;
- separate DRP natural-gas combustion CO2 is not added;
- `drp_direct_co2_proxy_counted=true` for C1 result rows;
- `drp_ng_combustion_co2_counted=false`.

This is a non-double-counting convention. A later explicit natural-gas combustion policy may replace the DRP direct proxy, but the two policies must not be active simultaneously.

## Excluded Components

Electricity scope-2 emissions remain blocked because no electricity emissions factor is selected. Proxy electricity import exposure may be reported in MWh only.

Downstream emissions remain blocked because downstream/end-processing profiles currently contain accounting drivers, not emissions coefficients. Missing downstream emissions must not be interpreted as zero.

Retained BF/BOF non-WAG process emissions, coking non-WAG process emissions, oxygen/ASU emissions, and residual site emissions remain unresolved material components for a complete direct-emissions ledger.

## Readiness

Current readiness remains:

- `complete_direct_emissions_ready=false`;
- `ets_ready=false`;
- `gross ETS cost blocked`;
- `cost_da_ready=false`;
- `monetary_values_ready=false`.

Gross ETS cost is blocked because the ledger is partial, no CO2 price is selected, and free allocation remains out of scope.

## C0/C1 Interpretation

C0 partial direct emissions include WAG oxidation only.

C1 partial direct emissions include WAG oxidation plus the DRP direct CO2 proxy. This supports static scenario comparison under the current snapshot boundary, but not complete plant-emissions ranking or ETS-cost claims.

The C1 comparison remains useful for directionality: higher DRP/EAF share increases DRP gas and DRP direct-proxy CO2 while reducing retained BF/BOF/coking WAG. The result is still not plant truth because downstream, residual process, scope-2, and complete direct-emissions components are unresolved.

## Remaining Blockers

Before complete direct emissions, ETS, or monetary CO2 accounting can be reported, the model still needs:

- retained BF/BOF non-WAG process emissions policy or explicit exclusion;
- coking non-WAG process emissions policy or explicit exclusion;
- downstream/reheating emissions coefficients or explicit exclusion;
- oxygen/ASU emissions boundary;
- residual site emissions boundary review;
- explicit choice between DRP direct-proxy policy and explicit NG combustion decomposition;
- electricity scope-2 factor if indirect reporting is reopened;
- complete direct-emissions readiness review;
- CO2/ETS price input and ETS policy, including free-allocation treatment if later in scope.

No DA prices, WAG price response, bidding, settlement, stochastic scenarios, CVaR, mFRR, product revenue, tariff logic, route optimisation, or market logic is introduced by this policy.
