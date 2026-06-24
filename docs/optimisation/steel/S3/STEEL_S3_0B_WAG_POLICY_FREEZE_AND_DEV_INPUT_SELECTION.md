# STEEL_S3_0B_WAG_POLICY_FREEZE_AND_DEV_INPUT_SELECTION

## Purpose

This memo freezes the `S3.0b` WAG policy surface and records the development-only coefficient selections prepared after the canonical source-card and candidate parameter-evidence registers were populated.

The existing source-card integration was verified and not recreated. The controlling evidence surfaces are:

- `data/03_Optimisation/inputs/assets/steel/source_evidence/steel_source_card_register.csv`
- `data/03_Optimisation/inputs/assets/steel/source_evidence/steel_candidate_parameter_evidence_register.csv`

Research memos remain discovery aids only. They do not replace the canonical source cards or parameter-evidence rows.

## Frozen WAG Policy

`S3.0b` uses separate `BFG`, `COG`, `BOFG_or_LD_gas`, natural-gas, and grid-electricity carriers.

`COG` is represented through an accounting-only coking proxy. `S3.0b` must not add flexible coking, coking activity variables, coke storage activation, or coking dispatch. The future calculation chain remains throughput-coupled and development-only until implemented in `S3.0b-b`.

`C0` and `C1` are not allowed to receive the same flat WAG credit. `C0` links BFG to BF activity, BOFG/LDG to BOF activity, and COG to the coking proxy. `C1` links WAG only to retained BF-route and retained BOF/coking activity, while DRP and EAF add natural-gas and electricity demands through their own accounting paths.

Gross COG is not fully allocatable. Gross COG generation, mandatory coking self-use, mandatory process use, and residual allocatable COG must remain distinct.

The sole `S3.0b` WAG allocation hierarchy is process-first:

1. mandatory carrier-specific process and self-use;
2. throughput-coupled steam and boiler demand;
3. WAG-to-power import-offset interface;
4. flare, spill, or unused residual.

Within a shared stage, residual eligible carrier energy may be allocated proportionally. `S3.0b` does not optimise carrier choice and does not use prices.

Hierarchy sensitivity is excluded. Sensitivity work applies only to uncertain numerical coefficients.

The WAG-to-power interface reduces net site electricity import only. It creates no export, no export revenue, no settlement, no unit commitment, and no Vattenfall dispatch model. Where no reviewed capacity exists, the development mode is `potential_import_offset`.

## Frozen Emissions Policy

`S3.0b` uses a physical-site point-of-oxidation ledger. WAG generation creates a carbon-carrying gas flow but does not itself count direct CO2. Direct CO2 is counted once when the gas is combusted, flared, or explicitly transferred across the model boundary.

Carrier-specific energy-based factors must be used for BFG, COG, and BOFG/LDG. Aggregate route-emission anchors must not be layered on top of WAG oxidation emissions if those anchors already contain WAG carbon.

For the first development diagnostic, flare uses complete carbon oxidation for CO2 closure. Methane slip, CO slip, incomplete combustion, and other non-CO2 flare emissions remain deferred.

Natural-gas substitution is useful-energy based. The EU ETS/FAR `0.667` allocation factor is not a physical conversion coefficient.

Captured CO2 remains visible as a separate reporting flow and is not automatically subtracted from emissions. Gross ETS cost remains blocked until the direct-emissions ledger is complete. Free allocation remains separate and must not be netted silently.

## Development-Only Selection Rule

Selected values are not Tata-exact and not thesis-grade. They are development-only coefficients for building and testing the `S3.0b-b` scaffold.

Central values use this order:

1. explicit representative or average value from the strongest applicable public source;
2. most specific value from the highest-authority public source;
3. midpoint of one defensible internally consistent source range.

Midpoints are recorded as `midpoint_modelling_assumption`, not as extracted evidence.

## Accepted Automatically

The following were accepted for development-only use because canonical evidence has complete locators and unambiguous units or accounting-rule status:

- BFG generation intensity and LHV;
- BOFG/LDG generation intensity and LHV;
- COG yield per tonne dry coal and COG LHV;
- BFG, COG, BOFG/LDG, and natural-gas combustion factors;
- WAG-to-power efficiency as a generic sensitivity coefficient;
- flare complete-oxidation convention;
- point-of-oxidation and no-double-counting boundary rules;
- net-import-offset convention;
- useful-energy substitution convention;
- captured-CO2 visibility convention.

## Sensitivity Required

The limited sensitivity plan covers coefficients only:

- `bfg_generation`
- `bofg_generation`
- `cog_chain`
- `conversion_efficiency`

The selected generic boiler/steam useful-energy efficiency is `0.85/0.875/0.90` for development-only coefficient sensitivity. This does not resolve the missing throughput-coupled steam or boiler demand profile.

No hierarchy-policy sensitivity is allowed. No full factorial design is opened.

## Suspicious Or Unresolved Inputs

The following remain blocked or unresolved:

- BOFG/LDG alternative 50-120 range because the basis differs from the selected suppressed-combustion row;
- exact WAG-to-power capacity because public Vattenfall/Tata sources support interface existence but not executable dispatch capacity;
- C1 WAG availability reduction because public transition evidence is structural and scenario-like, not a coefficient;
- coke requirement per tonne hot metal;
- dry-coal input per tonne coke;
- C0 and C1 on-site coking shares;
- mandatory COG self-use or mandatory process-use coefficient;
- mandatory BFG and BOFG process-use demands;
- throughput-coupled steam or boiler demand;
- site electricity demand cap for meaningful net-import offset.

## S3.0b-b Start Decision

`S3.0b-b` may start as a scaffold plus blocked runtime.

The calculation scaffold may load and validate the provisional development-input packet, activity-profile package, policy register, sensitivity plan, and required source links. A meaningful fixed-profile diagnostic run remains blocked until mandatory process, steam or boiler, and site-electricity demand inputs are complete.

No WAG calculation, S2 model change, market logic, export revenue, objective optimisation, or approved-input promotion is created by this memo.
