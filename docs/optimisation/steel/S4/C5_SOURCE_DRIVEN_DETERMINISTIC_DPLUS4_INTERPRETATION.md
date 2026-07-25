# Source-Driven Deterministic D-D+4 Interpretation

## Decision

The frozen source-driven C0/C1 model is suitable for a bounded thesis
interpretation of deterministic D-D+4 operational response. It demonstrates
physically feasible forecast-responsive operation on the selected support, but
it does not establish an economic-uplift estimate, a full-year empirical result,
an exact Tata Steel IJmuiden representation, or an independently calibrated
digital twin.

The central result is structural rather than financial:

- C0 responds mainly by substituting selectively timed grid imports for
  WAG-derived internal generation; it shows no material expensive-to-cheap load
  shift under the reported definition.
- C1 combines generator response with DRP/EAF and inventory-mediated demand
  timing. This shifts about 11 GWh/y on the representative-period-annualised
  basis from expensive to cheaper hours in both splits.
- The whole-period procurement-cost differences cannot be interpreted as
  savings, forecast value, or forecast harm because terminal inventories differ
  and no terminal-inventory value bridge exists.

## Evidence basis

The evidence is the immutable source-driven baseline in run
`steel_c5_source_emulation_validation_v1_20260721`:

- four development/validation and four held-out/test representative periods;
- 168 or 169 executed hours per period, with weights normalised separately
  within each split;
- C0 and C1 under price-insensitive operation, governed `y_pred`, and a
  separately labelled rolling `y_true` sensitivity;
- 24 cases, 336 optimal rolling replans, and 736 of 736 physical guardrails
  passed;
- fixed model logic and physical parameters across strategies;
- only `y_pred` available to the governed operational strategy.

All weighted quantities below are `representative_period_annualised`. They are
not observations from a complete year. The validation and held-out splits are
kept separate; their weights must never be pooled.

## Governed `y_pred` result

| Split | Configuration | Gross electricity (TWh/y) | Internal WAG electricity (TWh/y) | Grid import (TWh/y) | Named NG (TWh-LHV/y) | Expensive-to-cheap shift vs flat (GWh/y) | `y_pred - flat` cost arithmetic (EURm/y) |
|---|---|---:|---:|---:|---:|---:|---:|
| Validation | C0 | 2.18100 | 2.12858 | 0.05242 | 0 | 0.000 | -2.454 |
| Held-out | C0 | 2.18288 | 2.14742 | 0.03546 | 0 | 0.000 | -0.505 |
| Validation | C1 | 3.44172 | 0.65171 | 2.79001 | 8.18946 | 10.962 | +63.612 |
| Held-out | C1 | 3.44370 | 0.69589 | 2.74781 | 8.28557 | 11.822 | +46.542 |

The last column is arithmetic before terminal-inventory valuation. Its sign is
not an economic conclusion.

Both configurations produce exactly 6.75 Mt/y final product on the annualised
basis in every strategy and split. Residual electricity and NG remain zero as
model inputs, carrier-specific WAG balances close, and export remains disabled.

## C0 interpretation: supply substitution, not load shifting

Relative to price-insensitive operation, governed C0 adds 52.424 GWh/y of grid
imports in validation and 35.461 GWh/y held out. Internal WAG electricity falls
by 54.403 and 35.603 GWh/y respectively. The expensive-to-cheap load-shift
metric remains zero.

This means the observable C0 response should be described as a bounded
generation-substitution mechanism: the model reduces internal WAG-fired power
and imports electricity in selected favourable hours while maintaining the
production target. It is not evidence that the largely continuous BF-BOF route
itself shifts substantial electrical load. The result is also conditional on
the development VN25 abstraction, whose omitted minimum-load, commitment,
ramping, outage, and CHP/steam constraints make it an upper-bound flexibility
representation.

## C1 interpretation: material-buffered demand response

Governed C1 shifts 10.962 GWh/y in validation and 11.822 GWh/y held out from
expensive to cheaper hours. Gross electricity is about 3.44 TWh/y, of which
about 2.75-2.79 TWh/y is imported. The similar qualitative response in the two
separate splits supports a bounded behavioural conclusion: adding the DRP/EAF
route and represented buffers creates materially more demand-timing freedom
than the C0 route.

The response is not a pure same-output energy reshuffle. Compared with flat
operation, governed C1 produces about 0.233 Mt/y more DRI in validation and
0.228 Mt/y more held out, while final product stays fixed. It ends with a
weighted 4.340 kt and 4.189 kt more DRI inventory, respectively, plus about
0.55-0.63 kt more cold slab. These different terminal states explain why the
whole-period cost arithmetic cannot rank the strategies economically.

