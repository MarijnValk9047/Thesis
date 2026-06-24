# S3.2 Static Material-Energy-Carbon Economics and Endogenous Route Diagnostic

Date: 2026-06-19

## Scope

S3.2 attaches a static material, energy, direct-carbon, Scope 2, and operating-cost layer to the S2.13 downstream-aware physical MILP. It keeps final hot-rolled-product output fixed and does not introduce DA prices, bidding, settlement, stochastic scenarios, CVaR, mFRR, product revenue, electricity export, ETS free allocation, CBAM, or grade-campaign scheduling.

## Main Additions

- S2.13a slab-yard central capacity: `25000 t`, with preserved initial inventory `1630.13544 t`.
- Static electricity price: `77.29 EUR/MWh`.
- Static natural-gas price: `33.50 EUR/MWh_th` = `9.3055555556 EUR/GJ`.
- Static gross direct CO2 price: `65 EUR/tCO2`.
- Operational Scope 2 factor: `0.20 tCO2/MWh` on grid import only.
- Full-chain grid factor sensitivity: `0.268 tCO2e/MWh`, reported separately.
- Bounded residual WAG-to-power utilisation: low `0.25`, central `0.50`, high `0.75` of residual WAG after mandatory heat uses.
- Material-cost coverage for BF-BOF and DRP-EAF routes using governed development-only recipe and price rows.

## Carbon Boundary

WAG emissions are counted once at point of oxidation/use. Natural-gas combustion is counted for DRP and any external NG used by reheating or steam. The DRP proxy is decomposed into explicit NG combustion plus a non-negative residual process component, and the original total proxy is not added again. BF-BOF non-WAG direct emissions are represented by a development aggregate residual proxy after subtracting WAG oxidation. Scope 2 is reported separately and excluded from gross ETS cost.

## Route Choice

The fixed C1 0.61/0.39 route-share case remains the principal benchmark. S3.2 adds `c1_endogenous_route_static_economics`, bounded to the already demonstrated feasible BF-BOF share interval `0.5471962` to `0.67988981`. The route share is an output of the static cost objective, not a WAG-share target.

## Results Summary

All mandatory 24-hour and 168-hour central cases passed. The endogenous route diagnostic selected the upper feasible BF-BOF share bound under the current development-only material and carbon price assumptions.

Key 24-hour central results:

| Case | BF-BOF share | WAG share vs C0 | Direct CO2 t | Scope 2 t | Cost EUR | EUR/t |
|---|---:|---:|---:|---:|---:|---:|
| C0 | 1.000000 | 1.000000 | 14671.218960 | 11.360007 | 3409579.995169 | 418.318615 |
| C1 fixed | 0.610000 | 0.610000 | 11210.299972 | 566.007166 | 3830418.962371 | 469.951008 |
| C1 endogenous | 0.679889810 | 0.679889810 | 11830.512717 | 459.133137 | 3752112.528944 | 460.343655 |

Key 168-hour central results:

| Case | BF-BOF share | Final product t | Cost EUR | EUR/t |
|---|---:|---:|---:|---:|
| C0 | 1.000000 | 57054.740400 | 23840719.518765 | 417.856945 |
| C1 fixed | 0.610000 | 57054.740400 | 26812932.736595 | 469.946047 |
| C1 endogenous | 0.679889810 | 57054.740400 | 26264787.702610 | 460.340126 |

## Limitations

The S3.2 economic baseline is development-only. Material prices and several route recipes are Tier-D scenario assumptions. The BF-BOF residual direct-carbon boundary is a development proxy and not a public Tata plant emissions validation. The WAG-to-power interface is a bounded practical assumption, not Vattenfall dispatch. The model remains a deterministic static baseline and not a DA market model.

## Next Step

Use S3.2 as the static baseline for S4 deterministic hourly DA price-taking only after preserving fixed production fulfilment, route-cost coverage, WAG balance closure, and the direct/Scope 2 separation.
