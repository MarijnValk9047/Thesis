# Model Equations

## Purpose

This file is a short formulation roadmap for the hydrogen optimisation workstream. It is not the final thesis mathematics chapter and it is not intended to reproduce every Pyomo detail.

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

## 7. What This File Does Not Claim

This file does not claim that:

- the current code implements every later thesis phase already;
- all scenario inputs are thesis-final;
- current quarter-hour or `D_plus_4` paths are already the optimisation default;
- the current equations here are the final thesis notation.

It is a roadmap document for repository structure and modelling intent.
