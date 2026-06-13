# Onderzoeksnotitie voor Wave D over WAGs, interne energienetten, waardering en emissieboekhouding voor een Tata Steel IJmuiden-geïnspireerde S3-laag

## Executive finding

De robuuste hoofdconclusie is dat een eerste verdedigbare S3-laag voor jouw thesis **niet** moet starten met een volledig elektriciteits-, stoom- en Vattenfall-dispatchmodel, maar met een **carrier-specifieke WAG-laag** voor ten minste **BFG, COG en BOF/LD-gas**, gekoppeld aan de S2-materiaalstromen via publieke generieke opbrengstcoëfficiënten en publieke Tata-topologie. De reden is eenvoudig: in geïntegreerde staalwerken vormen juist deze gassen het hart van het interne energiesysteem; BAT-documentatie beschrijft ze expliciet als de basis van de energievoorziening, en Tata’s publieke documenten bevestigen dat productiegassen op IJmuiden intern en via Vattenfall voor warmte en elektriciteit worden ingezet. Een geaggregeerde “één WAG-crediet”-aanpak is alleen bruikbaar als tijdelijke debuglaag, omdat die de fysische verschillen tussen BFG, COG en BOF-gas verbergt en het risico vergroot dat gassen impliciet als gratis opslag of gratis arbitrage fungeren. citeturn12view0turn14view0turn8view3turn26view0turn40view0

Voor Tata IJmuiden-achtige Phase 1-scenario’s is de publieke richting helder: **BF7 en KGF2 verdwijnen**, **BF6 en KGF1 blijven**, en daardoor dalen de volumes **hoogovengas, kooksgas en oxygas**. Tata’s MER zegt expliciet dat in Heracless minder van deze productiegassen beschikbaar is, dat **VN25** primair op de resterende productiegassen draait, dat **aardgas** moet worden bijgestookt wanneer de minimale brandstofbehoefte anders niet gehaald wordt, en dat **IJM-01** en **VN24** als back-up/logische varianten fungeren. Dat betekent dat het eerste S3-model de **schaarste van WAGs** moet kunnen laten zien; precies daar zit de beleids- en ontwerpwaarde van de laag. citeturn6view3turn8view2turn32view1turn24view4

Een tweede hoofdconclusie is dat **interne waardering** van WAGs in S3 **niet** moet worden gebaseerd op veronderstelde interne Tata/Vattenfall-transferprijzen en ook **niet** rechtstreeks op de elektriciteitsmarktprijs zonder expliciete omzettingslogica. De veiligste methode is: **fysische balans eerst**, vervolgens waardering via **vervanging van extern aardgas of andere expliciet gemodelleerde externe energie**, aangevuld met een **niet-nul affakkel-/spill-penalty**. Zodra je een WAG positieve waarde geeft zonder expliciet verbruikskanaal, creëer je modelmatig gratis energie; zodra je WAG waardeert tegen elektriciteitsprijs zonder boiler/CHP-conversie, creëer je gratis arbitrage. citeturn12view0turn36view0turn37view0turn40view1

Een derde hoofdconclusie betreft emissies: voor een eerste S3-laag is het verdedigbaar om een **site-brede emissiearchitectuur** te maken met gescheiden posten voor **procesemissies**, **verbranding/fakkelen van WAGs en aardgas**, **afgevangen CO2 uit de DRI-route**, en optioneel **scope-2/indirecte elektriciteit**. Wat je nog **niet** moet claimen is een Tata-specifieke ETS-optimalisatie met vrije allocatie, benchmarkrechten, interne koolstofprijzen of contractuele Vattenfall-verrekeningen; die vragen om detaildata en formele grensafbakening die publiek niet volledig beschikbaar zijn. Officiële EU ETS-bronnen vereisen volledigheid van zowel proces- als verbrandingsemissies, terwijl de officiële waste-gas-guidance duidelijk maakt dat CO2 die onderdeel is van een waste-gas-mix boekhoudkundig aan die stroom gekoppeld blijft. citeturn22view1turn22view0turn39view0turn39view1

Mijn aanbeveling is daarom: **bouw eerst een “B-lite” variant van optie B**. Dat is een **semi-gedetailleerde WAG-laag** met aparte BFG/COG/BOF-balansen, WAG-generatie uit S2-throughput, import van aardgas en elektriciteit, expliciete spill/fakkelvariabelen, en hoogstens **een eenvoudige houderrepresentatie voor BOF/oxygas** omdat juist daarvoor Tata publiek een expliciete bufferfunctie beschrijft. Stoom, gedetailleerde boilers/CHP, Vattenfall-dispatch, oxygenet en utilitynetten horen daarna in een latere verfijningsstap. citeturn7view2turn12view0turn36view0turn37view0

## Source inventory

Voor webbronnen zonder DOI fungeert het broncitaat als klikbare locator. Waar een DOI publiek beschikbaar is, staat die expliciet vermeld.

