# S3.1 Downstream-Aware Energy, Emissions, And Static Economic Integration

Date: 2026-06-19

## Purpose

`S3.1-a` attaches deterministic energy, WAG, direct-emissions, and static-economic accounting hooks to the physical `S2.13` downstream scheduling MILP. `S3.1-b` reconciles the WAG activity basis and re-freezes the corrected integrated ledger. The model is built by wrapping the re-frozen `S2` liquid-steel core and the `S2.13` downstream extension; it does not optimise over exported S3 fixed profiles.

The layer remains deterministic and fixed-output. It does not implement DA prices, bidding, stochastic scenarios, CVaR, mFRR, product revenue, electricity export revenue, scope-2 electricity emissions, ETS free allocation, full Vattenfall dispatch, or sequence-dependent HSM grade campaigns.

## Architecture

New modules:

- `scripts/Data/04_Steel_Test_Case/steel/site_energy_economic_inputs.py`
- `scripts/Data/04_Steel_Test_Case/steel/site_energy_economic_builder.py`
- `scripts/Data/04_Steel_Test_Case/steel/site_energy_economic_runner.py`

The builder sequence is:

1. Build the re-frozen liquid-steel S2 model.
2. Apply the `S2.13` downstream physical scheduling extension.
3. Attach S3.1 energy, WAG, direct-emissions, and static-cost expressions.
4. Preserve the hard final-product target, terminal neutrality, route shares, and downstream sequencing constraints.

The current objective mode is `energy_emissions_diagnostic` because governed static price inputs are missing. Static-cost solve mode is blocked until grid-electricity, natural-gas, CO2, flare, startup, and tariff inputs are selected.

## Selected Inputs

Source-backed or derived inputs reused:

- WAG generation coefficients and carrier CO2 factors from the governed S3 WAG development inputs. After `S3.1-b`, BFG uses BF hot metal, COG uses the BF hot-metal to coke to dry-coal chain, and BOFG uses BOF liquid-steel activity.
- C1 DRP/EAF electricity, natural-gas, and direct CO2 coefficients from the governed Tier-B route-energy input table.
- WAG-to-power efficiency derived from the current governed S3 WAG efficiency input.

Tier-D development inputs selected for sensitivity:

- secondary metallurgy electricity;
- continuous-casting electricity;
- slab-handling electricity;
- DSP electricity;
- reheating useful heat;
- reheating auxiliary electricity;
- HSM electricity;
- ASU electricity and BOF oxygen driver;
- residual auxiliary electricity;
- natural-gas energy content;
- natural-gas combustion factor for non-DRP fuel only.

All Tier-D values are marked development-only, sensitivity-required, not Tata-exact, and not validation-claim eligible.

## Energy Coupling

Energy demand follows scheduled hourly throughput:

- secondary metallurgy, casting, slab handling, DSP, HSM, ASU, residual auxiliary, DRP, and EAF create electricity demand;
- cold-slab reheating creates useful-heat and auxiliary-electricity demand;
- hot charging avoids the selected reheating heat physically by bypassing cold-slab reheating;
- natural gas supplies residual reheating or steam demand after compatible WAG allocation;
- grid import supplies residual electricity demand.

The model reports gross electricity, WAG power output, potential WAG power output, grid import, DRP natural gas, natural-gas import, reheating heat, and asset-level electricity. In the base policy, WAG-to-power is a potential-only no-export interface, not an unconditional cost credit.

## WAG Policy

The deterministic allocation hierarchy is process-first:

1. mandatory carrier-compatible process use;
2. required steam or boiler demand;
3. compatible reheating demand;
4. WAG-to-power interface;
5. flare or spill residual.

Carrier balances are enforced hourly for BFG, COG, and BOFG/LD gas. No WAG disappears. No export or WAG revenue is created.

## Direct Emissions

The current policy remains a partial direct-emissions proxy:

- WAG emissions are counted once at point of oxidation/use, including flare;
- DRP direct CO2 proxy is counted for C1;
- separate DRP natural-gas combustion CO2 is not counted while the DRP direct proxy is active;
- reheating natural-gas emissions are counted when residual NG reheating fuel is used;
- scope-2 electricity emissions remain excluded;
- BF/BOF/coking residual non-WAG direct emissions remain incomplete.

