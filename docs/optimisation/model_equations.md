# Model Equations

## Purpose

This file is a short formulation roadmap for the active steel path and the
historical hydrogen optimisation workstream. It is not the final thesis
mathematics chapter and it is not intended to reproduce every Pyomo detail.

The goal is to explain the current modelling layers in human-readable form so later work can see how the pieces fit together.

## 1. Baseline Physical Schedule Model

At the physical level, the hydrogen test case is a constrained dispatch problem.

Core elements are:

- electrolyser power;
- hydrogen production efficiency;
- optional compressor electricity use where relevant;
- hydrogen storage / buffer state;
- daily production target semantics;
- electricity procurement or availability from the market layer.

Conceptually, the model chooses an operating schedule that:

- respects power limits;
- respects storage balance;
- converts electricity into hydrogen with the configured efficiency;
- accounts for shortfall or related penalties where those are active.

This is the foundation underneath bidding, clearing, and redispatch work.

## 1A. Steel physical and fixed-reference deterministic-cost contract

The editable thesis-facing formulation is maintained in
`docs/optimisation/steel/S4/methodology/`. That working set defines the core
physical MILP once, gives every symbol a domain and unit, records parameter
sources, and treats deterministic DA, stochastic, CVaR and mFRR as delta-only
extensions. This file remains a compact cross-workstream roadmap.

The active C0/C1 steel formulation has a separately executable price-free
physical mode and an accepted fixed-reference represented-procurement-cost
mode. For each rolling solve both enforce hard cumulative final-product quotas,
material and origin balances, capacities and operating classes, separate
BFG/COG/BOFG balances, the represented steam abstraction and inventory
handoffs.

The governed electricity identity is:

```text
represented_gross_electricity[t]
  = internal_generator_electricity[t]
  + represented_grid_import[t]
```

Every gross-demand term is a named non-overlapping bucket. Unknown/background
electricity is a reporting residual and is absent from the equality and from
dispatch.

Named NG is the sum of explicit component flows on one LHV basis:

```text
represented_named_NG[t]
  = DRP_NG[t] + EAF_NG[t] + HSM_NG[t] + PEFA_NG[t]
  + boiler_NG[t] + VN25_NG[t]
```

IJ01 NG is fixed to zero. Full-site residual NG is reported separately and
cannot enter a plant balance.

For each represented generator unit:

```text
BFG[t] + COG[t] + BOFG[t] + named_NG[t]
  = electricity_output[t] + useful_steam_output[t] + conversion_loss[t]
```

VN25 uses the accepted development electricity conversion. IJ01 retains a
named deferred-conversion output until a quantitative CHP split is evidenced;
this preserves energy without inventing electricity or steam.

For the bounded VN25 development-response mode:

```text
VN25_fuel[t] = BFG_to_VN25[t] + COG_to_VN25[t]
             + BOFG_to_VN25[t] + named_NG_to_VN25[t]
VN25_electricity[t] = eta_VN25 * VN25_fuel[t]
0 <= VN25_electricity[t] <= 350 MWh_e per hourly step
VN25_electricity[t] <= represented_gross_electricity[t]
```

The central development efficiency is `eta_VN25 = 0.345`; the only active
bounded sensitivity is 0.34. WAG has no direct purchase price and named NG is
priced once on the common LHV basis. With no export, the marginal named-NG
break-even electricity price is:

```text
p_break_even = p_NG / eta_VN25
```

Minimum load, startup/shutdown, ramping, outages and CHP/steam obligation are
omitted rather than assigned unsupported zeros. IJ01 has no price-responsive
decision and retains zero modelled electricity plus its named deferred-
conversion identity.

Mode B counts carrier-specific WAG and named NG once at their represented
oxidation sink, including flare oxidation. Aggregate process-counter CO2 is
excluded from the same total.

The complete ex-post and optimised ledgers book only executed hours `E`, not
overlapping planned horizons. Let `F_ext` contain the represented external
grid, named-NG, coking-coal, PCI, ore, DR-pellet, purchased-scrap and imported-
slab flows:

```text
executed_procurement_cost
  = sum_(t in E, f in F_ext)(price[f,t] * solved_external_quantity[f,t])
```