| source_id | titel | organisatie / auteurs | jaar / datum | stabiele locator | type | kwaliteit | hoofdgebruik | beperkingen |
|---|---|---|---|---|---|---|---|---|
| S01 | *Best Available Techniques Reference Document for Iron and Steel Production* citeturn10view0 | Europese Commissie JRC; Remus, Aguado-Monsonet, Roudier, Delgado Sancho | 2013 | DOI: 10.2791/97469 | officiële BREF | hoog | generieke ranges voor BFG/COG/BOF-gas, BAT-logica, gas holders, CHP/boilers | geen Tata-specifieke waarden |
| S02 | *MER Heracless – Deel B Technische Beschrijving* citeturn5view0turn6view3 | Tata Steel Nederland / Royal HaskoningDHV | 15 sep 2025 | officiële publieke PDF via citaat | officiële projectdocumentatie | hoog | IJmuiden-topologie, Phase 1-wijzigingen, Vattenfall-interface, DRI/EAF-energie, oxygashouder | projectdocument; geen operationele contractwaarden |
| S03 | *Tata Steel Nederland Annual Report and Accounts 2024–2025* citeturn25view0turn26view0 | Tata Steel Nederland | 2025 | officiële publieke PDF via citaat | jaarverslag | hoog | openbare emissiegrenzen, residual-gas gebruik, scope-behandeling Vattenfall | corporate rapportage; niet bedoeld als modelparameterbestand |
| S04 | *Joint Letter of Intent Tata Steel and government* citeturn27view0 | Tata Steel Nederland | 2024/2025 publieke webpagina | officiële publieke pagina via citaat | officiële projectpagina | middel-hoog | publieke bevestiging van vervanging BF7 + KGF2 door DRI/EAF en reductiedoel | samenvattende publiekscommunicatie |
| S05 | *The way towards carbon neutral steel* citeturn27view1 | Tata Steel Nederland | publieke webpagina | officiële publieke pagina via citaat | officiële projectpagina | middel-hoog | scope-1/2 interpretatie en Vattenfall-relatie in Tata-rapportage | GHG-protocolcommunicatie, geen ETS-methodologie |
| S06 | *Tata Steel IJmuiden* citeturn26view4 | Tata Steel Nederland | publieke webpagina | officiële publieke pagina via citaat | officiële sitepagina | middel | bevestigt eigen gas- en elektriciteitsnet op site | topologisch, niet kwantitatief |
| S07 | *Fuel, Electric Power and Steam Supply-and-Demand Guidance System in Steel Works* citeturn17view0 | JFE Steel; Yatsu, Suzuki, Uno | 2023 | officiële JFE PDF via citaat | technisch bedrijfsrapport | middel-hoog | mixed-gas logica, holders, prioriteiten, gezamenlijke gas-stoom-stroomaanpak | Japans case-materiaal; geen Tata-waarden |
| S08 | *Guidance for Fuel and Power Management in Steel Works Through Model Predictive Control* citeturn36view0 | JFE Steel | 2021 | officiële JFE PDF via citaat | technisch bedrijfsrapport | middel-hoog | geïntegreerde gas-/stoom-/stroomlogica, externe brandstof en power purchases | praktijkgericht; beperkt in publieke detailcoëfficiënten |
| S09 | *Case Study of Optimal Byproduct Gas Distribution in Integrated Steel Mill Using Multi-Period Optimization* citeturn36view1turn37view0 | ABB | 2012 | officiële ABB PDF via citaat | industrieel case paper | middel | MILP-structuur, holders, mixstations, flaring, power-plant koppeling | conferentie/case paper, geen peer-reviewed artikel |
| S10 | *Energy use in the steel industry* citeturn40view0 | worldsteel | 2021 | officiële worldsteel PDF via citaat | factsheet | middel-hoog | belang van co-product gases en flare-ladder | sectorbreed, beperkt detail |
| S11 | *Commission Implementing Regulation (EU) 2018/2066* citeturn22view1 | Europese Commissie | 2018 | officiële regelgeving via citaat | wet-/regelgeving | hoog | basisregels MRV, volledigheid proces + verbranding | juridisch kader, geen staal-specifieke modelkeuzes |
| S12 | *Guidance Document 8 – Waste gases and process emissions sub-installation* citeturn22view0 | Europese Commissie ETS guidance | 2024 | officiële guidance via citaat | officiële guidance | hoog | definitie waste gas, behandeling CO2 in gasmix, FAR-logica | allocatie/ETS-focus, niet operationele dispatch |
| S13 | *Update of benchmark values for 2021–2025 of phase 4 of the EU ETS* citeturn22view2turn39view0turn39view1 | Europese Commissie | 2021 | officiële benchmark factsheet via citaat | officiële guidance/factsheet | hoog | benchmarkcontext en waste-gas-factoren voor ETS/free allocation later | niet geschikt als Tata-specifieke allocatie |
| S14 | *A methodology to determine the LCI of steel industry co-products* citeturn40view1 | worldsteel | 2014 | officiële worldsteel PDF via citaat | methodologiedocument | middel-hoog | interne gas/steam/electricity-stromen en credit-logica in LCA | LCA-logica, geen ETS of operationele optimalisatie |
| S15 | *Iron and Steel Technology Roadmap* citeturn20search2 | IEA | 2020 | officiële IEA PDF via citaat | technologieroadmap | hoog | context over emissie-intensiteit van off-gases en NG-DRI | systeemniveau; geen plantspecifieke dispatch |
| S16 | *BOF steelmaking technology factsheet* citeturn34view0 | energy.nl / TNO-initiatief | 2020 | officiële factsheet via citaat | factsheet | middel | generieke BOF/BFG/COG-composities en zuurstof-orde-grootte | samengestelde secundaire bron |

## WAG- en interne-energietopologie

De publieke Tata- en BAT-bronnen ondersteunen een vrij consistente topologie: geïntegreerde staalproductie genereert **BFG, COG en BOF/LD-gas**, het Tata-energiebedrijf verdeelt deze over interne verbruikers en Vattenfall, en bij de BOF-route is ten minste één expliciete **oxygashouder** nodig omdat conversie batchgewijs is terwijl afnemers een continu debiet vragen. Tata bevestigt bovendien dat de site een eigen gas- en elektriciteitsnet heeft en dat productiegassen historisch een groot deel van de stroom- en warmtevoorziening dragen. citeturn8view3turn7view2turn26view4turn33view0turn26view0

