# S3.3j Boundary Acceptance, Final Validation and S4 Entry

Status: S3.3 close-out and S4 entry plan. This document does not implement S4 logic.

## Decision

S3.3 is frozen with limitations. The accepted validation status is boundary-aligned contextual validation, not strict independent validation.

C0 remains calibrated. The final C1 boundary-aligned case is confirmed from the governed S3.3h accepted Block B artifact `S33H_B_004`. S3.3j does not rerun calibration and does not create a run folder.

## Boundary Acceptance

The broader C1 utility boundary is accepted as a model-boundary choice. The accepted evidence basis is the user-provided external evidence summary plus the existing S3.3i and research-memo source surface:

- Tata IJmuiden public evidence supports an internal Energiebedrijf, multiple large steam boilers, BFG/COG/BOFG/NG gas networks and Vattenfall IJM-01/VN24/VN25 interface use of Tata residual gases.
- Public evidence supports a utility scale with about 54 PJ/y WAG reused for electricity or heat/steam, about 13 PJ/y reference natural gas, large boiler capacity, K15/K16 mixed-gas boiler evidence and Heracless WAG-to-steam plus Vattenfall NG supplementation context.
- Public evidence does not directly report exact 3 PJ/y boiler NG, exact 3 PJ/y boiler WAG or exact Vattenfall WAG fraction 1.0.

Therefore:

- combined 6 PJ/y C1 utility steam/gas sink is accepted as provisional-source-supported;
- internal 3 PJ/y NG and 3 PJ/y WAG split is a modelling allocation placeholder;
- Vattenfall is represented as a gas-mixture/interface abstraction, not a literal public WAG fraction;
- the S3.3h HSM implementation slot is relabelled as broader downstream/light-side process heat and must not be called HSM-only;
- pelletizing 2.26008 PJ/y remains unresolved as a firm current-state pelletizing NG value.

## Final Case

Final accepted case:

- source case: `S33H_B_004`;
- C1 configuration: `C1_phase1_hybrid_BF_BOF_NG_DRP_EAF`;
- C0 regression configuration: `C0_current_BF_BOF_reference`;
- BF-BOF share: 0.5033645161290323;
- combined C1 utility steam/gas sink: 6 PJ/y;
- internal split: 3 PJ/y NG and 3 PJ/y WAG;
- downstream electricity scale: 0.875;
- residual auxiliary electricity scale: 3.85;
- WAG-to-power efficiency: 0.3715;
- WAG LHV scale: 1.0.

No residual C1 gas closure is used. No inherited C0 residual NG is used as a C1 fit term. No arbitrary WAG availability cap is used. Approved-input shells are not populated.

## Final Metrics

### C0 Regression

| Metric | Error |
| --- | ---: |
| gross electricity | -3.5722% |
| WAG electricity | +3.5286% |
| natural gas | -0.0001% |
| direct CO2 | -0.0000% |
| primary proxy | -0.0540% |

C0 mean absolute error is 1.4310%. C0 maximum absolute error is 3.5722%. C0 remains within calibration tolerance.

### C1 Boundary-Aligned Contextual Validation

| Metric | Error |
| --- | ---: |
| gross electricity | +6.1159% |
| WAG electricity | -2.0489% |
| natural gas | -4.4822% |
| direct CO2 | +6.9019% |
| primary proxy | +2.0140% |

C1 mean absolute error is 4.3126%. C1 maximum absolute error is 6.9019%. All principal C1 targets are within 10%, but not within 5%.

Remaining C1 gaps:

- natural gas shortfall: 6,798.298 m3/h;
- WAG electricity deficit: 0.025202 TWh/y;
- gross electricity surplus: 0.299065 TWh/y.

Carrier-share errors:

- coal share: -2.0763%;
- electricity share: +4.1783%;
- natural gas share: +0.2668%.

Solver status is `ok`; termination is `optimal`; solver is `appsi_highs`. Runtime is 2.479748 s for C0 and 2.049687 s for C1.

Maximum reported balance residual is 1.3642420526593924e-12 across the final C0/C1 artifacts. Cold, hot and reheated terminal residuals are zero.

