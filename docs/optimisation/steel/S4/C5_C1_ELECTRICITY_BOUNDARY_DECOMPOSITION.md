# C5 C1 Electricity Boundary Decomposition

## Result

The current C1 first-window gross electricity is 15819.144 MWh.
It is fully explained by the active DRP and EAF electricity expressions.
HSM and PEFA development-controller electricity contracts exist, but are not
integrated into this closed-loop C1 gross-electricity output; their implied
values are reported separately rather than double counted.

ASU/oxygen, KGF, BOF/OSF, DSP/downstream and background site electricity are
not separately visible in this output. They therefore remain named boundary
gaps, not inferred loads. The site-level electricity residual is retained as a
signed reporting KPI only.

## Guardrails

- No model equation, input, source card or WAG allocation changed.
- Gross demand, generator offset and net import remain separate.
- C5p_o is the authoritative WAG interface; no WAG conclusion is drawn from
  the remaining electricity gap.
- The 17.8 PJ/y site anchor is validation context, not an optimisation target.