| gas_or_energy_carrier | generated_by | consumed_by | stored_or_buffered_where | publieke/generieke evidentie | source_id | model treatment | confidence | caveat |
|---|---|---|---|---|---|---|---|---|
| BFG | hoogoven(s) | hot stoves, diverse thermische verbruikers, Vattenfall/centrales, eventueel gemengd met COG/BOFG/NG | BAT noemt gas holders voor alle by-product gases; Tata noemt productiegasnet en energiebedrijf, maar geen publieke BFG-holdercapaciteit | BFG is kernonderdeel van geïntegreerd energiebeheer; Tata gebruikt hoogovengas intern en bij Vattenfall; BF-topgas kan na reiniging als brandstof worden gebruikt en soms worden verrijkt. citeturn12view0turn14view0turn14view2turn26view0 | S01, S02, S03 | **include** | hoog | Tata-specifieke voorraad-/drukdata niet publiek |
| COG | KGF/coke ovens | batterijen zelf, sinterfabriek, warmband/reheating, andere verbruikers op en buiten site, Vattenfall | publiek geen capaciteiten; wel flares en netwerkbescherming; na sluiting KGF2 valt redundantie weg | Tata noemt KGF1/KGF2 en het gebruik van kooksgas binnen en buiten de site; bij uitval gasreiniging is in Phase 1 aardgas-back-up nodig voor sinter en HO6. citeturn7view1turn6view3turn24view4 | S02 | **include** | hoog | netlogica publiek, maar geen contract/dispatchdetail |
| BOF/LD-gas / oxygas | converters / Oxystaalfabriek | interne brandstofverbruikers en Vattenfall | **expliciete oxygashouder** op Tata-site; buffer nodig door batchgewijze vrijgave | Tata beschrijft de oxygashouder als buffer om affakkelen te voorkomen en continue aanvoer te garanderen; BAT beschrijft buffering van BOF gas in gasholder na suppressed combustion. citeturn7view2turn11view3turn16view2 | S01, S02 | **include** | hoog | capaciteit niet publiek, alleen logica |
| Mixed gas | mengstations die gy cap/verwarmingswaarde aanpassen door BFG/COG/LDG te mengen | vooral grote thermische afnemers; in JFE o.a. hot strip en plaatwalserij | via achterliggende holders per carrier | JFE definieert mixed gas als gas waarvan de verbrandingswaarde door mengen wordt aangepast; ABB noemt mixstations en calorific constraints als expliciete netwerkrestricties. citeturn17view0turn36view0turn37view0 | S07, S08, S09 | **later only** of **aggregate** | middel | geen robuuste publieke universele setpointrange gevonden |
| Aardgas | externe import (GOS Noord / Zuid; externe markt) | thermische back-up, DRI, furnaces, VN25-bijstook, WB2, HO6-stoves-back-up | geen relevante publieke site-opslag voor thesisdoel | Tata MER beschrijft grotere aardgaslevering via GOS Zuid naar DRI en via GOS Noord naar WB2; VN25 krijgt aardgas bij tekort aan productiegassen. citeturn24view4turn32view1turn24view0 | S02 | **include** | hoog | geen vertrouwelijke inkoopprijs gebruiken |
| Elektriciteit | Vattenfall op residual gases, interne recovery zoals expansieturbine/TRT bij hoogoven, externe netimport | vrijwel alle productiestappen, sterk bij walserijen en later DRI/EAF | elektriciteitsnet, geen “stock” in model | Tata noemt eigen elektriciteitsnet, publieke TenneT-aansluitingen, gemiddeld 360 MW huidige vraag en ~2.0 TWh Vattenfall-opwek uit residual gases. citeturn26view4turn33view0turn26view0 | S02, S03, S06 | **include**, maar eerst geaggregeerd | hoog | endogene dispatch pas later verfijnen |
| Stoom | waste-heat boilers, CHP, DRI-stoomsysteem, EAF/FTP-warmteterugwinning | DRI CO2-capture, vacuümpanbehandeling, utilities, opstart | stoomsysteem; condensaatrecirculatie; geen publieke volledige drukniveaus | BAT noemt optimized steam and heat management; Tata MER beschrijft DRI- en EAF-stoomsystemen, koppeling met bestaand systeem en hergebruik van condensaat. citeturn12view0turn23view4turn28view2 | S01, S02 | **aggregate** in minimal S3; **later only** als netwerk | middel-hoog | publieke drukniveaus/efficiënties onvoldoende volledig |
| Zuurstof | ASU/utilitysysteem; hoogoven/BOF/EAF procesgebruik | BOF, EAF, diverse utilities | Tata toont zuurstofbuffers in projectkaart en noemt zuurstofbufferlocaties | Tata MER screenshot toont zuurstofbuffers en verplaatsing rond DRI/EAF-bouw; generieke factsheet noemt 110–130 Nm³ O₂/t crude steel voor BF-BOF-routes. citeturn9view2turn34view0 | S02, S16 | **validation only** / **later only** | middel | capaciteiten en kosten niet publiek robuust genoeg |
| Waterstof | extern netwerk of toekomstige import; in Phase 1 initieel nog grotendeels aardgas in DRI | DRI als reductant/energiebron in latere fase | geen publieke Phase 1-grootschalige opslag op site in default plan | Tata zegt dat een on-site H₂-fabriek niet in het voornemen zit en dat de operationele fase start op aardgas, later mix met waterstof. citeturn24view0turn24view1 | S02 | **later only** of **sensitivity** | hoog | geen default-S3 invoer zolang je Phase 1 aardgasvariant modelleert |
| DRI procesgas / tailgas | DRI-gasloop intern | primair intern recirculatie- en heatergebruik; anders flare bij opstart/stops | **lokale** procesgas- en koelgascircuits | Tata beschrijft tailgas-samenstelling, interne recirculatie, inzet in procesfornuis en flare bij opstart/drukafbouw. citeturn31view0turn31view1 | S02 | **later only** | hoog | geen onderdeel van de traditionele WAG-hoofdruggengraat in minimal S3 |
| EAF off-gas warmte / stoom | EAF en secundaire metallurgie | schrootvoorverwarming, stoomsysteem, daarna schoorsteen | EAF-stoomsysteem en koppeling bestaand systeem | Tata beschrijft warmteterugwinning uit EAF-afgassen voor schrootvoorverwarming en stoomproductie. citeturn29view4turn28view2 | S02 | **later only**, of als eenvoudige stoomcredit | middel-hoog | geen publiek volledig rendement of hourly demandstructuur |
| Vattenfall-interface | externe centrales VN24/VN25/IJM-01 gebruiken Tata-productiegassen | levert elektriciteit en warmte aan/naast Tata | buiten de grens van minimal S3 als dispatchmodel; binnen de grens als exogene interface | Tata noemt VN25 primair, IJM-01 back-up/warmtekracht en VN24 back-up; in publieke rapportage worden Vattenfall-emissies uit residual-gasverbranding onder Tata scope 1 geplaatst. citeturn32view1turn26view1turn27view1 | S02, S03, S05 | **include als interface**, niet als volledige dispatch | hoog | contracten, minimum loads en transferwaarden zijn niet publiek |

## Candidate parameter ranges

Onderstaande tabellen scheiden publieke evidentie van modelleringstoepassing. Waar ik waarden **afleid** uit publieke compositie/LHV met eenvoudige stoichiometrie, staat dat expliciet vermeld als **afgeleid** en dus **hoogstens sensitivity-only**.

### BFG

| parameter_id | description | value_or_range | unit | process/carrier | source_id | source quality | confidence | suitable use | caveat |
|---|---|---:|---|---|---|---|---|---|---|
| WAG_BFG_GEN_HM | generatie van BFG | 1200–2000 citeturn14view2turn15view0 | Nm³/t HM | BFG | S01 | hoog | hoog | candidate input | generiek, niet Tata-specifiek |
| WAG_BFG_LHV | lower heating value | 2.7–4.0 citeturn14view2turn14view1 | MJ/Nm³ | BFG | S01 | hoog | hoog | candidate input | gebruik als range/sensitivity |
| WAG_BFG_CO | CO-fractie | 20–28 citeturn14view2turn15view0 | vol-% | BFG | S01 | hoog | hoog | candidate input | na gasreiniging nog steeds variabel |
| WAG_BFG_H2 | H₂-fractie | 1–5; tot ca. 10 bij NG/COG-injectie in BF citeturn14view2 | vol-% | BFG | S01 | hoog | middel-hoog | candidate input / sensitivity | injectieschema verandert samenstelling |
| WAG_BFG_CO2 | CO₂-fractie | 17–25 citeturn14view2turn15view0 | vol-% | BFG | S01 | hoog | hoog | candidate input | relevant voor emissie-intensiteit |
| WAG_BFG_USE_RULE | gebruikslogica | BFG vaak verrijkt met COG/BOFG/NG; kan soms direct in hot stoves met moderne branders en/of luchtvoorverwarming citeturn14view2turn15view0 | n.v.t. | BFG | S01 | hoog | hoog | approved modelling structure | ondersteunt keuze voor sink-/mixrestricties |
| WAG_BFG_EF_DERIVED | **afgeleide** stream-emissiefactor op basis van publieke compositie + LHV | ca. 180–390 | tCO₂/TJ | BFG | S01, S15 | hoog | middel | sensitivity only | **afgeleid**, niet direct Tata-input; hoge range door inert CO₂ en laag LHV citeturn14view2turn20search2 |

### COG

| parameter_id | description | value_or_range | unit | process/carrier | source_id | source quality | confidence | suitable use | caveat |
|---|---|---:|---|---|---|---|---|---|---|
| WAG_COG_GEN_COAL | ruwe gasopbrengst per droge koleninput | 280–450 citeturn15view1 | m³/t coal | COG | S01 | hoog | hoog | validation target / assumption | handig als coking coal de driver is |
| WAG_COG_GEN_COKE | netto COG-output per ton coke | 360–518 citeturn15view2 | Nm³/t coke | COG | S01 | hoog | hoog | candidate input | vaak praktischer als S2 coke-output bekend is |
| WAG_COG_LHV | lower heating value | 17.4–20.0; netto COG vaak 17–18 citeturn15view1turn15view2 | MJ/Nm³ | COG | S01 | hoog | hoog | candidate input | onderscheid raw vs cleaned/net |
| WAG_COG_H2 | H₂-fractie | 39–65 citeturn15view1 | vol-% | COG | S01 | hoog | hoog | candidate input | belangrijke bron van hoge LHV |
| WAG_COG_CH4 | CH₄-fractie | 20–42 citeturn15view1 | vol-% | COG | S01 | hoog | hoog | candidate input | relevante koolstofdrager |
| WAG_COG_CO | CO-fractie | 4–7 citeturn15view1 | vol-% | COG | S01 | hoog | hoog | candidate input |  |
| WAG_COG_H2S_RAW | H₂S in raw COG | 4–12 citeturn15view1 | g/Nm³ | COG | S01 | hoog | hoog | validation only / later only | voor energiemodel alleen **cleaned** COG gebruiken |
| WAG_COG_EF_DERIVED | **afgeleide** stream-emissiefactor uit publieke compositie + LHV | ca. 30–55 | tCO₂/TJ | COG | S01 | hoog | middel | sensitivity only | **afgeleid**; sterk afhankelijk van CH₄/CxHy-aannames |

