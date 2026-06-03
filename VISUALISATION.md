# Visual Reporting Policy

Recommended repository path:

```text
VISUALISATION.md
```

This document defines the visual reporting policy for the thesis/research codebase. It applies to forecast evaluation, scenario evaluation, bidding, clearing, redispatch, settlement, optimisation diagnostics, solver diagnostics, and thesis-ready result reporting.

The goal is not to make figures decorative. The goal is to make model behaviour, methodological risks, economic outcomes, operational feasibility, and uncertainty visible in a consistent academic style.

Use this document together with:

```text
visual_style.py
```

The Markdown policy defines **what to show and why**. The Python module defines the reusable colour palette and Matplotlib defaults.

---

## 1. Core principle

Every figure should answer a methodological or interpretive question.

Before creating a plot, identify:

1. what behaviour is being tested;
2. which model, strategy, horizon, granularity, period, and scenario set are shown;
3. whether the comparison uses common support;
4. whether the result concerns forecast quality, scenario calibration, bidding performance, physical feasibility, realised settlement, risk, or solver tractability;
5. what the reader should check before trusting the result.

Do not create a plot only because it looks attractive. A figure should first be correct and interpretable, then visually polished.

---

## 2. Global style rules

Use a restrained academic visual style:

- muted colours;
- clear axis labels with units;
- consistent model and strategy names;
- visible but unobtrusive gridlines;
- no default Excel, Matplotlib, Pandas, or Seaborn colour cycles;
- no unnecessary chart decorations;
- no 3D plots unless explicitly justified;
- no overloaded figures with many unrelated variables.

Default thesis/reporting figures:

```python
figure.figsize = (8, 4.5)
figure.dpi = 120
savefig.dpi = 300
```

Export thesis-ready figures as PNG and preferably PDF:

```python
fig.savefig("figure_name.pdf", bbox_inches="tight")
fig.savefig("figure_name.png", dpi=300, bbox_inches="tight")
```

Use PDF for vector quality in LaTeX/Word when possible. Use 300 dpi PNG when PDF insertion causes formatting problems.

---

## 3. Mandatory support statement

Every comparison figure or table must state the support used. Include this in the title, subtitle, caption, nearby markdown, or table note.

Minimum support metadata:

- evaluated period;
- model set;
- strategy set, if applicable;
- granularity: hourly or quarter-hour;
- horizon: D-only, D+4, or lead-day range;
- scenario count and scenario generation method, if applicable;
- whether common support was used;
- whether results are expected-objective outputs or realised settlement outputs.

This is a hard rule. A visually clean comparison is misleading if support differs silently.

---

## 4. Semantic colour mapping

Use colours semantically. The same concept should have the same colour throughout the project.

| Concept | Colour role | Hex |
|---|---:|---|
| Actual / realised / observed data | Charcoal | `#222222` |
| Main forecast/model/result | Deep blue | `#1F4E79` |
| Alternative model/strategy | Muted orange | `#C97941` |
| Secondary alternative | Teal | `#3A7D7C` |
| Benchmark / naive / reference | Grey | `#7A7A7A` |
| Perfect foresight / oracle upper bound | Olive grey | `#6F7D4E` |
| Price-insensitive baseline | Dark grey | `#333333` |
| Risk-neutral stochastic strategy | Deep blue | `#1F4E79` |
| CVaR-sensitive / risk-averse strategy | Muted orange | `#C97941` |
| Scenario uncertainty band | Pale blue | `#DDEAF2` |
| Warning / infeasibility / violation / shortfall | Muted red | `#B85C5C` |
| Gridlines | Light grey | `#D9D9D9` |
| Background fill | Off-white | `#FAFAF7` |
| Text / axes | Dark charcoal | `#2B2D33` |

Preferred visual encodings:

| Concept | Preferred encoding |
|---|---|
| Realised/actual price | Charcoal solid line |
| Main forecast | Deep blue solid line |
| Alternative forecast/model | Teal or muted orange line |
| Naive/reference model | Grey dashed line |
| Perfect foresight | Olive grey line or marker |
| Price-insensitive strategy | Dark grey line/bar |
| Risk-neutral stochastic strategy | Deep blue line/bar |
| CVaR-sensitive strategy | Muted orange line/bar |
| Scenario uncertainty | Pale blue shaded band |
| Violations/infeasibility | Muted red markers or shaded region |
| Zero-profit/reference line | Dark grey dashed horizontal line |
| Capacity/storage/reserve limit | Grey dashed horizontal line; muted red only if violated |

---

## 5. Figure taxonomy

The project covers a forecast-to-operation chain:

