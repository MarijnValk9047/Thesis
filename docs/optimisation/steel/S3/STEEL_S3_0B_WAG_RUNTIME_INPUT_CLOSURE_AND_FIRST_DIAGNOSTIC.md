# S3.0b-b2 WAG Runtime Input Closure And First Diagnostic

## Scope

This memo records the `S3.0b-b2` runtime-input closure attempt for the fixed-profile WAG diagnostic.

The task used the canonical source-card and candidate-evidence registers as controlling evidence. The WAG research memo was treated only as discovery context. No approved-input table was populated, no S2 model file was modified, and no generated run folder was used as a source artifact.

## Preflight

The existing WAG validation-only CLI passed and reported the same runtime blockers as the `S3.0b-b1` scaffold:

- `coke_rate_per_t_hot_metal`;
- `dry_coal_input_per_t_coke`;
- `c0_onsite_coke_production_share`;
- `c1_retained_onsite_coke_production_share`;
- `mandatory_cog_self_or_process_use_fraction`;
- mandatory carrier-specific process-use profile;
- steam/boiler useful-demand profile;
- site-electricity-demand profile.

The selected-input loader still reads only `s3_wag_selected_dev_inputs.csv`. It does not read the selection-review CSV, source-card tables, approved-input shells, or generated run folders.

## C1 Route-Share Identifiability

A separate in-memory auxiliary LP diagnostic was run against cloned C1 smoke models. It preserved the frozen topology, process bounds, conversion coefficients, feasible-smoke target, first-buffer CYC50 endpoint policy, and no-shortfall rule. A no-overproduction cap was applied only in the auxiliary diagnostic so route share was measured against the target rather than arbitrary surplus production.

Result:

- minimum retained BF-BOF liquid-steel output: `7671.24 t`;
- maximum retained BF-BOF liquid-steel output: `9531.495144 t`;
- minimum BF-BOF share: `0.5471962`;
- maximum BF-BOF share: `0.67988981`;
- identifiability tolerance: `0.01`;
- route-share identified: `false`.

The C1 route split is therefore non-identified for fixed-profile construction. No arbitrary solver-selected C1 split may become canonical. No public governed route-share evidence in the current canonical WAG registers supports selecting a development-only C1 route share.

## COG-Chain Inputs

Already selected and still source-backed:

- `cog_raw_yield_per_tonne_dry_coal`: selected central `365 m3/t_dry_coal`, low/high `280/450`, sensitivity required;
- `cog_lhv_raw_gas`: selected central `18.7 MJ/Nm3`, low/high `17.4/20.0`.

Still unresolved:

- coke rate per tonne hot metal;
- dry-coal input per tonne coke;
- C0 on-site coke-production share;
- C1 retained on-site coke-production share;
- mandatory COG self-use or process-use coefficient.

These remain unresolved because the canonical evidence surface contains no locator-complete, unit-compatible public value or range for them. They were not inferred from S2 material recipes, plant counts, or validation anchors.

## Demand Profiles

No loader-eligible WAG demand coefficient was created.

The new governed demand surface is:

- `data/03_Optimisation/inputs/assets/steel/S3/s3_provisional_dev_input/s3_wag_demand_coefficients.csv`

It is currently header-only. The canonical evidence supports structural process fuel, steam/boiler use, and import-offset accounting, but not numerical throughput-coupled demand sinks for:

- mandatory BFG-compatible process use;
- mandatory BOFG-compatible process use;
- mandatory COG self/process use;
- steam or boiler useful-energy demand;
- site electricity demand cap.

Annual electricity or energy anchors were not converted into hidden hourly truth.

## Fixed Profiles

No fixed 24-hour profile package was created.

C0 is blocked by missing COG-chain inputs and missing demand profiles. C1 is blocked by the same runtime demand/COG inputs and by non-identified BF-BOF versus DRP-EAF route share.

The fixed-profile directory now contains a README documenting that future profiles must be development-only, UTC-timestamped, provenance-complete, generated from canonical S2 inputs, and not sourced from generated run folders.

## First Guarded Diagnostic

No central WAG diagnostic was run.

No configuration satisfied all runtime gates:

- C0: not runtime-ready;
- C1: not runtime-ready.

Therefore no WAG generation, WAG use, natural-gas substitution, net-import offset, flare/spill, or emissions result is claimed.

## Sensitivity Status

No coefficient sensitivity was executed because no central runtime diagnostic passed first.

Eligible sensitivity groups remain policy-defined only:

- `bfg_generation`;
- `bofg_generation`;
- `cog_chain`;
- `conversion_efficiency`.

No hierarchy sensitivity, full factorial design, market-price sensitivity, Vattenfall-capacity sensitivity, or route-share sensitivity was introduced.

## Limitations

The current result is an evidence-governance closure result, not a plant diagnostic.

The key remaining work is to obtain governed public or human-reviewed development assumptions for the unresolved COG-chain and demand-profile inputs. Until then, the scaffold can validate inputs but must not claim a meaningful WAG diagnostic.
