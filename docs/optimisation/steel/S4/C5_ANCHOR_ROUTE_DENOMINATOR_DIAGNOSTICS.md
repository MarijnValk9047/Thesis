# C5 Anchor, Route, Denominator And Material-Accounting Diagnostics

## Purpose And Scope

This is a diagnostic-only review of the current C5 plant-layer artifacts after KGF/BF/BOF/HSM/WBW/Sinter/PEFA/pellet burden/DRP/EAF/DSP. It does not change model equations, parameters, targets, route shares, coefficients, utility layers, or economics.

The model remains a public Tata Steel IJmuiden-inspired development model. It is not a confidential digital twin and not thesis-approved.

## Current C5 Coverage Summary

- Active C0/C1 liquid-steel target remains 6.75 Mt/y.
- C5l_d `base_0_50` remains the default HSM/WBW heat case.
- PEFA, pellet burden, DRP, EAF, DSP and Linde/ASU oxygen are represented as development-only accounting/physical layers with compact healthchecks.
- Linde/ASU oxygen now adds current-C5 process electricity accounting, but WAG, CO2 and steam remain diagnostic or partial utility layers, not economic objective layers.

## Anchor Reconciliation Summary

- C0_current_BF_BOF_reference `final_product_proxy`: model 6259090.90891 t/y, gap -640909.09109 versus active/raw reference. Denominator candidate, not yet final economics denominator.
- C0_current_BF_BOF_reference `hsm_wbw_output`: model 4909090.90891 t/y, gap -490909.09109 versus active/raw reference. HSM output reflects slab input factor and imported slab context.
- C0_current_BF_BOF_reference `bf_hot_metal`: model 5906250.0 t/y, gap -393750 versus active/raw reference. BF HM differs from raw anchors after no-buffer BOF coupling.
- C1_phase1_BF_BOF_plus_DRP_EAF `linde_total_oxygen_demand`: model 982143.7312000002 t/y, gap 238143.7312 versus active/raw reference. Core demand excludes residual/unmodelled O2 users; DRP basis caveated.
- C0_current_BF_BOF_reference `sinter_output`: model 3468752.44056 t/y, gap -231247.55944 versus active/raw reference. C0 site-average and C1 retained-BF coupling caveated.
- C1_phase1_BF_BOF_plus_DRP_EAF `final_product_proxy`: model 6800534.76175 t/y, gap -199465.23825 versus active/raw reference. Denominator candidate, not yet final economics denominator.

The largest gaps are mostly expected consequences of the active 6.75 Mt/y target, the C5l_d downstream/HSM routing convention, and explicit development reconciliation choices. They are not fixed in this diagnostic task.

## Scaling And Reconciliation Modes

- `C5_DECISION_ACTIVE_TARGET_6P75`: C0/C1 active target fixed at 6.75 Mt/y. Recommended action: Freeze as C5 development baseline or schedule explicit target sensitivity before DA economics.
- `C5_DECISION_HSM_BASE_0_50`: C5l_d base_0_50 is active HSM/WBW heat case. Recommended action: Keep base_0_50 as base and preserve high/uncapped references.
- `C5_DECISION_PELLET_PROXY`: Single fired_pellets_proxy with fixed PEFA and imported pellet supply. Recommended action: Keep proxy for C5; add grade split only if required for DRP/BF feasibility claims.
- `C5_DECISION_EAF_DRI_COEFF`: Preserve C5 EAF LS target and derive active DRI coefficient from available DRP DRI. Recommended action: Freeze as C5 reconciliation or implement explicit HBI/import sensitivity before DA claims.
- `C5_DECISION_DSP_PLACEHOLDER`: Preserve C5l_d 1.35 Mt/y DSP placeholder and wrap explicit DSP process around it. Recommended action: Decide whether to keep 1.35 Mt/y active DSP or align to 1.5 Mt/y with downstream rerouting.
- `C5_DECISION_COKE_RECONCILIATION`: C5m_f bounded coke reconciliation is the active development baseline; external/unmodelled coke is fallback-only. Recommended action: Keep C5m_f bounded reconciliation as active development baseline; do not reopen unless a later test finds inconsistency.
- `C5_DECISION_FINAL_DENOMINATOR`: Report liquid steel target and downstream final-product proxy separately. Recommended action: Do not choose yet; keep unresolved until C5p_a Linde/ASU is reviewed and boiler/steam plus generator/interface layers are implemented.
- `C5_DECISION_INTERNAL_SCRAP`: HSM/DSP internal losses are reported; EAF scrap input remains explicit accounting input. Recommended action: Add scrap-pool accounting before raw-material economics.

## Final-Product Denominator Discussion