```text
forecast -> scenarios -> bid submission -> clearing -> redispatch -> settlement -> metrics
```

Figures should make the relevant part of this chain explicit.

### 5.1 Forecast and scenario figures

Use before optimisation results or when explaining input quality.

| Figure family | Purpose |
|---|---|
| Forecast vs actual | Shows deterministic forecast behaviour |
| Scenario fan vs actual | Shows uncertainty spread and undercoverage |
| Scenario coverage diagnostic | Shows P50/P90/P95 containment |
| Scenario temporal coherence | Shows whether scenarios preserve daily shape and intertemporal structure |
| Forecast operational usefulness | Shows top-k hit rate, rank correlation, and operating-window regret |

### 5.2 Bidding and clearing figures

Use once bid submission and bid clearing are implemented.

| Figure family | Purpose |
|---|---|
| Bid curve | Explains submitted willingness-to-pay |
| Acceptance heatmap | Shows which bid blocks cleared |
| Submitted vs cleared energy | Shows market procurement effect |
| Cleared vs used vs unused energy | Shows whether the plant can physically use procured electricity |
| Rejected energy timeline | Shows when forecast/scenario errors reduced procurement |

This distinction is essential. In a true bidding model, wrong forecasts can mean that bids do not clear and electricity is not received. That differs from a simple schedule-and-settle model where the plant can always buy electricity at the realised price.

### 5.3 Physical operation figures

Use to prove that the optimisation is operationally credible, not merely economically attractive.

| Figure family | Purpose |
|---|---|
| Dispatch profile | Shows electrolyser, compressor, storage, and other asset operation |
| Storage trajectory | Shows buffer feasibility and flexibility use |
| Production fulfilment | Shows whether the product target is met |
| Boundary-hit plot | Shows storage, ramping, grid, reserve, or operational limits |
| Energy balance residual plot | Debugging and validation of conservation constraints |

### 5.4 Economic and risk figures

Use for thesis comparison and model/strategy selection.

| Figure family | Purpose |
|---|---|
| Strategy comparison bar | Net profit/cost, average price, production, clearing ratio |
| Economic waterfall | Explains why one strategy performs better |
| Cumulative profit | Shows path dependency, drawdowns, and timing of value |
| Profit/cost distribution | Shows downside exposure |
| CVaR sensitivity | Shows risk-aversion trade-off |
| Risk-return frontier | Shows profit sacrificed for risk reduction |
| Value captured vs perfect foresight | Shows how much oracle value is captured |

### 5.5 Computational and reproducibility figures

Use in methods or appendix unless computational tractability is a main result.

| Figure family | Purpose |
|---|---|
| Runtime by scenario count | Tractability |
| Runtime by horizon/granularity | Hourly vs quarter-hour and D-only vs D+4 scaling |
| MIP gap by run | Solver reliability |
| Failed/infeasible run table | Transparency |
| Model size table | Variables, binaries, constraints |

---

## 6. Chart selection guide

Choose figures based on the analytical question, not based on what looks attractive.

