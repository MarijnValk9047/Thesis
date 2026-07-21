# C5 Generator and WAG-Sink Boundary Audit

## Purpose

This read-only audit explains the C1 gap between the carrier-specific WAG fuel
sent to the modelled VN25/IJ01 interface and the MER annual generator-fuel
context. It does not change generator capacities, WAG allocation, named NG,
flare, CO2 factors or the production model.

## Result

The exact 6.75-Mt/y run sends 2.434519 PJ/y of BFG/COG/BOFG to the represented
generator interface, against the partial MER generator-WAG context of 10.5
PJ/y. The inherited interface cap is 181.907 MWh_LHV/h, while realised fuel is
about 77.2 MWh_LHV/h. The cap is therefore not the immediate cause of the gap.

The represented non-generator sinks consume about 17.261 PJ/y of the 19.695
PJ/y generated WAG. Combining those sinks with the 10.5-PJ/y generator anchor
would require about 27.761 PJ/y, which exceeds the present gross WAG boundary.
This proves a boundary/sink-definition mismatch if the rows are treated as one
system; it does not identify a value to tune.

## Interpretation

- The current model may not increase the generator cap just to reach 10.5 PJ/y.
- It may not remove WAG from HSM, process self-use or boilers merely to improve
  the annual generator fit.
- The next evidence task is a source-backed audit of each represented
  non-generator WAG sink, beginning with HSM reheat and mandatory self-use.
- The MER generator rows remain carrier-specific validation context. They are
  not hourly dispatch constraints or evidence for a fixed WAG/NG ratio.

## Boundary rules retained

- BFG, COG and BOFG stay separate.
- Aggregate or mixed WAG never physically supplies a sink.
- Named NG remains a named backup flow; full-site NG is a reported residual.
- The 0.1-PJ/y MER flare is retained as an unsplit reporting gap. No flare CO2
  is added from it.
- WAG-explicit Mode-B CO2 remains separate from aggregate process counters.
