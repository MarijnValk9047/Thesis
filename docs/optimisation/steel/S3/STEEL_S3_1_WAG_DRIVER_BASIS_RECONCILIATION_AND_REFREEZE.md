# S3.1-b WAG Driver-Basis Reconciliation and Re-Freeze

Date: 2026-06-19

## Purpose

This record reconciles the S3.1-a integrated WAG generation totals against the earlier governed S3 static WAG accounting snapshots. The task does not alter S2 or S2.13 physical equations. It corrects only the S3.1 activity-to-WAG accounting interface.

## Discrepancy

The S3.1-a integrated ledger reported:

| configuration | BFG GJ/24h | COG GJ/24h | BOFG GJ/24h | total WAG GJ/24h |
|---|---:|---:|---:|---:|
| C0 before fix | 43687.629792 | 20731.431460 | 5856.261568 | 70275.322820 |
| C1 central before fix | 26649.454173 | 12646.173190 | 3572.319557 | 42867.946920 |

Earlier governed static accounting snapshots reported:

| configuration | BFG GJ/24h | COG GJ/24h | BOFG GJ/24h | total WAG GJ/24h |
|---|---:|---:|---:|---:|
| C0 static snapshot | 34950.103834 | 16585.145168 | 5856.261568 | 57391.510570 |
| C1 central static snapshot | 21319.563338 | 10116.938552 | 3572.319557 | 35008.821447 |

The exact carrier pattern was:

- BFG before-fix/static ratio: 1.25.
- COG before-fix/static ratio: 1.25.
- BOFG before-fix/static ratio: 1.00.
- Total-WAG ratio: about 1.224489 because BOFG was already correctly based.

## Root Cause

S3.1-a used `bof_liquid_steel_output` as the integrated driver for BFG and COG generation. That was compatible with BOFG but not with the selected BFG and COG coefficient bases:

- BFG coefficient basis is `Nm3_BFG/t_hot_metal`, so the driver must be BF hot-metal production.
- COG coefficient basis is `m3_COG/t_dry_coal`, so the driver must follow the governed coking chain from BF hot metal to coke to dry coal.
- BOFG coefficient basis is `Nm3_BOFG/t_liquid_steel`, so the existing BOF liquid-steel driver was already correct.

The 1.25 factor is the inverse of the governed C0 fixed-profile hot-metal to BOF liquid-steel activity ratio:

```text
bf_hot_metal / bof_liquid_steel = 6520.541760 / 8150.677200 = 0.8
bof_liquid_steel / bf_hot_metal = 1.25
```

## Correction

The S3.1 integrated layer now uses:

| carrier | corrected driver | coefficient basis |
|---|---|---|
| BFG | `bf_hot_metal_driver_t` | `Nm3_BFG/t_hot_metal` |
| COG | `cog_dry_coal_driver_t` | `m3_COG/t_dry_coal` |
| BOFG | `bof_liquid_steel_output` | `Nm3_BOFG/t_liquid_steel` |

S2.13 does not expose an independent hot-metal decision variable. For S3.1 accounting, `bf_hot_metal_driver_t` is derived from the governed C0 fixed WAG profile hot-metal to BOF liquid-steel ratio. `cog_dry_coal_driver_t` is then derived through the governed coke-rate and dry-coal conversion inputs. This is an accounting-interface derivation, not a physical S2/S2.13 model change.

An activity-basis validation guard now rejects incompatible WAG driver and coefficient pairs, including liquid steel with hot-metal coefficients and final product with dry-coal coefficients.

## Corrected Results

| configuration | BFG GJ/24h | COG GJ/24h | BOFG GJ/24h | total WAG GJ/24h |
|---|---:|---:|---:|---:|
| C0 corrected | 34950.103834 | 16585.145168 | 5856.261568 | 57391.510570 |
| C1 central corrected | 21319.563338 | 10116.938552 | 3572.319557 | 35008.821447 |

The corrected integrated totals reconcile to the static S3 WAG accounting snapshots carrier by carrier.

## Allocation and Flare Interpretation

Corrected base smokes:

| case | process use GJ | steam/boiler use GJ | reheating use GJ | flare/spill GJ |
|---|---:|---:|---:|---:|
| C0 integrated | 18229.087366 | 929.270351 | 0.000000 | 38233.152852 |
| C1 central integrated | 11119.743293 | 566.854914 | 0.000000 | 23322.223240 |
| C1 recoverable outage | 11119.743293 | 566.854914 | 633.035929 | 22689.187311 |
| C0 cold-heavy | 18229.087366 | 929.270351 | 326.027088 | 37907.125764 |

The remaining flare/spill is therefore not explained only by the driver defect. It is also caused by the current potential-only WAG-to-power policy and limited represented heat and reheating sinks. No unsupported sink or WAG revenue term was added to eliminate flare.

## Emissions Effect

Corrected WAG point-of-oxidation emissions:

| configuration | before-fix WAG CO2 t/24h | corrected WAG CO2 t/24h |
|---|---:|---:|
| C0 | 12819.441472 | 10480.316497 |
| C1 central | 7819.859298 | 6392.993063 |

C1 DRP direct CO2 proxy remains unchanged. Scope-2 electricity emissions remain excluded. Complete direct-emissions readiness remains false.

## Objective Interpretation

Every S3.1 smoke row now records:

- `objective_type=energy_emissions_diagnostic`;
- `static_cost_result=false`;
- `monetary_values_ready=false`;
- `wag_driver_basis_status=reconciled_s3_1_b`.

The numerical objective is not a EUR result and must not be interpreted as total cost.

## Re-Freeze Decision

Decision: S3.1 is re-frozen after WAG driver-basis reconciliation.

Basis:

- BFG, COG and BOFG drivers are now consistent with selected coefficient bases.
- Carrier-by-carrier corrected totals reconcile to governed static WAG snapshots.
- Energy and emissions balances close in mandatory integrated smokes.
- S2/S2.13 physical equations were not changed.
- Monetary readiness remains false.
- S4 readiness remains conditional on later static-price input selection and a true S3 cost baseline.

## Remaining Blockers

- Static grid-electricity price input.
- Static natural-gas price input.
- Static gross CO2 price input.
- WAG-to-power interface remains potential-only and not a firm economic credit.
- Complete direct-emissions ledger remains false.
- S4 DA price-taking must wait until the static-price baseline is selected and reconciled.

## Git Safety

No git add, commit, push, reset, restore, checkout, clean, rm, delete, revert, move, rename or archive operation was performed.
