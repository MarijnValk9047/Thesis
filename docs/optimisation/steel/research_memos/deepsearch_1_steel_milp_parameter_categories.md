# Parameteruniversum en modelstructuur voor een Tata Steel IJmuiden-geïnspireerde staal-MILP

## Kernbevindingen

**Executive finding.**  
Voor jouw thesis is het belangrijkste inzicht dat een tractable staal-MILP niet begint met “alle mogelijke parameters”, maar met een **gelaagde procesnetwerkrepresentatie** waarin een beperkt aantal parameterfamilies eerst correct wordt vastgezet: topology, doorzet/capaciteit, materiaalrecepten en -yields, gedeelde bottlenecks, interne energiedragers, opslaggrenzen, emissieregels en marktinterfaces. De publieke Tata-bronnen bevestigen dat IJmuiden vandaag een klassieke geïntegreerde BF–BOF-site is met kooks- en gasfabrieken, sinter- en pelletfabriek, twee hoogovens, de Oxystaalfabriek, Direct Sheet Plant, warmbandwalserij en een eigen energiebedrijf dat werkt met procesgassen; het publieke Heracless/MER-ontwerp voegt daar voor fase 1 een DRI-fabriek, EAF, extra secundaire metallurgie, schrootlogistiek, DRI-silo’s en nieuwe elektrische infrastructuur aan toe, terwijl KGF2 en HO7 uit bedrijf gaan. Dat maakt een **hybride BF–BOF + DRP–EAF procesnetwerk** publiek verdedigbaar, maar alleen als je strikte anti-arbitrage- en anti-fake-flexibiliteitsregels opneemt voor gashouders, schroot, DRI, slab/WIP en eindvoorraden. citeturn8view0turn8view1turn12view0turn6view1turn6view2turn9view8turn30view0turn30view1

**Wat het model in fase één wél en niet moet zijn.**  
De publieke Tata-documenten zijn sterk genoeg om een **site-geïnspireerde topologie, publieke validatiedoelen en orde-grootte constraints** te onderbouwen, maar niet om een digitale twin met vertrouwelijke recepturen, kostcurves en quality windows te bouwen. Voor een eerste deterministische, uurlijke LP is het daarom methodologisch beter om **massabalansen en gedeelde capaciteiten** centraal te zetten en pas later stapsgewijs energiekosten, ETS, scenario-onzekerheid, kwartierresolutie, D+4 en mFRR toe te voegen. De reviewliteratuur over staal-materiaal- en energiestromen laat bovendien zien dat veel bestaande studies nog statisch of deelgeoptimaliseerd zijn; juist de koppeling tussen materiaalflow en energienetwerk veroorzaakt de moeilijkheidsgraad en de grootste kans op modelmisleiding. citeturn22view0turn31view5turn27view0turn15view2

**De hoogste-risico parametercategorieën.**  
De categorieën met het grootste risico op verkeerde conclusies zijn deze:

- **Gedeelde route- en downstreamcapaciteiten**: BF/BOF/OSF/caster/rolling/EAF/DRI moeten als gekoppeld netwerk worden begrensd, niet als losse eenheden. citeturn10view0turn11view4turn12view0
- **Materiaalrecepten en yields**: hot metal, sinter/pellets/coke/PCI, BOF-schroot, DRI- en EAF-recepten, slak/dust/losses en steel yield domineren haalbaarheid. citeturn11view7turn35view1turn35view3turn35view4
- **WAG- en intern gasnetwerk**: BFG, COG, BOF/LD-gas, gasholders, mengregels, calorische waarde en afnemers zijn geen detail; ze bepalen zowel kosten als realistische flexibiliteit. citeturn31view0turn33view0turn33view1turn33view2turn10view3
- **Buffers en stores**: schrootopslag, koude DRI-silo’s, zuurstofbuffers, oxygashouder, slab/WIP en terminal inventory mogen nooit als gratis batterij worden gemodelleerd. citeturn9view0turn9view8turn9view7turn10view3turn10view0
- **Elektriciteitsaansluiting en piekbegrenzing**: de EAF maakt netcapaciteit en pieklast economisch dominant, dus alleen gemiddelde energieprijzen modelleren is onvoldoende voor latere fasen. citeturn30view1turn30view2turn30view3
- **Productmix en kwaliteitskoppelingen**: schroot- en DRI-fracties hangen af van kwaliteitsdoel, metallisatie, downstream specificaties en secundaire metallurgie; zonder die koppelingen ontstaat valse extra flexibiliteit. citeturn15view2turn23view5turn10view0
- **Emissiebehandeling**: directe emissies, CO2-afvang, ETS/free allocation/CBAM en by-product credits zijn economisch te dominant om als één vaste scalar te worden vastgezet zonder sensitiviteit. citeturn35view2turn29search0turn29search1turn29search13
- **Eindhorizon- en voorraadwaardering**: eindvoorraad zonder floor, penalty of shadow value veroorzaakt structureel intertemporele arbitrage. Dat is vooral riskant zodra DA-prijzen, scenario’s of reservewaarden worden toegevoegd. citeturn22view2turn27view3turn31view5

**Kort advies.**  
De kleinste verdedigbare eerste staalversie is geen marktbied-MILP maar een **deterministische uurlijke materiaalstroom-LP** met twee routes, gedeelde downstreams, begin/eindvoorraadrestricties, beperkte opslag, vaste of begrensde route-yields en expliciete throughput-validatie. Alles wat economisch dominant maar publiek zwak is — echte marginale kosten, ETS-netting, netwerktarieven, exact grade-mixgedrag, onderhoudspatronen, EAF-onderbreekbaarheid en mFRR-logica — hoort pas later of uitsluitend als sensitiviteit in beeld. citeturn22view0turn27view0turn24view5turn25view6

## Zoekscope en bronkwaliteit

**Zoekscope en methode.**  
Deze scan is opgebouwd volgens de door jou gevraagde hiërarchie: eerst publieke Tata/IJmuiden-bronnen, daarna Europese/sectorale primaire bronnen, vervolgens peer-reviewed literatuur over geïntegreerde staalplantoptimalisatie, en pas daarna technologie- en transitie-rapporten. De door jou genoemde theses van Athanasiadis en Badarinath waren in deze onderzoekssessie niet rechtstreeks toegankelijk; daarom gebruik ik ze hier niet als feitelijke parameterbron, maar behandel ik hun rol impliciet als “prior work dat later offline moet worden gespiegeld aan publieke bronnen”. Methodologisch zijn wel termen gescand rond BF–BOF, DRI–EAF, integrated steel plant MILP, by-product gas scheduling, mass-thermal networks, Tata Green Steel Plan/Heracless, JRC BREF, IEA roadmap, Agora en MPP.

**Bronkwaliteit en wat elke bronsoort wél ondersteunt.**  
Voor dit onderwerp is de robuustste volgorde ongeveer als volgt:

| bronsoort | betrouwbaarheid voor topology | betrouwbaarheid voor parameterwaarden | wat de bron goed ondersteunt | wat de bron meestal níet goed ondersteunt |
|---|---|---:|---|---|
| Publieke Tata-site, MER, jaarverslag | zeer hoog voor site-topologie | middelmatig voor publieke capaciteiten en validatiedoelen | huidige en geplande route-architectuur, installatieketen, publieke volumedoelen, publieke aansluitingen, openbare stores/buffers | vertrouwelijke yields, exacte kostcurves, maintenance data, grade-specifieke recipe-ranges |
| Officiële primaire sectorbronnen zoals JRC BREF, IEA, EC ETS/CBAM | hoog | middelmatig tot hoog voor generieke ranges en definities | procesdekking, typische gascomposities, emissie- en energiedragerdefinities, beleidscategorieën | staalsoortspecifieke site-economie, lokale operationele keuzes |
| Peer-reviewed reviews en optimalisatiepapers | middelmatig tot hoog | middelmatig | welke variabelen/constraints MILP’s typisch gebruiken, waar de modelrisico’s zitten, welke subsystemen vaak vergeten worden | Tata-specifieke waarden en openbare verdedigbaarheid |
| Transitie- en technologie-rapporten van Agora, MPP, worldsteel | middelmatig voor structuur, hoog voor routevergelijking | middelmatig | orde-grootte routing, technologieafweging, pellets/scrap/H2/elektriciteit als kosten- en bottleneckdrivers | echte sitespecifieke dispatchlogica op uurniveau |
| Theses en interne projectnota’s | nuttig voor modellogica | laag tot middelmatig voor publieke waarden | code-/modelopzet, vocabulaire, implementatiekeuzes, redactionele waarschuwingen | externe verdedigbaarheid als primaire bron voor sitewaarden |

Deze ranking volgt direct uit hoe de bronnen zichzelf positioneren: de Tata MER geeft de technische beschrijving van huidige en voorgenomen installaties; de JRC BREF definieert welke processen in geïntegreerde en EAF-staalwerken onder het systeem vallen; de IEA roadmap en Agora/MPP-documenten vergelijken routefamilies en resource drivers; de reviewliteratuur vat vervolgens samen welke mathematische modelblokken in de praktijk dominant zijn. citeturn4view0turn15view1turn24view5turn15view2turn15view3turn22view0

**Praktische bronconclusie.**  
Gebruik publieke Tata-bronnen vooral voor **topologie, publieke verificatiepunten en openbare grensvoorwaarden**. Gebruik JRC/IEA/worldsteel/Agora/MPP voor **generieke parametersets, carrierdefinities, orde-grootte ranges en structuur van emissie- en energienetwerken**. Gebruik academische optimalisatiepapers vooral voor **constraintfamilies, objective-termen, inventory-dynamiek, robust/stochastic uitbouw en bekende failure modes**. Gebruik aannames alleen bij parameters die ofwel openbaar niet bestaan, ofwel extreem productspecifiek/confidentieel zijn — en label die aannames dan expliciet als sensitivity-only. citeturn4view0turn33view0turn33view1turn15view0turn22view0turn27view0turn27view2

## Ontdekte modelstructuur

**Generieke procesnetwerkstructuur.**  
De meest verdedigbare generieke representatie voor jouw thesis is een **process-network model** met zes typen objecten: procesunits, materiaalcarriers, energiecarriers, stores/buffers, externe bronnen/markten en accountinglagen. De JRC BREF legt voor geïntegreerde werken en EAF-werken expliciet de operationele scope vast: bulk handling, blending, coke, sinter/pellet, hot metal via blast furnace, BOF-staalmaken inclusief hot-metal desulfurisation en ladle metallurgy, EAF-staalmaken inclusief downstream ladle metallurgy en continue gieterij. De review van Sun et al. splitst de literatuur bovendien systematisch in drie blokken: materiaalflow, energienetwerk en hun onderlinge koppeling, wat precies aansluit op jouw gefaseerde thesisopzet. citeturn15view1turn22view0

**Procesunits.**  
Voor huidige IJmuiden-topologie horen in een publiek verdedigbare baseline minimaal thuis: erts-/kolenontvangst en mengvelden, pelletfabriek, sinterfabriek, kooks- en gasfabrieken, hoogovens, Oxystaalfabriek met converters, secundaire metallurgie, continugieten/DSP en warmbandwalserij, plus een interne energievoorziening die productiegassen, stoom en elektriciteit verdeelt. Tata’s publieke Plants-pagina en MER beschrijven precies die keten. Voor fase 1 verschuift de topologie naar één resterende hoogovenroute plus één DRI–EAF-route, met nieuwe DRI-reactor, heater, gasbehandeling, CO2-afvang, EAF, extra secundaire metallurgie, schrootopslag, dagsilo’s en koude DRI-silo’s, en nieuwe elektrische aansluitingen. citeturn8view1turn12view0turn6view1turn6view2turn8view0turn7view1turn7view2turn9view7

**Carriers en bussen.**  
Je model moet carriers niet beperken tot “elektriciteit en staal”. Voor BF–BOF zijn minstens relevant: ijzererts/sinter/pellets/coke/PCI/fluxen/schroot/hot metal/liquid steel/slak/stof als materiaalcarriers, en BFG, COG en BOF/oxygas als works-arising gases, plus aardgas, stoom, zuurstof, stikstof, water en elektriciteit als energie- en utilitycarriers. De BREF geeft typische procesgassamenstellingen en verbrandingswaarden, terwijl de reviewliteratuur expliciet aangeeft dat staalwerken vaak een gas-subnetwerk met BFG/COG/LDG en soms mixed gas hebben, naast stoom-, power- en oxygen-network modellen. citeturn33view0turn33view1turn33view2turn31view0turn31view1turn31view4

**Stores en buffers.**  
Buffers zijn in staal niet generiek; ze zijn technisch gekwalificeerd. Tata noemt onder meer zuurstofbuffertanks om continue O2-productie te koppelen aan batchvraag van converters, een oxygashouder van 83.400 m³ om batchvrij oxygas te bufferen, schrootopslagplaatsen SOP4 en SOP5, dagsilo’s voor pellets en koude DRI-silo’s. Tegelijk zegt de MER expliciet dat koude DRI slechts wordt gebruikt bij stilstanden/afwijkende situaties en dat DRI en EAF planmatig samen moeten worden afgestemd. Dat betekent dat jouw model opslag wel moet hebben, maar mét fysische rol, minimale/ maximale inhoud, initiële/finale niveaus, charge/discharge-beperkingen, verlies- of degradatietermen en zo nodig dwell-time- of throughput-gebonden restricties. citeturn9view0turn9view8turn9view7turn5view4