| Analytical question | Recommended figure | Use when | Avoid / warning |
|---|---|---|---|
| How does a forecast compare with realised prices? | Actual vs forecast time-series line plot | Selected days/weeks; explaining forecast behaviour | Do not compare many models over a long period in one plot |
| How well do scenarios cover realised prices? | Scenario fan plot: actual + median + P10/P90/P95 or min/max band | Scenario calibration, undercoverage, tail behaviour | Do not show all scenarios unless scenario count is small |
| Is scenario undercoverage economically harmful? | Scatter: coverage metric vs profit/uplift/CVaR/shortfall | Linking scenario quality to optimisation performance | Do not claim undercoverage is fatal without economic evidence |
| Are scenarios temporally coherent? | Scenario spaghetti plot for selected stress days; autocorrelation/correlation heatmap | Checking path structure, D+4 coherence, quarter-hour shape realism | Avoid independent-looking hourly samples without explanation |
| Which model performs best on one metric? | Sorted bar chart with uncertainty/period labels | MAE, RMSE, profit, cost, clearing ratio, shortfall | Avoid if sample support differs across models |
| Which model performs best across many metrics? | Metric table + heatmap or small multiples | Comparing forecast, economic, risk, reliability, operational metrics | Heatmaps can hide units; normalise or clearly label |
| How does performance differ by lead day or horizon? | Line plot or grouped bar by lead_day / horizon | D-only vs D+4, lead_day 0-4 | Do not compare horizons if sample support differs silently |
| How does performance differ by granularity? | Paired comparison plot or matched-period bar chart | Hourly vs quarter-hour with same period/settings | Do not change model, period, scenario count, and granularity at once |
| How does performance differ by market regime? | Faceted bar chart, boxplot, or regime summary table | Calm, volatile, stress/crisis weeks or months | Avoid if regime definitions are subjective and undocumented |
| Are forecasts systematically biased? | Predicted vs actual scatter with 45-degree line; residual by price-bin plot | Diagnosing over/underprediction and tail bias | Not a thesis headline plot unless tied to optimisation impact |
| Which hours are selected correctly? | Top/bottom-k hit-rate bar; operating-window regret plot | Operational forecast usefulness for load shifting | Do not rely only on MAE/RMSE |
| How do submitted bids clear? | Bid acceptance heatmap by hour x bid block | Debugging bid-price grid and clearing logic | Useless before true bidding layer exists |
| How much electricity is submitted, cleared, used, rejected? | Stacked or grouped time-series / area plot | Showing market-to-physical chain | Avoid stacked bars if negative values occur |
| What does the bid curve look like? | Stepwise demand bid curve with actual price line | Explaining one representative hour/day | Avoid plotting every hour's curve in thesis body |
| Does redispatch remain physically feasible? | Multi-panel operation plot: cleared energy, used energy, electrolyser, compressor, storage | Debugging one day/week and thesis explanation | Do not overload with too many y-axes |
| Does the model meet production targets? | Daily production vs target bar/line; cumulative fulfilment plot | Reliability reporting | Never report profit without this |
| How often are constraints binding or violated? | Boundary-hit timeline + summary bar chart | Storage bounds, ramping, grid limit, reserve delivery later | Do not hide violation magnitude |
| How does profit evolve over time? | Cumulative profit/cost line plot | Strategy comparison over weeks/months | Final profit alone hides drawdowns and risk |
| What explains profit differences? | Economic waterfall or component bar chart | DA cost, H2 revenue, penalties, terminal inventory, unused energy | Stacked bars can mislead when components have mixed signs |
| What is the downside-risk distribution? | Profit/cost distribution, boxplot, ECDF, or downside-tail plot | CVaR and worst-case interpretation | Avoid violin plots for small sample counts |
| How does CVaR weight affect outcomes? | Sensitivity line plot: gamma vs profit, CVaR, production, clearing | Risk-aversion sweep | Do not choose gamma on test performance |
| What is the trade-off between profit and risk? | Risk-return scatter / Pareto frontier | Expected profit vs CVaR, worst-case, shortfall | Not useful with fewer than three alternatives |
| How close is the model to perfect foresight? | Value-captured bar chart | Comparing stochastic model to oracle and price-insensitive benchmark | Label perfect foresight explicitly as upper bound |
| How robust is the solver/model? | Runtime and MIP-gap plots; model-size table | Scaling scenario count, horizon, quarter-hour granularity | Do not omit failed/infeasible solves |
| Which result is thesis-usable? | Compact annotated summary table | Final comparison of models/strategies | Must include warnings, support, and caveats |

---

## 7. Standard figure contracts

These contracts describe recurring figures. Implement plotting functions only after the data schema has stabilised. Until then, use these contracts as reporting requirements.

### 7.1 Forecast vs actual

**Purpose:** show deterministic forecast behaviour for a selected period.

Required columns:

- `delivery_start` or equivalent timestamp;
- `y_true` or actual price;
- `y_pred` or forecast price;
- `model_name` if multiple models are shown;
- `lead_day` or horizon metadata.

Recommended encoding:

- actual: charcoal solid line;
- main forecast: deep blue solid line;
- benchmark: grey dashed line.

Use for objective weeks, stress periods, typical periods, and explanation plots.

### 7.2 Scenario fan vs actual

**Purpose:** show whether realised prices fall inside the scenario distribution.

Required columns:

- timestamp;
- actual price;
- scenario quantiles such as P05, P10, P50, P90, P95;
- scenario generation method;
- model/horizon/granularity metadata.

Recommended encoding:

- actual: charcoal solid line;
- median/P50: deep blue or slate line;
- uncertainty band: pale blue fill;
- violations/outside-band observations: muted red markers.

Avoid showing all scenario paths in thesis body unless the scenario count is small or the figure is explicitly illustrative.

### 7.3 Bid curve

**Purpose:** explain submitted willingness-to-pay for one representative hour/day.

Required columns:

- bid block or quantity segment;
- submitted quantity;
- bid price;
- realised clearing price;
- accepted/rejected status if available.

Recommended encoding:

- stepwise bid curve in blue or purple;
- realised price as charcoal vertical/horizontal reference line;
- rejected part in muted red if shown.

Use only after true bidding logic exists.

### 7.4 Submitted, cleared, used, unused, and rejected energy

