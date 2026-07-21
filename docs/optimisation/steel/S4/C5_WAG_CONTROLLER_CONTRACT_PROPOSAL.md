# C5 WAG Controller Contract Proposal

## Purpose And Scope

This document is the non-executable C5p_n WAG controller contract proposal for the C5 physical/accounting baseline. It reconciles the WAG/controller surfaces audited in C5p_m and states what later diagnostics may safely use. It does not implement a new allocator, does not change model equations, does not migrate any source-card candidate values to executable inputs, and does not create an economics or CO2 objective layer.

The canonical anchor register remains the leading source for validation and residual KPI anchors. C5p_k remains exploratory warning evidence only: it used aggregate residual WAG fallback and must not be treated as physical WAG allocation evidence.

This proposal is meant to protect later electricity, NG, CO2, and sensitivity work from silently bypassing existing WAG/controller logic.

## Carrier Definitions

COG, BFG, and BOFG are the quantitative WAG carriers in the current C5 diagnostics where carrier rows exist. They may be used for reporting and diagnostic comparison through the accepted surfaces that already preserve the carrier split. They must not be collapsed into a generic physical WAG carrier.

`mixed_wag` is structural-only. S4.4b2 records mixer topology and eligibility, but no quantitative Wobbe, gas-quality, or share-constrained mixer is ready for executable or sensitivity use.

`aggregate_wag` is reporting-only. It is useful for balance closure, warning metrics, and high-level anchor comparison, but it must not allocate physical fuel to plants.

NG is an external/back-up fuel carrier, not WAG. Explicit NG consumers may be reported where current C5 stages already represent them, but residual NG policy remains blocked until common-plant WAG/NG treatment is controller-compatible or kept strictly as a site-level residual KPI.

## Sink/Controller Assignments

The accepted current surfaces are:

- Process/prep mandatory self-use: existing WAG diagnostic and upstream C5 process ledgers.
- HSM/WBW: C5l HSM WAG dispatch and hot-charge/reheat controllers.
- Sinter: C5m sinter gas/WAG controller, with COG/NG eligibility and no useful sinter WAG generation.
- PEFA/pelletizing: upstream C5n/C5p_b-consumed gas artifacts, still partial.
- Steam/boiler: C5p_b boiler/steam allocator. BFG and COG are active where allowed; BOFG is blocked in the steam layer.
- IJ01/VN25 generator interface: C5p_c fixed/interface allocator, with BFG/BOFG/COG/NG rows and no price-responsive dispatch.
- Flare/spill and residual reporting: C5p_c/C5p_m rows, with C1 flare not carrier-split.
- Common-plant overlay / NG residual diagnostics: C5p_k only, warning/context use only.
- Structural mixed-gas eligibility: S4.4b2 only, structural and non-quantitative.

## Allocation Sequence

The current C5 outputs imply this diagnostic sequence:

1. WAG generation and mandatory/process self-use are established by upstream profiles and process ledgers.
2. HSM, sinter, and PEFA process uses are accounted through their current carrier-specific surfaces.
3. C5p_b allocates remaining eligible WAG/NG to steam and boiler demands.
4. C5p_c allocates remaining WAG/NG to IJ01/VN25 generator-interface reporting.
5. C5p_c/C5p_m report flare/spill and residual WAG.

This sequence is current-implied, not a final physical truth claim.

The conservative governed diagnostic sequence for future work is:

1. Preserve COG/BFG/BOFG carrier rows and self-use before any downstream interpretation.
2. Use only accepted process-controller outputs; do not use aggregate fallback to serve plant demand.
3. Let C5p_b remain the steam/boiler diagnostic surface.
4. Let C5p_c remain the generator-interface diagnostic surface.
5. Report flare and residuals visibly; do not recycle them into another sink.
6. Use site-level residual KPIs for unresolved energy gaps instead of physical plug variables.

Quantitative mixed-gas allocation and common-plant WAG/NG physical allocation remain blocked alternatives.

## Treatment Of C5p_k

C5p_k may be cited as evidence that aggregate fallback is dangerous. It may be used for warning metrics and gap illustration. It must not allocate WAG to common plants, must not justify C0 NG equals zero as physical truth, and must not feed NG residual policy.

Any future common-plant NG/WAG logic must either use accepted carrier-specific controller surfaces or remain a site-level residual KPI with no plant allocation.

## Contract Gaps And Blockers

The main blockers are:

- No single authoritative model-wide WAG allocation contract interface.
- No explicit common-plant WAG/NG split ratio.
- No quantitative mixed-gas/Wobbe controller.
- C1 flare/spill is not carrier-split.
- The current WAG precedence is reconstructed across stages and not frozen as one governed policy.
- Aggregate process CO2 and WAG/fuel-explicit CO2 could be double-counted if modes are mixed.
- Some WAG anchors differ in boundary or denominator and are not directly comparable.

These gaps block NG residual physical implementation, WAG/fuel-explicit CO2, full sensitivity execution, economics, and DA readiness.

## Readiness For Next Phases

- Phase 2 electricity boundary decomposition: GO for non-WAG load decomposition, with WAG offsets caveated.
- WAG-dependent electricity interpretation: NO-GO until the contract is hardened.
- NG residual policy: NO-GO for physical allocation; site-level residual reporting only.
- CO2 site-level residual reporting: GO diagnostic-only.
- WAG/fuel-explicit CO2: NO-GO.
- Full sensitivity execution: NO-GO.
- Migration to executable inputs: NO-GO.
- Economics readiness: NO-GO.
- DA readiness: NO-GO.

## Follow-Up Tasks

1. Proceed to Phase 2 electricity boundary decomposition for non-WAG loads, keeping WAG-dependent offsets separate and caveated.
2. If common-plant NG residual must be physically allocated, run a WAG contract hardening task focused on accepted controller-compatible common-plant fuel logic.
3. Repair WAG/CO2 factor and carbon-accounting policy before any WAG/fuel-explicit CO2 implementation.

## Created Artifacts

Machine-readable contract artifacts are stored in:

`data/03_Optimisation/inputs/assets/steel/S4/s4_4c5p_n_wag_controller_contract_proposal/`

They include contract rules, sink-controller assignments, sequence proposals, carrier/sink eligibility, C5p_k use policy, conflict register, readiness gate, and summary JSON.