## Freeze Decision

S3.3 freezes with limitations because:

1. C0 remains within calibration tolerance.
2. C1 boundary-aligned case remains within contextual validation tolerance.
3. No residual C1 gap closure is used.
4. No inherited C0 residual NG is used as C1 fit.
5. No arbitrary WAG availability factor is used.
6. Combined 6 PJ/y utility sink is recorded as provisional-source-supported, not an exact Tata measurement.
7. The 3/3 PJ split is recorded as a modelling allocation placeholder.
8. HSM, pelletizing and Vattenfall values are not overclaimed.
9. Balance and terminal residuals pass.
10. No S4 executable logic is introduced.

S3.3j does not convert candidate or provisional assumptions into approved-input tables.

## S4 Entry Plan

### Revised Stage Order

S3.3j remains the frozen static calibrated and boundary-aligned public process-network model. It is not strict independent C1 validation and not a Tata digital twin.

Before deterministic DA price-taking, insert a short physical guardrail hardening stage:

1. `S3.4/S4.0a`: physical flexibility guardrails and constraint evidence audit.
2. `S4.0b`: static-price or zero-price regression after guardrails.
3. `S4.1`: deterministic hourly DA price-taking dispatch.
4. `S4.2`: realised-price cost reporting and careful benchmarks.
5. `S5+`: bidding, clearing, full settlement, stochastic scenarios, mFRR, quarter-hour, `D_plus_4`, CVaR and detailed EAF heat sequencing remain later.

### S3.4/S4.0a Physical Guardrails

Physical hardening is required before DA price response because missing capacity, storage, WAG, grid, ramp or minimum-load limits can create artificial economic flexibility. S4 must not claim price responsiveness from constraints that were absent rather than from real operational degrees of freedom.

Immediate guardrails:

- explicit max capacity for every active process;
- finite storage or buffer capacity for every active store;
- terminal inventory rules for all intertemporal material buffers;
- bounded or deliberately disabled grid import/export;
- explicit WAG allocation, flare or spill variables and balance closure;
- closed electricity, NG, WAG and steam/boiler balances where represented;
- ramp limits for DRP, EAF-equivalent, caster, reheating, HSM, boilers and major utility assets where evidence or governed assumption ranges exist;
- minimum stable load for BF, DRP, EAF-equivalent, caster, HSM and boilers where defensible;
- reporting of ramp hits, capacity hits, buffer hits, WAG flaring, grid peaks, terminal residuals and balance residuals.

Deferred or sensitivity-only constraints:

- minimum up/down time;
- startup and shutdown logic;
- detailed EAF heat sequencing beyond the hourly semi-continuous guardrail;
- minimum time between heats;
- intra-heat EAF power modulation;
- campaign or sequence constraints for casting and rolling;
- detailed quality compatibility constraints.

Initial S4 should remain mostly continuous/LP where possible, with one explicit exception now prepared for review: the base EAF guardrail may be an hourly semi-continuous binary on/off abstraction with bounded on-state operation. This prevents a fake smooth EAF dimmer while still deferring heat-level scheduling, minimum time between heats, sub-hour modulation and detailed restart logic.

For EAF/DRP guardrails, `STEEL-SC-0021` is the closest Tata-IJmuiden-inspired process-network precedent. `S3_4_GUARDRAIL_BADARINATH_2025` supports the semi-continuous formulation and DRI-buffer decoupling. `S3_4_GUARDRAIL_PAULUS_BORGGREFE_2011` is generic scrap-EAF DSM evidence for later sensitivity only. Do not mix the Athanasiadis 0.5 MWh/t DRI value with the Paulus and Borggrefe 0.525 MWh/t steel value without explicit basis conversion.

The source-card audit for this gate is recorded in `data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review/s3_4_s4_0a_physical_guardrail_source_audit.csv`. It identifies existing local evidence and the highest-priority deepsearch gaps without promoting candidate rows into approved Tata-specific operating truth.

### S4.0b Regression Gate

After guardrails are added, run static-price or zero-price regression before DA prices. The hardened model should reproduce S3.3j static behaviour within tolerance, or every deviation must be explained as a physical-hardening consequence.