The positive C1 cost arithmetic therefore must not be called adverse forecast
value. It combines dispatch, route timing, procurement, and unvalued
work-in-progress differences. Conversely, the negative C0 arithmetic must not
be called savings.

## Forecast-information interpretation

The separately labelled rolling `y_true` sensitivity weakly dominates governed
`y_pred` in all 16 identical-initial-state first-planning-window comparisons.
The split-weighted first-window gaps are approximately EUR 18.2 thousand for C0
and EUR 53.8 thousand for C1 in validation, and EUR 3.1 thousand for C0 and
EUR 147.6 thousand for C1 held out.

This is the only admissible upper-bound comparison. It shows that perfect
knowledge of realised prices could improve the first 120-hour planning decision
from the same state, especially for the more electrically exposed C1 route. It
does not make rolling `y_true` deployable, does not turn it into a global-week
perfect-foresight bound, and does not quantify whole-period forecast value.

## External-evidence interpretation

The source comparison is mixed but usable as behavioural context:

- HSM-over-DSP activity and EAF high-price curtailment align directionally with
  the Badarinath precedent.
- BF6-over-BF7 preference and the reported DRI-storage relationship do not
  align.
- Compatible oxygen-buffer and BF6-capacity evidence are unavailable.
- Athanasiadis WAG electricity remains comparable only after a boundary bridge;
  the C0 and C1 residuals remain -0.80004 TWh/y (-26.82%) and -0.69028 TWh/y
  (-51.55%).
- MER C1 DRI output of 2.72860 Mt/y versus 2.8 Mt/y is only a
  scenario-definition consistency check because the 2.8/3.3 ratio defines the
  active HDRI coefficient. It is not independent validation.

Across both splits the Badarinath checks comprise four directionally aligned,
four partially aligned, four not aligned, and four evidence-missing outcomes.
There are zero strict independent quantitative MER validation families.
Accordingly, the model is a public-source, Tata-inspired operational test bed,
not a validated site replica.

## Reporting correction

During this interpretation, a reporting-only unit defect was found in the
compact period summary. `represented_ng_pj_y` had been divided by 0.0036, which
converts PJ to GWh, while the output column is named `named_ng_mwh_lhv_y`. The
factor is now 0.0000036 PJ/MWh. The aggregate-only revision corrects the compact
summary and derived named-NG comparisons; it does not change cached cases,
physical ledgers, model logic, parameters, or solver results. The corrected
held-out C1 value is 8,285,566 MWh-LHV/y, or 8.28557 TWh-LHV/y.

## Thesis-ready conclusion

> On eight frozen representative periods, a source-governed deterministic
> D-D+4 forecast can drive physically feasible C0 and C1 rolling operation while
> preserving annualised production. C0 flexibility is expressed mainly through
> substitution between internal WAG-derived generation and selectively timed
> grid import. C1 additionally shifts approximately 11 GWh/y on the
> representative-period-annualised basis from expensive to cheaper hours through
> DRP/EAF and material-buffer timing. This establishes a bounded operational
> response mechanism, not an economic value estimate: terminal inventories differ
> across strategies, temporal coverage is representative rather than annual, and
> independent quantitative site validation is absent.

## Claim boundary and next work

This interpretation closes the permitted deterministic response-analysis gate.
The result may be integrated into the thesis methods, results, and limitations
sections with the labels above. It does not authorise DA bidding, settlement,
export revenue, ETS, stochasticity, CVaR, mFRR, further calibration, or an exact
Tata claim.

Before any future calibrated-emulation or whole-period economic-uplift claim,
the model needs source-backed PeFa consumption coupling, a fired-pellet inventory
identity, terminal-use reconciliation, and a terminal-inventory value bridge.
Genuinely independent validation evidence must then be requalified.

## Governed evidence files

- [Run README](../../../../data/03_Optimisation/runs/steel_c5_source_emulation_validation_v1_20260721/README.md)
- [Run summary](../../../../data/03_Optimisation/runs/steel_c5_source_emulation_validation_v1_20260721/run_summary.json)
- [Period-strategy summary](../../../../data/03_Optimisation/runs/steel_c5_source_emulation_validation_v1_20260721/period_strategy_summary.csv)
- [Strategy comparisons](../../../../data/03_Optimisation/runs/steel_c5_source_emulation_validation_v1_20260721/strategy_comparison.csv)
- [Terminal-inventory comparisons](../../../../data/03_Optimisation/runs/steel_c5_source_emulation_validation_v1_20260721/terminal_inventory_comparison.csv)
- [Behavioural comparisons](../../../../data/03_Optimisation/runs/steel_c5_source_emulation_validation_v1_20260721/behavioural_comparison.csv)
