# C5 Normalised Anchor Diagnostics

This diagnostic asks whether differences to annual anchors persist after
normalising modelled energy, WAG, NG and explicit WAG CO2 by output/activity.
It uses the closed-loop run's first 168-hour window and existing local
anchor/register values only.

## Rules

- Model ratios use final-product proxy unless a plant activity is explicitly
  available.
- MER/public anchors retain their own liquid-steel denominator.
- Athanasiadis Table 8/9 ratios are conditional on the user-supplied 6.2 Mt/y
  denominator and remain model-precedent evidence, not Tata truth.
- A ratio can expose a likely boundary or coefficient problem, but does not
  become a parameter-fitting objective.
- Carrier generation coefficients are checked only for wiring consistency to
  governed development inputs; this is not independent validation.

## Interpretation

The output distinguishes four questions:

1. Is an annual gap still present per unit output?
2. Is it likely a numerator problem, denominator problem or boundary problem?
3. Do BFG/COG/BOFG coefficients reproduce the selected development input?
4. Which next audit could distinguish high generation from too-flexible use or
   insufficient generator conversion?

No DA, price, residual fill, CO2 aggregation or parameter migration is active.