**Conversiefactoren, emissies, kosten en validatie.**  
De kernconversies zijn materiaalrecepten, yields en carrierconversies per procesunit: BF ore-to-hot-metal plus BFG/slag; BOF hot-metal-plus-scrap-to-liquid-steel plus oxygas/slag; DRI pellets-plus-reductant-to-hot/cold DRI plus off-gas/CO2; EAF DRI-plus-scrap-plus-electricity-plus-auxiliaries-to-liquid steel plus slag/off-gas. Op de accountinglaag moeten daar dan directe emissies, captured CO2, indirecte power exposure, variable raw-material costs, utility costs, gas opportunity costs, waste/by-product values en later DA settlement-parameters bovenop komen. Validatie hoort niet pas achteraf te gebeuren: je hebt publieke validatiedoelen nodig voor jaarthroughput, route-splits, schrootratio’s, liquid-steel output, publieke netaansluiting en bekende openbare installatiecapaciteiten. De Tata MER en jaarverslag leveren daar openbare ankerpunten voor, bijvoorbeeld 6.75 MTPA liquid steel in FY2024/25, een nominale sitecapaciteit van circa 7.23 Mt crude steel per jaar, en publieke fase-1 routevolumes en netverzwaring. citeturn35view1turn35view3turn35view4turn25view0turn25view1turn30view1turn30view2

**Marktgerichte parameters.**  
Marktparameters horen pas een laag later thuis dan massabalans, maar ze moeten vanaf het begin als aparte datadomeinen worden gedacht: DA price time series, gate closure, productieverplichting per horizon, imbalance/settlementregels, ETS and free allocation treatment, transporttarieven, contracted capacity, scenario probabilities en later reserve-capacity/activation rules. De IEA en EC-bronnen maken duidelijk dat material efficiency, electrification, hydrogen en policy variables zoals ETS/CBAM de route-economie sterk beïnvloeden; juist daarom moet je zulke parameters als **exogene marktlaag** modelleren en niet door elkaar mengen met fysische procescoëfficiënten. citeturn24view5turn24view1turn29search0turn29search1turn29search13

## Kandidaat parameteruniversum

De tabel hieronder is een **synthese**, geen finale inputlijst. Hij combineert publieke Tata-topologie, JRC/IEA/Agora/MPP-routekennis en peer-reviewed optimalisatieliteratuur over materiaal-, gas-, stoom- en powernetwerken. De tabel is dus bedoeld als **parameterkaart voor classificatie**, niet als goedgekeurde waardenset. citeturn4view0turn12view0turn15view1turn15view2turn15view3turn22view0turn27view0

