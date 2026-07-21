# C5 Component Ontology and Route Reconciliation

## Decision

The project already has a PyPSA-inspired topology ontology in S4.4b2:
`config_components.csv`. C5 does not replace it. The C5 adapter adds only
operating-class metadata needed by the active Pyomo feasibility builder.

## Operational abstraction

- Coking, sinter, BF6 and NG-DRP are `continuous_must_run` where they are
  represented in C1: they are on throughout a planning horizon, while the
  existing source-carded throughput range remains free.
- BOF and EAF are `batch_equivalent`: the model retains its existing
  commitment treatment and does not invent a heat calendar.
- HSM is a bounded downstream asset. DSP is a route interface; neither gets a
  top-down HSM/DSP production split.
- COG, BFG and BOFG remain carrier-specific. Aggregate/mixed WAG cannot feed
  physical allocation.

## Route scenarios

The active default remains `quota_driven_topology`. This stage runs four
diagnostic scenarios only: free route, source-informed BOF liquid-steel band,
central 3.4/6.75 BOF liquid-steel share, and that central share with MER
HDRI-plus-named-scrap material context. Imported slab stays outside the
endogenous BOF/EAF liquid-steel share.

The output root is a run artifact, not Git provenance:
`data/03_Optimisation/runs/steel_component_ontology_route_reconciliation_v5/`.

## Executed result and pre-economics stop

All four 168-hour/three-replan quota scenarios were infeasible at the
6.75-Mt/y-scaled final-product target. This includes the free C1 route, so the
result is not caused by the source-informed BOF/EAF band or named-scrap case.
No annual anchor-fit row is therefore reported from those quota runs.

The bounded, no-parameter-change capacity probes separate two findings:

| Case | Annualised maximum final product | Gap to 6.75 Mt/y | Interpretation |
|---|---:|---:|---|
| C1 free route, operating-class classification only | 6.541 Mt/y | -3.09% | Current represented C1 capacities/conversions fall short before a route split is imposed. |
| C1 central 3.4/6.75 liquid-steel share + named scrap | 6.269 Mt/y | -7.13% | The source-context route/material scenario is more restrictive, but it is not used to tune capacity. |
| C1 free route, continuous processes fixed on | no feasible steady state | n/a | The current coke/sinter/BF/DRP material-and-terminal-buffer contracts do not yet support simultaneous must-run enforcement. |
| Earlier C0 capacity audit | 5.898 Mt/y | -12.62% | C0 is separately below the 6.75-Mt/y development target under current represented constraints. |

The ontology is therefore accepted as a structural classification and the
route policy scenarios are accepted for diagnostics. They are **not** a basis
to change capacity or conversion inputs. Before a new annual-anchor
sensitivity, the next physical gate is a targeted steady-state reconciliation
of the continuous C1 coke/sinter/BF chain and the exact capacity/conversion
drivers responsible for the 3.09% C1 free-route shortfall.

This completes the bounded pre-economics effort: four of at most five scenario
families were executed, no economics was entered, and the remaining fifth slot
should be reserved for that reconciled physical case rather than spent on
further route-share tuning.

## Guardrails

- No capacity or conversion factor is changed.
- No route share is enforced in the default model.
- No WAG/NG split or Wobbe-quality model is invented.
- Residual electricity and NG remain reporting quantities.
- Annualisation is a representative-window comparison only.
- Economics, DA, ETS and product revenue remain out of scope.