Complete direct-emissions readiness is false. ETS or gross CO2 cost readiness is false because the direct ledger is incomplete and no governed CO2 price is selected.

## Static Economics

No static monetary result is produced in S3.1-a. The price input register records missing selected inputs for:

- grid electricity price;
- natural-gas price;
- gross CO2 price;
- flare or spill penalty;
- startup cost proxy;
- network or tariff proxy.

Monetary output columns remain blank and `monetary_values_ready=false`. Missing prices are blockers, not zeros.

## Smoke Results

All 24 h mandatory smoke cases were run with `appsi_highs`.

| case | termination | objective | variables | binaries | constraints | final product t | grid MWh | NG GJ | direct CO2 t |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C0 integrated central | optimal | 1859.484925 | 1297 | 216 | 1558 | 8150.6772 | 1820.861286 | 0.000000 | 10480.316497 |
| C1 central integrated | optimal | 5607.639711 | 1297 | 216 | 1558 | 8150.6772 | 4033.397766 | 31010.584733 | 8653.849470 |
| recoverable HSM outage | optimal | 5613.557710 | 1297 | 216 | 1558 | 8150.6772 | 4038.673065 | 31010.584733 | 8653.849470 |
| all-hot reference | optimal | 1859.484925 | 1297 | 216 | 1558 | 8150.6772 | 1820.861286 | 0.000000 | 10480.316497 |
| cold-heavy diagnostic | optimal | 1862.154612 | 1297 | 216 | 1559 | 8150.6772 | 1823.578179 | 0.000000 | 10480.316497 |
| hard-target stress | infeasible |  | 1297 | 216 | 1558 |  |  |  |  |

MIP gap is reported as `not_reported_by_solver` by the solver interface. Maximum material, WAG, electricity, and reheating residuals in feasible S3.1 smoke results are zero within tolerance. Terminal cold-slab, hot-slab, and reheated-queue deviations are zero.

## Hand Reconciliation

For the C1 central 24 h total:

- final product equals DSP output plus HSM output: `1630.13544 + 6520.54176 = 8150.6772 t`;
- route input equals final-product target under unit yields: `4971.913092 t BOF + 3178.764108 t EAF = 8150.6772 t`;
- WAG generation equals allocation: `35008.821447 GJ = 11119.743293 process + 566.854914 steam + 0 reheating + 23322.223240 flare`;
- electricity balance closes: gross modelled electricity equals grid import because base WAG-to-power dispatch is disabled;
- reheating balance closes at zero in the base C1 schedule because all slab is hot charged;
- direct CO2 equals WAG oxidation plus DRP direct proxy: `6392.993063 + 2260.856407 = 8653.849470 t`.

For the recoverable outage, `527.529941 t` of slab is reheated and reheating heat is `633.035929 GJ`, matching `1.20 GJ/t` within rounding.

## Sensitivity Results

Limited coefficient sensitivities were run:

- low energy coefficients: optimal, grid electricity `941.403217 MWh`, potential WAG power `3409.122796 MWh`;
- high energy coefficients: optimal, grid electricity `3252.120203 MWh`, potential WAG power `4481.775140 MWh`.

These are one-at-a-time grouped development diagnostics, not a full factorial sensitivity study.

## Limitations

- WAG-to-power remains potential-only in the base, so actual WAG economic value is conditional.
- Static prices are missing; no total static operating cost is reported.
- Complete direct emissions are not ready because retained BF/BOF/coking residual emissions are incomplete.
- Scope-2 electricity emissions are excluded.
- No plant-validation claim is allowed from Tier-D downstream coefficients.
- The model is Tata-inspired and public-evidence governed, not a confidential Tata digital twin.

## S4 Implication

S4 deterministic DA price-taking must wait until static-price input selection and a true S3 cost baseline are completed. The reconciled S3.1 ledger is suitable for gross-load and import-sensitivity preparation, but actual WAG economic-value claims, static cost claims, ETS claims, and complete plant-emissions claims remain conditional on missing governed inputs and policy hardening.