| category | subcategory | example_parameter_id | description | unit | applies_to_process_or_carrier | configuration: current / Phase 1 / both / later | model role: input / constraint / objective / validation target / assumption / sensitivity | required phase: S2 material-flow LP / S3 energy-cost-emissions / S4 Phase 1 flexibility / S5 DA bidding / S6 stochastic-CVaR / S7 quarter-hour-D+4 / S8 mFRR | priority: critical / important / optional / later | likely source tier | public_reportability: public / likely confidential / assumption-only / mixed | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| time and market | time set | T_HOUR | dispatch periods | h | all | both | input | S2+ | critical | 5 | public | starts as hourly deterministic |
| time and market | horizon set | HORIZON_DA | optimization horizon | h/day | both | input | S2+ | critical | 5 | public | D-only first; D+4 later |
| time and market | DA prices | p_da_t | day-ahead electricity price | €/MWh | power bus | both | input/objective | S5+ | important | 1 | public | not needed for pure S2 feasibility |
| time and market | scenario weights | prob_s | scenario probability | - | scenarios | later | input | S6+ | later | 1/5 | public | only after deterministic stability |
| site boundary | route activation | y_route_bf_bof, y_route_dri_eaf | available route topology | binary/share | route blocks | current/Phase 1 | input/constraint | S2+ | critical | 1 | public/mixed | topology public; dispatch freedom partly assumed |
| site boundary | external sources | cap_import_scrap_t | allowable external feed imports | t/h | scrap/pellets/slabs/gas | both | input/constraint | S2+ | important | 1/4/5 | mixed | sourcing split often confidential |
| production | liquid steel target | dem_ls_t | required liquid steel / crude steel output | t/h or t/day | route sink | both | input/constraint | S2+ | critical | 1/5 | mixed | thesis needs explicit target discipline |
| production | route share target | target_bf_share | desired route split | % | BF–BOF / DRI–EAF | Phase 1 | validation target/sensitivity | S4+ | important | 1 | public/mixed | use as scenario or validation, not hard fact unless justified |
| production | product mix | mix_flat_auto_packaging | steel grade / product family mix | % | downstream demand | both | input/sensitivity | S3+ | important | 1/4/5 | likely confidential | crucial but weakly public |
| process unit | BF throughput | cap_bf_hm_t | max/min hot metal rate | t HM/h | BF | current/both | input/constraint | S2+ | critical | 1/2 | mixed | campaign behavior cannot be ignored |
| process unit | BOF throughput | cap_bof_ls_t | converter liquid steel capacity | t LS/h | BOF | current/both | input/constraint | S2+ | critical | 1/2 | mixed | converter is batch physically, but LP may average hourly |
| process unit | DRI throughput | cap_dri_t | DRI production capacity | t DRI/h | DRI | Phase 1 | input/constraint | S4+ | critical | 1/4 | public/mixed | public annual range exists; hourly detail not public |
| process unit | EAF throughput | cap_eaf_ls_t | EAF liquid steel capacity | t LS/h | EAF | Phase 1 | input/constraint | S4+ | critical | 1/2/4 | mixed | avoid unconstrained fast interruption |
| process unit | caster/downstream | cap_cast_t / cap_hsm_t | shared casting/rolling sink capacities | t/h | casting/DSP/HSM | both | constraint/validation target | S2+ | critical | 1 | public/mixed | prevents fake “produce and park forever” behavior |
| process unit | availability | avail_u_t | outages / maintenance / operational status | 0-1 | all units | both | input/constraint/sensitivity | S2+ | important | 1/5 | mixed | public only for coarse planned outages |
| process unit | ramping | ramp_u | change limit in hourly throughput | t/h² or MW/h | selected units | both | constraint/assumption | S2+ | important | 2/3/5 | mixed | especially for EAF, boilers, gas users |
| material conversion | BF recipe | alpha_bf_ore, alpha_bf_coke, alpha_bf_pci | feed coefficients for BF | t/t HM | BF | current/both | input/constraint | S2+ | critical | 2/4 | mixed | may aggregate sinter/pellet/coke upstream initially |
| material conversion | BOF recipe | alpha_bof_hm, alpha_bof_scrap, alpha_bof_flux, alpha_bof_o2 | BOF input recipe | t/t LS, Nm3/t | BOF | current/both | input/constraint | S2+ | critical | 2/4 | mixed | scrap share is quality-sensitive |
| material conversion | DRI recipe | alpha_dri_pellet, alpha_dri_ng, alpha_dri_h2 | DRI input recipe | t/t DRI, GJ/t, kg/t | DRI | Phase 1 | input/constraint | S4+ | critical | 1/4 | mixed | DR-grade pellets required |
| material conversion | EAF recipe | alpha_eaf_dri_hot, alpha_eaf_dri_cold, alpha_eaf_scrap, alpha_eaf_power | EAF input recipe | t/t LS, MWh/t | EAF | Phase 1 | input/constraint | S4+ | critical | 1/2/4 | mixed | scrap ratio depends on quality and route mode |
| yields | steel yield | yield_u | metallic yield to liquid/crude steel | % | BF/BOF/DRI/EAF/casting | both | input/validation target | S2+ | critical | 2/4 | mixed | do not hide losses in slack variables |
| yields | by-products and losses | beta_slag, beta_dust, beta_scale | slag/dust/scale generation | t/t product | multiple units | both | input/constraint | S2+ | important | 1/2/4 | mixed | necessary for mass closure |
| energy carriers | electricity intensity | e_int_u | electricity consumption/generation coefficient | MWh/t | EAF, rolling, CHP, TRT | both/later | input/objective | S3+ | important | 1/2/4 | mixed | distinction between internal generation and grid import |
| energy carriers | fuel intensity | f_int_u | gas/coal/fuel use coefficient | GJ/t or Nm3/t | BF, DRI, boilers, stoves | both | input/objective | S3+ | important | 1/2/4 | mixed | use ranges, not confidential exacts |
| WAG network | gas generation | gen_bfg_t, gen_cog_t, gen_bofg_t | by-product gas generation coefficients | Nm3/t or GJ/t | BF/COG/BOF gas | current/both | input/constraint | S3+ | critical | 2/3 | mixed | central for internal energy realism |
| WAG network | gas quality | lhv_bfg, lhv_cog, lhv_bofg, comp_g | calorific value and composition | MJ/Nm3, vol-% | gas buses | both | input/constraint | S3+ | critical | 2 | public | public generic values available |
| WAG network | gas holder bounds | lvl_min_g, lvl_max_g, lvl0_g, lvlT_g | storage limits and boundary levels | Nm3 | BFG/COG/BOF gas holders | current/both | constraint | S3+ | critical | 1/3 | mixed | anti-spill and anti-battery category |
| WAG network | gas distribution | cap_pipe_g, cap_user_g | sendout / user consumption bounds | Nm3/h | gas network | both | constraint | S3+ | important | 1/2/3 | likely confidential | often confidential by branch and consumer |
| utilities | oxygen system | cap_o2_prod, tank_o2, alpha_o2_u | O2 generation/buffer/use | Nm3/h, Nm3 | BOF/EAF/utility | both | input/constraint | S3+ | important | 1/3 | mixed | Tata publicly confirms O2 buffers |
| utilities | steam system | cap_steam_hp, cap_steam_mp, h_steam | steam levels, enthalpy, demand | t/h, GJ/t | boilers/CHP/process use | both | input/constraint | S3+ | important | 2/3 | mixed | required if internal energy layer added |
| buffers/stores | scrap storage | inv_scrap_t | scrap inventory dynamics | t | scrap yards | Phase 1/both | constraint/input | S2+ | important | 1/5 | mixed | not a free arbitrage device |
| buffers/stores | DRI storage | inv_dri_cold_t | cold DRI inventory dynamics | t | DRI silos | Phase 1 | constraint/input | S4+ | critical | 1 | public/mixed | strong anti-fake-flex requirement |
| buffers/stores | slab/WIP storage | inv_slab_t | slab or WIP inventory | t | caster/HSM/DSP interface | both | constraint/assumption | S2+ | important | 1/5 | mixed | add penalties or age/heat logic if represented |
| thermal/quality | thermal degradation | loss_thermal_slab, reheat_penalty | cooling/reheating penalties | GJ/t or €/t | slabs/hot DRI | both | input/assumption/sensitivity | S3+ | important | 2/5 | mixed | prevents “hot inventory battery” effect |
| thermal/quality | quality restrictions | qual_scrap_max, met_dri_min | feed quality windows | % impurity / % metallization | DRI/EAF/BOF | both/Phase 1 | constraint/sensitivity | S4+ | important | 2/4 | likely confidential | often decisive but poorly public |
| grid and tariffs | connection limit | cap_grid_import, cap_grid_export | site power exchange bounds | MW | grid interface | both | input/constraint | S3+ | critical | 1 | public/mixed | public connection architecture exists; contract details mixed |
| grid and tariffs | tariff terms | tariff_energy, tariff_capacity, tariff_network | delivery/network charges | €/MWh, €/MW | grid | both | objective/sensitivity | S3+ | important | 1/4 | mixed | economically dominant; strong sensitivity needed |
| emissions | direct factors | ef_dir_u | direct CO2 emissions factors | tCO2/t or tCO2/GJ | BF/BOF/DRI/boilers | both | objective/reporting | S3+ | important | 1/2/4 | mixed | distinguish process and combustion emissions |
| emissions | capture and ETS | cap_co2_capture, price_eua, free_alloc | CO2 capture/net ETS treatment | t/h, €/tCO2 | DRI/ETS layer | Phase 1/later | objective/sensitivity | S3+ | important | 1/4 | mixed | do not approve without sensitivities |
| finance | raw material prices | c_scrap, c_pellet_dr, c_coke, c_flux | commodity input prices | €/t | materials | both | objective/input | S3+ | important | 1/4 | public/mixed | route economics highly sensitive |
| finance | by-product values | rev_slag, rev_tar, cost_disposal | by-product revenue/disposal | €/t | slag/dust/tar/BTX | both | objective/sensitivity | S3+ | important | 1/4/5 | mixed | public direction, weak precise values |
| bidding and settlement | bid volume bounds | bid_da_min, bid_da_max | DA bidding limits | MW | market interface | later | input/constraint | S5+ | important | 1/5 | public | no exclusive group bids for now |
| bidding and settlement | settlement rules | imbalance_settlement, nomination_rule | realized settlement parameters | €/MWh, rule set | market interface | later | input | S5+ | important | 1 | public | only after DA-only plant logic is stable |
| stochastic/CVaR | risk parameters | alpha_cvar, lambda_cvar | CVaR confidence and weight | -, €/€ | scenario layer | later | objective/input | S6+ | later | 5 | public | methodological, not site-specific |
| mFRR later | reserve terms | cap_reserve, act_prob, act_price | reserve capacity and activation | MW, %, €/MWh | reserve interface | later | input/objective | S8 | later | 1 | public/mixed | explicitly postpone |
| validation | public anchors | val_ls_year, val_scrap_share, val_grid_cap | public validation targets | varies | whole model | both | validation target | S2+ | critical | 1 | public | must be separated from solved inputs |

**Gedetailleerd parameteruniversum per modellaag.**

**Tijd- en marktstructuur.**  
Zelfs in de eerste materiaal-LP heb je een expliciete tijdset, horizondefinitie, intervalduur, begin- en eindvoorwaarden, kalendermapping en doelhorizon nodig. Zodra DA-logica wordt toegevoegd, komen gate closure, biedperioden, settlement- en nominatieregels, prijsreeksen en scenario-indexen erbij. Voor latere uitbouw naar stochastic/CVaR en D+4 moeten scenario’s bovendien informatie-consistent blijven met wat op biedtijdstip bekend is; de IEA- en staal-DR-literatuur onderstrepen dat marktrelevante flexibiliteit vooral waardevol lijkt wanneer prijs- en load-timing apart van de fysische plantlaag wordt gehouden. citeturn24view5turn22view4turn22view3

