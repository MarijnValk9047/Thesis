# STEEL_S3_0B_FIXED_PROFILE_WAG_DIAGNOSTIC_INPUT_AND_CONTRACT

## Purpose

`S3.0b-a` is a contract and provenance design stage only.

It prepares the governed input package for a later fixed-profile `WAG` diagnostic, but it does not calculate `WAG` generation, allocate `WAG`, change objectives, or implement accounting equations.

The later `S3.0b` diagnostic may use fixed `S2` activity profiles and reviewed candidate or provisional `WAG` coefficients to produce diagnostic accounting tables. It must not become price-responsive optimisation.

## Fixed Profile Rule

The later diagnostic must consume fixed activity profiles from governed input packages.

It must not read arbitrary generated run folders as canonical source artifacts.

Generated run folders may be referenced as provenance evidence if the package records:

- source stage
- source artifact ID
- source artifact path
- source artifact hash
- extraction method
- configuration ID
- horizon and timestep basis
- activity IDs and units

The canonical package must live under governed input surfaces before any diagnostic calculation is implemented.

## WAG Coefficient Rule

`WAG` coefficient rows remain candidate or provisional until reviewed.

Required coefficient families include generation coefficients, lower-heating-value or energy-content factors, useful-energy substitution coefficients, interface efficiencies, capacity or interface limits, flare or spill treatment, emissions factors, natural-gas displacement conventions, net-import offset conventions, captured-`CO2` visibility, and no-double-counting rules.

`S3.0b-a` approves no coefficients.

No row is executable.

No row is thesis-usable.

## Blocked Logic

`S3.0b-a` does not allow:

- day-ahead prices
- price-responsive `WAG` allocation
- stochastic scenarios
- `CVaR`
- `mFRR`
- 15-minute logic
- product revenue or order-book logic
- settlement logic
- objective optimisation
- export revenue
- downstream flexibility activation
- cold slab or slab-`WIP` storage activation
- strategic hot slab `WIP` flexibility
- finished-goods flexibility
- generated run folders as canonical source artifacts

## WAG Value Interpretation

`WAG` value is limited to diagnostic useful-energy substitution or diagnostic net-import offset.

It is not free revenue.

`WAG` electricity must not be treated as automatic export revenue.

Direct electricity-price valuation remains blocked unless a later reviewed stage introduces explicit conversion logic and market treatment.

## Residual And Emissions Boundary

Flare, spill, and unused `WAG` residual accounting is mandatory.

The diagnostic contract must preserve a visible residual sink so that unallocated `WAG` is not hidden.

Emissions-boundary logic must prevent double counting:

- direct process emissions remain separate
- `WAG` combustion or flare emissions remain separate
- natural-gas combustion emissions remain separate
- captured-`CO2` visibility remains explicit where applicable
- indirect electricity emissions remain reporting-only unless later reopened

## Output Status

`S3.0b` outputs remain development-only and non-thesis until:

- fixed activity-profile provenance is reviewed
- coefficient families are reviewed
- diagnostic validation checks pass
- emissions double-counting checks pass
- balance closure checks pass
- a later prompt explicitly implements the diagnostic calculation

This memo creates no activity-profile data rows and no coefficient-value rows.

## S3.0b-a3 Development-Only Selection Addendum

The later `S3.0b-a3` policy freeze and development-selection packet does create provisional development-only WAG input rows under:

- `data/03_Optimisation/inputs/assets/steel/S3/s3_provisional_dev_input/s3_wag_selected_dev_inputs.csv`

Those rows are not approved model inputs and are not thesis-usable. They support future `S3.0b-b` scaffold development only.

The selected `S3.0b` policy is a single fixed process-first hierarchy:

1. mandatory carrier-specific process and self-use;
2. throughput-coupled steam and boiler demand;
3. WAG-to-power net-import offset;
4. flare, spill, or unused residual.

Hierarchy sensitivity is excluded. `S3.0b` coefficient sensitivities may vary selected numerical coefficients only.

The WAG-to-power interface reduces net site import only. It does not create export revenue, settlement, price-responsive dispatch, or a full Vattenfall dispatch model.

The emissions policy is point-of-oxidation accounting: WAG carbon is not counted at generation and is counted once at combustion, flare, or explicit transfer.

`S3.0b-b` may start as a scaffold plus blocked runtime. A meaningful diagnostic remains blocked until mandatory process-use, steam or boiler demand, and site-electricity demand inputs are complete.
