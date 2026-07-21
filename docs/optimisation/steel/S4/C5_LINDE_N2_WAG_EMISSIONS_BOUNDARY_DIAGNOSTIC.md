# C5 Linde N2, WAG and Emissions Boundary Diagnostic

## Decision

The Linde N2/auxiliary electricity load is a separate, opt-in development
context load. It is not part of the O2-specific ASU intensity and does not
create O2, WAG, NG or CO2 flows. This diagnostic measures its boundary effect
and explains remaining WAG/emissions anchor gaps without tuning to anchors.

## Evidence boundary

- Athanasiadis describes non-steel processes such as nitrogen production as a
  varying Linde electricity load and describes about 45 MW unrelated to steel.
- Badarinath describes Linde as supplying over 150 t O2/h and a large stable
  electricity consumer, but does not directly identify the 45-MW component.
- The 45-MW row is therefore a Rank-3 development context, not official Tata
  meter evidence.

## Modelling policy

`Linde_total_meter_electricity = ASU_O2_process_electricity + N2_auxiliary_context_electricity`.

The second term is fixed in this physical diagnostic. It remains separate in
all ledgers and has no O2 driver, N2 allocation, market response, CO2 factor
or production effect. C0 remains reporting-only because its gross electricity
proxy is not decomposed enough to add another physical bucket safely.

## WAG and CO2 interpretation

Carrier-specific WAG is compared only where units and boundaries match.
The Athanasiadis Table 9 WAG total and the full-site Scope 1 anchors are not
used to tune carrier coefficients or emissions factors. Mode B reports only
represented BFG/COG/BOFG oxidation plus separately tracked named NG where the
existing model supports it; it never adds aggregate process counters.

The current integrated C1 run reports 26.291 PJ_LHV/y carrier WAG, whereas
C5p_m reported 13.885 PJ/y from an earlier aggregate interface. This internal
stage difference must be reconciled through activity bases and the three
development generation coefficients before any anchor-directed WAG
sensitivity. Athanasiadis Table 9 labels its 1.23-TWh field only as `Total
WAGs Generation`; it does not state the LHV/electricity boundary in that
table, so it is retained as non-comparable context rather than converted.

The current represented WAG combustion subtotal is 4.563 MtCO2/y against an
8.3-MtCO2/y full-site context anchor. That residual is a coverage diagnostic:
it must not be filled by aggregate BF/BOF/KGF/PEFA/sinter process counters.
