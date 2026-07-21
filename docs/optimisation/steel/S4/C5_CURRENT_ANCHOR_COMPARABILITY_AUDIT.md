# C5 Current C1 Anchor Comparability Audit

## Purpose

This audit records what the current exact-quota C1 physical run can and cannot
compare to annual anchors. It is a boundary audit, not a parameter-tuning
exercise. The source run is `steel_c1_6_75_wag_generator_boundary_correction_v1`:
it is optimal, produces 6.75 Mt/y final-product proxy, and has no failed
physical guardrails.

The canonical anchor register contains 53 rows: 26 C1, 21 C0, and six
both/generic rows. The current run maps ten C1 rows directly. It does not make
an unsupported comparison merely because an anchor exists in the register.

## Current score eligibility

| Current C1 anchor | Result | Comparability decision | Score status |
|---|---:|---|---|
| Final-product target | 6.75 / 6.75 Mt/y | Same active proxy and boundary | Eligible; within 5% |
| WAG to generators plus flare | 9.861 / 10.6 PJ/y | Same carrier-specific WAG subtotal | Eligible; -6.97%, within 10% review |
| Generator flare | 0.0 / 0.1 PJ/y | Same physical carrier ledger but very small annual value | Eligible only as a supporting diagnostic; do not create flare |
| Generator total incl. VN25 NG | 14.6 PJ/y anchor | Model has no hourly VN25-NG driver | Not comparable |
| Gross electricity | 3.584 / 4.89--4.94 TWh/y | Partial model boundary versus site/model-precedent total | Not scoreable |
| Net grid import | 2.567 / 3.25 TWh/y | Partial site-meter boundary | Not scoreable |
| WAG generator electricity | 1.018 / 1.23 TWh/y | Athanasiadis generator/denominator convention unresolved | Not scoreable |
| CO2 | 4.561 / 8.3--9.11 MtCO2/y | Mode-B WAG subtotal versus site/model total | Not scoreable |

The comparable generator-WAG subtotal deliberately excludes the 4.1 PJ/y
named VN25 NG embedded in the MER 14.6-PJ/y total. Treating that total as WAG
previously created an artificial generator-fuel gap.

## Boundary findings

### Electricity is the main remaining site-boundary gap

The current gross-electricity gap is 1.31--1.36 TWh/y relative to the
Athanasiadis and official C1 contexts. Existing bounded non-WAG candidates
could add at most about 0.403 TWh/y in total:

- higher HSM rolling electricity: 0.196 TWh/y;
- EAF secondary metallurgy: 0.104 TWh/y;
- DSP high proxy: 0.072 TWh/y;
- KGF gross-service difference: 0.031 TWh/y.

They cannot safely all be activated together and still leave roughly 0.9--1.0
TWh/y of unrepresented site electricity. This is evidence of a real remaining
site/background boundary, not permission to create a residual model load.

### WAG fuel is materially more closed than WAG electricity

The annual carrier ledger shows 15.02 PJ/y BFG, 8.82 PJ/y COG and 2.44 PJ/y
BOFG generated. Their mandatory/process, HSM/PEFA, boiler and generator uses
close carrier by carrier. The total generator-WAG-plus-flare comparison is
within 10%, although the individual mix differs: BFG is -8.4%, BOFG is
+17.5%, and COG is -0.1 PJ/y against a very small 0.1-PJ/y context.

This does not justify moving COG from an existing KGF/HSM sink to generators:
the annual table is a validation context, not an hourly gas-mix target. The
remaining WAG-electricity difference may arise from a generator electricity
conversion, named generator NG, or Athanasiadis boundary convention; none is
safe to tune from the current evidence.

### NG needs a component-to-site bridge, not an allocation rule

Current outputs retain DRP/EAF NG, controller NG and full-site residual NG as
separate quantities. The C1 full-site-NG anchor cannot be scored until all
named consumers use a coherent energy basis and the source locator/boundary is
confirmed. The 4.1-PJ/y VN25 NG table value remains a named annual context,
not an input that may be injected to close a generator or electricity gap.

### CO2 has a coverage boundary rather than a numerical correction problem

The exact run's 4.561 MtCO2/y is WAG combustion at represented sinks. The
separate C5p_v ledger can report named modelled NG oxidation, but it is not a
license to combine Mode-B WAG, aggregate process counters, capture streams and
site Scope 1 into one total. The remaining Scope-1 difference therefore
measures unrepresented coverage and accounting mode, not a calibrated factor
gap.

### Downstream and C0 anchors require separate runs

The active C1 final-product proxy is intentionally not the same denominator as
the HSM/DSP public output anchors: imported slab and route-specific downstream
output remain explicit boundary questions. C0 has its own topology and no
current equivalent exact-quota run in this audit. It must not be inferred from
the C1 result.

## Priority order

1. Keep the generator-WAG correction frozen: it is the strongest comparable
   annual energy result and needs no physical retuning.
2. Complete an explicit non-WAG electricity bucket/decomposition audit. Report
   any residual site electricity, but never use it as a load or calibration
   variable.
3. Export a coherent named-NG component ledger on a common LHV basis and
   compare only its source-backed components before using full-site NG as a
   residual KPI.
4. Keep C5p_v explicit-fuel CO2 and aggregate process/capture diagnostics
   separate; do not seek Scope-1 proximity with a mixed ledger.
5. Only then revisit plant-level HSM/DSP/final-product denominator and slab
   import conventions. C0 requires a separate configuration-matched audit.

## Outputs and gate

The reproducible machine-readable audit is in
`data/03_Optimisation/runs/steel_c1_annual_anchor_comparability_audit_v1/`.
Its `annual_anchor_reconciliation.csv` records numerator, denominator,
boundary and scoring eligibility per compared row.

- Annual anchor reporting: GO.
- WAG carrier reconciliation: GO, diagnostic-only.
- Annual anchor tuning, full-site electricity/NG/CO2 claims, economics and DA:
  NO-GO.
