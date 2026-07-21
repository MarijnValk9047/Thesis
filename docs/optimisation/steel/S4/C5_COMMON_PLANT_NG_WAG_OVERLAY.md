# C5 Common-Plant NG/WAG Overlay

This report is a diagnostic-only C5p_k overlay. It explains why C0 modelled NG was previously zero: current C5 explicit NG counts only represented NG consumers inside the executable/diagnostic boundary, not full-site residual gas use.

No executable development inputs, model equations, objective terms, residual load variables, CO2 objective terms, economics, DA bidding logic, or source cards are changed by this stage.

## Scope

Common C0/C1 fuel-using plants included: HSM/WBW, KGF/coking.
C1-only/new assets excluded from C0 replication: DRP, EAF.

No explicit common-plant WAG/NG ratio was found in the current candidate/register artifacts. The overlay therefore uses a labelled WAG-priority residual fallback: existing post-steam residual WAG is allocated first, and any remaining candidate fuel demand is reported as diagnostic NG residual.

## Summary Metrics

| Configuration | Common fuel demand PJ/y | WAG allocated PJ/y | Common NG residual PJ/y | Total diagnostic NG PJ/y | Full-site NG anchor PJ/y | Residual to anchor PJ/y |
|---|---:|---:|---:|---:|---:|---:|
| C0_current_BF_BOF_reference | 13.480977 | 13.480977 | 0 | 0 | 12.5 | 12.5 |
| C1_phase1_BF_BOF_plus_DRP_EAF | 11.17966 | 6.574393 | 4.605267 | 36.388942 | 46.5 | 10.111058 |

## Caveats

- Residual NG remains diagnostic/reporting-only, not a plug variable and not a dispatch decision.
- WAG allocation uses an aggregate residual-WAG pool because common-plant carrier splits are underparameterised.
- BOF volume fuel candidates remain visible but unconverted because the source unit and LHV/normalisation policy are not executable.
- CO2 remains not ETS-ready and this overlay does not compute CO2 from residual NG/WAG.
- Economics and DA readiness remain NO-GO.

## GO/NO-GO

- Residual NG reporting: GO_DIAGNOSTIC_ONLY_WITH_PARTIAL_PROVENANCE.
- Migration to executable inputs: NO_GO.
- CO2 implementation: NO_GO.
- Economics readiness: NO_GO.
- DA readiness: NO_GO.

Warnings emitted: 14.