The prices and their active central scenario IDs are read from
`c5_external_supply_costs.csv`; no price is embedded in Python. Component
costs reconcile to configuration totals. Annualised cost is reporting only:
`executed_168h_cost * 8760 / 168`. Residual electricity/NG and all internal
carriers contribute zero direct cost.

In `fixed_reference_cost` mode the first lexicographic solve is:

```text
minimise C = sum_(t in H, f in F_ext)(price[f,t] * external_quantity[f,t])
```

After obtaining `C*`, the model adds `C <= C* + 0.01 EUR`, deactivates the euro
objective and minimises the existing physical tie-breaker. This keeps
avoidable overproduction, flare and inventory cycling out of the economic
objective. Imported slab is priced on actual HSM delivery, never on its cap.
Residual electricity/NG, BFG/COG/BOFG, aggregate WAG, steam, internal
generation, inventory, product output, revenue and ETS are excluded.

Fixed route scenarios use horizon bands `[L_f,U_f]` and proportional cumulative
execution deadlines `d`:

```text
L_f * d/H <= sum_(t < d) quantity[f,t] <= U_f * d/H
```

This fixes cumulative route quantities within their governed tolerance without
fixing hourly throughput or an operating calendar. The price-free physical
mode uses the same physical bands and remains independently executable.

The pre-DAM operational-hardening lineage retains these bands but adds a
cumulative production-progress state. Let `q` be the central execution-block
quota, `B` the execution-block length, `X_r` cumulative completed production
before replan `r`, and `g_r = X_r - r*q` the carried production credit (negative
when debt). The remaining local lower deadline at local hour `d` is:

```text
T[r,d] = max(0, (r + d/B)*q - X_r)
next_block_target[r] = max(0, q - g_r)
```

For the next executed block, non-negative surplus and deficit variables define
one deviation tier:

```text
sum_(t < B) final_product[r,t] - next_block_target[r]
    = progress_surplus[r] - progress_deficit[r]

minimise progress_surplus[r] + progress_deficit[r]
```

The active objective order is production-progress deviation, represented
procurement cost, then the existing physical inventory tie-break. The progress
optimum is preserved within numerical tolerance and the cost optimum within
EUR 0.01. This is one lexicographic objective, implemented through sequential
solves with optimum-preservation constraints.
This does not fix hourly output or route shares. With flat prices the seven
executed blocks now annualise to 6.75 Mt/y; the former 6.78375-Mt/y result is a
superseded diagnostic of repeatedly resetting the first-block timing choice.
Under later varying prices, any permitted surplus remains credit in the next
replan instead of resetting cumulative obligations.

For replan `r`, electricity prices are selected only from values whose
information timestamp is available at the replan time:

```text
p[r,t] = latest eligible price(series_id, delivery=t,
                               information_available <= replan_time[r])
```

The flat series is available before the first replan. The synthetic varying
series is forecast-only and validates slicing; no realised future price,
bidding or settlement enters the model.

The current decision is `development_VN25_price_response_ready`. It accepts
only the bounded VN25 upper-bound development abstraction and permits the
separate governed price-data/forecast-contract task. It does not activate or
authorise real DAM dispatch, bidding, clearing, settlement, export or revenue;
IJ01 remains non-price-responsive and the missing historical/unit operating
features remain explicit limitations.

## 2. Bid-Clearing Logic

The bidding layer sits on top of the physical model.

Conceptually:

1. the strategy submits demand-side bid quantities across a bid-price grid;
2. realised market prices determine which bid blocks clear;
3. cleared electricity becomes the physically available electricity for the operational layer;
4. rejected bid quantities do not become usable energy.

This matters because the bidding model is not just "dispatch at known prices". Forecast or scenario quality affects:

- which quantities are submitted;
- which quantities clear;
- how much electricity is actually procured before redispatch.

The current implementation should be understood as price-taking DA bidding and settlement logic, not full market-clearing equilibrium or EUPHEMIA replication.

## 3. Redispatch After Clearing

Redispatch is the post-clearing physical adjustment step.

Conceptually:

- first the market determines cleared electricity;
- then the plant re-optimises or adjusts its physical operation using that cleared electricity as the realised availability constraint.

The key accounting idea is:

- cleared electricity is split into used and unused quantities;
- the redispatch layer must not use electricity that did not clear.

This is one of the major differences between a schedule-and-settle approximation and a true bid-clear-redispatch chain.