### BOF/LD-gas / oxygas

| parameter_id | description | value_or_range | unit | process/carrier | source_id | source quality | confidence | suitable use | caveat |
|---|---|---:|---|---|---|---|---|---|---|
| WAG_BOF_GEN_LS | verzameld BOF-gas bij suppressed combustion | 50–100 citeturn16view4turn16view1 | Nm³/t liquid steel | BOF gas | S01 | hoog | hoog | candidate input | alleen voor recovery-systeem, niet full-combustion off-gas |
| WAG_BOF_CO | CO-fractie | 55–80; gemiddelde 72.5 citeturn14view3 | vol-% | BOF gas | S01 | hoog | hoog | candidate input | kernparameter voor energetische waarde |
| WAG_BOF_H2 | H₂-fractie | 2–10; gemiddelde 3.3 citeturn14view3 | vol-% | BOF gas | S01 | hoog | hoog | candidate input |  |
| WAG_BOF_CO2 | CO₂-fractie | 10–18; gemiddelde 16.2 citeturn14view3 | vol-% | BOF gas | S01 | hoog | hoog | candidate input |  |
| WAG_BOF_N2_AR | N₂ + Ar-fractie | 8–26; gemiddelde 8.0 citeturn14view3 | vol-% | BOF gas | S01 | hoog | hoog | candidate input | sterk afhankelijk van air ingress/recovery method |
| WAG_BOF_LHV | lower heating value | 7.1–10.1; gemiddelde 9.58 citeturn14view3turn16view4 | MJ/Nm³ | BOF gas | S01 | hoog | hoog | candidate input |  |
| WAG_BOF_FLARE_LOGIC | flare-/ventlogica | gas aan begin/einde van blow niet verzameld en wordt om veiligheidsredenen gefakkeld citeturn16view2turn14view3 | n.v.t. | BOF gas | S01 | hoog | hoog | approved modelling structure | motiveert spill/fakkelvariabele of vaste recoveryfractie |
| WAG_BOF_RECOV_SAV | energiebesparing t.o.v. flaring | 0.35–0.7 citeturn16view2 | GJ/t LS | BOF gas | S01 | hoog | middel-hoog | validation target | afhankelijk van recoveryconfiguratie |
| WAG_BOF_EF_DERIVED | **afgeleide** stream-emissiefactor uit publieke compositie + LHV | ca. 125–270 | tCO₂/TJ | BOF gas | S01 | hoog | middel | sensitivity only | **afgeleid**; sterk afhankelijk van recovery en samenstelling |

### Mixed gas

| parameter_id | description | value_or_range | unit | process/carrier | source_id | source quality | confidence | suitable use | caveat |
|---|---|---|---|---|---|---|---|---|---|
| WAG_MIX_DEF | definitie mixed gas | warmtewaarde-gecorrigeerde mix van by-product gases citeturn17view0turn36view0 | n.v.t. | mixed gas | S07, S08 | middel-hoog | hoog | approved modelling structure | definitorische/topologische parameter |
| WAG_MIX_STATIONS | mengstations aanwezig in generieke staalwerksystemen | ja; ABB-case heeft expliciet twee gasmixstations met BFG+COG citeturn37view0 | n.v.t. | mixed gas | S09 | middel | middel | later detailed refinement | niet automatisch Tata-specifiek |
| WAG_MIX_CV_CONTROL | calorific/Wobbe control | BAT noemt computer-controlled calorific value control en calorific matching van gassen aan verbruikers citeturn12view0turn12view1 | n.v.t. | mixed gas | S01 | hoog | hoog | later only | goede reden om mixing niet te vroeg te modelleren |
| WAG_MIX_LHV_PUBLIC | publieke universele LHV-range | **geen robuuste generieke publieke range geïdentificeerd** | n.v.t. | mixed gas | S07–S09 | middel | middel | later only / validation only | site-specifieke setpoints en gebruikers bepalen dit |

### Natural-gas substitution

| parameter_id | description | value_or_range | unit | process/carrier | source_id | source quality | confidence | suitable use | caveat |
|---|---|---|---|---|---|---|---|---|---|
| NG_SUB_RULE | vervangingslogica WAG ↔ NG | waardeer alleen via **nuttige energievervanging** in expliciete sink; niet via ruwe marktprijs-elektriciteit citeturn12view0turn37view0turn40view1 | n.v.t. | NG substitution | S01, S09, S14 | hoog/middel | hoog | approved modelling structure | methodische keuze, geen fysische constante |
| NG_PRIORITY_BOF_TO_BFG | prioriteitslogica | BOF-gas kan BFG opwaarderen; COG en NG als tweede/derde prioriteit in mixstation-cascade citeturn16view2 | n.v.t. | BOF/BFG/NG | S01 | hoog | middel-hoog | candidate structure / sensitivity | generieke literatuurreferentie in BREF, niet Tata-specifiek |
| NG_TATA_VN25_TOPUP | VN25-bijstook | VN25 krijgt aardgas bijgestookt als minimale brandstofbehoefte niet door productiegassen wordt gehaald citeturn32view1 | n.v.t. | Vattenfall interface | S02 | hoog | hoog | validation target / candidate structure | geen publieke minimum-load of efficiëntie |
| NG_DRI_RED | aardgas voor DRI-reductie | 8.1 citeturn28view0 | GJ/t DRI | DRI | S02 | hoog | hoog | candidate input | Phase 1 gas-based DRI |
| NG_DRI_HEATER | aardgas als brandstof in DRI-procesfornuis | 1.8 citeturn28view0 | GJ/t DRI | DRI | S02 | hoog | hoog | candidate input | Phase 1 gas-based DRI |
| NG_SITE_INTERFACE | aardgasinterfaces | extra levering naar DRI via GOS Zuid en naar WB2/andere verbruikers via GOS Noord/Zuid citeturn24view4 | n.v.t. | site import | S02 | hoog | hoog | validation target / candidate structure | geen publieke contractcapaciteiten voor modelgebruik |

### Stoom, boiler/CHP en on-site generation

