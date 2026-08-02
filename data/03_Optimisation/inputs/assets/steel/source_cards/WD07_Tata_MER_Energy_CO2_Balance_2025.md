# Source Card

- `source_id`: `WD07`
- `title`: `Detailstudie Energie en CO2-balans MER Heracless`
- `source_type`: `official MER technical study PDF`
- `authors_or_organisation`: `Tata Steel Nederland / Royal HaskoningDHV`
- `publication_date`: `2025-09-15`
- `stable_url_or_file_reference`: `https://pas.commissiemer.nl/files/nl/3730/01-Energie.pdf`
- `public_or_confidential_status`: `public`
- `evidence_tier`: `Tier A - primary public site-specific`
- `source_trust_rank`: `Rank 1`
- `modelling_use_allowed`: `Annual configuration-matched validation anchors; named annual energy-service accounts; generator fuel/output accounting; bounded DRI natural-gas intensity; Scope 1 category accounting.`
- `modelling_use_not_allowed`: `Do not convert rounded annual balances into hourly dispatch profiles, minimum loads, ramp limits, outage calendars, prices, or exact plant-level burner shares. Do not use source totals as anchor-minus-model plugs.`
- `unit_convention`: `PJ/year; the DRI specific natural-gas value is explicitly LHV. Other table values retain the MER energy-balance convention and are not silently converted between LHV and HHV.`
- `production_basis`: `Reference situation and Heracless gas scenario as defined by the MER; site totals are not linearly rescaled to the active 6.75-Mt production proxy.`
- `confidence`: `high for stated annual balances and category splits; medium for using rounded table values as exact identities.`

## Exact locators used in Phase 5E

| MER report page | PDF page | Evidence used |
|---:|---:|---|
| 17 | 23 | Table 4.2 reference energy balance: C0 NG, process electricity demand, generator fuels/output, and process-gas heat/power use. |
| 18 | 24 | Table 4.3 reference Scope 1 inventory: coal, iron-bearing material, NG, fluxes, and total. |
| 23 | 29 | DRI gas-scenario balance: 9.9 GJ-LHV NG/t H-DRI and 0.3 GJ electricity/t H-DRI. |
| 63 | 69 | Table 6.1 reference and Heracless gas-scenario Scope 1 inventories. |
| 65 | 71 | Table 6.2 Heracless gas-scenario energy balance, including named NG and electricity categories and Vattenfall fuel/output. |
| 67 | 73 | Vattenfall operating context: 85% VN25 and 15% IJM01 use in the Heracless scenarios; increased NG because process gases fall and VN25 has limited part-load operation. |
| 69-70 | 75-76 | Table 6.5 complete C0/C1 gas production and consumption by ironmaking, DRI/EAF, downstream, and Vattenfall. |
| 71 | 77 | Tables 6.6-6.7 full-site energy and Scope 1 totals, including gross electricity and public-grid purchase. |

## Phase 5E methodological interpretation

1. The official reference NG total is 12.5 PJ/y, superseding the older 9.666-PJ/y comparison as the primary configuration-matched real-site anchor.
2. The official Heracless gas-scenario NG total is 46.7 PJ/y. Its independent components are 2.0 PJ existing ironmaking/energy, 13.1 PJ existing steel/downstream, 3.8 PJ Vattenfall, 27.7 PJ DRI, and 0.1 PJ EAF.
3. `Stroomgebruik` is the named operating-process demand boundary: 11.5 PJ/y in C0 and 16.2 PJ/y in C1. Table 6.6's broader totals are 13.7 and 17.8 PJ/y. The difference is retained as a visible boundary remainder, not assigned to an invented process.
4. C0 generator fuels are 18.6 PJ BFG, 1.0 PJ COG, 4.0 PJ BOFG, and 1.9 PJ NG, with 9.8 PJ electricity output and 15.7 PJ balance/losses. C1 values are 8.9, 0.0, 1.4, and 3.8 PJ, with 5.9 PJ electricity output and 8.2 PJ balance/losses.
5. Fuel-proportional WAG electricity attribution is a derived reporting indicator, not an operational constraint. It gives about 2.519 TWh/y for C0 and 1.197 TWh/y for C1.
6. The Scope 1 rows are configuration totals by source class. They replace an arbitrary CO2 bridge for annual comparison but do not turn the hourly model into an ETS-ready carbon ledger.

