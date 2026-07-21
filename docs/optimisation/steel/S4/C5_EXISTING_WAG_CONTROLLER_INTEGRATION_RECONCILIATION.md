# C5 Existing WAG-Controller Integration Reconciliation

## What this stage found

KGF underfiring, BF hot-stove heat and PEFA total gas heat were already
implemented in upstream C5 layers. They must therefore not be rebuilt or added
as extra WAG sinks in C5p_o. The task is an integration/reconciliation problem,
not a missing-controller problem.

## Controller status

- **KGF:** upstream COG self-use exists, but its clean-COG boundary does not
  numerically match the current C5p_o COG generation. Adding it again would
  double count self-use.
- **BF hot stove:** upstream BFG-first use exists, but its net BFG boundary
  does not numerically match the current C5p_o BFG generation. Adding it again
  would double count hot-stove use.
- **PEFA:** upstream Option-A PEFA outputs explain the full C5p_q unclassified
  COG and BOFG process-use gaps when the 24-hour annualised output is used.
  C5p_q also carries 168-hour HSM/sinter rows, so this remains explanation-only
  until a common annualisation horizon is frozen.

## Athanasiadis methodology

The architecture is aligned: separate carrier-specific process controllers,
plant-specific eligibility, utility/generator separation and no direct WAG
market valuation. It is not yet fully aligned as one coherent controller
network because the annualisation horizon is not common. No raw Athanasiadis
PDF was inspected and this is not a numeric replication or an official Tata
claim.

## Gate

- Existing-controller reconciliation: GO, diagnostic-only.
- PEFA explanation of C5p_q COG/BOFG gaps: GO at 24h only, pending horizon
  normalisation.
- KGF/BF direct integration into C5p_o: NO-GO pending gross-to-net boundary
  bridges.
- Full physical WAG/NG allocation, NG residual policy, WAG/fuel-explicit CO2,
  sensitivity, migration, economics and DA: NO-GO.

Status: `partial_existing_controller_integration_reconciled`. No model behaviour changed.