| parameter_id | description | value_or_range | unit | process/carrier | source_id | source quality | confidence | suitable use | caveat |
|---|---|---:|---|---|---|---|---|---|---|
| CHP_BAT_USE | BAT-inzet van WAGs in boilers/CHP | desulphurised/dedusted surplus COG, BFG en BOF gas (mixed of apart) in boilers/CHP voor steam/electricity/heat citeturn12view0 | n.v.t. | boiler/CHP | S01 | hoog | hoog | approved modelling structure | exacte rendementen niet publiek |
| SITE_WAG_REUSE_REF | orde-grootte hergebruik productiegassen in referentie | 54 citeturn33view0 | PJ/yr | site level | S02 | hoog | hoog | validation target only | sitebalans, niet uurcoëfficiënt |
| SITE_RESIDUAL_POWER | residual-gas-based power generation | about 2.0 citeturn26view0 | TWh/yr | Vattenfall power | S03 | hoog | hoog | validation target only | corporate/public statement, geen dispatchcurve |
| BOF_WH_STEAM | stoom uit suppressed combustion waste heat boiler | 0.1–0.3 citeturn16view2 | GJ/t LS | BOF / boiler | S01 | hoog | middel | validation target / later only | discontinu, dus lastig voor simpele uur-MILP |
| BOF_TOTAL_RECOV | totale energie-terugwinning suppressed combustion + gas recovery | tot ca. 90% citeturn16view2 | % | BOF system | S01 | hoog | middel | validation target | procesconfiguratie-afhankelijk |
| DRI_STARTUP_STEAM | externe stoombehoefte bij DRI-opstart | ca. 50 citeturn31view1 | t/h | DRI steam | S02 | hoog | hoog | later only / startup scenario | niet gebruiken in steady-state minimal S3 |
| VATTENFALL_RUN_PATTERN | publieke inzetvolgorde centrales in Phase 1 | VN25 85% van de tijd, IJM-01 15%, VN24 back-up citeturn32view1 | n.v.t. | Vattenfall interface | S02 | hoog | hoog | validation target / later only | geen dispatchoptimalisatie zonder extra data |

### Zuurstof en utility buffers

| parameter_id | description | value_or_range | unit | process/carrier | source_id | source quality | confidence | suitable use | caveat |
|---|---|---:|---|---|---|---|---|---|---|
| OXYHOLDER_EXISTS | oxygashouder als buffer | ja; nodig door batchgewijze convertergasproductie en continue vraag citeturn7view2 | n.v.t. | BOF/oxygas | S02 | hoog | hoog | approved modelling structure | ondersteunt minimaal één BOF-holder of time-smoothing |
| OXYHOLDER_CAP_PUBLIC | publieke capaciteit oxygashouder | **niet robuust publiek geïdentificeerd** | n.v.t. | BOF/oxygas | S02 | hoog | middel | later only / assumption | niet invullen als “feit” |
| O2_BF_BOF_USE | generieke zuurstofbehoefte BF-BOF route | ca. 110–130 citeturn34view0 | Nm³/t crude steel | oxygen | S16 | middel | middel | validation only / sensitivity | secundaire factsheet, niet primair Tata |
| UTILITY_BUFFERS_PUBLIC | overige utilitybuffers | Tata noemt zuurstofbuffers en noodbuffer voor koelwater; EAF/DRI stoomsystemen hebben koppeling/met noodlogic citeturn9view2turn28view2 | n.v.t. | utilities | S02 | hoog | middel | later only | geen voldoende numerieke publieke ranges |

### DRI/EAF energy carriers en relevante off-gases

| parameter_id | description | value_or_range | unit | process/carrier | source_id | source quality | confidence | suitable use | caveat |
|---|---|---:|---|---|---|---|---|---|---|
| DRI_NG_RED | aardgas als reductiemiddel | 8.1 citeturn28view0 | GJ/t DRI | DRI | S02 | hoog | hoog | candidate input | Phase 1 aardgasfase |
| DRI_NG_FURN | aardgas als heater fuel | 1.8 citeturn28view0 | GJ/t DRI | DRI | S02 | hoog | hoog | candidate input | Phase 1 aardgasfase |
| DRI_EL | elektriciteitsverbruik DRI | 0.3 citeturn28view0 | GJ/t DRI | DRI | S02 | hoog | hoog | candidate input | beide DRI-fases volgens MER |
| DRI_CAPTURED_CO2 | afgevangen CO₂ in aardgasfase | circa 0.8 citeturn23view1turn23view2 | Mt/yr | DRI CO₂ capture | S02 | hoog | hoog | validation target / scenario input | niet automatisch “gepermanent opgeslagen” |
| DRI_TAILGAS_NG | tailgas-samenstelling aardgasfase | H₂ 54, CO 16, CH₄ 14, CO₂ 10, N₂ 5, H₂O 1 citeturn31view0 | vol-% | DRI tailgas | S02 | hoog | hoog | later only | lokale DRI-submodelparameter, niet minimal S3 |
| DRI_TAILGAS_H2 | tailgas-samenstelling waterstoffase | H₂ 87, N₂ 6, CH₄ 4, CO 1, CO₂ 1, H₂O 1 citeturn31view0 | vol-% | DRI tailgas | S02 | hoog | hoog | later only / sensitivity | fase 2/verdere verduurzaming |
| EAF_HEAT_RECOVERY | EAF-off-gas gebruikt voor scrap preheat + steam | ja citeturn29view4turn28view2 | n.v.t. | EAF | S02 | hoog | hoog | candidate structure / later only | zonder rendement eerst niet monetiseren |
| EAF_DRI_BUFFER | korte fysieke buffer tussen continue DRI en batch-EAF | hot DRI bunkers; koude DRI-opslag als noodbuffer citeturn29view4turn31view1 | n.v.t. | DRI/EAF coupling | S02 | hoog | hoog | later only | belangrijk, maar buiten minimal S3 |
| SEC_MET_EL | elektriciteit secundaire metallurgie | avg. 35; range 23–42 citeturn29view1turn29view2 | kWhe/t liquid steel | ladle/secondary metallurgy | S02 | hoog | hoog | candidate input | dit is **niet** het totale EAF-smeltverbruik |

### Emissiefactoren en CO₂-accounting

| parameter_id | description | value_or_range | unit | process/carrier | source_id | source quality | confidence | suitable use | caveat |
|---|---|---:|---|---|---|---|---|---|---|
| ETS_MRR_COMPLETE | monitoring moet alle proces- en verbrandingsemissies omvatten | ja citeturn22view1 | n.v.t. | accounting rule | S11 | hoog | hoog | approved accounting structure | wettelijke systematiek, geen modeldetail |
| ETS_WASTE_GAS_DEF | waste gas bevat onvolledig geoxideerde koolstof; CO₂ in mix blijft deel van waste gas | ja citeturn22view0 | n.v.t. | accounting rule | S12 | hoog | hoog | approved accounting structure | relevant voor ETS/free allocation-logica |
| NG_REF_EF | referentie-emissiefactor aardgas in EU benchmark guidance | 56.1 citeturn39view0 | tCO₂e/TJ | natural gas | S13 | hoog | hoog | candidate input / sensitivity | ETS-guidance bron; voor operationele emissies liefst documenteer als generieke EF |
| WG_EXPORT_ADJ | waste-gas exportcorrectie in benchmarkupdate | 37.4 af te trekken van actual EF bij exports citeturn39view0 | tCO₂e/TJ | waste gas ETS | S13 | hoog | hoog | later only | **alleen** voor ETS/free allocation-later, niet voor fysieke site-emissies |
| WG_IMPORT_EF | waste-gas importwaarde in benchmarkupdate | 48.0 citeturn39view0 | tCO₂e/TJ | waste gas ETS | S13 | hoog | hoog | later only | idem |
| TSN_SCOPE1_BASE | publieke historische baseline | 12.6 citeturn26view1turn21search15 | MtCO₂/yr | TSIJ/TSN | S03, S04 | hoog/middel | middel-hoog | validation target only | corporate/policy baseline, geen operationele parameter |
| TSN_SCOPE1_2425 | FY24/25 gross scope 1 TSN | 11.45 citeturn26view1 | MtCO₂e/yr | TSN | S03 | hoog | hoog | validation target only | corporate reporting scope |
| TSIJ_INTENSITY_2425 | FY24/25 CO₂-intensiteit TSIJ | 1.69 citeturn26view1 | tCO₂/t crude steel | TSIJ | S03 | hoog | hoog | validation target only | scope volgt Tata-reportinggrens |
| VATTENFALL_SCOPE1_RULE | verbranding residual gases bij Vattenfall telt in Tata reporting onder scope 1 | ja citeturn26view0turn27view1 | n.v.t. | boundary choice | S03, S05 | hoog | hoog | validation target / accounting choice | reporting boundary, geen universele ETS-regel |
| INTERNAL_GAS_LCA_RULE | interne BF/BOF-gas-, steam- en elektriciteitsstromen krijgen in worldsteel LCI geen extra burden; alleen netto export krijgt credit | ja citeturn40view1 | n.v.t. | accounting interpretation | S14 | middel-hoog | hoog | caution / sensitivity | **LCA-methodiek**, niet 1-op-1 ETS of dispatch |