The first concrete runner for this gate is `scripts/Data/04_Steel_Test_Case/run_s4_0b_guardrail_regression.py`. It runs the C1 DRP/EAF S3.4 guardrail wrapper without DA prices and writes `data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review/s4_0b_guardrail_regression_report.json` plus a CSV companion. This is a development-only future-route guardrail regression; C0 remains the frozen S3.3j baseline and heat-cycle details remain deferred.

Required failsafes before DA:

- active assets have explicit max capacity;
- storage variables have finite upper bounds;
- intertemporal buffers have terminal rules;
- WAG balances close;
- flare or spill is explicit and reported;
- grid import/export is bounded or deliberately disabled;
- S4 DA modes may not run unless guardrail checks pass;
- no quarter-hour, stochastic, CVaR, mFRR, bidding, clearing or product-revenue fields are active in S4;
- infeasibility is diagnosed with named constraints and IIS where available, not hidden by unreported slack.

### S4.1 Deterministic DA Scope

Start deterministic hourly DA price exposure only after `S3.4/S4.0a` and `S4.0b` pass:

- deterministic hourly DA price-taking exposure;
- no stochastic optimisation;
- no CVaR;
- no mFRR;
- no quarter-hour mode;
- no bidding or clearing;
- no product-revenue objective;
- no full settlement layer until deterministic dispatch is stable.

The first S4.1 development runner is `scripts/Data/04_Steel_Test_Case/run_s4_1_da_price_taking.py`. It uses `data/01_cleaned/Day_ahead_prices/DA_prices/hourly/da_prices_NL_hourly.csv` directly, with a fixed complete UTC window from `2022-01-02T00:00:00Z` to `2022-01-03T00:00:00Z`. Its config and compact reports are stored under `data/03_Optimisation/inputs/assets/steel/S4/s4_1_da_price_taking/`, not under S3 candidate review.

### S4.1 Required Inputs

Required inputs before S4 runs:

- DA price series;
- internal electricity balance;
- grid import/export treatment;
- WAG electricity valuation convention;
- natural-gas price;
- CO2/ETS gross-cost treatment;
- product fulfilment policy;
- rolling-horizon policy.

Every volatile price input must carry source, timestamp and scenario tags.

For the first S4.1 development runner, only the real DAM price series and DRP/EAF diagnostic electricity quantities are active. Full-site electricity balance, gas prices, CO2, WAG valuation, grid import/export and rolling-horizon logic remain later extensions and must not be inferred from this first result.

### S4.1 Model Changes

S4.1 should extend the objective from static cost to time-varying exogenous DA electricity cost while keeping the hardened material and energy physics unchanged. Terminal inventory rules must be preserved. Free storage, free WAG arbitrage and unbounded grid response remain blocked. Model stats and solver diagnostics must be exposed.

### S4.1 Verification

Required checks:

- zero-price or static-price regression reproduces S3.3 static behaviour;
- deterministic DA smoke tests for 24 h and 168 h;
- infeasibility tests;
- WAG flaring and import/export sanity checks;
- terminal inventory checks;
- guardrail-hit reporting.

### S4.2 Outputs

When S4 runs begin, use compact governed run folders only. Do not write root-level outputs. Record solver status, runtime, gap, model size, energy cost, grid import/export, gas use, WAG allocation, emissions cost and production fulfilment.

### S4.2 Stage Gates

Proceed only after physical guardrails, static-price regression, and deterministic DA-only C0/C1 checks pass. Define the price-insensitive benchmark before richer market comparisons. Perfect foresight remains an oracle or upper-bound benchmark, not a realistic operating strategy. Stochastic, quarter-hour, mFRR, bidding, clearing, product revenue and CVaR remain blocked until deterministic hourly DA is stable.

## Remaining Limitations

The freeze is not a claim of exact Tata utility dispatch. The combined utility sink is provisional, the 3/3 split is placeholder, Vattenfall allocation is unresolved and the downstream/light-side process-heat bucket remains aggregated. Direct CO2 remains the largest C1 error.
