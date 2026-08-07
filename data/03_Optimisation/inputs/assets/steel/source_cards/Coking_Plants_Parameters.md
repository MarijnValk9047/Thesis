# Coking plant, COG and WAG parameter note

**Scope:** Tata Steel IJmuiden-inspired coking-plant representation for the steel MILP physical/economic input layer.
**Status:** candidate parameter note; not an approved executable input table.
**Last updated:** 2026-06-29.
**Main use:** source-backed assumptions for KGF/COG/WAG modelling, especially KGF self-use of coke oven gas and surplus COG allocation.

## 1. Core modelling conclusion

For the base Tata-inspired C0/C1 steel model, the coking plant should be represented as a mostly continuous, production-coupled process rather than a day-ahead price-responsive flexibility asset.

The relevant process logic is:

```text
coal input
  -> KGF / coke ovens
  -> coke output + raw coke oven gas
  -> gas cleaning
  -> clean coke oven gas (COG)
  -> priority internal KGF underfiring demand
  -> surplus COG to other site users, gas mixing, boilers / steam, Vattenfall interface, storage, or flare/spill
```

The key numerical insight is that typical COG production is larger than the KGF's own oven-heating demand:

```text
COG produced:          7.2-9.0 GJ/t coke
KGF underfiring demand: 3.2-3.9 GJ/t coke
COG surplus:           approximately 3.3-5.8 GJ/t coke
```

So the KGF heat demand can in principle be supplied fully by cleaned COG, but the coke plant is not an unlimited sink for WAG. Surplus COG should remain a scarce internal gas-network product.

## 2. Source hierarchy ordered by relevance, usability and certainty

| Rank | Source | Relevance for this parameter set | Usability for model inputs | Certainty / caveat |
|---:|---|---|---|---|
| 1 | **Haskoning Nederland B.V. / Tata Steel IJmuiden B.V. (2025). _MER Heracless - Groen Staal, Deel B: Technische beschrijving_. Definitief, 15 September 2025.** URL: https://www.tatasteelnederland.com/sites/default/files/mer-groen-staal-deel-b-technische-beschrijving.pdf | Best public Tata/IJmuiden-specific source for topology, KGF1/KGF2 operation, KGF2 closure, KGF production volumes, gas cleaning, product-gas use, and Heracless energy-system effects. | High for topology, annual validation anchors, and base-case operating logic. | High for public project scope; low for detailed conversion coefficients because it does not provide full per-ton COG/steam/electricity conversion tables. |
| 2 | **Remus, R., Aguado Monsonet, M. A., Roudier, S., & Delgado Sancho, L. (2013). _Best Available Techniques (BAT) Reference Document for Iron and Steel Production_. European Commission Joint Research Centre, EUR 25521 EN. DOI: 10.2791/97469.** URLs: https://publications.jrc.ec.europa.eu/repository/handle/JRC69967 and https://bureau-industrial-transformation.jrc.ec.europa.eu/sites/default/files/2019-11/IS_Adopted_03_2012.pdf | Best technical source for coke oven conversion values: coal input, COG yield, LHV, underfiring energy, steam, electricity and CO2 ranges. | High for generic EU candidate input ranges. | High technical authority, but generic EU range; not Tata-specific and BREF warns against blind benchmarking from broad ranges. |
| 3 | **Bieda, B., Grzesik, K., Sala, D., & Gaweł, B. (2015). _Life cycle inventory processes of the integrated steel plant (ISP) in Krakow, Poland - coke production, a case study_. The International Journal of Life Cycle Assessment, 20(8), 1089-1101. DOI: 10.1007/s11367-015-0904-9.** URL: https://doi.org/10.1007/s11367-015-0904-9 and accessible metadata/full-text page: https://www.researchgate.net/publication/277962814_Life_cycle_inventory_processes_of_the_integrated_steel_plant_ISP_in_Krakow_Poland-coke_production_a_case_study | Academic LCI case for coke production with a 1 Mg coke functional unit. Useful cross-check for coal input, COG consumption, electricity and steam. | Medium-high as academic validation/sensitivity source. | Peer-reviewed but non-Tata, older 2004 Krakow case; scope may differ from Tata IJmuiden. |
| 4 | **Ge, X., et al. (2016). _Greenhouse-Gas Emissions by the Chinese Coking Industry_. Polish Journal of Environmental Studies, 25(2), 593-598. DOI: 10.15244/pjoes/61065.** URL: https://www.pjoes.com/Greenhouse-Gas-Emissions-by-the-Chinese-Coking-Industry%2C61065%2C0%2C2.html and PDF: https://www.pjoes.com/pdf-61065-23683?filename=Greenhouse-Gas-Emissions.pdf | Useful for GHG intensity, fuel-gas-type effects, COG composition/carbon content, and load-rate/coking-time effects. | Medium for emissions and ramping/load sensitivity. | Peer-reviewed but Chinese coking-industry context; use as sensitivity/interpretation, not Tata truth. |
| 5 | **Athanasiadis, I. (2025). _Modeling the Energy Transition of an Integrated Steel Site: The Case of Tata Steel's IJmuiden Site_. MSc thesis, TU Delft.** Local project file: `Master_Thesis_Report_Athanasiadis (1).pdf` | Useful as Tata-inspired modelling precedent for WAG/gas-network architecture and gas-mixing simplification. | Medium for modelling structure; low for directly approved values because public version contains redactions and model-specific assumptions. | Use as precedent and architecture context, not as independent public Tata operating truth. |

