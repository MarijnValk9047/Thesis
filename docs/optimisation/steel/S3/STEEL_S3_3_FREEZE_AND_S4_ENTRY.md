# S3.3 Freeze and S4 Entry

Status: S3.3 frozen with limitations after S3.3j.

## Freeze Statement

S3.3 is frozen as the deterministic static energy, WAG, emissions and boundary-aligned validation baseline for S4 entry.

The freeze is limited to:

- C0 calibrated regression status;
- C1 boundary-aligned contextual validation status;
- accepted broader C1 utility-boundary interpretation;
- provisional-source-supported combined 6 PJ/y utility steam/gas sink;
- explicit caveats for the 3/3 PJ internal split, downstream/light-side bucket, pelletizing value and Vattenfall interface abstraction.

The freeze is not:

- strict independent C1 validation;
- approved-input promotion;
- a measured Tata utility-dispatch claim;
- S4 executable logic.

## Final Accepted Case

The S4 entry baseline is confirmed from S3.3h case `S33H_B_004`.

Accepted assumptions:

- BF-BOF share: 0.5033645161290323;
- combined C1 utility steam/gas sink: 6 PJ/y;
- internal split: 3 PJ/y NG and 3 PJ/y WAG;
- downstream electricity scale: 0.875;
- residual auxiliary electricity scale: 3.85;
- WAG-to-power efficiency: 0.3715;
- WAG LHV scale: 1.0.

Guardrails:

- no residual C1 NG closure;
- no inherited C0 residual NG used as C1 fit;
- no arbitrary WAG availability correction;
- no Table 9 back-calculated correction factor;
- no DA, stochastic, CVaR, mFRR, settlement or market logic.

## Final Validation Summary

C0 remains within calibration tolerance:

- gross electricity error: -3.5722%;
- WAG electricity error: +3.5286%;
- natural gas error: -0.0001%;
- direct CO2 error: -0.0000%;
- primary proxy error: -0.0540%.

C1 is boundary-aligned contextual validation:

- gross electricity error: +6.1159%;
- WAG electricity error: -2.0489%;
- natural gas error: -4.4822%;
- direct CO2 error: +6.9019%;
- primary proxy error: +2.0140%;
- mean absolute error: 4.3126%;
- maximum absolute error: 6.9019%.

All principal C1 targets are within 10%, but not within 5%.

## S4 Entry

S4 may start only after a short physical guardrail hardening gate. This gate may be labelled `S3.4` or `S4.0a`; in either case it sits between frozen S3.3j and deterministic hourly DA price-taking.

Allowed first step:

- `S3.4/S4.0a` physical flexibility guardrails and constraint evidence audit;
- explicit capacity, finite storage, terminal inventory, WAG, grid, utility-balance, ramp and minimum-load checks where evidence or governed assumption ranges exist;
- `S4.0b` static-price or zero-price regression back to S3.3j behaviour after guardrails;
- `S4.1` hourly deterministic DA price exposure only after guardrails and regression pass;
- 24 h and 168 h deterministic smokes once DA prices are activated;
- compact governed run folders once implementation runs begin.

Blocked until later gates:

- stochastic optimisation;
- CVaR;
- mFRR;
- quarter-hour market layer;
- settlement and bidding;
- product-revenue objective;
- detailed EAF heat sequencing, sub-hour modulation and binary commitment logic beyond the reviewed hourly semi-continuous EAF guardrail;
- perfect-foresight except later as oracle benchmark.

The S4 implementation must preserve the S3.3 material and energy physics, terminal inventory rules, WAG guardrails and boundary caveats. DA price response may not run if guardrail checks fail, and infeasibility must be diagnosed with named constraints or IIS where available rather than hidden behind unreported slack.

The S3.4/S4.0a EAF guardrail may use an hourly semi-continuous binary on/off abstraction with bounded on-state operation. Heat-cycle constants from generic scrap-EAF evidence remain registered for later sensitivity and must not enter the first executable hourly base case.
