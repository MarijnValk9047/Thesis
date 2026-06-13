# Steel Planning Docs

## Purpose

This folder holds the planning and scope-control documents for the transition from the verified hydrogen optimisation test case toward a later steel-plant MILP asset configuration.

These files are the fallback reference for future Codex work on the steel workstream. They define what may be implemented next, what must stay frozen, and what must remain explicit assumptions rather than hidden facts.

Hydrogen remains the current verified optimisation baseline. Steel is the next workstream, not the current solved implementation.

## Documents

| Document | Role |
|---|---|
| `STEEL_MODEL_BLUEPRINT.md` | Freezes the first steel-model scope and phased modelling layers. |
| `STEEL_DATA_AND_PARAMETER_PLAN.md` | Defines how steel data and parameters move from sources into approved model inputs. |
| `STEEL_ASSUMPTION_REGISTER.md` | Records uncertain or disputed site/model assumptions that must be exposed and versioned. |
| `STEEL_VALIDATION_AND_TRACTABILITY_PLAN.md` | Defines validation gates, solver reporting, and tractability rules before thesis use. |
| `STEEL_IMPLEMENTATION_ROADMAP.md` | Gives the practical implementation sequence for future Codex sessions. |

## Placement Choice

The steel planning docs are placed under `docs/optimisation/steel/` because:

- optimisation governance already lives under `docs/optimisation/`;
- hydrogen-specific technical detail already exists under `scripts/Data/03_Hydrogen_Test_Case/docs/`;
- the steel workstream needs a stable planning surface before code scaffolding is created.

No steel code or data scaffold is created here. This folder is documentation-only by design.

## Current Boundary

The planning set assumes:

- hydrogen remains the verification case;
- steel is Tata-inspired, not a confidential site digital twin;
- first steel implementation is deterministic, hourly, DA-only, and continuous/LP where possible;
- stochastic DA, CVaR, quarter-hour, `D_plus_4`, and `mFRR` are later phases only;
- exclusive group bids remain out of scope unless reopened explicitly.