- C0 final-product proxy is 6259090.90891 t/y versus raw final-product context 6900000 t/y.
- C1 final-product proxy is 6800534.76175 t/y versus raw final-product context 7000000 t/y.
- Liquid steel is an internal technical target; HSM plus DSP is the current downstream final-product proxy.
- A future economics denominator must be frozen before EUR/t claims. Options are liquid-steel equivalent, current final-product proxy, or an explicitly revised downstream product target.
- The denominator remains unresolved after C5p_a because boiler/steam and generator/interface layers are still incomplete. Product revenue remains blocked.

## DSP Route-Origin Status

- C0 has a 20% OSF-to-DSP route-share check that passes under the current C5l_d placeholder replacement.
- C1 has only a pooled liquid-steel-to-DSP interface. The approximate 90% EAF-origin DSP anchor cannot currently be validated.
- This does not block current physical feasibility, but it blocks a thesis claim that 90% of DSP material is EAF-origin unless route-origin tagging is added.

## Internal Scrap Status

- BOF and EAF scrap inputs are active material-accounting inputs.
- HSM and DSP internal losses/scrap are reporting-only diagnostics.
- Internal scrap is not currently a free EAF input. A governed scrap-pool layer is needed before raw-material economics or scrap-loop claims.

## Upstream/Downstream Consistency

- PEFA -> pellet burden -> DRP closes in the compact pellet-balance diagnostics.
- DRP -> DRI buffer -> EAF closes with terminal DRI inventory equality after C5o_b.
- BOF/EAF -> DSP/HSM/WBW is coherent as pooled downstream routing, but route-origin precision is missing for C1 DSP.
- DSP/HSM/WBW -> final-product proxy is reported and placeholder replacement is explicit.

## Utility Readiness

- `Linde_ASU_oxygen`: implemented_accounting_only_after_C5p_a. Recommended stage: review_DRP_oxygen_basis_then_C5p_b_boiler_steam. Risk: Oxygen accounting exists, but DRP O2 basis and buffer/flexibility claims remain caveated.
- `boilers_steam`: partial_proxy_only. Recommended stage: C5p_b_boiler_steam_proxy_hardening. Risk: WAG residuals and steam demands cannot be valued or balanced physically.
- `Vattenfall_IJ01_VN25_generators`: interface_placeholder_only. Recommended stage: C5p_c_generator_interface_boundary. Risk: Full-site electricity and WAG opportunity-cost claims remain unsupported.
- `residual_electricity`: process_scope_only. Recommended stage: after_Linde_boilers_generators_boundary. Risk: DA economics would price only modelled process loads and may be mistaken for full-site cost.
- `residual_NG`: partial_process_NG_only. Recommended stage: with_boiler_and_residual_utility_boundary. Risk: NG cost comparison excludes non-modelled utility and residual loads.
- `consolidated_CO2`: diagnostic_only. Recommended stage: after_utility_boundary_before_ETS_sensitivity. Risk: CO2 values may be double-counted or overinterpreted as ETS/full-site emissions.

## Key Red Flags

- No immediate model-health failure is introduced by C5o_c artifacts.
- The red flags before economics are denominator ambiguity, C1 DSP route-origin opacity, missing governed scrap loop, DRP oxygen-basis review, boiler/steam proxy status, generator/interface absence, residual electricity/NG boundary absence, and diagnostic-only CO2.

## Recommended Next Decisions

1. Freeze denominator policy for future EUR/t reporting: liquid-steel equivalent versus current final-product proxy versus revised downstream target.
2. Decide whether C1 DSP route-origin tagging is required before thesis route-share claims.
3. Keep C5p_a Linde/ASU as oxygen accounting only until DRP oxygen basis is reviewed and remaining utility boundaries are scoped.
4. Defer economics until boiler/steam, generator/interface and residual electricity/NG boundaries are explicitly scoped.

## Generated Tables

- `data/03_Optimisation/inputs/assets/steel/S4/c5_anchor_route_diagnostics/c5_anchor_reconciliation_matrix.csv`
- `data/03_Optimisation/inputs/assets/steel/S4/c5_anchor_route_diagnostics/c5_reconciliation_decision_register.csv`
- `data/03_Optimisation/inputs/assets/steel/S4/c5_anchor_route_diagnostics/c5_final_product_denominator_diagnostics.csv`
- `data/03_Optimisation/inputs/assets/steel/S4/c5_anchor_route_diagnostics/c5_route_origin_and_scrap_diagnostics.csv`
- `data/03_Optimisation/inputs/assets/steel/S4/c5_anchor_route_diagnostics/c5_utility_readiness_diagnostics.csv`
