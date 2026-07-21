# C5 Horizon And Gross/Net Boundary Bridge

## Purpose

C5p_t establishes a **24-hour diagnostic candidate contract ledger**. It does
not replace C5p_q, change C5p_o carrier totals, create a new allocator, or
promote any source-card parameter. The 24-hour basis is selected because C5p_m
uses it to construct the C5p_o carrier contract and because the existing PEFA
controller exactly reconciles the COG/BOFG process gaps on that basis.

## Result

At 24-hour annualisation, HSM, sinter and PEFA fully explain the C5p_o
carrier-specific process/preparation use. PEFA therefore changes from an
unclassified gap to a source-traceable explanation in the candidate ledger.
Its Option-A controller remains total-gas based: no fixed Malerij/Branderij
share is introduced.

KGF self-use and BF hot-stove use remain upstream gross-to-net boundary
deductions. Their upstream net carrier values do not match C5p_o, so this stage
does not select a scaling factor and does not add them as new physical sinks.
That prevents double counting.

## Gate

- 24-hour controller-mix and PEFA explanation ledger: GO, diagnostic-only.
- C5p_q migration: review required; C5p_q itself is not modified here.
- KGF/BF direct C5p_o integration: NO-GO pending an evidence-backed gross/net
  bridge.
- NG residual, WAG/fuel-explicit CO2, full sensitivity, migration, economics
  and DA: NO-GO.

## Athanasiadis comparison

The candidate ledger follows the same useful architectural separation:
carrier-specific gas controllers, process/utility/generator distinction and no
direct WAG-market value. It is not a numeric replication, no raw Athanasiadis
PDF was inspected, and no official Tata claim is made.

Status: `candidate_24h_contract_ledger_reconciled`. Thesis usability: `false`.