**Purpose:** show the market-to-physical chain.

Required columns:

- submitted energy;
- cleared energy;
- used energy;
- unused cleared energy;
- rejected energy;
- timestamp;
- strategy/model metadata.

Recommended encoding:

- submitted energy: slate blue;
- cleared energy: deep blue;
- used energy: teal;
- unused cleared energy: muted orange;
- rejected energy: muted red.

This plot is central for diagnosing whether forecast/scenario errors cause procurement failures or unused procurement.

### 7.5 Physical operation profile

**Purpose:** verify redispatch and plant feasibility.

Required columns depend on the model, but may include:

- electrolyser power;
- compressor power;
- storage level;
- hydrogen production;
- production target;
- grid import/export;
- storage minimum, maximum, and reserve boundaries;
- violation/shortfall indicators.

Recommended format:

- use multi-panel plots with shared x-axis;
- avoid too many dual axes;
- mark boundary hits and violations explicitly.

### 7.6 Production fulfilment

**Purpose:** prevent profit-only interpretation.

Required columns:

- produced hydrogen or product output;
- target production;
- shortfall;
- cumulative production and cumulative target if relevant.

Recommended figures:

- daily production vs target;
- cumulative fulfilment plot;
- shortfall bar chart.

Never report profit without production fulfilment.

### 7.7 Economic waterfall

**Purpose:** explain profit differences.

Required components may include:

- hydrogen revenue;
- DA electricity cost;
- penalties;
- unused energy cost;
- terminal inventory value;
- imbalance/reserve/mFRR components later;
- net profit.

Use a waterfall chart when components have mixed signs. Do not casually stack positive and negative financial components.

### 7.8 CVaR sensitivity

**Purpose:** show how risk-aversion changes behaviour and outcomes.

Required columns:

- risk-aversion parameter, e.g. `gamma`;
- expected profit or realised profit;
- CVaR/downside metric;
- production fulfilment;
- clearing ratio or used/cleared ratio if relevant;
- selected validation period.

Recommended figures:

- line plot of gamma vs profit/CVaR/production/clearing ratio;
- risk-return scatter.

Do not select gamma on test-period profit. Use validation logic.

### 7.9 Solver tractability

**Purpose:** document computational feasibility and reproducibility.

Required columns:

- runtime;
- MIP gap;
- solve status;
- number of variables;
- number of binary variables;
- number of constraints;
- scenario count;
- horizon;
- granularity.

Recommended figures:

- runtime vs scenario count;
- MIP gap by run;
- model-size table;
- failed/infeasible solve table.

Do not omit failed or infeasible solves.

---

## 8. Project-specific reporting rules

### 8.1 Forecast evaluation

Always report both conventional and operational forecast metrics.

Minimum conventional metrics:

- MAE;
- RMSE;
- bias / mean error;
- p90/p95 absolute error;
- rMAE if and only if numerator and denominator are computed on identical common-support timestamps.

Minimum operational metrics:

- top/bottom-k hit rate;
- daily Spearman rank correlation;
- operating-window regret;
- tail MAE by actual price regime;
- high-low daily spread error where relevant.

Do not select a model based only on MAE/RMSE if the downstream optimisation depends on price ordering, cheap-hour selection, or tail behaviour.

### 8.2 Scenario evaluation

Distinguish point forecast quality from scenario calibration.

Recommended plots:

- actual price path with P10/P50/P90 or P05/P50/P95 scenario bands;
- coverage by model, horizon, and granularity;
- scenario spread versus realised volatility;
- tail coverage for high-price and low-price periods;
- scenario fan charts for objective weeks;
- scenario temporal coherence checks for D+4 and quarter-hour settings.

Do not claim scenario undercoverage is fatal unless linked to economic or operational outcomes such as lower profit, higher shortfall, lower clearing ratio, or worse CVaR.

### 8.3 Hydrogen test case and bidding evaluation

Report economic performance and operational behaviour together.

Minimum tables:

- produced hydrogen;
- production target and shortfall;
- electricity consumption;
- average electricity price;
- submitted, cleared, used, unused, and rejected energy;
- revenue;
- electricity cost;
- penalties, if any;
- net profit;
- profit margin;
- CVaR/downside-risk metric;
- infeasible/violating periods, if applicable.

Recommended plots:

- cumulative profit over time by strategy/model;
- hydrogen production over time;
- production vs target;
- bid curve for representative hours/days;
- bid acceptance heatmap;
- submitted/cleared/used/rejected energy timeline;
- electricity consumption schedule overlaid with realised DA price;
- storage trajectory with boundaries;
- profit distribution by scenario or test period;
- CVaR sensitivity plot;
- profit-risk scatter plot;
- value captured vs perfect foresight.