## 2026 source repair update - Radó-Fóty et al. 2025 real-plant LCI candidates

This update adds reviewed coke-production LCI candidates from Radó-Fóty et al.
(2025). It is a source-card repair only: no row below is an executable input,
Tata IJmuiden measurement, or thesis-approved value. The original article was
not locally inspected in this repository during this repair, so page/table
locators remain non-verified and all values carry the
`value_from_reviewed_research_note_not_locally_verified` caveat.

| Parameter ID | Value / range | Unit | Original basis | Converted basis / derivation | Status label | Recommended model use | Source title, authors, year, URL/DOI | Locator status | Caveat |
|---|---:|---|---|---|---|---|---|---|---|
| `KGF_COAL_BLEND_T_PER_T_COKE` | 1.39 | t coal blend/t coke | Overall inputs and outputs per 1 t coke, scenario 1 | source unit retained | source_backed_candidate | development_input_candidate or sensitivity_range | Radó-Fóty, Domokos, Nagy, Sebestyén and Egedy (2025), *Life cycle assessment of coke production based on real plant and model-optimised data*, International Journal of Life Cycle Assessment 30, 2203-2220, https://doi.org/10.1007/s11367-025-02455-6 | source_locator_not_verified_in_repo | Hungarian real-plant LCI, not Tata IJmuiden; compare with existing BREF/Tata candidate; value_from_reviewed_research_note_not_locally_verified. |
| `KGF_COG_FOR_HEATING_GJ_PER_T_COKE` | 4.30 | GJ/t coke | COG for coke-oven heating | source unit retained | source_backed_candidate | development_input_candidate for coking underfiring candidate | Radó-Fóty et al. (2025), DOI above | source_locator_not_verified_in_repo | Use as self-use/underfiring candidate; do not also treat the same gas energy as surplus. |
| `KGF_COG_FOR_TRADING_GJ_PER_T_COKE` | 3.74 | GJ/t coke | COG for trading / outside-coking use in source | source unit retained | source_backed_candidate | WAG surplus sanity check | Radó-Fóty et al. (2025), DOI above | source_locator_not_verified_in_repo | In this thesis, "trading" is only candidate clean COG available to the site WAG network, not external revenue. |
| `KGF_ELECTRICITY_PURCHASED_GJ_PER_T_COKE` | 0.24 | GJ/t coke | Purchased electricity per t coke | 0.24 / 3.6 = 0.0667 MWh/t = 66.7 kWh/t | source_backed_candidate | development_input_candidate for external/purchased electricity candidate | Radó-Fóty et al. (2025), DOI above | source_locator_not_verified_in_repo | Non-Tata boundary and CDQ/recovery context may differ. |
| `KGF_ELECTRICITY_PRODUCED_GJ_PER_T_COKE` | 0.11 | GJ/t coke | Internally produced electricity per t coke | 0.11 / 3.6 = 0.0306 MWh/t = 30.6 kWh/t | context_only or sensitivity_only | validation/context if CDQ or internal recovery is explicitly represented | Radó-Fóty et al. (2025), DOI above | source_locator_not_verified_in_repo | Do not net against purchased electricity unless internal recovery is modelled. |
| `KGF_ELECTRICITY_GROSS_SERVICE_GJ_PER_T_COKE` | 0.35 | GJ/t coke | Purchased 0.24 + produced 0.11 GJ/t | 0.35 / 3.6 = 0.0972 MWh/t = 97.2 kWh/t | derived_candidate | sensitivity_range / gross auxiliary demand candidate | Derived from Radó-Fóty et al. (2025) values | source_locator_not_verified_in_repo | Use only if modelling gross demand before internal recovery. |
| `KGF_STEAM_PURCHASED_GJ_PER_T_COKE` | 0.33 | GJ/t coke | Purchased steam per t coke | source unit retained | source_backed_candidate | sensitivity_range / steam demand check | Radó-Fóty et al. (2025), DOI above | source_locator_not_verified_in_repo | Steam-network relevance depends on source boundary and Tata steam topology. |
| `KGF_STEAM_PRODUCED_GJ_PER_T_COKE` | 1.73 | GJ/t coke | Produced steam per t coke | source unit retained | context_only | recovery context only unless CDQ/heat recovery is represented | Radó-Fóty et al. (2025), DOI above | source_locator_not_verified_in_repo | Do not create steam credit unless recovery technology is explicitly modelled. |
| `KGF_STEAM_GROSS_SERVICE_GJ_PER_T_COKE` | 2.06 | GJ/t coke | Purchased 0.33 + produced 1.73 GJ/t | 0.33 + 1.73 = 2.06 GJ/t | derived_candidate | sensitivity_range only | Derived from Radó-Fóty et al. (2025) values | source_locator_not_verified_in_repo | Not Tata-specific; do not impose without steam-network review. |
| `KGF_DIRECT_CO2_T_PER_T_COKE_AGGREGATE` | 0.4595 | tCO2/t coke | Aggregate direct/process CO2 from source note | source unit retained | source_backed_candidate | aggregate CO2 validation/sensitivity | Radó-Fóty et al. (2025), DOI above | source_locator_not_verified_in_repo | High double-counting risk if COG carbon is later counted at boilers/generators; use either aggregate KGF counter or WAG-explicit combustion, not both. |

