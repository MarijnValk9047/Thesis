# C5 WAG/NG Controller Diagnostic Allocator

## Purpose

C5p_q is the first diagnostic implementation of the C5p_p WAG/NG design. It does **not** introduce a new physical allocator. Instead, it compiles accepted existing controller outputs into one carrier-specific ledger and fails closed where the current model lacks a reconciled controller demand or mix.

C5p_o remains authoritative for the WAG contract. COG, BFG and BOFG remain separate physical carriers where existing rows preserve them. `mixed_wag` remains structural-only, `aggregate_wag` remains reporting-only, and C5p_k is excluded from physical allocation.

## What is actually allocated here

The ledger reports only existing quantitative controller outputs for HSM/WBW, sinter, the governed steam/boiler layer, and the generator interfaces. Its purpose is provenance and reconciliation, not a new dispatch result. The C5p_o carrier balance is copied unchanged as the authoritative balance.

## What remains blocked

KGF underfiring, BF hot-stove heat, PEFA mixes, a common-plant WAG/NG split, and C1 carrier-split flare are not generated from residual WAG. They remain explicitly blocked. Count: 6. Wobbe/gas-quality constraints are deliberately outside the thesis scope.

## WAG-explicit CO2

`wag_point_of_oxidation_co2_ledger.csv` adds a separate partial WAG combustion/flare ledger. It counts BFG, COG and BOFG only where an accepted controller row records their use, using the existing RVO/Netherlands fuel-list factor selection. It excludes NG residuals, electricity residuals, Scope 2 and aggregate BF/BOF/KGF/PEFA process counters. It is therefore not a site total, not ETS-ready and not a cost input.

## Validation status

Validation checks: `{'pass': 8, 'warning': 1}`. The WAG balances are preserved. A warning remains because HSM and sinter account for only part of C5p_o's process/prep carrier totals; the unclassified remainder is reported rather than reassigned.

## Athanasiadis alignment

The comparison is methodological only: carrier-specific generation/use, plant controller separation, steam/boiler and generator interfaces, no direct WAG-market value, and fail-closed mixing are aligned at an architectural level. It is not a numeric replication, no raw Athanasiadis PDF was inspected, and no official Tata claim is made.

## Critical review

Review `controller_mix_allocation.csv` to verify that each mix has an existing-controller provenance. Review `process_controller_reconciliation.csv` to see exactly what process use remains unclassified. Any aggregate WAG physical row, mixed-WAG numeric allocation, C5p_k provenance, or a newly inferred WAG/NG ratio invalidates this stage.

## Gate

- Controller mix and carrier-balance reporting: GO, diagnostic-only.
- Complete common-plant physical WAG/NG allocation: NO-GO.
- NG residual policy, full sensitivity, executable migration, economics and DA: NO-GO.
- WAG-explicit CO2 ledger: GO, diagnostic-only and partial. Consolidated site/ETS CO2: NO-GO.