Never report profit without production fulfilment. A high-profit strategy that misses hydrogen production targets is not necessarily better.

### 8.4 Realised settlement

Never show only the expected optimisation objective once realised market outcomes are available.

Report the distinction between:

- expected objective value;
- submitted bids;
- cleared bids;
- realised redispatch;
- realised settlement cost/revenue;
- penalties and shortfalls;
- final realised profit.

Expected performance is not the same as realised performance.

### 8.5 Hourly vs quarter-hour comparison

Never compare hourly and quarter-hour results while changing other assumptions unnecessarily.

When comparing granularity, keep constant as much as possible:

- model family;
- plant parameters;
- scenario count;
- scenario generation method;
- period;
- CVaR settings;
- bidding/settlement rules;
- support window.

Use matched-period comparisons where possible. State when exact matching is impossible.

### 8.6 D-only vs D+4 comparison

Do not mix lead days in headline plots unless the figure explicitly studies horizon effects.

Recommended structure:

- report D-only separately;
- report D+4 or lead_day 4 separately;
- use lead-day plots for horizon behaviour;
- use common-support checks when comparing models.

### 8.7 Future mFRR or additional market layers

When mFRR or other market layers are added, extend this policy rather than creating separate inconsistent plot rules.

Additional reporting should distinguish:

- DA procurement;
- reserve capacity commitment;
- activation or non-activation;
- non-delivery penalties;
- opportunity costs;
- physical feasibility under reserve constraints.

---

## 9. Thesis body vs appendix

### 9.1 Thesis body figures

Thesis body figures should be few, clear, and interpretation-oriented.

Prefer:

- compact summary tables;
- actual vs forecast/scenario examples for objective weeks;
- cumulative profit by main strategy;
- production fulfilment;
- value captured vs perfect foresight;
- profit-risk trade-off;
- one or two representative operational dispatch plots.

Avoid:

- excessive diagnostics;
- many almost-identical model comparison plots;
- plots with too many lines;
- figures that require lengthy debugging context.

### 9.2 Appendix figures

Appendix figures can include detailed diagnostics:

- all objective week plots;
- full metric heatmaps;
- scenario coverage by horizon/model/granularity;
- solver runtime and MIP gap;
- infeasible/failed solve tables;
- energy balance residual checks;
- detailed distributional plots;
- sensitivity sweeps.

Appendix figures still need captions, units, and support metadata.

---

## 10. Anti-patterns

Avoid the following:

1. Reporting profit without production fulfilment.
2. Reporting expected objective value without realised settlement.
3. Comparing models without stating common support or support mismatch.
4. Comparing hourly and quarter-hour results while also changing period, model, scenario count, or CVaR settings.
5. Using default Excel, Matplotlib, Pandas, or Seaborn colour cycles.
6. Using too many colours where line style or panels would be clearer.
7. Using dual axes when separate panels would be more readable.
8. Hiding infeasibility, shortfall, penalties, or failed solves.
9. Using stacked bars for mixed-sign financial components when a waterfall is more appropriate.
10. Showing too many individual scenario paths in thesis figures.
11. Selecting a CVaR weight based on test-period profit.
12. Treating perfect foresight as a realistic strategy rather than an upper bound.
13. Treating price-insensitive operation as a poor model rather than a baseline.
14. Hiding whether results are based on submitted, cleared, used, or settled energy.
15. Making visually attractive plots that obscure methodological weaknesses.

---

## 11. Python usage

In notebooks and reporting scripts, use the shared style module:

```python
from src.reporting.visual_style import (
    COLORS,
    MODEL_COLORS,
    STRATEGY_COLORS,
    MARKET_CHAIN_COLORS,
    apply_visual_style,
    save_figure,
)

apply_visual_style()
```

When a recurring plot type stabilises, create a plotting helper function in the relevant reporting module. Do not put chart-selection logic inside `visual_style.py`; it should remain a style module.

---

## 12. Minimum review checklist before accepting a figure

Before accepting a plot into a notebook, report, or thesis draft, check:

- Does the figure answer a clear analytical question?
- Are units shown?
- Are model and strategy names human-readable?
- Is the evaluated period stated?
- Is the horizon/granularity stated?
- Is common support stated when comparing models?
- Are colours semantically consistent with this policy?
- Are infeasibilities, shortfalls, violations, and penalties visible?
- Is production fulfilment shown when profit is shown?
- Is realised settlement shown when bidding/clearing is evaluated?
- Would the plot still be understandable in grayscale or with limited colour perception?
- Is this figure thesis-body material, or should it be appendix-only?
