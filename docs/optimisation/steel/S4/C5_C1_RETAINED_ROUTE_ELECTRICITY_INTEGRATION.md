# C5 C1 Retained-Route Electricity Integration

## Decision

When the existing C1 development controllers are activated, gross electricity
now includes their already-defined HSM/WBW rolling and PEFA electricity
expressions alongside DRP/EAF electricity. This repairs a reporting-boundary
omission; it does not add a new parameter, WAG allocation, residual load, cost
term, or production constraint.

## Boundary

HSM and PEFA are development-only controller contracts. ASU/oxygen, KGF,
BOF/OSF, DSP/downstream and site/background electricity remain outside this
integration until separately reconciled. WAG/generator interpretation remains
subject to C5p_o.

## Validation

The controlled run must show, per C1 hour:

`gross electricity = DRP/EAF electricity + development-controller electricity`

This is not an annual anchor fit or a sensitivity result.