Contextual repair notes:

- The reviewed note reports CDQ-produced electricity covering approximately
  30-40% of plant electricity demand and produced steam covering approximately
  70-80% of steam needs. Treat this as context unless Tata-specific CDQ/heat
  recovery is explicitly modelled.
- Do not combine Radó-Fóty `COG_FOR_TRADING` with an independently modelled COG
  generation coefficient unless the source-card explicitly reconciles gross COG
  production, coking self-use and clean COG surplus.
- Do not use Radó-Fóty aggregate CO2 together with WAG-explicit COG combustion
  in a consolidated CO2 total.

## 3. Candidate parameter table

### 3.1 High-priority base-case parameters

| Parameter ID | Parameter | Candidate value / range | Suggested central value | Unit | Source basis | Model use | Status and caveat |
|---|---|---:|---:|---|---|---|---|
| `KGF_COKE_TIME_H` | Coking time | 18-22 | 20 | h | MER Heracless, Section 3.2.4 | Physical continuity / no hourly DR asset | Tata-specific public process description; not a ramp limit. |
| `KGF_COKE_TEMP_C` | Coking temperature | approximately 1000 | 1000 | °C | MER Heracless, Section 3.2.4 | Descriptive process condition | Not an optimisation variable. |
| `KGF1_COKE_OUTPUT_C0_C1` | KGF1 coke production | 1.0 | 1.0 | Mt coke/y | MER Heracless, Table 5.1 | C0/C1 annual anchor | Tata-specific public anchor. Use as validation or annual scaling, not hourly dispatch truth. |
| `KGF2_COKE_OUTPUT_C0` | KGF2 coke production in reference situation | 0.8 | 0.8 | Mt coke/y | MER Heracless, Table 5.1 | C0 annual anchor | Tata-specific public anchor. |
| `KGF2_COKE_OUTPUT_C1` | KGF2 coke production with Heracless | 0 | 0 | Mt coke/y | MER Heracless, Table 5.1 and Heracless description | C1 closure logic | Base C1 topology: KGF2 closed. |
| `COG_CLEANING_REQUIRED` | Raw COG must be cleaned before normal fuel use | true | true | Boolean | MER Heracless, Section 3.2.4; JRC BREF coke ovens chapter | Topology / carrier distinction | Distinguish `raw_COG` and `clean_COG`; do not use raw COG as normal fuel. |
| `COG_TO_KGF_UNDERFIRING_PRIORITY` | KGF underfiring is priority internal COG demand | true | true | Boolean | MER Heracless states cleaned gas is used to heat coke ovens; KGF2 shutdown text supports COG-only operational reading | WAG allocation priority | Treat as priority self-consumption before surplus allocation. |
| `KGF_BASECASE_COG_ONLY_UNDERFIRING` | Tata-inspired basecase does not allow free BFG/BOFG/NG substitution in KGF ovens | `BFG=0`, `BOFG=0`, `NG=0` unless sensitivity | 0 | GJ/h to KGF underfiring from non-COG gases | MER Heracless KGF2 shutdown logic; generic BREF allows broader designs, so this is Tata-inspired not universal | Prevent fake flexibility | Use as base-case assumption. Reopen only as explicit burner/gas-system sensitivity. |