**Site boundary en configuratie.**  
Voor baseline-current is een BF–BOF-keten met upstream voorbereidingsunits, bestaande energie-infrastructuur, casters/DSP/HSM en externe import/exportpoorten voldoende. Voor fase 1 moet je die boundary uitbreiden met DRI, EAF, nieuwe secundaire metallurgie, schrootlogistiek, DRI-silo’s, CO2-afvang en nieuwe 380/150/50 kV-infrastructuur. De MER bevestigt ook dat de EAF hoofdafnemer wordt van het nieuwe 150 kV-net en dat Tata twee transformatoren van 380 kV naar 150 kV heeft voorzien, elk geschikt voor 825 MVA, met ruimte voor verdere elektrificatie buiten Heracless. Dat maakt “site boundary” geen decoratieve keuze, maar een parametercategorie met directe invloed op latere DA- en netwerklagen. citeturn8view0turn6view2turn9view2turn30view1turn30view3

**Productiedoel en productmix.**  
De MER en het jaarverslag leveren publieke ankers voor validatie: de huidige site opereerde in FY2024/25 weer rond volle capaciteit met ongeveer 6.75 Mt liquid steel; voor het Heracless-ontwerp worden publieke routevolumes gegeven voor de overblijvende BF–BOF-route en de nieuwe DRI–EAF-route, inclusief schrootaandelen. Wat níet publiek sterk onderbouwd is, is de grade-mix die bepaalt hoeveel scrap, DRI, BOF-route en secundaire metallurgie werkelijk compatibel zijn met het productportfolio. Daarom horen productmixparameters in jouw universum thuis als **mixed/confidential** en niet als achteloos vaste input. citeturn25view0turn25view1turn35view1turn35view4turn10view0

**Procesunit-parameters.**  
Per unit heb je minstens capaciteit, availability, eventueel ramping, vaste/variabele throughputgrenzen, start/batch-approximering en gedeelde interfaces nodig. Voor BF–BOF zijn dat onder meer BF hot-metal capacity, converter capacity, ladle/secondary metallurgy en casting throughput. Voor DRI–EAF komen daar DRI shaft throughput, heater/gas treatment, hot-vs-cold DRI mode, EAF melting throughput en downstream OSF/caster toegang bij. Tata beschrijft EAF bovendien expliciet als batchgewijs proces met cyclustijd, terwijl DRI en EAF onderhouds- en stilstandspatronen hebben en tijdelijke ontkoppeling via koude DRI mogelijk is. Voor een eerste LP mag je dat middelen naar uurlijke doorzetbanden, maar niet interpreteren als onbeperkte continue flexibiliteit. citeturn6view3turn5view4turn7view1turn7view2

**Materiaalconversie en yields.**  
Voor BF–BOF moet je recepten kennen voor sinter/pellets/coke/PCI/flux naar hot metal, en vervolgens hot metal plus schroot plus O2/flux naar liquid steel. Voor DRI–EAF zijn DR-grade pellets, reductantgas, hete of koude DRI, schroot, koolstofhoudende hulpstof, fluxen, elektroden en elektriciteit essentieel. Agora benadrukt dat DRI–EAF hoge Fe-inhoud en DR-grade pellets vraagt, terwijl DRI–SMELT–BOF juist toleranter is voor lagere pelletkwaliteit; dat onderstreept dat feed-quality parameters geen optionele verfijning zijn maar een routebepalende factor. Openbare Tata-cijfers voor fase 1 bevestigen bovendien dat publieke schrootfracties in DRI–EAF niet één getal zijn, maar een range, wat precies aangeeft dat scrap share modelmatig niet als gratis beslisruimte zonder kwaliteitskoppeling mag worden gezet. citeturn15view2turn23view5turn35view4

**Energiecarriers en interne energienetwerken.**  
Een geïntegreerde staalplant is een multi-carrier systeem. De reviewliteratuur noemt BFG, COG, LDG, natural gas, steam, oxygen/nitrogen, electricity en waste heat expliciet als gekoppelde energiestromen; Frontiers en MDPI-plantscheduling papers modelleren gas holders, boilers, CHP, steam levels, tie-line grenzen en mixed-gas calorific constraints als standaard. Voor jouw thesis betekent dit dat de interne energielaag later minstens moet kunnen omgaan met carrier-specifieke massabalansen, calorische waardes, route-naar-gebruiker mappings, boiler- en CHP-efficiënties, steam-pressure levels, O2-buffers en grid exchange. Voor pure S2 is dit nog geen volledige energiebalanslaag, maar je moet de categorieën al wel vastleggen in de parameterkaart. citeturn31view0turn31view4turn27view0turn28view1turn28view2

**WAGs en internal gas network.**  
De literature en BREF maken dit onderdeel uitzonderlijk belangrijk. BFG, COG en BOF-gas verschillen sterk in samenstelling en lagere verbrandingswaarde; de BREF geeft voor steelworks process gases typische waarden van ongeveer 2.6–4.0 MJ/Nm³ voor BFG en 9–19 MJ/Nm³ voor COG, terwijl een aparte BOF-table een range van ongeveer 7.1–10.1 MJ/Nm³ en een zeer hoog CO-gehalte laat zien. De review van Sun et al. toont ook dat optimalisatiemodellen typisch expliciete gasholder level constraints, boiler input bounds en steam/power satisfaction opnemen. Voor Tata is dit extra relevant omdat de huidige site productiegassen intern gebruikt en deels richting Vattenfall stuurt, terwijl het publiek Heracless-ontwerp minder kooksgas/hoogovengas/oxygas beschikbaar maakt en een nieuwe oxygashouder en vervangend aardgasleidingwerk voorziet. Een model zonder WAG-parameters zal dus systematisch te optimistisch zijn over flexibiliteit, kosten en emissies. citeturn33view0turn33view1turn33view2turn31view1turn10view3turn10view4turn9view8turn5view2

**Buffers, stores en inventaris.**  
Schrootopslag, DRI-silo’s, zuurstofbuffers, gashouders en eventueel slab/WIP-voorraden moeten allemaal eigen dynamiek hebben: beginvoorraad, eindvoorraad, min/max bounds, laad-/ontlaadlimieten, verliezen en een economische of operationele waardering van eindvoorraad. Tata laat publiek zien dat SOP4/SOP5 en koude DRI-silo’s expliciet worden toegevoegd voor de EAF-route, en dat zuurstofbuffers nodig zijn om continue productie met discontinue convertervraag te verzoenen. Dat zijn precies de signalen dat deze objecten geen “slappe slack nodes” mogen zijn. Voor slab yards en WIP geldt hetzelfde: omdat HSM slabs eerst opnieuw verhit en DSP juist als continu en efficiënt proces wordt beschreven, is voorraad op dit niveau procesmatig duur en thermisch verliesgevoelig, niet gratis intertemporele opslag. citeturn7view4turn9view7turn9view0turn12view0

