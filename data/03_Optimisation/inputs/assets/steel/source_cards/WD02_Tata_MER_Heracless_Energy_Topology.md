# Source Card

- `source_id`: `WD02`
- `canonical_source_card_id`: `STEEL-SC-0016`
- `title`: `MER Heracless - Deel B - Technische beschrijving`
- `source_type`: `technical EIA / MER report`
- `authors_or_organisation`: `Tata Steel Nederland / Royal HaskoningDHV`
- `edition`: `definitief, 15 September 2025`
- `report_reference`: `BI3580-MER`
- `stable_url_or_file_reference`: `https://www.tatasteelnederland.com/sites/default/files/mer-groen-staal-deel-b-technische-beschrijving.pdf`
- `local_file_path_if_any`:
- `public_or_confidential_status`: `public`
- `verified_pdf_pages`: `124`
- `verified_sha256`: `8A7A358183234E0B0C5D77588020DD58DC8F8FD20036954CB7004149C6EFB455`
- `page_mapping`: `Cover is PDF page 1; the document-information page is PDF page 2/report page 1; thereafter PDF page = report page + 1.`
- `confidence`: `very_high`

## Supported uses

- public Heracless topology for BFG, COG, BOFG/oxygas, NG, electricity and steam interfaces;
- configuration-specific annual or operating-time validation where the report states the basis;
- non-executable candidate evidence for DRI/EAF transition, bypass, outage and decoupling tests;
- separate validation of DRI reduction-gas, furnace-gas and electricity intensities;
- topology and capacity evidence for the oxygas holder, without an energy-store conversion;
- confirmation that declining COG supply increases WBW natural-gas demand;
- Vattenfall topology: VN25 primary on available production gases, NG top-up to an unspecified minimum fuel need, IJM-01 standby and VN24 tertiary backup.

## Prohibited interpretations

- Do not turn an annual value, an EIA scenario or an operating-time share into an hourly dispatch rule.
- Do not read the reported VN25/IJM-01 operating-time assumption as an output, fuel or WAG allocation split.
- Do not infer a VN25 minimum MW, minimum fuel rate, efficiency, ramp, outage schedule or economic dispatch rule.
- Do not convert the oxygas-holder geometric capacity into energy without usable volume, composition, pressure and LHV basis.
- Do not extrapolate transition-only minimums or the downstream coordination ceiling to universal normal operation.
- Do not construct a complete site steam balance from DRI/EAF recovery and startup statements.
- Do not fit WAG yields, hourly production, generator use or flare to the aggregate annual recovery context.
- Do not use this report to approve executable inputs, settle coal/coke definition conflicts, claim BF6/BF7 comparability or replace terminal-aware held-out validation.

## Exact locator map

| Evidence family | Report page | PDF page | Section, table or figure | Supported reading |
| --- | ---: | ---: | --- | --- |
| Current energy system | 23 | 24 | 3.6.1 | ENB/ECC distribute steam, electricity and separate production gases to Tata and Vattenfall consumers. |
| Current annual recovery | 32 | 33 | 4.3 | Aggregate WAG heat/electricity recovery and grid import are annual context only. |
| Phase-1 operating-time assumption | 48 | 49 | 5.3-5.4 | The VN25/IJM-01 pair refers to time in operation. |
| Phase-1 volumes | 49 | 50 | Tables 5.1-5.2 and footnotes | Annual production and flexibility values are EIA scenario bases, with rounded-volume caveats. |
| Phase-1 annual energy | 51 | 52 | 5.5 | Annual coal, NG, electricity, generator and grid totals; no hourly profile. |
| Energy-central variants | 61 | 62 | 6.3.4 | Primary/backup topology and the reversed environmental variant. |
| Oxygas buffering | 70-71 | 71-72 | 7.4; Figure 7.2 | Batch BOFG buffering to constant consumers and the holder-capacity locator. |
| Hot commissioning and bypass | 82 | 83 | 9.3-9.4 | Cold DRI, bypass mode and commissioning-specific DRI minimum setting. |
| Transition coordination | 85 | 86 | 9.7; Figure 9.1 | Downstream ceiling, approximate BF/DRI minimums and coordinated ramp-up. |
| DRI steam recovery | 87 | 88 | 10.2 | Top-gas heat recovery produces steam used inside the DRI plant. |
| DRI fuel topology | 89 | 90 | 10.3 | Tailgas/NG/H2 furnace fuel and unresolved alternative use or flare. |
| DRI energy intensities | 92 | 93 | 10.6; Figure 10.2 | Separate reduction NG, furnace NG and electricity values per tonne DRI. |
| EAF/DRI decoupling topology | 93 | 94 | 11.1 | Hot-DRI transfer and cold-DRI storage; short-term hot-DRI buffer at the EAF. |
| EAF heat recovery | 98 | 99 | 11.3 | Off-gas heat recovery makes steam for vacuum-ladle treatment. |
| Vattenfall interface | 115 | 116 | 14.5 | VN25 production-gas-first direction, NG top-up, IJM-01/VN24 backup and operating-time interpretation. |
| WBW natural gas | 116 | 117 | 14.6 | GOS North supplies more NG to WBW2 as COG use falls. |
| DRI startup | 118 | 119 | 15.1 | External startup steam, startup flare duration/flows and prerequisites. |
| Shutdown and annual maintenance | 119 | 120 | 15.2-15.3 | Short-stop bypass/external steam, long-stop flare and annual outages. |
| Repeating maintenance and emergencies | 120-121 | 121-122 | 15.3-15.4 | Monthly/weekly maintenance, coordinated outages, cold-DRI decoupling and emergency handling. |

## Document limitations

This is a public planning and environmental-impact description, not a control-room log, historian dataset, fuel contract, dispatch manual or validation result. Diagrams establish topology and direction, not unlabelled capacities. The PDF metadata title says `Samenvattend Hoofdrapport`, while the cover and document-information page identify this file as the definitive `Deel B - Technische beschrijving`; citations therefore use the cover title, report reference, date, verified hash and page mapping above.