### 3.2 Conversion coefficients per tonne coke

| Parameter ID | Parameter | Candidate value / range | Suggested central value | Unit | Source basis | Model use | Status and caveat |
|---|---|---:|---:|---|---|---|---|
| `DRY_COAL_PER_COKE_TPT` | Dry coal input per tonne coke | 1.22-1.35 | 1.285 | t dry coal / t coke | JRC BREF, Table 5.2 | Coal-to-coke input coefficient | Strong generic EU candidate; compare with Bieda 1.35 t/t. |
| `COG_YIELD_NM3_PER_T_COKE` | Clean COG volume yield | 360-518 | 439 | Nm3/t coke | JRC BREF, Table 5.2 | WAG generation coefficient | Strong generic candidate. Ensure Nm3 basis is consistent. |
| `COG_LHV_MJ_PER_NM3` | COG lower heating value | 17-20 | 18 | MJ/Nm3 | JRC BREF, Table 5.1/5.2; Ge et al. | Volume-to-energy conversion | Use one convention consistently; central 18 MJ/Nm3. |
| `COG_YIELD_GJ_PER_T_COKE` | COG energy yield | 7.2-9.0 | 8.1 | GJ/t coke | JRC BREF, Table 5.2 | WAG energy balance | Preferred energy-basis coefficient for MILP. |
| `KGF_UNDERFIRING_GJ_PER_T_COKE` | Coke oven underfiring / heat demand | 3.2-3.9 | 3.55 | GJ/t coke | JRC BREF, Table 5.2, reported as BF gas + COG for coke oven firing | Priority internal KGF fuel demand | Strong candidate. In Tata basecase supply with COG. |
| `KGF_UNDERFIRING_NM3_COG_PER_T_COKE` | COG volume required for KGF underfiring | approximately 178-229 | approximately 197 | Nm3/t coke | Derived from `KGF_UNDERFIRING_GJ_PER_T_COKE / COG_LHV_MJ_PER_NM3` | Useful for volume-basis gas balance | Derived, not direct source value. Bieda 195 m3/t is an independent plausibility check. |
| `COG_SELF_USE_SHARE_ENERGY` | Share of produced COG energy needed for KGF self-use | approximately 36-54 | approximately 44 | % | Derived from JRC BREF COG yield and underfiring ranges | Diagnostic / allocation sanity check | Derived; do not impose exact share if using energy coefficients directly. |
| `COG_SURPLUS_GJ_PER_T_COKE` | Surplus COG after KGF underfiring | approximately 3.3-5.8 | 4.55 | GJ/t coke | Derived: COG yield minus underfiring demand | Surplus WAG for other sinks | Derived. Use only after priority self-consumption. |
| `KGF_ELECTRICITY_KWH_PER_T_COKE` | Coke plant electricity consumption | 5.6-63.9 | 35-55 as practical initial sensitivity | kWh/t coke | JRC BREF: 20-230 MJ/t coke | Electricity load estimate | Broad range; scope can vary. Do not use for flexibility unless backed by operating data. |
| `KGF_STEAM_ENERGY_MJ_PER_T_COKE` | Steam input energy | 60-800; old plants up to 1200 | no single base value | MJ/t coke | JRC BREF, Table 5.2 | Utility demand / sensitivity | Wide range. Convert to t steam only with pressure/enthalpy assumption. |
| `KGF_STEAM_MASS_T_PER_T_COKE` | Steam mass input | 0.27-0.384 | 0.33 | t steam/t coke | Bieda et al. 2015; non-Tata LCI | Utility cross-check | Useful if steam is modelled on mass basis; not Tata-specific. |

