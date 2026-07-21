# C5 WAG-Explicit CO2 Anchor Reconciliation

## Purpose

C5p_u is an annual, diagnostic-only reconciliation. It books represented
BFG/COG/BOFG oxidation once at existing C5p_t controller sinks, compares the
subtotal with C0/C1 Scope 1 validation anchors and retains the remainder as a
visible boundary residual. It does not allocate residual electricity or NG,
change fuel allocation, or create an ETS/economics layer.

## Result

- C0 represented WAG-explicit subtotal: 6.374735 MtCO2/y.
- C1 represented WAG-explicit subtotal: 2.909737 MtCO2/y.

These subtotals use the coherent 24-hour C5p_t candidate contract ledger, not
C5p_q's historical 168-hour partial compilation. PEFA's carrier-specific
controller use is therefore represented. Carrier-unsplit C1 flare, residual
NG, residual electricity, Scope 2, DRP capture and aggregate BF/BOF/KGF/PEFA
counters are excluded.

## Carbon-boundary policy

The WAG-explicit mode is point-of-oxidation accounting. It is mutually
exclusive with aggregate process counters that contain the same WAG carbon.
The optional EAF context row is reported separately because the current EAF
route has no WAG fuel carrier; it remains a range-midpoint diagnostic, not an
ETS component.

## Residual policy

Electricity, NG and CO2 residuals are signed reporting KPIs. They are neither
loads nor allocated fuel, and they are not used to fit the model to anchors.

## Gate

- WAG-explicit point-of-oxidation CO2 subtotal: GO, diagnostic-only.
- Site Scope 1 residual reporting: GO, validation-only.
- Consolidated site/ETS CO2, NG residual allocation, sensitivity, economics and DA: NO-GO.