**Thermische en kwaliteitsdegradatie-parameters.**  
Dit is de laag die vaak te laat wordt opgemerkt. In de publieke Tata-documenten is te zien dat hete DRI op circa 600–700 °C uit de DRI-fabriek komt en onder inert transport naar de EAF kan gaan, maar ook gekoeld kan worden tot koude DRI voor opslag; bij slabs bestaan DSP en HSM als verschillende downstreamroutes, waarbij HSM een reheat furnace gebruikt. Zodra je zulke objecten als voorraad opneemt, horen daar temperatuurstatus, koeling/reheat penalty, dwell-time-grenzen of ten minste een expliciete opslagstraf bij. Anders creëert het model “hittebatterijen” die fysiek en economisch niet bestaan. citeturn35view3turn12view0

**Elektriciteitsaansluiting en netwerkkosten.**  
Voor jouw latere DA-biedlaag is de elektriciteitsinterface niet één prijsreeks maar een pakket parameters: import/export bounds, contract- of technische capaciteit, eventuele capaciteitstarieven, netwerktarieven, verliesfactoren en piekgevoelige kosten. In de Tata MER staat dat de fase-1-vraag gemiddeld circa 565 MW wordt, dat extra 380 kV-aansluiting is voorbereid en dat de EAF de voornaamste afnemer van het nieuwe 150 kV-net wordt. Dat maakt “power connection” al in de parameterkaart kritisch, ook al hoeft S2 nog geen volledige neteconomische laag te bevatten. citeturn30view1turn30view2turn30view3turn29search7

**Emissies, ETS en CBAM.**  
Minimaal heb je per route directe proces- en verbrandingsemissies nodig, plus captured CO2 waar relevant. Voor fase 1 meldt de Tata MER bijvoorbeeld expliciet CO2-afvang in de DRI-route van circa 0.8 Mt/jaar in de aardgasfase. Maar economisch is de lastigste categorie de **netto ETS-blootstelling**: vrije allocatie blijft benchmarkgedreven, CBAM gaat vanaf 2026 de definitieve fase in, en de uiteindelijke netto carbon cash cost hangt af van allocatie, benchmark, productievolume en marktprijs. Daarom moeten ETS/CBAM-parameters niet als één “CO2-prijs × emissies”-term worden goedgekeurd, maar als sensitivity block of aparte policy-layer. citeturn35view2turn29search0turn29search1turn29search13

**Financiële en commerciële parameters.**  
Raw-material prices, by-product revenues, disposal costs, contractgas, variable OPEX, electrode/refractory replacement, water/oxygen/steam costs en downstream value penalties zijn nodig voor een realistische objective. Maar precies deze parameters zijn vaak het minst openbaar en economisch het meest dominant. Agora laat bijvoorbeeld zien dat in H2-DRI-routes ijzerertsinput, low-carbon hydrogen, scrap en electricity de grootste kostendrijvers zijn; Tata’s jaarverslag onderstreept tegelijk dat energie-, CO2- en netwerkkosten cruciale competitiviteitsrisico’s zijn. In jouw parameteruniversum moeten deze categorieën daarom nadrukkelijk als **mixed/confidential/sensitivity-heavy** worden geclassificeerd. citeturn23view3turn25view6

**DA bidding, stochastic/CVaR en later mFRR.**  
Voor DA-only heb je pas na fysische stabiliteit bidding bounds, nomination timing, settlementregimes en productie-/leveringsverplichtingen nodig. Voor stochastic/CVaR komen scenario probabilities, scenario tree/index, recourse-vrijheidsgraden, non-anticipativity sets en risk aversion parameters erbij. Voor mFRR zijn bovendien reserve capacity, baseline-definition, activation uncertainty, response times, rebound, non-delivery penalties en energy accounting vereist. Niets in de publieke Tata-bronnen ondersteunt nog om dat nu al site-specifiek vast te zetten; deze categorieën horen daarom duidelijk in de “later” of “methodological” kolom. citeturn22view4turn22view1turn27view3

**Validation targets.**  
Je model heeft publieke verificatieankers nodig die níet tegelijk vrij kalibreerbare inputs mogen zijn. Bruikbare publieke targets zijn: huidige liquid/crude steel volumes en nominale sitecapaciteit uit Tata’s jaarverslag, publieke productiecapaciteiten van BOF/DSP/HSM op de Plants-pagina, publieke fase-1 routevolumes en schrootranges uit de MER, en openbare netaansluitingsarchitectuur inclusief de 380/150 kV-verbinding en gemiddelde vraag. Zulke targets zijn ideaal om plausibiliteit te toetsen zonder vertrouwelijke waarden te claimen. citeturn25view0turn25view1turn11view4turn12view0turn35view1turn30view1turn30view2

## Fasering, evidentiematrix en rode vlaggen

**Aanbevolen modelleringsbehandeling per categorie.**  
De onderstaande behandeling past het best bij jouw thesisvolgorde:

| categorie | eerste deterministische LP | energy/cost/emissions layer | later MILP / stochastic | beste status nu |
|---|---|---|---|---|
| topology en route-activatie | opnemen | behouden | behouden | direct opnemen |
| publieke throughput/capaciteiten | opnemen | behouden | behouden | direct opnemen |
| materiaalrecepten en yields | opnemen in geaggregeerde vorm | verfijnen | verder verfijnen | direct opnemen |
| buffers met bounds en boundary conditions | opnemen | behouden | behouden | direct opnemen |
| WIP/slab/DRI/scrap storage met anti-arbitrage | opnemen | behouden | behouden | direct opnemen |
| interne WAG- en steamnetwerken | nog niet volledig, maar categorie expliciet reserveren | opnemen | verfijnen | S3 |
| echte commodity-, ETS- en netwerkkosten | nog niet voor kernclaim | opnemen met sensitiviteiten | behouden | S3 |
| productmix en quality windows | als exogene of banded parameter | verfijnen | behouden | sensitivity / gedeeltelijk |
| DA bidding en settlement | uitstellen | uitstellen | opnemen | S5 |
| stochastic scenarios en CVaR | uitstellen | uitstellen | opnemen | S6 |
| quarter-hour en D+4 | uitstellen | uitstellen | opnemen | S7 |
| mFRR | uitstellen | uitstellen | opnemen | S8 |

Deze volgorde volgt zowel uit jouw thesisprioriteiten als uit de staaloptimalisatieliteratuur, waarin dynamische koppelingen tussen materiaal- en energiestromen vaak juist de grootste complexiteitsbron zijn. citeturn22view0turn31view5turn27view0