### 3.3 Academic cross-check parameters

| Parameter ID | Parameter | Candidate value | Unit | Source basis | Model use | Status and caveat |
|---|---|---:|---|---|---|---|
| `BIEDA_COAL_PER_COKE_TPT` | Coal input in Krakow LCI case | 1.35 | Mg coal/Mg coke | Bieda et al. 2015 | Cross-check for coal input | Academic, site-specific to Krakow, upper side of JRC range. |
| `BIEDA_COG_CONSUMPTION_M3_PER_T_COKE` | COG consumed in Krakow LCI case | 195 | m3/Mg coke | Bieda et al. 2015 | Plausibility check for derived KGF underfiring volume | Very close to derived central value ~197 Nm3/t. Confirm normalisation before direct use. |
| `BIEDA_ELECTRICITY_KWH_PER_T_COKE_CDQ` | Electricity use in Bieda CDQ-related case | 37.56 | kWh/t coke | Bieda et al. 2015 | Electricity sensitivity/cross-check | Not Tata-specific; scope can differ. |
| `BIEDA_ELECTRICITY_KWH_PER_T_COKE_PERMIT_RANGE` | Permit-like electricity range in Bieda discussion | 65.4-112.1 | kWh/t coke | Bieda et al. 2015 | High-scope sensitivity | Likely includes different boundary/utility treatment; do not use as base without scope match. |
| `BIEDA_STEAM_T_PER_T_COKE` | Steam input in Bieda case | 0.27 | Mg steam/Mg coke | Bieda et al. 2015 | Steam cross-check | Non-Tata. |

### 3.4 Emissions and carbon-accounting parameters

| Parameter ID | Parameter | Candidate value / range | Suggested central value | Unit | Source basis | Model use | Status and caveat |
|---|---|---:|---:|---|---|---|---|
| `KGF_DIRECT_CO2_BREF_KG_PER_T_COKE` | Direct coke oven CO2 emissions | 160-860 | no single base value | kgCO2/t coke | JRC BREF, Table 5.2 | Reporting / sensitivity | Very broad range; depends on fuel gas, plant condition and accounting boundary. |
| `KGF_DIRECT_CO2_NORMAL_KG_PER_T_COKE` | Normal-operation coking plant CO2 intensity | 150-250 | 200 | kgCO2/t coke | Ge et al. 2016 | Reporting / sensitivity | Non-Tata, useful normal-operation check. |
| `COG_CARBON_CONTENT_GC_PER_MJ` | Carbon content of COG | approximately 10 | 10 | gC/MJ COG | Ge et al. 2016 | Carbon-in-gas and later combustion accounting | Use for carbon carried in COG, not necessarily direct KGF emissions. |
| `COG_CO2_POTENTIAL_KG_PER_T_COKE` | CO2 potential if produced COG is later combusted | approximately 264-330 | 297 | kgCO2/t coke | Derived: 7.2-9.0 GJ/t * 10 gC/MJ * 44/12 | Emissions accounting check | This is carbon in COG. Do not also count fully as direct KGF emission if COG is burned later elsewhere. |
| `NO_DOUBLE_COUNT_COG_CARBON` | COG carbon counted once | true | true | Boolean | Accounting principle from WAG/carbon boundary logic | Prevents double counting | Count carbon at generation OR at combustion according to selected boundary, not both. |

### 3.5 Load/ramping and operational flexibility interpretation