## Modelleringsopties voor S3 en interne energiewaardering

### Vergelijking van drie modelleringsniveaus

| optie | kernopzet | vereiste data | benefits | risks | computational impact | thesis suitability | before/after DA bidding |
|---|---|---|---|---|---|---|---|
| **A. Geaggregeerde energielaag** | één of enkele geaggregeerde energiedragers; WAG-crediet als fuel-offset; geen houders; weinig interne topologie | geaggregeerde route-energiecoëfficiënten, totale gas-/energiebalans, generieke emissiecoëfficiënten | snel, weinig databehoefte, goed voor debug en sanity checks | verbergt carrier mismatch; risico op gratis opslag/arbitrage; zwakke koppeling aan Tata-topologie en Phase 1-schaarsheid | laag | alleen bruikbaar als tijdelijke tussenstap | **vóór** DA, maar niet sterk genoeg als verdedigbare eind-S3 |
| **B. Semi-gedetailleerde WAG-laag** | aparte BFG/COG/BOF-balansen; generatie gekoppeld aan materiaalstromen; optionele eenvoudige houder(s); generieke boiler/CHP/Vattenfall-sinks; spill/fakkelen | carrier-specifieke opbrengstcoëfficiënten, LHV/compositie, geaggregeerde sinks, importvariabelen, flare-penalty, eventueel simpele holder-bounds | bewaart fysica van WAG-schaarste; tracteerbaar; consistent met BAT en openbare Tata-topologie | nog beperkte zichtbaarheid op steam levels, unit efficiencies en contracten; houdercapaciteiten publiek schaars | middel | **beste keuze voor jouw S3** | **vóór** DA aanbevolen; eerst dit stabiel maken |
| **C. Gedetailleerd intern energienet** | gasmixing en calorific constraints, meerdere steam levels, unit-specifieke boilers/CHP, Vattenfall-dispatch, utilitynetten, oxygenet | unit- en netwerkspecifieke capaciteiten, rendementen, min/max loads, mengstations, holdercapaciteiten, steam pressure layers, contract/interfacelogica | hoge operationele realiteit; betere aansluiting op markt- en utilityvraagstukken | datavretend; gevoelig voor vertrouwelijke aannames; gevaar van schijnprecisie en solververzwaring | hoog tot zeer hoog | voor deze thesisfase te zwaar | **na** interne accounting-stabilisatie; pas daarna eventueel DA/markt |

De publieke literatuur en industriële cases ondersteunen vooral optie B als “sweet spot”. BAT zegt expliciet dat de energie-efficiëntie in geïntegreerde staalwerken verbetert door het optimaliseren van procesgasbenutting, gas holders, calorific control en het gebruik van by-product gases in boilers/CHP. JFE en ABB laten zien dat in de praktijk juist **gas holders, mixstations, externe brandstoffen, steam/power-koppeling en flaring** de bepalende structuur vormen van operationele modellen. citeturn12view0turn12view1turn36view0turn37view0

Voor jouw scope betekent dat: **start niet met optie C**. Tata-specifieke dauwpunten, stoomdrukniveaus, unit efficiency curves, houdercapaciteiten, minima van VN25/IJM-01 en interne transferprijzen zijn publiek niet robuust genoeg. Een full-network model zou daarom waarschijnlijk **meer aannamen dan bewijs** bevatten. citeturn32view1turn24view4turn26view0

### Interne energiewaardering zonder vertrouwelijke transferprijzen

De veiligste S3-aanpak is een **fysisch-boekhoudkundige objective** met externe kosten en emissies, niet met interne pseudo-omzet. Dat leidt tot de volgende waarderingshiërarchie.

| methode | logica | sterke punten | zwakke punten | beoordeling voor S3 |
|---|---|---|---|---|
| **Replacement value vs. natural gas** | waardeer 1 GJ WAG alleen wanneer die aantoonbaar een expliciet gemodelleerde externe brandstof vervangt, gecorrigeerd voor nuttige energie / conversiepad | publiek verdedigbaar; geen vertrouwelijke transferprijzen nodig; sluit aan op BAT-logica van vervanging van primaire energie citeturn12view0turn16view2 | vereist expliciet sink- en efficiëntiepad; geen directe stroomprijs-credit zonder conversie | **veiligste primaire methode** |
| **Marginale on-site generation value** | waarde = vermeden externe stroominkoop via expliciet gemodelleerde boiler/CHP/power plant | economisch realistisch zodra CHP/boiler gemodelleerd is | zonder publieke rendementen/minima wordt dit snel speculatief; risico op stroomprijs-arbitrage | **sensitivity only** totdat CHP/Vattenfall voldoende expliciet is |
| **Avoided flaring / spill penalty** | kleine maar niet-nul penalty op flare/spill om energieverlies en emissiedisutility weer te geven | essentieel om gratis disposal te voorkomen; past bij BAT-flaremonitoring en worldsteel flare ladder citeturn12view0turn40view0 | publieke absolute penaltywaarde niet robuust | **aanbevolen als aanvullende term** |
| **Zero-value fysieke boekhouding** | WAG alleen balanceren, geen positieve waarde geven | veilig voor debug en fysieke validatie | in vergelijkende scenariostudies kan dit de waarde van WAG-benutting onderschatten; als flare ook nul kost, ontstaat free-disposal | **alleen debug/validation-only** |
| **Elektriciteitsmarktprijs als directe WAG-waarde** | 1 GJ WAG ≈ stroomprijs | simpel | fysisch fout zonder conversie; creëert gratis arbitrage en overschat waarde van lage-LHV-gassen | **niet gebruiken** |
| **Vertrouwelijke interne transferprijs** | Tata/Vattenfall interne verrekening | mogelijk realistischer intern | niet publiek verdedigbaar | **niet gebruiken** |

Mijn concrete aanbeveling voor jouw minimal S3 is daarom:

1. **Geef WAG geen autonome opbrengstterm.**  
2. **Laat WAG alleen waarde krijgen via expliciet gemodelleerde substitutie** van extern aardgas of, later, expliciet gemodelleerde on-site generation.  
3. **Voeg een niet-nul flare/spill-penalty toe** om gratis dumpen te voorkomen.  
4. **Rapporteer eventueel ex post schaduwprijzen** van gasbalansen als diagnostiek, maar gebruik die niet als exogene inputparameter. citeturn12view0turn36view0turn37view0turn40view1

## Emissieboekhouding en aanbevolen minimale S3

### Eerste emissielaag voor S3

Een verdedigbare **eerste** emissielaag voor S3 kan uit vijf delen bestaan.

Ten eerste moet je **directe procesemissies** apart kunnen registreren voor productiestappen die niet louter een energieverbrandingskwestie zijn. Dat is vooral belangrijk voor de BF–BOF-basisroute en voor de gas-based DRI-route, waar Tata publiek zegt dat de DRI-fabriek in de aardgasfase ongeveer **0,8 Mt/jaar CO2** produceert en afvangt. citeturn23view1turn23view2

Ten tweede moet je **verbranding en fakkelen van WAGs en aardgas** apart kunnen boeken. De EU MRR vereist dat monitoring en rapportage volledig zijn en zowel proces- als verbrandingsemissies omvatten. Voor waste gases zegt de ETS-guidance bovendien dat een gasstroom met onvolledig geoxideerde koolstof als waste gas wordt behandeld en dat CO2 die onderdeel is van die mix boekhoudkundig tot de waste-gas-stroom blijft behoren. citeturn22view1turn22view0

Ten derde moet je **WAG-combustie niet dubbel tellen**. Dat is waarschijnlijk de grootste modelvalkuil. Als je de koolstof in BFG/COG/BOFG al volledig als procesemissie boekt op het moment van generatie, en daarna opnieuw als verbrandingsemissie bij gebruik of fakkelen, verdubbel je de site-emissies. Daarom moet je in S3 één **consistente koolstofarchitectuur** kiezen. De veiligste keuze voor een eerste operationele energielaag is meestal:  
**(a)** boek expliciete niet-WAG-procesemissies direct bij het proces,  
**(b)** boek de koolstof in WAGs pas wanneer die het systeem als emissie verlaat via verbranding/fakkel/vent/export,  
**(c)** geef interne WAG-verplaatsingen geen extra emissiecredit of -debet.  
Die aanpak is ook consistent met worldsteel’s waarschuwing dat interne process-gas flows methodisch geen nieuwe extra last of credit krijgen zolang zij binnen het systeem blijven. citeturn40view1turn22view0turn22view1

Ten vierde kun je **elektriciteit-indirecte emissies** optioneel meenemen, maar dan als **aparte rapportagelaag**. Tata’s publieke corporate scope-2 logica is niet automatisch de juiste keuze voor jouw MILP-grens, ook al rapporteert Tata bij IJmuiden Vattenfall-residual-gasemissies onder scope 1. Voor de thesis is het veiliger om scope 2 als aparte, schakelbare module te houden met een expliciete grid-emissiefactor en met een heldere noot dat dit **geen ETS-emissie** is. citeturn26view0turn27view1turn22view1

Ten vijfde kun je een **ETS-gross-cost placeholder** opnemen, maar **niet** al een volledige free-allocation-module. Officiële EU-bronnen bevestigen dat vrije allocatie benchmarkgebaseerd is en dat ijzer/staal daar productbenchmarks voor heeft, onder meer voor **coke, sintered ore, hot metal en EAF carbon steel**. Dat is genoeg om later een Wave E- of later-S3+ accountingstudie te rechtvaardigen, maar onvoldoende om nu een Tata-specifieke netto-ETS-positie te claimen. citeturn22view2turn39view0turn39view1

Wat je in deze wave **niet** moet claimen, is dus: een Tata-specifieke netto ETS-lastenreeks, exacte vrije allocatie na CBAM/fase-4-wijzigingen, contractueel juiste emissietoerekening tussen Tata en Vattenfall, of proces-unit-specifieke CO2-prijzen. citeturn22view2turn39view0

### Recommended minimal S3 parameter set

De kleinste verdedigbare uitbreiding na S2 is geen complete utility simulator, maar een **energy-cost-emissions layer met drie expliciete WAG-carriers plus externe imports en emissieboekhouding**.

| categorie | minimale S3-set | geschikte status | motivatie |
|---|---|---|---|
| carriers | BFG, COG, BOF/LD-gas, aardgas, elektriciteit, optioneel captured CO₂ | approved modelling structure | deze zes dekken de kern van het publieke Tata/BAT-verhaal citeturn14view0turn8view3turn23view1 |
| gas generation coefficients | BFG per t HM; COG per t coke of coal; BOF-gas per t liquid steel | candidate input | publiek goed onderbouwde generieke ranges uit BREF citeturn14view2turn15view1turn15view2turn14view3 |
| energy demand coefficients | route-/unit-geaggregeerde thermische vraag; DRI aardgas + elektriciteit; optioneel secundaire metallurgie-elektriciteit | candidate input | DRI-gegevens publiek Tata; overige thermische vraag eerst geaggregeerd houden citeturn28view0turn29view1 |
| WAG-balans | per uur per carrier: generatie + import + beginvoorraad = gebruik + eindvoorraad + flare/spill | approved modelling structure | nodig om gratis brandstof/opslag te voorkomen |
| holder bounds | minimaal optioneel voor BOF/oxygas; anders initieel geen houders maar wél spill | candidate structure | Tata-specifieke houder-existence is sterk voor oxygas, niet voor capaciteiten citeturn7view2 |
| gas mixing | géén expliciete mixed-gas-compositie in minimal S3 | postpone | onvoldoende robuuste publieke setpoints; pas later |
| fuel import | aardgasimport expliciet; elektriciteitsimport expliciet | approved modelling structure | externe kosten en emissies moeten zichtbaar worden citeturn24view4turn33view0 |
| on-site generation interface | één generieke Vattenfall/on-site-generation sink met bounds of availability scenario; geen unit-dispatch | candidate structure / validation only | vangt publieke Phase 1-logica zonder vertrouwelijke power-plantdata citeturn32view1turn26view0 |
| flare/spill variable | aparte flare- of spillvariabele per carrier | approved modelling structure | BAT en Tata-documenten maken flare expliciet relevant citeturn12view0turn7view2turn31view1 |
| emissions coefficients | aardgas EF; carrier-specifieke WAG-EF’s als sensitiviteit; captured CO₂ apart | candidate input + sensitivity | consistente eerste emissielaag |
| valuation terms | aardgasvervangingswaarde + flare penalty; geen autonome WAG-revenue | approved modelling structure | vermijdt arbitragelogica |
| validation checks | totale orde-grootte WAG-hergebruik, residual-gas-based stroom, Phase 1 daling productiegassen, stijging NG | validation target only | sluit aan op publieke Tata-evidentie citeturn33view0turn26view0turn32view1 |

In woorden is de minimale S3-uitbreiding dus: **“carrier-specifieke WAG-massa/energiebalansen + externe imports + flare + emissies + eenvoudige waardering”**. De grootste winst daarvan is niet dat hij alle utilities perfect beschrijft, maar dat hij jouw basisscenario en Phase 1-route **consequent vergelijkt** zonder de energetische rol van WAGs te verbergen. citeturn12view0turn40view0turn26view0

