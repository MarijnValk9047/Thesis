# Steel Optimisation Scope

## Purpose

This file is the focused scope reference for the active steel optimisation workstream. It replaces the long steel background that previously lived in `AGENTS.md`.

## Active default

The active implementation path is the C0/C1 Tata Steel IJmuiden-inspired physical model.

For the current executable state, accepted baseline, historical exclusions and
next implementation gate, read
`steel/S4/C5_MODEL_STATE_AND_DETERMINISTIC_OPTIMISATION_ROADMAP.md`. Do not
reconstruct the active C0 policy from older fixed-schedule reports.

The current objective is not market optimisation. It is to prove that a rolling deterministic steel model can close:

- final-product quota deadlines;
- material balances;
- configuration-specific process limits;
- carrier-specific WAG balances;
- steam and utility balances;
- named NG backup and residual reporting;
- solver-size and runtime reporting.

The first executable default is a 168-hour planning horizon with a 24-hour execution block. This is not an annual whole-site optimisation.

## Phase sequence

### S1: rolling deterministic production feasibility

Build and maintain a price-free C0/C1 optimiser with hard cumulative final-product-proxy quota deadlines. This is the active priority.

S1 policies:

- the executable 24-hour final-product-proxy quota is a hard cumulative lower
  bound; overproduction is allowed and reported;
- the 6.75 Mt/y value is annual-equivalent development and validation context, not a direct hourly constraint;
- C0 uses quota-driven availability with source-classified KGF1/KGF2, sinter and BF6/BF7 fixed on while their throughput remains unfixed inside governed bounds;
- the enforced-continuous smoke case passes; the thesis-scale quota exceeds the
  governed terminal-balanced sinter-limited capacity envelope, which must not
  be hidden behind a fixed or relaxed C0 schedule;
- preserve BFG, COG, and BOFG as separate carriers;
- aggregate WAG is reporting only;
- mixed gas and Wobbe-quality modelling are out of scope;
- use eligible WAG before explicitly permitted NG backup;
- never invent a plant-level WAG/NG split;
- report electricity and NG residuals without filling, calibrating, costing, or allocating them;
- keep WAG-explicit combustion CO2 separate from aggregate process-counter CO2;
- do not claim an ETS-ready or whole-site Scope 1 ledger from the partial steel boundary.

Required S1 outputs:

- resolved configuration and quota-deadline plan;
- per-execution-block quota fulfilment and carried inventories;
- material, WAG, steam, and utility balance checks;
- carrier-specific WAG use, flare, and residuals;
- named NG backup plus electricity/NG residual reporting and limitations;
- solver status, objective, runtime, MIP gap, variables, binaries, and constraints.

### S2: deterministic energy-cost optimisation

Only after S1 is physically feasible and its balance checks pass, introduce transparent deterministic energy costs.

S2 must preserve the same production, material, and utility constraints. It must not introduce DA bidding, price scenarios, product revenue, ETS costs, CVaR, or mFRR.

### S3: market and uncertainty extensions

Only after S1/S2 are stable and reportable:

1. DA-only bidding and settlement;
2. stochastic scenario optimisation;
3. CVaR risk aversion;
4. mFRR capacity and activation modelling, only if explicitly reopened.

## Active implementation scope

Implement and maintain:

1. C0/C1 rolling-horizon deterministic production feasibility.
2. Configuration-specific material, WAG, steam, and utility coupling.
3. Layered annual-equivalent validation against the canonical anchor register.
4. Deterministic energy-cost optimisation after physical boundaries are ready.
5. Standardised steel run reporting, experiment registry, and reproducible run folders.
6. Later DA-only bidding and settlement logic.
7. Later stochastic scenario optimisation and CVaR.

When a steel run becomes thesis-significant, record it in the central experiment registry (`docs/optimisation/experiment_registry.md` or `.csv`) if that registry exists or is created for the active reporting phase.

## Out of scope unless explicitly requested

- exclusive group bids;
- full EUPHEMIA market clearing;
- price-making or bi-level market equilibrium;
- intraday market participation;
- long-term investment planning;
- deep reinforcement learning;
- annual whole-site or ETS claims from a partial steel boundary;
- new forecasting-model research unless required to consume existing artifacts.

## Technical default

Use:

- Python;
- Pyomo;
- Gurobi;
- `scripts/Data/04_Steel_Test_Case/configs/steel_quota_driven_physical_feasibility.yaml` for active S1 C0/C1 quota-feasibility work.

`steel_rolling_feasibility.yaml` is retained as a historical fixed-schedule
diagnostic config and is not the active default.

Local Gurobi licence paths may be set through runtime configuration. Never commit licence contents, WLS keys, API keys, or secrets.

## Hydrogen status

Hydrogen is historical context, not the active case.

Reusable patterns:

- rolling-deadline quota logic;
- run-folder and reporting structure;
- price-insensitive and perfect-foresight benchmark framing;
- later DA/stochastic/CVaR market experiment patterns.

Do not route the deterministic steel physical runner through DA prices, scenarios, or the hydrogen command centre while S1 is active.

## Steel source documents

Read only when relevant:

- `docs/optimisation/PROJECT_DECISIONS.md`
- `docs/optimisation/steel/S4/C5_MODEL_STATE_AND_DETERMINISTIC_OPTIMISATION_ROADMAP.md`
- `docs/optimisation/steel/S4/C5_ROLLING_PRODUCTION_FEASIBILITY_OPTIMISER.md`
- `docs/optimisation/steel/S4/C5_MODEL_ANCHOR_REGISTER_AND_EVIDENCE_HIERARCHY.md`
- `docs/optimisation/steel/S4/C5_WAG_CONTROLLER_CONTRACT_HARDENING.md`
- `docs/optimisation/steel/S4/C5_WAG_AND_EMISSIONS_MILP_IMPLEMENTATION_PLAN.md`
- `docs/optimisation/steel/STEEL_TRACTABILITY_AND_CHANGE_CONTROL.md`
