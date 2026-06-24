WAG Source-Card Register — S3.0b Candidate Evidence Only
Status of this register: discovery-to-source-card conversion draft.
Stage: S3.0b WAG diagnostic evidence preparation.
Use status: candidate evidence only; no approved model inputs.
Rule: the discovery memo may be linked as provenance, but the primary evidence source for any coefficient must be the source card and the underlying public document.
Register-level stage decision
Before any WAG coefficient is used in code, config, or approved input tables:
1.	every coefficient must point to a source_card_id;
2.	every source_card_id must contain stable bibliographic information;
3.	every extracted value must state exact unit, basis, carrier, locator, confidence, and review status;
4.	candidate values remain non-executable until promoted through a separate approval step;
5.	Tata/Vattenfall/MER interface sources may support topology, validation, and caveats, but not exact dispatch or contract rules;
6.	public annual or scenario anchors must not be treated as hourly operational truth;
7.	source-card review must be performed on the primary source, not on the deep-research report.
________________________________________
Source cards
WAG-SC-001 — JRC Iron and Steel BREF
•	Source title: Best Available Techniques (BAT) Reference Document for Iron and Steel Production
•	Organisation: European Commission Joint Research Centre, European IPPC Bureau
•	Authors/editors: Rainer Remus, Miguel A. Aguado-Monsonet, Serge Roudier, Luis Delgado Sancho
•	Publication year: 2013; BAT conclusions adopted 2012
•	Identifier: Report EUR 25521 EN; JRC 69967; DOI 10.2791/97469; Industrial Emissions Directive 2010/75/EU
•	Stable URL: https://bureau-industrial-transformation.jrc.ec.europa.eu/sites/default/files/2019-11/IS_Adopted_03_2012.pdf
•	Main locators:
o	Table 5.1, raw coke oven gas yield and composition
o	Table 5.2, input/output data from coke oven plants
o	Chapter 6, BF gas text and Table 6.2 / Table 6.8
o	Table 7.5, BOF gas composition and characteristics
o	Table 7.6, suppressed-combustion BOF gas flow
•	Extracted values and exact basis:
o	BFG generation: 1200–2000 Nm³/t hot metal; blast-furnace gas production basis
o	BFG energy: 3377–6061 MJ/t hot metal; BF gas output energy basis
o	BFG LHV: 2.7–4.0 MJ/Nm³; BF gas heating value basis
o	COG raw yield: 280–450 m³/t dry coal; raw gas from coking basis
o	COG direct coke-basis yield: 360–518 Nm³/t coke; COG output basis
o	COG LHV: 17.4–20 MJ/Nm³ in Table 5.1, and 17,000–18,000 kJ/Nm³ in Table 5.2
o	BOFG/LDG generation: 50–100 Nm³/t liquid steel in suppressed combustion text; 50–120 Nm³/t liquid steel in Table 7.6
o	BOFG/LDG LHV: 7100–10100 kJ/Nm³, average 9580 kJ/Nm³; downstream of gas holder / recovered BOF gas basis
o	BOFG/LDG composition: CO average 72.5 vol-%, H₂ 3.3 vol-%, CO₂ 16.2 vol-%, N₂+Ar 8.0 vol-%
•	Confidence: high for generic EU-sector ranges
•	Review status: extracted_from_primary_source; needs second reviewer before promotion
•	Stage decision: candidate_range for BFG/COG/BOFG generation and LHV; not approved model input
•	Main caveat: EU sector-level range, not Tata-specific; do not convert annual or table values into hourly caps without translation assumptions.
WAG-SC-002 — EU ETS Guidance Document 8, Waste Gases and Process Emissions
•	Source title: Guidance Document n°8 on the harmonised free allocation methodology for the EU ETS — Waste gases and process emissions sub-installation
•	Organisation: European Commission, Directorate-General Climate Action
•	Publication year: 2024 revision; final version issued 28 March 2024
•	Identifier: EU ETS FAR Guidance Document 8
•	Stable URL: https://climate.ec.europa.eu/document/download/8ed1815d-3408-4f3d-9286-efb7618ee307_en?filename=8_gd8_waste_gases_process_emissions_en.pdf&prefLang=pt
•	Main locators:
o	Section 1.1, scope
o	Chapter 4, allocation in case of production and consumption of waste gases
o	Section around HALWasteGas formula
o	Sections around Corrη and natural-gas reference
•	Extracted values and exact basis:
o	Natural gas reference EF in allocation formula: 56.1 tCO₂/TJ
o	Corrη default correction factor: 0.667
o	Values are FAR/free-allocation methodology values, not physical boiler or process substitution coefficients
•	Confidence: high for EU ETS allocation-convention interpretation
•	Review status: extracted_from_primary_source; not executable
•	Stage decision: assumption_only / accounting_convention; do not use as a physical efficiency coefficient
•	Main caveat: guidance is not legally binding and is about allocation methodology, not optimisation physics.
WAG-SC-003 — EU ETS Monitoring and Reporting Regulation
•	Source title: Commission Implementing Regulation (EU) 2018/2066 on monitoring and reporting of greenhouse gas emissions
•	Organisation: European Commission; accessed via Energy Community consolidated/adapted version
•	Publication year: 2018; Energy Community adaptation applies from 2024 in opened version
•	Identifier: Commission Implementing Regulation (EU) 2018/2066; MRR
•	Stable URL: https://www.energy-community.org/dam/jcr%3Aaf029ec5-13d3-4b10-a754-ddf890ce6814/IMPLEMENTING_REGULATION_EU_2018_2066.pdf
•	Main locators:
o	Article 3 definitions: source stream, emission source, emission factor, net calorific value, inherent CO₂
o	Article 48, inherent CO₂
o	Article 49, transfer of CO₂
o	Annex IV, production of pig iron and steel
o	Annex VI default factors
o	Flares section
•	Extracted values and exact basis:
o	Inherent CO₂ in waste gases, including blast furnace and coke oven gas, must be included in the emission factor for the source stream
o	Pig iron and steel monitoring scope includes process gases such as COG, BFG and BOFG
o	Annex VI default factors include COG 44.4 tCO₂/TJ and BFG 260 tCO₂/TJ
o	Flaring rules include routine and operational flaring and inherent CO₂
•	Confidence: high for legal/accounting boundary
•	Review status: extracted_from_primary_source; use for accounting rule, not coefficient approval
•	Stage decision: validation_target / accounting_rule
•	Main caveat: legal MRV rules must be translated carefully into model-boundary accounting; they do not specify plant dispatch or WAG allocation.
WAG-SC-004 — EU ETS FAR Monitoring and Reporting Guidance
•	Source title: Guidance on Monitoring and Reporting in Relation to the Free Allocation Rules
•	Organisation: European Commission, Directorate-General Climate Action
•	Publication year: 2024 revision
•	Identifier: EU ETS FAR Guidance Document 5
•	Stable URL: https://climate.ec.europa.eu/document/download/91ac02da-9b82-4b08-9d8a-9ebf4aa31638_en?filename=5_gd5_mnr_guidance_for_far_en.pdf&prefLang=sv
•	Main locators:
o	Section around integrated steel plant “bubble” approach
o	Section 6.15, rules for waste gases
o	Waste-gas attribution examples and tables
•	Extracted values and exact basis:
o	In an integrated steel plant monitored under one mass-balance bubble, coke and waste gases may not need to be monitored separately if the coal entering the coke oven is monitored
o	Waste gases are source streams like other fuels
o	Inherent CO₂ in the waste-gas stream is accounted for through the emission factor
o	Export/import waste-gas attribution examples distinguish producer, consumer and boundary treatment
•	Confidence: high for accounting-architecture design
•	Review status: extracted_from_primary_source; not executable
•	Stage decision: accounting_rule / validation_target
•	Main caveat: supports no-double-counting design, not physical WAG coefficient values.
WAG-SC-005 — IPCC 2006 Metal Industry Guidelines
•	Source title: 2006 IPCC Guidelines for National Greenhouse Gas Inventories, Volume 3, Chapter 4: Metal Industry Emissions
•	Organisation: IPCC National Greenhouse Gas Inventories Programme
•	Publication year: 2006
•	Identifier: 2006 IPCC Guidelines, Volume 3, Chapter 4
•	Stable URL: https://www.ipcc-nggip.iges.or.jp/public/2006gl/pdf/3_Volume3/V3_4_Ch4_Metal_Industry.pdf
•	Main locators:
o	Section on coke production and iron/steel production completeness
o	Text around double counting or omission across coke production, energy sector and IPPU
•	Extracted values and exact basis:
o	Warning that coke production and iron/steel production create risks of double counting or omission
o	Carbon consumed as COG or BFG must be attributed consistently across coke, steel and energy categories
•	Confidence: high for inventory-boundary logic
•	Review status: extracted_from_primary_source; not executable
•	Stage decision: accounting_rule / validation_target
•	Main caveat: inventory accounting guidance, not an optimisation formulation.
WAG-SC-006 — IPCC 2019 Refinement, Metal Industry
•	Source title: 2019 Refinement to the 2006 IPCC Guidelines, Volume 3, Chapter 4: Metal Industry Emissions
•	Organisation: IPCC National Greenhouse Gas Inventories Programme
•	Publication year: 2019
•	Identifier: 2019 Refinement, Volume 3, Chapter 4
•	Stable URL: https://www.ipcc-nggip.iges.or.jp/public/2019rf/pdf/3_Volume3/19R_V3_Ch04_Metal_Industry.pdf
•	Main locators:
o	Box 4.0, flaring activities in metallurgical coke and iron/steel production
o	Text around integrated facilities and Tier combinations
•	Extracted values and exact basis:
o	Integrated facilities usually flare a mix of COG, BFG and LDG/converter gas
o	Minor proportion of total gas produced is usually flared; the source mentions usually less than 5%, mainly during emergencies or consumer maintenance
o	Mixed use of Tier 1 and Tier 2/3 methods can double count or underestimate gas flows in integrated plants
•	Confidence: high for flaring and double-counting caveats
•	Review status: extracted_from_primary_source; not executable
•	Stage decision: validation_target / accounting_rule / sensitivity_only for flare-rate sanity checks
•	Main caveat: “less than 5%” is inventory guidance context and should not become a fixed hourly flare cap.
WAG-SC-007 — worldsteel Energy Use Fact Sheet
•	Source title: Energy use in the steel industry
•	Organisation: World Steel Association
•	Publication year: 2021
•	Identifier: Fact sheet; April 2021 | HR/CB/IM
•	Stable URL: https://worldsteel.org/wp-content/uploads/Fact-sheet-energy-in-the-steel-industry-2021-1.pdf
•	Main locators:
o	Page 1, co-product gases section
o	Table 1, energy inputs and applications
•	Extracted values and exact basis:
o	Co-product gases from coke oven, BF and BOF are used as direct fuel substitutes or for electricity generation
o	Co-product gases typically contribute more than 60% of a steel plant’s energy requirements
o	Gases are flared only if no other use option is available
•	Confidence: high for sector-level structural evidence
•	Review status: extracted_from_primary_source; not executable
•	Stage decision: validation_target / structural_evidence
•	Main caveat: fact-sheet statement is not a process-specific generation coefficient.
WAG-SC-008 — worldsteel Raw Materials Fact Sheet
•	Source title: Steel and raw materials
•	Organisation: World Steel Association
•	Publication year: 2023
•	Identifier: Fact sheet; March 2023 | BC
•	Stable URL: https://worldsteel.org/wp-content/uploads/Fact-sheet-raw-materials-2023-1.pdf
•	Main locators:
o	Page 2, responsible management of natural resources / gases section
•	Extracted values and exact basis:
o	Cleaned gases from coke oven, BF and BOF are used internally to produce steam and electricity
o	Internal use reduces externally-produced electricity demand
o	Gases can provide more than 60% of a site’s power
o	Gases are flared only if no other option is available
•	Confidence: high for sector-level structural evidence
•	Review status: extracted_from_primary_source; not executable
•	Stage decision: validation_target for net-import-offset convention
•	Main caveat: supports “reduce import first”, not automatic export revenue.
WAG-SC-009 — JRC/SETIS Prospective Scenarios Report
•	Source title: Prospective Scenarios on Energy Efficiency and CO₂ Emissions in the EU Iron & Steel Industry
•	Organisation: European Commission Joint Research Centre / SETIS
•	Authors: N. Pardo et al.
•	Publication year: 2012
•	Identifier: JRC/SETIS report
•	Stable URL: https://setis.ec.europa.eu/system/files/2021-01/Prospective-Scenarios-on-Energy-Efficiency-and-CO2-Emissions-EU-Iron-Steel-Industry.pdf
•	Main locators:
o	Section discussing steel plant gas power generation
•	Extracted values and exact basis:
o	Most power plants operating on steel plant gases use a boiler plus steam turbine configuration
o	Total average efficiency for conversion from steel plant gases to electricity is stated as 32%
•	Confidence: medium-high for EU-sector power-interface range
•	Review status: extracted_from_primary_source; needs second reviewer
•	Stage decision: candidate_range / sensitivity_only for WAG-to-power diagnostic
•	Main caveat: sector average, not Tata/Vattenfall efficiency.
WAG-SC-010 — IEAGHG Integrated Steel Mill CCS Study
•	Source title: Understanding the Techno-Economics of Deploying CO₂ Capture Technologies in an Integrated Steel Mill
•	Organisation: IEA Greenhouse Gas R&D Programme; study with Swerea MEFOS and partners
•	Publication year: 2013
•	Identifier: IEAGHG 2013-04
•	Stable URL: https://ieaghg.org/publications/2013-04%20Iron%20and%20Steel%20CCS%20Study%20%28Techno-Economics%20Integrated%20Steel%20Mill%29.pdf
•	Main locators:
o	Overview section, integrated steel-mill boundary and off-gas use
o	Appendix / Unit 1200 power plant specifications
o	Power-plant sensitivity cases
o	Off-gas surplus/flaring assumption sections
•	Extracted values and exact basis:
o	Surplus off-gases from the steel mill are used by power/cogeneration plant to produce electricity or steam
o	Base captive power plant net efficiency: 32.1% LHV basis
o	Alternative power plant cases: 37.0%, 39.9%, 42.2%, 41.9% net efficiency
o	Surplus off-gases not used are assumed flared in the study boundary
o	Deficit off-gas can be supplemented by imported natural gas in the study boundary
•	Confidence: medium for generic integrated-steel diagnostic range
•	Review status: extracted_from_primary_source; not Tata-specific
•	Stage decision: sensitivity_only / candidate_range for WAG-to-power; validation_target for no-free-surplus treatment
•	Main caveat: conceptual Western European reference mill; not Tata dispatch or contract truth.
WAG-SC-011 — RVO Netherlands Fuel List
•	Source title: The Netherlands’ list of fuels and standard CO₂ emission factors, version of January 2025
•	Organisation: Netherlands Enterprise Agency (RVO), with Dutch Emission Authority and Emission Register stakeholders
•	Publication year: 2025
•	Identifier: Netherlands fuel list, January 2025
•	Stable URL: https://english.rvo.nl/sites/default/files/2025-02/the-Netherlands-%20list-of-fuels-January-2025.pdf
•	Main locators:
o	Section 1, fuel list table
o	Notes on the fuel list
•	Extracted values and exact basis:
o	Coke oven gas: 42.8 kg CO₂/GJ
o	Blast furnace gas: 247.4 kg CO₂/GJ
o	Oxy gas: 191.9 kg CO₂/GJ
o	Natural gas dry: 56.2–56.3 kg CO₂/GJ and 31.65 MJ/Nm³
o	Unit basis for WAG entries is MJ with NCV 1.0 MJ/MJ
•	Confidence: high for Dutch public reporting factors
•	Review status: extracted_from_primary_source; candidate only
•	Stage decision: candidate_range / reporting_factor for S3 emissions diagnostic
•	Main caveat: country-specific reporting factors, not plant-specific measured gas composition.
WAG-SC-012 — Umweltbundesamt CO₂ Emission Factors
•	Source title: CO₂ Emission Factors for Fossil Fuels
•	Organisation: Umweltbundesamt
•	Publication year: 2019
•	Identifier: Climate Change report; fossil-fuel emission factors
•	Stable URL: https://www.umweltbundesamt.de/system/files/medien/1968/publikationen/co2_emission_factors_for_fossil_fuels_correction.pdf
•	Main locators:
o	Section 6.1, industrial gases / steel gases
•	Extracted values and exact basis:
o	COG emission factors: 40.3–41.8 t CO₂/TJ
o	BFG implied emission factors: 254.9–272 t CO₂/TJ
o	BFG NCV: 3.3–3.6 MJ/m³
o	BOFG implied emission factors: 188.6–195.1 t CO₂/TJ
o	BOFG NCV: 8.1–8.5 MJ/m³
o	Source notes that BFG and BOFG are normally combusted as mixtures and natural gas may be added depending on gas quality
•	Confidence: medium-high for corroboration and sensitivity ranges
•	Review status: extracted_from_primary_source; candidate only
•	Stage decision: sensitivity_only / corroborating_range
•	Main caveat: German national factors and gas-mix treatment; do not combine blindly with Dutch factors.
WAG-SC-013 — TSN Climate-Neutral Pathways Study
•	Source title: Feasibility study on climate-neutral pathways for TSN IJmuiden
•	Organisation: Tata Steel Nederland / FNV-Zeester / Roland Berger
•	Publication year: 2021
•	Identifier: Public feasibility study
•	Stable URL: https://products.tatasteelnederland.com/sites/producttsn/files/TSN%20Climate%20Neutral%20Pathways%20Final%20Report.pdf
•	Main locators:
o	Current site and project focus schematic
o	DRI 1 and DRI 2 transition steps
o	Closure notes for coke and gas plants
•	Extracted values and exact basis:
o	Current TSN IJmuiden emissions around 12.6 Mt CO₂ at production volume around 7.2 Mt liquid steel
o	DRI 1 capacity described as 2.5 Mt/year
o	DRI 1 coupled with closure of coke and gas plant 2
o	DRI 2 replacement of blast furnace 7 coupled with closing coke and gas plant 1 and sinter lines
•	Confidence: medium-high for transition structure
•	Review status: extracted_from_primary_source; structural only
•	Stage decision: validation_target / structural_evidence
•	Main caveat: public transition pathway, not exact operational input or hourly WAG coefficient.
WAG-SC-014 — Vattenfall IJmond Power Plants Press Release
•	Source title: Tata Steel Nederland to acquire Vattenfall power plants in IJmond region
•	Organisation: Vattenfall
•	Publication year: 2025
•	Identifier: Press release, 14 November 2025
•	Stable URL: https://group.vattenfall.com/press-and-media/pressreleases/2025/tata-steel-nederland-to-acquire-vattenfall-power-plants-in-ijmond-region/
•	Main locators:
o	Section “Vattenfall power plants in IJmond region”
•	Extracted values and exact basis:
o	Power plants 24 and 25 in Velsen-Noord generate electricity predominantly from residual gases from the steel production process
o	This electricity is used by TSN in operational processes
o	IJmond 01 is a CHP plant on the Tata Steel site fuelled by residual gases and produces electricity and steam
o	Electricity and steam are used in the steel plant’s operational processes
o	Ownership transfer expected on 1 January 2026
•	Confidence: high for public structural interface evidence
•	Review status: extracted_from_primary_source; structural only
•	Stage decision: validation_target / structural_interface; blocked for dispatch coefficients
•	Main caveat: no contract dispatch, efficiency, allocation, or price rule.
WAG-SC-015 — Tata Steel Limited Acquisition Announcement
•	Source title: Tata Steel Limited announcement on acquisition of Vattenfall power plants
•	Organisation: Tata Steel Limited
•	Publication year: 2025
•	Identifier: Disclosure dated 14 November 2025; SEC/1166/2025-26
•	Stable URL: https://www.tatasteel.com/media/25040/tata-steel-announcement-ld.pdf
•	Main locators:
o	Annexure, target-entity details
o	Annexure, objects and impact of acquisition
•	Extracted values and exact basis:
o	Velsen power plants VN24, VN25 and IJmond01 convert gases arising from TSIJ’s works into electricity
o	Electricity is supplied back to TSIJ under a tolling contract
o	Total electric capacity of transferred Velsen power plants: 770 MW
o	Conversion of process gases into electricity and steam is governed by a tolling contract expiring 31 December 2025
o	Turnover line mentions fee related to tolling contract plus ancillary income for excess electricity sold to third parties
•	Confidence: high for public transaction/interface evidence
•	Review status: extracted_from_primary_source; structural only
•	Stage decision: validation_target / structural_interface; blocked for export revenue or tolling logic
•	Main caveat: capacity and contract existence are public, but dispatch rules and economic allocation are not public model inputs.
WAG-SC-016 — MER Heracless Deel B Technische Beschrijving
•	Source title: MER Groen Staal — Deel B Technische beschrijving
•	Organisation: Tata Steel Nederland / Royal HaskoningDHV
•	Publication year: 2025
•	Identifier: MER Heracless technical description; 15 September 2025
•	Stable URL: https://www.tatasteelnederland.com/sites/default/files/mer-groen-staal-deel-b-technische-beschrijving.pdf
•	Main locators:
o	Sections around current environment and Vattenfall interfaces
o	Section around energy-central variants and VN24/VN25/IJM-01
o	Glossary / summary discussion of power plants
•	Extracted values and exact basis:
o	Three installations generate electricity from combustible gases: VN24, VN25 and IJM-01
o	VN24 and VN25 are outside Tata Steel site and operated by Vattenfall; IJM-01 is on Tata site and operated by Vattenfall
o	Project Heracless changes volumes of combustible gases because one blast furnace and one coke-and-gas plant close
o	Proposed MER operating split: VN25 85% of time, IJM-01 15% of time, VN24 back-up; variant reverses IJM-01/VN25 priority
o	IJM-01 is CHP and provides electricity and heat; primarily uses BFG with oxygas and COG
•	Confidence: medium-high for public project-structure evidence
•	Review status: extracted_from_primary_source; structural / validation only
•	Stage decision: validation_target / scenario_context; blocked for exact dispatch
•	Main caveat: MER project scenario, not current actual operation or general hourly dispatch rule.
WAG-SC-017 — MER Heracless Detailstudie Energie en CO₂-balans
•	Source title: Detailstudie Energie en CO₂-balans — MER Heracless - Groen Staal
•	Organisation: Royal HaskoningDHV for Tata Steel IJmuiden B.V.
•	Publication year: 2025
•	Identifier: BI3580-IB-RP; final; 15 September 2025
•	Stable URL: https://pas.commissiemer.nl/files/nl/3730/01-Energie.pdf
•	Main locators:
o	Section 4.1, energy system in current situation
o	Section 5.7.2, energy-central variants
o	Section 6.3, shifts in production and use of process gases
o	Section 6.3.1, use at Vattenfall
o	Glossary entry for Vattenfall
•	Extracted values and exact basis:
o	The amount of gases to Vattenfall plants decreases by 45% in the Heracless scenario described
o	Gases are used 85% of time in Velsen 25 and 15% in IJmond 01 in the stated project configuration
o	Hardly any coke oven gas is supplied in the natural-gas and hydrogen scenarios described
o	Vattenfall uses combustible Tata Steel gases in Velsen-Noord 24, Velsen-Noord 25 and IJmond 1 to generate energy
o	Heracless reduces combustible gas availability, so Vattenfall effects are considered
•	Confidence: medium-high for MER scenario evidence
•	Review status: extracted_from_primary_source; structural / validation only
•	Stage decision: validation_target / scenario_context; blocked for exact operational dispatch
•	Main caveat: public MER scenario; should not be treated as actual hourly WAG availability or plant contract truth.
WAG-SC-018 — Energy.nl REF BOF Steelmaking Factsheet
•	Source title: REF BOF Steelmaking — Greenfield
•	Organisation: Energy.nl / Dutch technology factsheet
•	Author: Kira West
•	Publication year: 2020
•	Identifier: Technology factsheet; date 7 September 2020
•	Stable URL: https://energy.nl/wp-content/uploads/ref-bof-steelmaking-technology-factsheet_080920-7.pdf
•	Main locators:
o	Description section
o	Typical composition of gases section
o	Emissions explanation
•	Extracted values and exact basis:
o	COG typical composition: 60% H₂, 23% CH₄, 6% N₂, 4% H₂O, 4% CO, 1% CO₂, <0.5% O₂, 3% other; LHV 17.3 MJ/Nm³
o	BFG typical composition: 49% N₂, 22% CO, 22% CO₂, 4% H₂, 3% H₂O; LHV 3.2 MJ/Nm³
o	BOFG typical composition: 57% CO, 14% CO₂, 14% N₂, 12% H₂O, 3% H₂; LHV 7.5 MJ/Nm³
o	Off-gases can be reinjected, used to produce heat and power, and/or used as chemical feedstock
o	For Tata Steel IJmuiden, excess gases are described as combusted for furnace preheating, reinjected to BF, or used to generate electricity at nearby power plants
•	Confidence: medium as secondary corroboration
•	Review status: extracted_from_secondary_source; not primary
•	Stage decision: corroborating_evidence / sensitivity_only
•	Main caveat: secondary factsheet; use JRC BREF as primary coefficient source where available.
WAG-SC-019 — JRC Efficiency of Heat and Electricity Production Technologies
•	Source title: Efficiency of heat and electricity production technologies
•	Organisation: European Commission Joint Research Centre
•	Publication year: 2012
•	Identifier: JRC70956
•	Stable URL: https://publications.jrc.ec.europa.eu/repository/bitstream/JRC70956/jrc%20efficiency%20of%20heat%20and%20electricity%20production%20technologies%20final%20revision%2020121115%20online.pdf
•	Main locators:
o	Power-generation technology sections
o	Boiler / steam-cycle discussion
•	Extracted values and exact basis:
o	Natural-gas open-cycle gas turbine efficiency 35–42% LHV at full load
o	General heat/electricity conversion context for power technologies
o	Boiler-specific useful-energy values were not fully resolved in the discovery memo and require targeted follow-up extraction before use
•	Confidence: medium for generic technology context; low for steel-WAG boiler coefficient
•	Review status: bibliographic source card only; extraction incomplete
•	Stage decision: sensitivity_only / review_required
•	Main caveat: generic heat/electricity report; not a steel-WAG boiler source by itself.
WAG-SC-020 — Kim et al. Off-Gas Power-Generation Paper
•	Source title: Optimization Simulation, Using Steel Plant Off-Gas for Power Generation: A Life-Cycle Cost Analysis Approach
•	Organisation/source: Energies, MDPI; academic article
•	Authors: Y.K. Kim et al.
•	Publication year: 2018
•	Identifier: Energies 2018, 11(11), 2884; DOI 10.3390/en11112884
•	Stable URL/DOI: https://doi.org/10.3390/en11112884
•	Main locators:
o	Table 1, off-gas power plant parameters
•	Extracted values and exact basis:
o	Boiler efficiency reported in discovery search as 85.17%
o	Generator efficiency reported in discovery search as 95%
o	Annual operation time reported in discovery search as 8000 h
•	Confidence: low-medium until primary article table is re-opened and checked directly
•	Review status: discovery_only; primary-table verification required
•	Stage decision: sensitivity_only / not approved
•	Main caveat: single study, likely plant- or case-specific; do not use as base-case boiler efficiency without corroboration.
________________________________________
Parameter-level stage decision
Parameter family	Candidate source cards	Stage decision
BFG generation and LHV	WAG-SC-001	Candidate range only; may support development diagnostic after second review
BOFG/LDG generation and LHV	WAG-SC-001	Candidate range only; use suppressed-combustion basis explicitly
COG generation and LHV	WAG-SC-001	Candidate range only; prefer direct Table 5.2 coke-basis values over derived coal-to-coke estimate
WAG compositions	WAG-SC-001, WAG-SC-018	Candidate/corroborating range; JRC primary, Energy.nl secondary
WAG process-fuel use	WAG-SC-001, WAG-SC-007, WAG-SC-008, WAG-SC-018	Structural validation only; no direct substitution price
Boiler/steam conversion	WAG-SC-019, WAG-SC-020, WAG-SC-010	Sensitivity only; no approved central value yet
WAG-to-power efficiency	WAG-SC-009, WAG-SC-010	Candidate diagnostic range / sensitivity only; not Vattenfall exact
WAG flare/spill treatment	WAG-SC-006, WAG-SC-010, WAG-SC-001	Validation rule: surplus must not become free energy; flare/spill must be explicit
WAG combustion CO₂ factors	WAG-SC-011, WAG-SC-012, WAG-SC-003	Candidate reporting factors; choose one source hierarchy before use
Natural-gas displacement convention	WAG-SC-002, WAG-SC-007, WAG-SC-008	Assumption-only useful-energy convention; no direct price valuation
Net electricity import offset	WAG-SC-008, WAG-SC-014, WAG-SC-015	Structural rule: reduce site import first; no automatic export revenue
Vattenfall/IJmuiden interface	WAG-SC-014, WAG-SC-015, WAG-SC-016, WAG-SC-017	Structural/interface evidence only; dispatch and contract logic blocked
C1/Phase 1 WAG availability reduction	WAG-SC-013, WAG-SC-016, WAG-SC-017	Validation/scenario context only; not direct coefficient
No-double-counting emissions boundary	WAG-SC-003, WAG-SC-004, WAG-SC-005, WAG-SC-006	Accounting rule; model must count WAG carbon once at combustion/flare/interface boundary
Captured CO₂ visibility	WAG-SC-003, WAG-SC-017	Reporting-only unless transport/storage sink is explicitly modelled
________________________________________
Explicit blocked uses
The following must not be implemented from these source cards:
•	Tata-exact WAG generation coefficients;
•	hourly WAG availability profiles derived from annual/MER values;
•	Vattenfall dispatch optimisation;
•	VN24/VN25/IJM-01 unit commitment;
•	tolling-contract economics;
•	automatic export revenue for WAG electricity;
•	detailed mixed-gas calorific optimisation;
•	ETS free-allocation revenue or credit in the base objective;
•	market-price-responsive WAG allocation before a market and settlement layer exists;
•	treating the research report itself as primary evidence.
________________________________________
Minimum fields for repo source-card schema
Recommended source-card fields:
•	source_card_id
•	source_title
•	organisation
•	authors_or_editor
•	publication_year
•	document_identifier
•	source_type
•	stable_url
•	doi
•	document_status
•	locator_page_table_section
•	extracted_value
•	unit
•	basis
•	carrier
•	parameter_family
•	geographic_or_technology_scope
•	confidence
•	review_status
•	status_recommendation
•	main_caveat
•	discovery_memo_id
•	reviewer
•	review_date
•	approved_for_model_use