| Parameter ID | Parameter | Candidate value / range | Unit | Source basis | Model use | Status and caveat |
|---|---|---:|---|---|---|---|
| `KGF_HOURLY_DA_FLEX_ENABLED` | KGF as hourly DA flexibility asset | false | Boolean | MER Heracless continuity and KGF/HO coupling; Ge et al. load/coking-time evidence | Model policy | Basecase should not dispatch KGF hourly against DA prices. |
| `KGF_COKING_TIME_LOW_LOAD_H` | Coking time under strong load reduction | >30, sometimes >80 | h | Ge et al. 2016 | Sensitivity / shutdown or low-load scenario | Supports modelling load changes as slow day/week-scale effects, not hourly ramping. |
| `KGF_OPERATIONAL_FLEX_C1` | Heracless operational flexibility for KGF1 | fixed 1.0 | Mt/y | MER Heracless, Table 5.1 | C1 anchor | MER table lists no flexibility band for KGF1; use as fixed anchor unless a sensitivity is explicitly opened. |
| `COG_FLARE_OR_SPILL_ALLOWED` | COG flare/spill route | allowed only as explicit reported route with penalty | Boolean/policy | MER shutdown/flaring logic; project WAG policy | Feasibility and safety sink | Must not be free slack or hidden revenue. |

### 3.6 Gas mixing and allocation parameters

| Parameter ID | Parameter | Candidate value / rule | Unit | Source basis | Model use | Status and caveat |
|---|---|---|---|---|---|---|
| `COG_TO_MIXING_STATION_ALLOWED` | Clean COG may feed a mixed-gas station or internal product-gas network | yes, after KGF self-use | Boolean/policy | MER Heracless energy-company/product-gas description; JRC BREF integrated steel gas use; Athanasiadis modelling precedent | WAG allocation | Allow surplus clean COG to be allocated to mixed gas only after priority KGF self-use. |
| `WOBBE_CONSTRAINT_ACTIVE_FIRST_LP` | Explicit Wobbe-index constraint | false initially | Boolean | Athanasiadis modelling caveat; practical LP tractability | First LP simplification | Use energy-basis allocation first; add share/LHV/Wobbe constraints later only if needed. |
| `DIRECT_WAG_MARKET_VALUE_ALLOWED` | Direct electricity-market valuation of WAG | false | Boolean | Project WAG policy and physical conversion logic | Economic policy | Value WAG only via useful-energy substitution or explicit conversion/interface. |

### 3.7 Active C1 temporal route-scale reconciliation

The public `KGF1_COKE_OUTPUT_C0_C1 = 1.0 Mt/y` value is an annual validation
anchor, not an independently evidenced technical hourly minimum. In the active
C1 fixed-reference temporal model, the KGF1 development floor is reconciled to
the active BOF route scale:

```text
route_scale = 3,329,952.026 / 3,400,000
route_scaled_KGF1_coke = 1,000,000 * route_scale
dry_coal_floor = route_scaled_KGF1_coke * dry_coal_per_coke / 8,760
               = 143.667350012 t dry coal/h
```

This is labelled
`route_scaled_fixed_reference_development_floor_not_technical_minimum`. KGF1
remains continuous/must-run and its existing 180 t dry-coal/h upper bound is
unchanged. The reconciliation prevents the raw annual KGF1 anchor from being
combined with a smaller fixed-reference BOF route as though both described the
same physical scale. It does not establish an hourly Tata operating limit and
must not be used as such outside this explicit deterministic development
contract.

## 4. Derived annual C0/C1 estimates

These annual estimates are useful for validation and reporting only. They should not be converted into hard hourly dispatch without explicit availability and annual-to-hourly methodology.

| Configuration | Coke production | COG output | KGF self-use / underfiring | Surplus COG after self-use | Interpretation |
|---|---:|---:|---:|---:|---|
| `C0_current_BF_BOF_reference` | 1.8 Mt coke/y | 13.0-16.2 PJ/y; central 14.6 PJ/y | 5.8-7.0 PJ/y; central 6.4 PJ/y | 5.9-10.4 PJ/y; central 8.2 PJ/y | KGF1 + KGF2 active. COG surplus remains available for other WAG sinks after self-use. |
| `C1_phase1_hybrid_BF_BOF_NG_DRP_EAF` | 1.0 Mt coke/y | 7.2-9.0 PJ/y; central 8.1 PJ/y | 3.2-3.9 PJ/y; central 3.55 PJ/y | 3.3-5.8 PJ/y; central 4.55 PJ/y | KGF1 retained, KGF2 closed. Less COG available to the rest of the site. |