**Essentiële parameters voor de eerste deterministische uurlijke LP.**  
Voor S2 zijn onmisbaar: tijdset, site-topologie, route-enabled flags, externe feed nodes, per route uurlijke throughput bounds, materiaalrecepten per route, yield/loss parameters, downstream sink-capaciteiten, inventarisdynamiek voor alleen de meest cruciale stores, productieverplichting, en strikte begin/eind-inventory constraints. Niet nodig in S2 zijn precieze utilitykosten, publieke stroomprijzen, ETS, WAG dispatch, reserveproducten en scenario-onzekerheid. Het doel van S2 is niet economische optimaliteit maar **massabalans, routeconsistentie en haalbaarheid**. citeturn35view1turn35view3turn10view0turn22view0

**Parametertypes die je nog niet zou moeten goedkeuren.**  
Nog niet goedkeuringsrijp zijn: werkelijke Tata-grade mix; precieze route-yields per staalsoort; werkelijke BOF/EAF recipe windows; electrode/refractory costs; netaansluitingscontracten en transporttarieven; echte O2/steam marginal costs; Vattenfall/Tata gas- en stroomverrekenregels; nette ETS/net-free-allocation cost expressions; en alle mFRR-related parameters. Dit zijn precies de categorieën die óf vertrouwelijk zijn, óf economisch extreem dominant, óf beleidsmatig/marktmatig instabiel. citeturn25view6turn29search0turn29search1turn29search7

**Evidentiematrix per hoofdbron.**

| source | what it supports | parameter categories informed | what it cannot support | redactions/limitations | confidence |
|---|---|---|---|---|---|
| Tata MER Heracless technische beschrijving 2025 citeturn4view0 | current and phase-1 topology, public route volumes, public stores, utilities, grid architecture | topology, capacities, public validation targets, DRI/EAF logistics, oxygen and gas holders, public energy architecture | confidential costs, exact hourly recipes, grade-dependent operations | planning document, not an operating historian | hoog |
| Tata Plants page citeturn12view0 | current asset chain and named capacities | baseline topology, public annual capacities, downstream units | future dispatch, confidential economics | marketing/overview granularity | hoog voor topology, middel voor values |
| Tata FY2024/25 annual report citeturn25view0turn25view1 | public production volumes, nominal capacity anchor, strategic context | validation targets, baseline capacity, public transition context | operational recipes, marginal costs | corporate reporting scope | hoog voor validation anchors |
| JRC BREF Iron and Steel Production citeturn15view1turn18view0 | formal process coverage, generic gas compositions, BAT-linked process definitions | process scope, gas properties, emissions handling, generic material/utility categories | Tata-specific values, current policy economics | some data older, BAT-oriented not dispatch-oriented | hoog |
| IEA Iron and Steel Technology Roadmap citeturn24view1turn24view5 | route definitions, transition logic, material efficiency role | route families, later energy/policy sensitivity framing | plant-level operating data | sector roadmap, not site model | hoog |
| Agora low-carbon technologies 2024 citeturn15view2turn23view1turn23view3 | route comparison, pellets/scrap/H2/electricity bottlenecks, cost-driver ranking | DRI/EAF material and energy categories, sensitivity priorities | hourly operations, site-specific networks | scenario-based comparative analysis | hoog |
| Mission Possible Partnership steel strategy citeturn15view3 | hydrogen and route transition bottlenecks | later sensitivity priorities, H2 dependence, strategic structure | plant-specific operations | global strategy, not dispatch model | middel-hoog |
| Sun et al. review on material and energy flows citeturn22view0turn31view4 | literature map of material vs energy vs integrated models | parameter families, constraint families, network structure, missing categories | site-specific values | review-level synthesis | hoog |
| Steel plant gas/steam/power scheduling papers citeturn27view0turn27view2turn27view3 | concrete MILP constraint families for holders, boilers, CHP, steam and uncertainty | WAG, holders, power/steam constraints, stochastic later-stage classes | Tata site values, European market rules | often China-specific case settings | middel |

**Contradicties, ambiguïteiten en rode vlaggen.**  
De grootste ambiguïteit is niet meer “komt DRI–EAF überhaupt?”, want de publieke MER modelleert die fase expliciet; de live onzekerheid zit eerder in **hoe precies de site die route operationeel zal integreren** en welke publieke planningsaannames later nog wijzigen door vergunningen, tempo of steunafspraken. Het MER neemt HO7 en KGF2 uit bedrijf in de transitiefase, maar het jaarverslag laat ook zien dat over overheidsondersteuning, maatwerkafspraken en definitieve binding nog processen lopen. Voor jouw model betekent dat: topology mag fase-1-geïnspireerd zijn, maar investerings- en timingdetails mogen niet als harde waarheden in de parameterbasis terechtkomen. citeturn5view3turn5view2turn25view3

De tweede rode vlag is **WAG-waardering**. Zodra je BFG/COG/BOF-gas in een objective stopt, moet je kiezen of hun opportunity cost wordt bepaald door interne vervangingswaarde, Vattenfall-waarde, flaring avoidance of marginal boiler/CHP value. Die keuze is zelden publiek volledig observeerbaar. Zonder expliciete keuze krijg je schijnnauwkeurigheid in kosten én schijnflexibiliteit in dispatch. citeturn10view4turn27view2turn22view2

De derde rode vlag is **elektriciteitscapaciteit versus gemiddeld verbruik**. Publieke Tata-documenten geven je een gemiddelde fase-1-vraag en hoogspanningsconfiguratie, maar gemiddelden zijn geen piekgrenzen. Een EAF-gedreven site kan economisch en technisch door piekbelasting worden begrensd zelfs wanneer de gemiddelde MW-waarde ogenschijnlijk comfortabel lijkt. Wie alleen MWh-prijzen modelleert en MW-capaciteit uitstelt, overschat dus vrijwel zeker de later marktbare flexibiliteit. citeturn30view1turn30view2turn30view3

De vierde rode vlag is **buffers als gratis batterijen**. Dit geldt voor gashouders, koude DRI, schroot, slab yard en eindvoorraad. De literatuur over gasholders laat zien dat juist level constraints en stability penalties modeluitkomsten sterk beïnvloeden; Tata zelf motiveert sommige buffers expliciet als proceskoppeling, niet als arbitrage-instrument. Daarom moet elk inventory-object minstens een fysische functie hebben, en vaak ook een terminal condition of opportunity value. citeturn22view2turn27view3turn9view0turn9view7turn9view8

De vijfde rode vlag is **slab cooling en reheating**. Omdat Tata zowel DSP als HSM heeft, is niet iedere tonne steel identiek qua downstream-timing of thermische toestand. Een model dat slabs onbeperkt tussen uren laat zweven zonder thermische penalty of routingbeperking maakt downstream flex veel te goedkoop. Dit hoeft niet meteen een gedetailleerde thermo-MILP te worden, maar het vraagt minimaal een opslagstraf, dwell-time cap of sterk geaggregeerde routingregel. citeturn12view0turn10view0

**Open vragen en beperkingen.**  
Er blijven enkele onderwerpen open die in deze scan bewust niet met schijnzekerheid zijn ingevuld:

- de precieze grade-mixlogica en kwaliteitsvensters voor schroot/DRI/BOF/EAF;  
- exacte interne verrekening tussen Tata, Vattenfall en externe markten voor gases, steam en power;  
- echte contracted capacity, netwerkkosten en eventuele redispatch-/congestiekaders;  
- precieze routekeuzes van EAF-steel via secundaire metallurgie, casters, DSP en HSM per productfamilie;  
- exacte maintenance- en outageverdelingen op uurniveau;  
- economisch juiste netto ETS-behandeling onder veranderende free-allocation/CBAM-regels.  

Dat zijn geen gaten die je nu “even moet opvullen”, maar categorieën die ofwel later gezocht moeten worden, ofwel alleen als sensitivity mogen verschijnen. citeturn10view0turn25view6turn29search0turn29search1

## Repo-handoff en vervolgoverzicht

**Minimale S2-parameterset voor de eerste deterministische uurlijke materiaal-LP.**  
De kleinste verdedigbare S2-set bestaat uit:

- een vaste tijdset op uurbasis en één korte horizon;  
- een vaste huidige of fase-1-topologie met expliciete route- en sinknodes;  
- exogene feed-sourcenodes voor ten minste ore/pellets/sinter/coke/scrap en, in fase 1, DR-pellets, plus eventueel externe slab import als aparte source indien je publieke validatie daarop wilt toetsen;  
- per route een uurlijke throughput cap, minimum feasible throughput indien nodig, en shared downstream caps;  
- per route geaggregeerde materiaalrecepten en yields naar hot metal, DRI, liquid steel en by-products;  
- inventarisdynamiek alleen voor die stores die zonder modelinstorting niet kunnen ontbreken: schroot, koude DRI indien fase 1, en eventueel één WIP/slab-state als je caster/rolling loskoppelt;  
- begin- en eindvoorraadvoorwaarden;  
- productie- of leveringsdoel per horizon;  
- alleen zulke slackvariabelen die zwaar worden bestraft en expliciet als infeasibility diagnostics worden geïnterpreteerd, niet als verborgen bedrijfslogica.  

Wat je in S2 bewust níet nodig hebt, zijn marktprijzen, ETS, WAG-dispatch, stoomniveaus, tie-line-economie, CVaR en reserveproducten. S2 moet bewijzen dat de site-topologie en massabalans logisch zijn, niets meer en niets minder. citeturn22view0turn35view1turn35view3turn10view0

**Wat er in de repo zou moeten ontstaan.**  
De bevindingen vertalen zich het best naar een relatief strakke repository-structuur:

- **source-card categorieën**: `site_topology_public`, `site_validation_public`, `generic_bf_bof_technology`, `generic_dri_eaf_technology`, `wags_and_internal_energy`, `electricity_grid_and_tariffs`, `emissions_and_ets`, `market_rules_da`, `stochastic_risk_methods`, `assumption_only`;  
- **parameter_universe.csv kolommen**: precies de kolommen uit de tabel hierboven, aangevuld met `value_status`, `candidate_range_low`, `candidate_range_high`, `range_basis`, `citation_key`, `owner`, `last_reviewed`;  
- **schema files**: `topology_schema.yaml`, `process_params_schema.yaml`, `inventory_schema.yaml`, `carrier_schema.yaml`, `market_params_schema.yaml`, `validation_targets_schema.yaml`, `assumptions_register_schema.yaml`;  
- **validation_targets rows**: publieke liquid/crude steel volumes; publieke BOF/DSP/HSM capacities; publieke phase-1 routevolumes; publieke schrootaandelen/ranges; publieke grid architecture and average demand; openbare gas-holder or oxygen-buffer anchors waar publiek gemeld;  
- **assumptions-register entries**: aggregatie van sinter/pellet/coke naar BF-feed; aggregatie van BOF-batches naar hourly average; behandeling van slab yard; behandeling van terminal inventory; placeholder economics for tariffs and ETS; route-specific quality simplifications; exclusion of exclusive group bids; postponement of mFRR.  

Deze repo-uitvoer dwingt je om bronnen, aannames, validatiedoelen en nog-onzekere parameters van elkaar te scheiden voordat je code-implementatie te ver doorloopt. citeturn22view0turn25view0turn30view1

**Aanbevolen vervolgzoekslagen.**  
De natuurlijke vervolgzoekslagen na deze Wave A zijn:

- **Tata IJmuiden publieke topology en validation targets**: preciezere publieke ankers voor cast/rolling routing, slab import, OSF–EAF integratie, openbare output per lijn;  
- **technologieranges BF–BOF / DRI–EAF / HSM**: generieke recipe- en yieldranges, metallisatie, hot-vs-cold DRI treatment, EAF electricity ranges, refractory/electrode intensities;  
- **WAGs en interne energiewaardering**: hoe opportunity cost van BFG/COG/BOF-gas, steam en CHP het best methodologisch wordt gezet zonder vertrouwelijke interne contracting te veronderstellen;  
- **financiële en regulatoire laag**: ETS treatment, netwerktarieven, contracted capacity, capacity charges, possible congestion assumptions en later DA settlement details;  
- **later market layer**: DA bidding parameterisatie, scenario interface, risk metrics en pas daarna mFRR-capacity/activation.  

Deze volgorde is belangrijk omdat de grootste huidige missers waarschijnlijk **niet** uit avontuur in stochastic optimization komen, maar uit een te zwakke fysische parameterbasis. citeturn24view5turn27view0turn29search0turn29search7

**Handoff summary.**  
Neem dit compact mee naar je volgende gesprek:

- Bouw eerst een **gelaagd procesnetwerk**, niet meteen een full economic twin.  
- S2 moet een **deterministische uurlijke materiaal-LP** zijn met twee routes, gedeelde downstreamcaps, opslaggrenzen en strikte begin/eindvoorraadregels.  
- De **hoogste-risico categorieën** zijn: route-yields, WAG/gasholders, opslaggedrag, netcapaciteit, productmix/quality, ETS/netwerkkosten en terminal inventory valuation.  
- **Publiek goed verdedigbaar** zijn topology, publieke throughput-ankers, fase-1 architectuur, openbare netaansluiting en enkele openbare routevolumes; **waarschijnlijk vertrouwelijk of sensitivity-only** zijn echte kosten, quality windows, detailed recipes, tariff contracts en internal transfer values.  
- Classificeer elke parameter meteen naar **modelrol**: input, constraint, objective, validation target, assumption of sensitivity.  
- Keur nog **geen** dominante economische parameters goed zonder sensitiviteit.  
- Maak in de repo apart aan: **source cards**, **parameter_universe.csv**, **assumptions register**, **validation targets** en bijbehorende schema’s.  

Zo voorkom je dat de thesis te vroeg verschuift naar markt- en risicostudies terwijl de onderliggende staalplant nog niet fysisch geloofwaardig genoeg is. citeturn4view0turn22view0turn30view1turn25view6