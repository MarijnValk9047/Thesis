# C5 Phased Development Controller Activation

## Purpose

This stage activates the prepared HSM, PEFA, boiler and generator contracts in
four opt-in fixed-schedule 24-hour development rounds. It uses the existing
process-first WAG hierarchy: mandatory process use, HSM/PEFA, boiler/steam,
generator interface, then flare. No C0 free binary planning is used.

## Controller treatment

- HSM: throughput-linked reheat demand; BFG/COG/BOFG remain separate and named
  NG is used only if the represented WAG routes cannot meet demand.
- PEFA: reuses the existing C5n_a total-gas controller outputs. Its WAG routes
  are BOFG to Malerij and COG to Branderij; their fixed continuous heat demand
  receives named NG backup only in hours where the corresponding WAG is absent.
- Boilers: reuse the C5p_b demand-led scaffold, not nameplate capacity. BFG and
  COG are eligible; named NG is an explicit backup, not residual NG.
- Generator: a capped residual WAG interface with internal-offset reporting
  only. It has no export revenue, DA price response or mFRR behaviour.

## Interpretation

These are physical development checks. The static C0 schedule contains hours
without COG/BOFG/BFG production, so named PEFA and boiler NG may appear even
where the annual controller diagnostics had none. That is a useful visibility
result, not a reason to add residual NG or to tune parameters.

The Mode-B WAG subtotal counts each represented WAG stream once at its
oxidation sink. It is not a complete Scope-1, ETS or annual-anchor result.
