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
| `STEEL_MODEL_POLICY_DECISIONS.md` | Freezes production, carbon, tariff, and stage-sequencing policy decisions. |
| `STEEL_IMPLEMENTATION_FREEZE_V1.md` | Versioned cross-wave freeze that turns Waves `A` through `E` into a controlled implementation path. |
| `STEEL_S2_S3_IMPLEMENTATION_SCOPE.md` | Freezes the first coding scope for `S2` and `S3`. |
| `STEEL_STAGE_GATE_VALIDATION_PLAN.md` | Gives the detailed stage-gate validation contract for `S2` through `S9`. |
| `STEEL_TRACTABILITY_AND_CHANGE_CONTROL.md` | Separates methodological versus engineering changes and freezes tractability rules. |
| `STEEL_THESIS_WRITING_PLAN.md` | Maps implementation stages to thesis writing outputs and wording rules. |

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

## S2.0 to S2.2 Smoke Scaffold

The first code scaffold for steel now lives under:

- `scripts/Data/04_Steel_Test_Case/`

Current implemented boundary:

- deterministic hourly metallic material-flow LP only;
- one-day toy smoke configuration;
- simple indexed hours `0..23` rather than market-timestamped UTC delivery periods;
- fixed production target with cost minimisation;
- governed toy input tables under `data/03_Optimisation/inputs/assets/steel/s2_toy_scaffold/`;
- explicit infeasibility-classification smoke cases for `S2.2`;
- no product revenue;
- no S3 internal-energy, emissions-cost, tariff, DA, stochastic, reserve, or CVaR layers.

Run entry point:

- `python scripts/Data/04_Steel_Test_Case/run_s2_toy_smoke.py`

Important caveat:

- all numerical values in the current steel smoke configs and governed toy tables are scaffold or toy values only;
- they are not approved Tata Steel IJmuiden inputs;
- they are not Tata-specific quantitative evidence;
- feasible S2 smoke runs and infeasibility diagnostics are structural validation artifacts, not thesis-grade quantitative results.

Current `S2.2` infeasibility smoke classes:

- `capacity_bottleneck`
- `terminal_inventory_violation`
- `feed_shortage`

These are structural test labels for governed diagnostic runs only. They do not open any `S3`, DA, stochastic, `mFRR`, or CVaR scope.
