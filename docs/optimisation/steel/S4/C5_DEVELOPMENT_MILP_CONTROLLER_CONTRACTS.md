# C5 Development MILP Controller Contracts

## Status

This compact contract records the user-approved development choices used to
continue WAG integration. It does not turn candidate values into thesis truth.

## Active now

`BF_HOT_STOVE_CONTROLLER` applies to both C0 and C1 at 2.20 GJ/t hot metal.
It is BFG-first; COG, BOFG and NG remain explicit fallback routes that are not
activated by the current minimal WAG layer.

## Prepared, not active

- HSM reheat: 1.35 GJ/t HRC, with 1.20-1.50 sensitivity range.
- PEFA total gas heat: 0.320 GJ/t pellets, without an invented Malerij/
  Branderij split.
- Boiler/steam: C5p_b demand-led scaffold, never capacity-derived demand.
- VN25/IJ01: fixed or validation-scaled internal-offset interface only.

## CO2 policy

Mode B counts named fuel at the represented oxidation sink. Aggregate process
counters and residual energy remain outside that subtotal. Solid-fuel and
non-fuel process carbon remain source-repair work.
