# S3.0c-b C1 Scenario Route Policy and WAG Readiness

## Purpose

S3.0c-b represents C1 through governed same-output development scenarios rather than another external route-share search. The profiles preserve the C0 fixed-profile output volume and vary the retained BF-BOF versus added NG-DRP/EAF route share.

This is a development scenario policy. It is not Tata-exact operation, not an S2 optimisation result, and not thesis-grade validation.

## Route Scenarios

The selected scenarios are:

| scenario_id | BF-BOF share | DRP-EAF share | role |
|---|---:|---:|---|
| `c1_high_drp_eaf` | 0.55 | 0.45 | high electrification / low retained BF-BOF |
| `c1_central` | 0.61 | 0.39 | central development scenario |
| `c1_low_drp_eaf` | 0.68 | 0.32 | low electrification / high retained BF-BOF |

The shares sit inside or near the prior S2 feasible BF-BOF interval of approximately 0.5472 to 0.6799. The scenarios are not the auxiliary-LP midpoint and are not selected to hit an emissions target.

## Same-Output Basis

All C1 profiles use the C0 fixed-profile liquid-steel output of 8150.6772 t over 24 hours. This value is read from the governed C0 profile when profiles are built.

## Profiles Created

The governed C1 profiles are:

- `c1_high_drp_eaf_same_output_profile_24h_dev.csv`
- `c1_central_same_output_profile_24h_dev.csv`
- `c1_low_drp_eaf_same_output_profile_24h_dev.csv`

They are S3 wrapper profiles, not solved S2 route splits. Each profile records total output, BF-BOF route output, DRP-EAF route output, retained BF hot-metal proxy, retained BOF proxy, DRP/EAF activity proxies, retained coking proxy, and WAG generation driver rows.

## WAG Readiness

C1 WAG-generation-only validation is allowed because BFG, BOFG, and COG generation drivers are present and use already selected WAG coefficients. Full C1 diagnostics remain blocked.

Current full-diagnostic blockers are:

- DRP natural-gas coefficient;
- DRP electricity coefficient;
- EAF electricity coefficient;
- C1 site-electricity cap;
- C1 mandatory process-use demand;
- C1 steam/boiler demand.

Missing energy coefficients are not treated as zero. No import offset, natural-gas substitution, or full C1 emissions claim is made from the C1 route profiles.

## Emissions Context

The public Phase 1 combustible-gas reduction evidence remains plausibility context only. The C1 route scenarios are not derived by forcing an emissions target. The C1 emissions ledger is partial until DRP/EAF energy, non-WAG direct emissions, and electricity boundary inputs are selected.

No DA prices, route optimisation, price-responsive WAG allocation, settlement, export revenue, gross ETS cost, stochastic scenario, CVaR, mFRR, or product revenue are introduced.
