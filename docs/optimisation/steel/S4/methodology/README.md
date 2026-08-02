# Steel MILP Methodology Working Set

## Purpose

This directory is the editable bridge between the executable C0/C1 steel
model and the thesis methodology chapter. It deliberately separates the
stable physical formulation from later market and uncertainty extensions.

The documents are canonical methodology drafts, not generated run reports and
not a replacement for the active C5 state and roadmap document.

## Documents

1. [`CORE_PHYSICAL_MILP.md`](CORE_PHYSICAL_MILP.md) defines the physical model
   once. It contains the sets, indices, parameters, decision variables,
   domains, units, constraints, rolling-horizon state and lexicographic
   objective used by the deterministic model and inherited by later stages.
   It remains the implementation-faithful mathematical reference.
2. [`THESIS_DETERMINISTIC_FORMULATION.md`](THESIS_DETERMINISTIC_FORMULATION.md)
   provides the concise thesis-facing version: non-overlapping notation, one
   represented procurement-cost objective and five core constraint families.
   It is the preferred copy-and-edit source for the methodology chapter.
3. [`PARAMETER_SOURCE_REGISTER.md`](PARAMETER_SOURCE_REGISTER.md) records the
   numerical parameters reported in the methodology, their units, evidence
   class, source or governing decision, implementation status and caveat.
4. [`MARKET_AND_UNCERTAINTY_EXTENSIONS.md`](MARKET_AND_UNCERTAINTY_EXTENSIONS.md)
   defines only the additional notation and equations for deterministic DA,
   stochastic DA, CVaR and future mFRR participation.

## No-repeat writing rule

The thesis should present the formulation in the following order:

| Thesis subsection | Primary document | What is written there |
|---|---|---|
| System boundary and configurations | Core physical MILP | C0/C1 topology, represented boundary and exclusions |
| Mathematical formulation | Core physical MILP | All inherited physical symbols, variables and equations |
| Parameterisation | Parameter/source register | Values, units, sources, assumptions and calibration status |
| Deterministic DA extension | Market/uncertainty extensions | Price information, quantity bids and settlement delta only |
| Stochastic extension | Market/uncertainty extensions | Scenarios, probabilities, recourse and non-anticipativity only |
| Risk extension | Market/uncertainty extensions | CVaR variables and objective term only |
| mFRR extension | Market/uncertainty extensions | Reserve decisions, revenues, activation and deliverability only |

The stochastic subsection must not repeat plant descriptions, material
balances, storage equations, WAG equations, steam equations or the base
electricity balance. It should state that those constraints are inherited and
then explain only how they are indexed by scenario and linked by
non-anticipativity.

## Evidence language

Every numerical value in the parameter register has a provenance entry. The
provenance can be:

- an external source-backed value;
- a value derived transparently from an external source;
- a validation-selected aggregate abstraction;
- a governed development assumption or policy.

A governed assumption is not described as externally sourced. Where no public
Tata value exists, the register cites the exact project decision or source-card
lineage that introduced the assumption and identifies the evidence gap.

## Maintenance rule

When a parameter, equation or scope decision changes:

1. update the executable model or governing config first;
2. update the parameter/source register;
3. update the core or extension equation only if the mathematical contract
   changed;
4. update `docs/optimisation/PROJECT_DECISIONS.md` when the change is a
   methodological decision;
5. keep the active state and gate result in
   `C5_MODEL_STATE_AND_DETERMINISTIC_OPTIMISATION_ROADMAP.md` rather than adding
   another status or handoff document.