## 5. Recommended first implementation in the MILP

Use energy units internally for COG in the first implementation.

```text
clean_COG_produced[t] = coke_output[t] * COG_YIELD_GJ_PER_T_COKE

COG_to_KGF_underfiring[t] = coke_output[t] * KGF_UNDERFIRING_GJ_PER_T_COKE

clean_COG_surplus[t] =
    clean_COG_produced[t]
  - COG_to_KGF_underfiring[t]
```

Recommended central values:

```text
COG_YIELD_GJ_PER_T_COKE       = 8.10
KGF_UNDERFIRING_GJ_PER_T_COKE = 3.55
COG_SURPLUS_GJ_PER_T_COKE     = 4.55
DRY_COAL_PER_T_COKE           = 1.285
COG_LHV_MJ_PER_NM3            = 18.0
```

Base-case routing restrictions:

```text
raw_COG_to_fuel_sinks[t] = 0
BFG_to_KGF_underfiring[t] = 0
BOFG_to_KGF_underfiring[t] = 0
NG_to_KGF_underfiring[t] = 0
COG_flare[t] >= 0, explicitly reported and penalised
```

## 6. What should not be claimed

Do not claim that:

- these values are exact Tata Steel operating coefficients;
- KGF can act as an hourly DA-responsive flexible asset;
- all WAG can or should be pushed into the coke ovens;
- COG has direct electricity-market value without an explicit conversion/interface path;
- COG carbon can be counted as direct KGF emission and then counted again at later combustion.

The most defensible thesis wording is:

> The public Tata-specific sources support the topology, KGF1/KGF2 production anchors, gas-cleaning logic and the qualitative priority of cleaned COG for coke-oven heating. Generic EU BREF and academic LCI literature provide candidate conversion coefficients. These coefficients are used as reviewed candidate assumptions and sensitivity ranges, not as confidential Tata truth.

## C0 temporal development status (2026-08-05)

For the maintenance-excluded C0 temporal development model, KGF1 and KGF2 use
four-hour setpoints with at most 3 t/h change per setpoint. KGF2 inherits this
only as controlled symmetry with KGF1. These are development constraints, not
measured Tata control limits. In the accepted high-volatility example week both
plants remain at the existing 150-t/h lower bound. The resulting annualised
coke output is about 21.2% above the 6.75/7.2-scaled comparison anchor. This is
retained as a source-contract gap; neither minimum nor anchor is silently tuned.

### Superseding C0 development reconciliation (2026-08-05)

Run `c0_c1_downstream_contract_week_20260805_16` supersedes the preceding C0
example-week interpretation. The former 150--180 t/h ranges were not verified
technical capacities and mixed the C1 coke/hot-metal recipe into C0. The C0
development model now uses a governed 120--140 t/h operating envelope for
KGF1 and KGF2 and a C0-specific annual reconciliation of 0.285714 t coke per
t represented BF6/BF7 hot metal. Both values are labelled anchor-derived
development assumptions, not Tata operating limits or technology recipes.

The selected week keeps both coke plants at 120 t/h and annualises coke output
to 1.636 Mt/y, 3.05% below the scaled 1.6875-Mt/y comparison anchor. This
removes the earlier artificial 21.2% excess without claiming empirical plant
flexibility; measured minimum stable loads and ramp/setpoint data remain an
evidence need.

### Hourly annual route-reconciliation evidence gap (2026-08-06)

The active hourly C1 contract retains the route-scaled dry-coal reference with
an absolute one-ton annual reconciliation tolerance. In the D-only
perfect-foresight year, this combines with exact material balances and terminal
recovery to create a proven day-352 conflict of 0.618331 t coke over the final
336 hours. The public rounded ratio is 0.294118 t coke/t BOF liquid steel,
whereas the active recipe implies 0.295816 t/t, a 0.57744% difference. A
10-ppm diagnostic sensitivity closes the year, but is not active
because it changes an annual route tolerance and has no separate source basis.
This is therefore an explicit methodology decision point, not evidence for a
technical KGF1 production tolerance.
