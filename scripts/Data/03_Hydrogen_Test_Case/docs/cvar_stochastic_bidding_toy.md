# Toy CVaR Stochastic Bidding

## Purpose

Phase 5a adds a transparent linear CVaR formulation to the toy stochastic hourly hydrogen bidding MILP. The purpose is formulation validation, not thesis-grade scenario evaluation and not gamma tuning.

This phase remains:

- toy scenarios only;
- hourly only;
- one delivery day only;
- DA-only only;
- risk-measure validation only.

Real scenario integration is intentionally postponed until thesis-grade scenario artifacts and coverage diagnostics are good enough to support defensible risk claims.

## Baseline Convention

The stochastic bidding model already maximises expected adjusted profit:

`expected_adjusted_profit = sum_s pi_s * adjusted_profit_s`

Bid quantities `q[t,b]` remain first-stage and non-anticipative. They are shared by all scenarios. Scenario-specific clearing is still determined by fixed bid-price tiers, and physical dispatch remains scenario-dependent recourse after clearing.

## Loss Definition

CVaR is applied to scenario loss, not directly to profit:

`loss_s = - adjusted_profit_s`

This keeps the sign convention clean:

- higher profit means lower loss;
- worse downside outcomes mean larger loss;
- CVaR is penalised in the maximisation objective.

## Linear CVaR Formulation

Variables:

- `zeta`: VaR threshold for loss;
- `xi_s >= 0`: excess loss above `zeta`.

Constraints:

- `xi_s >= loss_s - zeta`
- `xi_s >= 0`

CVaR expression:

`CVaR_alpha = zeta + (1 / (1 - alpha)) * sum_s pi_s * xi_s`

Risk-adjusted objective:

`maximize expected_adjusted_profit - gamma * CVaR_alpha`

Where:

- `alpha` is the CVaR confidence level, default `0.95`;
- `gamma` is the risk-aversion weight.

## Interpretation

- `gamma = 0` reproduces the risk-neutral model, apart from negligible bid regularisation used only to break degeneracy.
- Larger `gamma` penalises downside loss more heavily.
- In the toy setting this can change bid firmness, expected clearing, minimum clearing across scenarios, expected shortfall, and worst-scenario profit.

The bid-price headroom diagnostic `bid_price - scenario_price` is reported only as a bidding-behaviour diagnostic. It is not a paid price. Accepted electricity still pays the scenario market price.

## Why This Is Not Parameter Tuning

The gamma sweep is only a formulation check on artificial scenarios. It is not used to claim a preferred operational policy and must not be described as validation-based model selection. Real gamma selection, if used later, must be based on proper validation periods and thesis-grade scenario inputs.

## Relationship To Backtesting

Inside the stochastic optimisation, scenarios evaluate ex-ante outcomes. After solving, realised ex-post backtesting still requires clearing the submitted first-stage bid curve against realised prices and then running deterministic redispatch from realised cleared electricity. That backtest loop remains separate from the scenario objective.

## Current Limitations

- no real thesis-grade scenario artifacts;
- no mFRR;
- no exclusive group bids;
- no endogenous bid prices;
- no full market-clearing model;
- no quarter-hour extension yet.

## Phase 5b Diagnostic Toy Cases

Phase 5a validated the CVaR algebra and sign convention, but its first toy case mainly moved bid firmness without materially changing clearing, shortfall, or realised outcomes. That is not enough to trust the behavioural side of the model.

Phase 5b therefore adds diagnostic toy cases whose only purpose is to make the risk logic economically active before real scenario integration:

- `cvar_high_price_exposure`
  - late hours are cheap in low scenarios, moderately expensive in mid scenarios, and very expensive in the stress scenario;
  - firmer late bids can improve expected profit but expose the plant to expensive stress clearing;
  - higher gamma should reduce some stress-clearing exposure, which can improve worst-scenario profit while increasing stress shortfall or reducing minimum cleared energy.

- `cvar_overprocurement_unused_energy`
  - one delayed-clearing scenario skips the first cheap hour and then clears the next hour;
  - the plant can then hit the electrolyser ramp limit and leave part of the cleared energy unused;
  - this activates `C_unused` in a controlled toy setting and keeps the unused-energy branch observable.

These cases are not evidence of thesis performance. They are model-behaviour checks only. The purpose is to verify that:

- CVaR can change economically relevant first-stage bids;
- stress-price exposure can alter downside outcomes;
- `C_unused` remains visible in stochastic bidding diagnostics;
- the model is ready for later validation on thesis-grade scenarios.
