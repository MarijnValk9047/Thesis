# C5 WAG Controller Contract Hardening

## A. Purpose and boundaries

This is the C5p_o hardened WAG controller contract/interface layer. It standardises and validates existing WAG/controller outputs into one diagnostic surface. It is not a new WAG allocator, does not run sensitivities, does not inspect raw PDFs, does not edit source cards, and does not change executable inputs or model equations.

The stage fails closed where existing functionality is missing. C5p_k remains warning/context only.

## B. Existing functionality used

This stage reads existing outputs from C5p_m, C5p_n, C5p_b, C5p_c, C5l, C5m and C5p_k. It inspects but does not call `wag_diagnostic`, `wag_fixed_profile_builder`, or S4.4b2 structural mixing rules. No runtime allocation algorithm is executed.

The call trace is in `wag_controller_call_trace.csv`.

## C. Hardened carrier policy

- COG, BFG and BOFG are quantitative only where existing carrier rows preserve them.
- `mixed_wag` is structural-only; no quantitative Wobbe/share-constrained mixer is unlocked.
- `aggregate_wag` is reporting/warning-only and cannot feed physical allocation.
- NG is external/back-up fuel, not WAG.
- No WAG/NG split ratio is invented.

## D. Hardened sink/stage policy

- Process/prep: accepted as existing carrier-specific diagnostic rows only.
- HSM/WBW: accepted through existing C5l controller outputs.
- Sinter/PEFA: accepted through existing C5m/C5n/C5p_b-consumed outputs where present.
- Steam/boiler: accepted through C5p_b; BOFG remains blocked in the steam layer.
- Generator interface: accepted through C5p_c as fixed/interface accounting, not price-responsive dispatch.
- Flare/spill and residual: reporting-only; C1 flare remains not carrier-split.
- Common-plant overlays: C5p_k warning/context only.
- CO2: site-level residual reporting only; WAG/fuel-explicit CO2 remains blocked.

## E. Validation checks

Validation check counts: `{'pass': 10, 'blocked': 2}`.

Aggregate WAG balance retained from C5p_m:

| Configuration | Generation PJ/y | Process/prep PJ/y | Steam/boiler PJ/y | Generator PJ/y | Flare/spill PJ/y | Residual PJ/y | Status |
|---|---:|---:|---:|---:|---:|---:|---|
| C0 | 29.140351 | 6.129506 | 1.117922 | 21.892922 | 0 | 0 | pass |
| C1 | 13.885042 | 6.791252 | 0.519397 | 5.736611 | 0.1 | 0.737782 | pass |

The checks pass for carrier-specific balance closure, aggregate WAG exclusion, C5p_k physical-use exclusion, mixed_wag structural-only policy, no hidden flooring, and no active WAG double-count mode. Common-plant WAG/NG split and WAG/fuel-explicit CO2 remain blocked.

## F. Athanasiadis alignment

Alignment counts: `{'partially_aligned': 4, 'aligned': 4}`.

This is a functional architecture check only. It does not replicate Athanasiadis numerically and does not claim official Tata truth. The current interface is aligned or partially aligned with the precedent of separating WAG generation, process/self-use, steam/boiler use, generator-interface use, flare/residual handling, gas-network structure, no direct WAG market valuation, and CO2 double-counting guardrails. Locator status remains indirect or partial and needs user review before thesis claims.

## G. Readiness for future phases

- Phase 2 electricity non-WAG decomposition: GO with WAG caveat.
- Generator/WAG-dependent electricity interpretation: caveated only.
- NG residual policy: NO-GO.
- CO2 site-level residual reporting: GO diagnostic-only.
- WAG/fuel-explicit CO2: NO-GO.
- Full sensitivity execution: NO-GO.
- Executable input migration: NO-GO.
- Economics: NO-GO.
- DA: NO-GO.

Blocked cases are listed in `wag_contract_blocked_cases.csv`; count = 6.

## H. How to critically review this WAG implementation

Inspect these files:

- `wag_contract_interface_ledger.csv`: confirm only BFG/BOFG/COG carrier-specific rows can feed physical allocation.
- `wag_carrier_sink_allocation_ledger.csv`: confirm aggregate C0/C1 WAG totals match C5p_m and carrier rows close.
- `wag_contract_validation_checks.csv`: any `fail` invalidates physical interpretation; `blocked` rows define next-stage blockers.
- `c5p_k_exclusion_audit.csv`: confirm C5p_k remains warning/context only.
- `athanasiadis_alignment_matrix.csv`: confirm functional alignment remains architecture-only and locator caveats are retained.

Warnings that invalidate physical interpretation include aggregate_wag feeding a plant, mixed_wag marked quantitative, C5p_k used as allocation evidence, negative residuals being floored away, or WAG/fuel-explicit CO2 being unlocked before carbon policy is frozen.

Evidence still missing before claiming WAG is implemented correctly: explicit common-plant WAG/NG split, quantitative mixed-gas/Wobbe policy, C1 flare carrier split, and WAG/fuel CO2 factor/carbon-counting policy.