## Niet nu modelleren, red flags, repo handoff en vervolg

### Parameters to postpone

| item | waarom uitstellen | status |
|---|---|---|
| full Vattenfall dispatch | publieke informatie bevestigt interface en inzetvolgorde, maar niet de detailrendementen, minima, contracten en dispatchregels | postpone |
| gedetailleerd stoomnet met drukniveaus | Tata beschrijft systemen, maar publieke data voor een consistent meerlagig steam network zijn onvoldoende | postpone |
| vertrouwelijke interne transferprijzen | niet publiek verdedigbaar | postpone |
| gedetailleerde ETS/free allocation-module | officiële benchmarkcontext is beschikbaar, maar Tata-specifieke netto-allocatie niet | postpone |
| volledig oxygenet/utility scheduling | topologie deels publiek, capaciteiten en kosten niet robuust | postpone |
| DA bidding / quarter-hour / mFRR / stochastic logic | expliciet buiten scope van deze wave en prematuur vóór stabiele interne energie-accounting | postpone |

### Red flags

| red flag | waarom problematisch | wat S3 moet doen |
|---|---|---|
| WAGs als gratis brandstof | onderschat externe energiebehoefte en vertekent routevergelijking | voer carrierbalansen en expliciete sinks in |
| WAGs als gratis opslag | creëert intertemporele waarde zonder houderkosten/-limieten | gebruik spill en eventueel simpele holder-bounds met terminale restrictie |
| waarderen tegen pure elektriciteitsprijs | fysisch onjuist zonder boiler/CHP-conversie | alleen waarderen via expliciete omzettingsketen |
| ETS als automatische revenue | vrije allocatie is benchmark-/regelgevingsafhankelijk en plantspecifiek | gebruik hoogstens gross-cost placeholder |
| dubbele emissietelling van WAGs | kan totale site-emissies fors overschatten | kies één consistente koolstofarchitectuur |
| fakkelen zonder penalty | maakt disposal kunstmatig goedkoop en kan WAG-benutting ondermijnen | gebruik altijd niet-nul flare/spill-penalty |
| negeren van gas-holder eindvoorwaarden | laat model “leegtrekken” of “volstoppen” voor gratis voordeel | gebruik end-horizon band of rolling-horizon consistentie |
| DA-biedlogica vóór interne accounting | optimaliseert op marktprikkel terwijl plantfysica nog instabiel is | market layer pas later toevoegen |
| BF–BOF versus DRI–EAF vergelijken zonder consistente WAG-accounting | bevoordeelt de route waarvan energetische bijproducten impliciet genegeerd worden | bouw eerst consistente WAG-keten in beide routes |

Deze red flags zijn geen theoretische details. De BAT-documenten, de JFE/ABB-praktijkcases en de Tata-documenten wijzen allemaal dezelfde kant op: geïntegreerde staalenergiesystemen zijn **interconnected systems**, en juist in zulke systemen veroorzaken kleine boekhoudkundige shortcuts snel grote systematische fouten. citeturn12view1turn36view0turn37view0turn8view3

### Repo handoff

| artefact | concrete actie |
|---|---|
| source cards | voeg ten minste S01–S14 toe; markeer S01/S02/S03/S11/S12/S13 als “high authority”; koppel elke card aan `evidence_type`, `scope_boundary`, `plant_specificity`, `suitable_use` |
| `parameter_universe` updates | voeg categorieën toe voor `gas_generation_coeff`, `gas_lhv`, `gas_composition`, `gas_holder_logic`, `flare_penalty`, `external_fuel_import`, `site_energy_interface`, `captured_co2`, `emission_factor`, `scope_boundary_rule`, `validation_target` |
| candidate parameter files | maak aparte bestanden of tabbladen voor `wags_bfg_generic`, `wags_cog_generic`, `wags_bof_generic`, `dri_eaf_energy_generic`, `tata_phase1_energy_topology`, `emissions_s3_accounting`, `valuation_sensitivity_s3` |
| assumptions register | voeg expliciet toe: `no confidential Tata transfer prices`, `Vattenfall modeled as interface not dispatch plant`, `BOF holder capacity unknown`, `mixed-gas setpoint unknown`, `WAG combustion accounting chosen to avoid double counting`, `derived WAG EFs are sensitivity only` |
| validation checks | maak checks op: (i) productiegassen zijn hoofdenergiedragers, (ii) referentiesite hergebruikt orde-grootte 54 PJ/yr productiegassen, (iii) residual-gas power orde-grootte ≈2.0 TWh/yr, (iv) Phase 1 vermindert BFG/COG/BOFG en verhoogt NG, (v) DRI aardgasfase geeft orde-grootte 0.8 Mt/yr captured CO₂ |
| toekomstige approved-input-tabelkolommen | voeg kolommen toe voor `source_id`, `public_or_derived`, `time_basis`, `unit`, `route`, `carrier`, `confidence`, `suitable_use`, `validation_link`, `assumption_flag`, `sensitivity_flag`, `boundary_note` |

### Follow-up research needed for Wave E

Voor Wave E blijven vooral de financieel-regelgevende en marktinterfacevragen over. Dat betreft: **ETS/free allocation**, **netwerktarieven**, **aansluitcapaciteiten**, **expliete elektriciteits- en gasprijsstructuren**, **mogelijke staal-/productwaarderingsvelden**, **settlementlogica**, en pas daarna eventuele **balancing- of mFRR-parameters**. De officiële benchmarkdocumenten zijn daarvoor relevant, maar pas nadat jouw interne energie-accounting fysisch stabiel is. citeturn22view2turn39view0turn39view1

### Open vragen en beperkingen

Niet robuust publiek gevonden, en dus **niet** invullen als “feit”, zijn onder meer: Tata-specifieke gas-holdercapaciteiten, specifieke rendementen van VN24/VN25/IJM-01, interne Tata/Vattenfall-transferwaarden, unit-specifieke stoomdrukniveaus en gedetailleerde calorific setpoints van mixed gas. Voor het thesisdoel is dat geen blokkade; het is juist een argument om minimal S3 als **carrier-specifieke maar geaggregeerde** laag te ontwerpen en die ontbrekende elementen als latere refinements of sensitiviteiten te behandelen. citeturn7view2turn32view1turn36view0

### Compacte handoff summary

De meest verdedigbare volgende stap na S2 is een **semi-gedetailleerde WAG-S3** met **BFG, COG en BOF/LD-gas als aparte carriers**, gekoppeld aan S2-throughput via publieke generieke coëfficiënten. Voeg **aardgas- en elektriciteitsimport**, **flare/spill-variabelen**, **optioneel een eenvoudige BOF/oxygas-holder**, en een **eerste emissielaag** toe met procesemissies, WAG-/NG-verbranding, en aparte DRI-CO₂-capture. Waardeer WAGs **niet** met vertrouwelijke transferprijzen en **niet** rechtstreeks met de stroomprijs; gebruik in plaats daarvan **vervangingswaarde tegenover expliciet gemodelleerde externe brandstof** plus een **niet-nul flare-penalty**. Houd **Vattenfall** in minimal S3 als **exogene interface**, niet als volledig dispatchmodel. Stel volledige steam-/utilitynetten, ETS-free allocation, contractdata en DA/mFRR-logica uit tot Wave E of later. citeturn12view0turn8view3turn32view1turn22view1turn40view1