## 4. Deterministic Versus Stochastic Decision Structure

The current optimisation work distinguishes between:

- first-stage decisions made before uncertainty resolves;
- second-stage or recourse behaviour conditional on scenarios or realised outcomes.

In conceptual terms:

- first-stage objects are the submitted bids or other non-anticipative decisions;
- scenario-dependent quantities may adapt only where the timeline allows it.

For realised historical backtesting:

- the stochastic model chooses first-stage bids using forecast/scenario inputs;
- realised DA prices determine actual clearing;
- redispatch and settlement are then computed on the realised path.

This separation is essential for methodological correctness.

## 5. Settlement Logic

The current reporting chain distinguishes clearly between:

- the optimisation-time objective under forecast/scenario assumptions;
- realised ex-post settlement after actual clearing and redispatch.

Conceptually, this means:

- expected scenario profit/cost is not the same thing as realised historical profit/cost;
- reporting must preserve both numbers and not merge them into a single metric.

## 6. CVaR Layer

The repository also contains a risk-averse branch based on CVaR.

At concept level, this adds:

- a VaR threshold variable;
- per-scenario excess-loss variables;
- a confidence level `alpha`;
- a risk-aversion weight, often represented by `gamma`.

The objective then balances:

- expected performance;
- downside-tail penalty through the CVaR term.

The current important distinction is:

- CVaR exists as an implemented branch;
- it is not yet the hardened command-centre default path.

## 7. Phase 6C Quarter-Hour Steel DA Formulation

Phase 6C reuses the Phase-6B bid--clear--redispatch formulation on an explicit
time grid. Let `dt` be the interval duration in hours, `H` the physical horizon
in hours and `T = H / dt` the number of model intervals. The accepted QH gate
uses `dt = 0.25`, `H = 120`, `T = 480`, with 24 hours/96 intervals executed per
replan. The hourly implementation remains the `dt = 1` special case.

Physical flows are interval quantities, not hourly rates:

```text
x_interval[t] = x_rate[t] * dt
inventory[t] = inventory[t-1] + inflow_interval[t] - outflow_interval[t]
interval_cost[t] = price_EUR_per_MWh[t] * grid_import_MWh[t]
```

Hourly capacity, fixed electricity/NG/steam/CO2 services and other rate bounds
are multiplied by `dt` exactly once. A rate ramp `R` is imposed on reconstructed
rates and is therefore equivalent to:

```text
abs(x_interval[t] / dt - x_interval[t-1] / dt) <= R * dt
abs(x_interval[t] - x_interval[t-1]) <= R * dt^2
```

Daily commitment remains one binary per local delivery day. Throughput,
inventories, carriers and energy flows are interval decisions. A 24-hour HSM
source-mix block becomes 96 QH intervals; production, route and generator/scrap
deadlines are translated from elapsed physical hours to aligned interval
indices. Historical fixed-hour calendars fail explicitly for `dt != 1`.

For each QH timestamp and bid-grid step `b`, the first-stage incremental
purchase bid `q[t,b]` is common to all scenarios. Scenario `s` clears:

```text
grid_import[s,t] = sum(q[t,b] for b >= scenario_price[s,t])
```

After submission, realised QH prices clear D with the same `bid >= actual`
rule. Redispatch fixes executed grid import to cleared MWh exactly; DA
settlement is `cleared_MWh * actual_EUR_per_MWh` and is excluded from the
separate non-grid represented procurement-cost term. Only D is executed and
settled. Actuals remain isolated from QH-point, QH-S10 and price-insensitive
bidding; configuration-matched true PF is an oracle benchmark only.

The week-end terminal bands are copied unchanged from accepted hourly Phase
6B. The last replans truncate to 96/72/48/24 physical hours, corresponding to
384/288/192/96 intervals. State handoff records elapsed physical hours and
executed intervals separately. No QH-specific start, minimum-load, outage,
CHP or plant ramp parameter is invented.

## 8. What This File Does Not Claim

This file does not claim that:

- the current code implements every later thesis phase already;
- all scenario inputs are thesis-final;
- the validated bounded QH week is a long-run optimisation default or annual
  economic evaluation;
- the current equations here are the final thesis notation.

It is a roadmap document for repository structure and modelling intent.
