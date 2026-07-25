# C5 Representative Process-Profile Test

## Purpose

This diagnostic separates a fixed-schedule timing effect from a structural fuel
shortage. It compares the current 24-hour development run with a narrow
source-coupled PEFA timing profile. No free C0 binary planning, economic
dispatch, annual scaling or anchor calibration is used.

## What changes

- The accepted BOFG-to-PEFA Malerij daily demand is redistributed over the
  BOFG-generation hours from the same fixed schedule.
- The accepted COG-to-PEFA Branderij daily demand is redistributed over the
  COG-generation hours from the same fixed schedule.
- Each component's daily energy total is preserved exactly.

## What does not change

- Carrier-specific BFG/COG/BOFG balances and existing controller eligibility.
- HSM's throughput-linked demand.
- Boiler demand: it stays on its accepted continuous C5p_b profile because no
  source-backed boiler operating-time profile has been selected.
- WAG/NG ratios, mixed-gas/Wobbe logic, residual NG/electricity allocation,
  CO2 policy, model objective, economics and DA behaviour.

## Interpretation

If PEFA named-NG decreases in the source-coupled case, that demonstrates that
part of the fixed 24-hour NG result is a timing artefact. It does not prove
that the source-coupled schedule is Tata's real operating pattern. Boiler NG
remains a separate timing/source-contract question.

This stage is not an annual anchor test. The 24-hour final-product target is a
development smoke target, so annualising these rows would be misleading.
