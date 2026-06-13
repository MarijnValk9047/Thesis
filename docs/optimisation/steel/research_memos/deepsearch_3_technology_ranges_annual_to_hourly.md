# Wave C memo voor technologiebandbreedtes en jaar-naar-uur vertaling in een eerste staal-materiaalstroom-LP

## Kernbevindingen

De belangrijkste methodologische conclusie is dat de eerste S2-implementatie **geen “exacte Tata-uurwaarheid” uit jaarcijfers mag afleiden**. Publieke jaarvolumes en MER-scenario’s zijn bruikbaar als **topologie- en validatie-ankers**, maar niet als directe uur-capaciteiten. Daarvoor zijn aparte aannames nodig over beschikbaarheid, benutting, procescontinuïteit, batchgedrag en buffergebruik. Juist in staal is dat essentieel, omdat BF’s en DRI-schachten typisch continuïteitsgedreven assets zijn, BOF en EAF warmte-/batchgedrag hebben, en casting/rolling thermisch en logistiek gekoppeld zijn aan voorraden en herverhitting. citeturn34view0turn32view0turn42view0turn44view0turn54view0turn58view0

Voor de eerste deterministische uur-LP is daarom een **smalle, fysisch verdedigbare materiaalstroomkern** beter dan een grote “alles-in-één” MILP. De kern moet vooral de metalen route modelleren: BF→HM→BOF, DRP→DRI→EAF, vervolgens casting→slab/DSP→HSM/flat output, met expliciete en begrensde DRI- en slab/WIP-buffers. Elektriciteit, gas, stoom, ETS, marktsturing, reserveproducten en batch-binaries horen nog niet in S2 thuis; ze maken de eerste feasibility-laag sneller ondoorzichtig zonder dat de fysieke materiaalhaalbaarheid al is bewezen. citeturn7search0turn11search4turn34view0turn32view0

De publieke technische evidentie ondersteunt ook drie concrete modelkeuzes. Ten eerste: **BF–BOF moet in S2 als weinig-flexibele continuïteitsroute worden behandeld**, met nauwe uurbanden en zonder “vrij schakelen”. Ten tweede: **DRI en EAF moeten expliciet ontkoppeld kunnen worden via begrensde buffers**, omdat het DRI-pad publiekelijk juist als decoupling-route wordt gezien, maar hot DRI logistiek zeer kort-cyclisch is en cold DRI/HBI fysiek andere opslagregels kent. Ten derde: **slabs en WIP mogen niet als gratis flexibiliteitsbatterij fungeren**, omdat afkoelen de hot-charging-waarde vernietigt, herverhitting extra tijd/energie vraagt en bovendien materiaalverlies en kwaliteits-/planningskosten meebrengt. citeturn7search0turn39view0turn38view2turn54view0turn58view0

Numeriek gezien is de publieke basis sterk genoeg voor **generieke kandidaatbanden** voor BF-burden, BOF HM/scrap, DRI-metallisatie en koolstof, EAF-elektriciteitsverbruik, hulpreagentia en downstream hot-charging-/reheating-effecten. Maar voor **proces-turndown, exacte Tata-specifieke mengverhoudingen, slab-yard-dynamiek en uur-tot-uur onderhoudslogica** blijft de publieke basis beperkt. Die parameters moeten dus als aannames, sensitiviteiten of latere MILP-verfijningen worden behandeld, niet als “approved public inputs”. citeturn35view0turn36view0turn34view0turn39view0turn44view0turn32view0turn54view0turn58view0

## Bronnenoverzicht

| source_id | titel | organisatie / auteurs | jaar | stabiele locator | type | kwaliteit | hoofdgebruik | beperkingen |
|---|---|---|---:|---|---|---|---|---|
| S1 citeturn14view0turn35view0turn36view0turn34view0turn32view0 | Best Available Techniques Reference Document for Iron and Steel Production | European Commission JRC, Remus et al. | 2013 | DOI `10.2791/97469` | BAT/BREF | zeer hoog | BF, BOF, EAF input/output-bandbreedtes; procescontinuïteit; casting/strip-casting | Veel data representeren EU-installaties rond 2004–2010; niet Tata-specifiek |
| S2 citeturn7search9turn8search15 | Iron and Steel Technology Roadmap | IEA | 2020 | `https://www.iea.org/reports/iron-and-steel-technology-roadmap` | roadmap / analyse | zeer hoog | routevergelijking, technologiepad, general steel transition context | Niet bedoeld als plant-level operating manual |
| S3 citeturn43view0turn44view0 | The Future of Hydrogen Assumptions Annex | IEA | 2019 | `https://iea.blob.core.windows.net/assets/a02a0c80-77b2-462e-a9d5-1099e0e572ce/IEA-The-Future-of-Hydrogen-Assumptions-Annex.pdf` | assumptions annex | hoog | H₂-DRI H₂-vraag; NG-DRI-EAF- en BF-BOF-energie; 95% beschikbaarheidsaanname | Techno-economische modelaannames, geen real-time plant data |
| S4 citeturn7search0turn51search20 | Low-carbon technologies for the global steel transformation | Agora Industry / Wuppertal Institute | 2024 | `https://www.agora-industry.org/fileadmin/Projekte/2021/2021-06_IND_INT_GlobalSteel/A-IND_324_Low-Carbon-Technologies_WEB.pdf` | transitierapport | hoog | DRI-route als decoupling-/transitieroute | Systeemperspectief; beperkte plantcoefficiënten |
| S5 citeturn7search1turn8search8 | Hydrogen-based ironmaking fact sheet | worldsteel | 2024/2025 | `https://worldsteel.org/wp-content/uploads/Fact-sheet-hydrogen-H2-based-ironmaking.pdf` | factsheet | hoog | H₂-DRI concept, systeemvereisten | Beperkt detailniveau voor plantmodellering |
| S6 citeturn37view0turn39view0turn50view0 | DRI Products & Applications | Midrex | 2018 | `https://www.midrex.com/wp-content/uploads/MIdrexDRI_ProductsBrochure_4-12-18-1.pdf` | technology brochure | hoog voor productdata, midden voor algemeenheden | DRI/HBI/HDRI vormen, metallisatie, C-gehalte, handling, hot charging | Vendorbron; geen volledige statistische range per fabriekstype |
| S7 citeturn40view0turn42view0 | Direct From MIDREX First Quarter 2026 | Midrex | 2026 | `https://www.midrex.com/wp-content/uploads/Midrex-DFM-1stQtr2026.pdf` | industry bulletin / case | midden | Publiek voorbeeld van 2.0 MTPY DRP, 250 t/h, 8,000 h/yr, bin-voorbeelden | Casus-specifiek; niet universeel |
| S8 citeturn45view0turn47view0turn46view1 | History, developments and processes of direct reduction of iron ores | Lüngen & Schmöle / VDEh | 2022 | `https://vdeh.de/media/luengen_dri_ecic_2022.pdf` | technisch overzicht | hoog | NG-DRI energie, metallisatie, carbon bandbreedten, procesvergelijking | Niet speciaal geschreven voor optimalisatiemodellen |
| S9 citeturn54view0 | Hot Charging | Institute for Industrial Productivity | n.d. | `https://www.iipinetwork.org/wp-content/Ietd/content/hot-charging.html` | technology database entry | midden-hoog | Hot charging energie-/productiviteitsinvloed en lay-outvoorwaarden | Samenvattingspagina; verwijst door naar onderliggende EPA/NEDO-publicaties |
| S10 citeturn55view0turn58view0 | Technology and Operation of a Hot Rolling Mill | D. Vanderschueren / Steelmasters | 2020 | `https://steelmasters.be/wp-content/uploads/2019/09/2020-Technology-and-operation-of-a-hot-rolling-mill-1-2.pdf` | technisch paper | midden | Reheat furnace, hot charging, schaalverlies, thermische inertie HSM | Niet peer-reviewed BAT/IEA-niveau |
| S11 citeturn48view0 | Reoxidation Behavior of DRI and HBI during Handling and Their Integration into EAF Steelmaking | Kieush et al. | 2024 | DOI-landing `https://www.mdpi.com/2075-4701/14/8/873` | peer-reviewed review | hoog | DRI-opslagveiligheid, reoxidatie, DRI/HBI in EAF | Review; veel subclaims steunen op onderliggende studies |
| S12 citeturn10search3 | EAF Efficiency | AIST / I. J. Cappel | 2021 | `https://www.aist.org/AIST/aist/AIST/Conferences_Exhibitions/MENA/Presentations/AIST_MENA_EAF-Efficiency_Cappel.pdf` | industry presentation | midden | Typische EAF-productiviteit in t/h | Presentatie, geen formeel reviewartikel |
| S13 citeturn10search8 | Electric Arc Furnace Process Modelling and Simulation | H. Völkl / TU Wien | 2023 | `https://repositum.tuwien.at/bitstream/20.500.12708/158341/1/Voelkl%20Hermann%20-%202023%20-%20Electric%20Arc%20Furnace%20Process%20Modelling%20and%20Simulation.pdf` | academische thesis | midden | batchkarakter, historische/typische tap-to-tap en SEC | Thesis, geen brede industriële survey |
| S14 citeturn20search2 | MAN0103300 Blast Furnace | steeluniversity | 2019 | `https://steeluniversity.org/courses/man0103300-blast-furnace/` | opleidingsmodule | midden | moderne grote BF-schaal / daily intensity | educatieve bron, beperkt detail |
| S15 citeturn53view0 | Prospective Scenarios on Energy Efficiency and CO₂ Emissions in the EU Iron & Steel Industry | Pardo et al. / JRC | 2012 | mirror used: `https://burgerplatform.net/doc/Tata/Emissies/Prospective-Scenarios-on-Energy-Efficiency-and-CO2-Emissions-EU-Iron-Steel-Industry.pdf` | JRC technical report | midden-hoog | DSP-definitie en vergelijking met conventionele slab+reheat route | In deze wave is een mirror gebruikt; officiële JRC-landing is niet opnieuw gevalideerd |

## Technologiebandbreedtes per proces

De tabellen hieronder scheiden **publieke evidentie** van **modelinterpretatie**. Waar een waarde direct in een bron stond, is dat als range of observatie opgenomen. Waar de publieke basis zwakker is, is de parameter bewust gelabeld als **assumption/sensitivity** of **later only**. Dat onderscheid is belangrijker dan het forceren van schijnprecisie. citeturn35view0turn36view0turn34view0turn39view0turn32view0turn54view0turn58view0

### BF–BOF route

| parameter_id | beschrijving | value_or_range | unit | proces / carrier | source_id | source quality | confidence | suitable use | caveat |
|---|---|---:|---|---|---|---|---|---|---|
| bf_hot_metal_intensity_large | generieke schaal moderne grote BF | ca. 10,000 | tHM/day | BF | S14 | midden | midden | validation target only | generieke grote BF; niet Tata-specifiek |
| bf_productivity_index | benchmarkproductiviteit moderne BF | rond 3.5 | tHM/m³/day | BF | S14 | midden | laag-midden | validation target only | educatieve benchmark, geen plantsurvey |
| bf_sinter_input | BF-sinterinput in EU-dataset | 116–1621; gewogen gem. 1088 | kg/tHM | BF burden | S1 | zeer hoog | hoog | candidate input / sensitivity | brede siteverschillen; niet als strak uurcoëfficiënt gebruiken |
| bf_pellet_input | BF-pelletinput in EU-dataset | 0–972; gewogen gem. 358 | kg/tHM | BF burden | S1 | zeer hoog | hoog | candidate input / sensitivity | burden-mix sterk siteafhankelijk |
| bf_coke_input | BF-coke-input | 282–515; gewogen gem. 359 | kg/tHM | BF reductant | S1 | zeer hoog | hoog | candidate input / sensitivity | afhankelijk van burden, PCI, ore-kwaliteit |
| bf_coal_pci_input | BF-coal/PCI | 0–232; gewogen gem. 162 | kg/tHM | BF injectant | S1 | zeer hoog | hoog | candidate input / sensitivity | publieke EU-range, geen Tata-waarheid |
| bf_slag_output | BF-slagoutput | 150.0–346.6 | kg/tHM | BF by-product | S1 | zeer hoog | hoog | candidate input / validation target | nuttig als sinkcoëfficiënt in LP |
| bof_hot_metal_input | BOF hot-metal-input | 788–931 | kg/tLS | BOF metallic charge | S1 | zeer hoog | hoog | candidate input | output-genormaliseerde EU-range |
| bof_scrap_input | BOF scrap-input | 101–340 | kg/tLS | BOF metallic charge | S1 | zeer hoog | hoog | candidate input / sensitivity | impliceert grofweg ~10–30% scrap in charge op basis van HM+scrap; interpretatie |
| bof_high_scrap_risk | boven ca. 30% scrap nemen kwaliteits- en warmtebalansproblemen toe | >30 | % metallic charge | BOF | S1 + peer-reviewed/industry literature | hoog | midden | sensitivity / later only | public evidence steunt hogere ratios, maar meestal met aanvullende maatregelen citeturn21search5turn21search14 |
| bof_oxygen_input | BOF zuurstofinput | 49.5–70 | m³/tLS | BOF | S1 | zeer hoog | hoog | later only | voor materiaal-LP niet essentieel tenzij O₂ apart wordt gevolgd |
| bof_slag_output | BOF-slag | 85–165 | kg/tLS | BOF by-product | S1 | zeer hoog | hoog | candidate input / validation target | bruikbaar als vaste sinkcoëfficiënt |
| bof_short_term_scrap_gain | lagere tapping T kan meer scrap toelaten | +8 kg/tLS scrap of ~9 kg/t crude steel minder HM | kg/t | BOF | S1 | zeer hoog | midden | sensitivity | effect is praktijk-/installatieafhankelijk |
| bof_continuity | BOF is discontinu proces; BF is continuïteitsasset | n.v.t. | qualitative | BF/BOF | S1 | zeer hoog | hoog | approved structure / later MILP refinement | in S2 via equivalente uurdoorzetting modelleren; batch-binaries later |

### DRP / DRI

| parameter_id | beschrijving | value_or_range | unit | proces / carrier | source_id | source quality | confidence | suitable use | caveat |
|---|---|---:|---|---|---|---|---|---|---|
| dri_metallization_midrex | typische metallisatie MIDREX-producten | 92–97 | % | DRI quality | S6 | hoog | hoog | candidate input | product- en siteafhankelijk |
| dri_metallization_shaft_generic | generieke shaft-furnace metallisatie | 92–95 | % | DRI quality | S8 | hoog | hoog | candidate input / validation target | bruikbaar als centrale range |
| dri_carbon_cdri_hdri | koolstofgehalte CDRI/HDRI | 1.0–4.0 | % mass | DRI quality | S6 | hoog | hoog | candidate input / sensitivity | hoog C is niet altijd beter voor EAF-cyclus |
| dri_carbon_hbi | koolstofgehalte HBI | 0.5–3.0 | % mass | DRI quality | S6 | hoog | hoog | candidate input / sensitivity | HBI-specifiek |
| dri_ng_energy_midrex | NG-gebaseerde Midrex-energiebehoefte | 9.5–10.0 | GJ/tDRI | DRP | S8 | hoog | hoog | validation target / candidate input | procestype-afhankelijk |
| dri_ng_energy_energiron | NG-gebaseerde Energiron-energiebehoefte | 9.4–10.9 | GJ/tDRI | DRP | S8 | hoog | hoog | validation target / candidate input | hangt af van C-gehalte, T, power generation |
| h2_dri_requirement | H₂-behoefte H₂-DRI | 47–68 | kg H₂/tDRI | DRP | S3 | hoog | midden-hoog | assumption / sensitivity | IEA techno-economische range, geen plant-handleiding |
| h2_dri_theoretical_benchmark | vaak geciteerde theoretische/near-theoretical benchmark | ca. 54 | kg H₂/tDRI | DRP | public review / transition literature | midden | midden | validation target only | benchmark, geen gegarandeerde operationele realisatie citeturn8search2turn8search10 |
| hdri_temperature | HDRI-transporttemperatuur | tot ca. 650 | °C | HDRI | S6 | hoog | hoog | approved structure / candidate rule | alleen voor nabijgelegen EAF; geen generieke lange opslag |
| cdri_temperature | CDRI-uitlaattemp. | ca. 50 | °C | CDRI | S6 | hoog | hoog | candidate input | handling relevant, niet doorslaggevend voor mass balance |
| drp_operation_example | publiek voorbeeld DRP-rated production | 250 | t/h | DRP | S7 | midden | midden | validation target only | Dillingen-case, niet generiek |
| drp_available_hours_example | publiek voorbeeld continue bedrijfsuren | 8,000 | h/yr | DRP | S7 | midden | midden | validation target only | voorbeeld van hoge beschikbaarheid |
| hdri_bin_example | publiek voorbeeld hot DRI bins | 2 × 400 | t | HDRI buffer | S7 | midden | midden | validation target only | casus-specifiek |
| cdri_bin_example | publiek voorbeeld cold DRI bins | 6 × 8,000 | t | CDRI buffer | S7 | midden | midden | validation target only | casus-specifiek |
| dri_safe_storage_rule | veilige DRI-opslag: vermijd >65°C; O₂ laag houden | >65°C vermijden; O₂ <3 | °C / % | DRI storage | S11 | hoog | midden-hoog | approved structure / assumption | veiligheidsregel, niet per se optimalisatiecoëfficiënt |
| dri_hot_vs_cold_buffering | publiek bewijs is sterk voor “HDRI = korte koppeling; CDRI/HBI = echte buffer” | kwalitatief | class | DRP logistics | S6 + S11 | hoog | hoog | approved structure | voor S2 belangrijker dan exacte bin-grootte |

### EAF

| parameter_id | beschrijving | value_or_range | unit | proces / carrier | source_id | source quality | confidence | suitable use | caveat |
|---|---|---:|---|---|---|---|---|---|---|
| eaf_electricity_eu_range | EAF-elektriciteitsverbruik EU-range | 404–748 | kWh/tLS | EAF | S1 | zeer hoog | hoog | candidate input / sensitivity | brede range incl. verschillende staalsoorten en ladle practices |
| eaf_electricity_best_practice | gehaald in geoptimaliseerde 100 MW DC EAF | 360 | kWh/t | EAF | S1 | zeer hoog | midden | validation target only | best-practice case, niet baseline aannemen |
| eaf_electricity_100_scrap_modern | moderne 100% scrap EAF rond | ca. 350 | kWh/t molten steel | EAF | S13 | midden | midden | validation target only | literatuur-/thesisindicatie, geen brede survey |
| eaf_scrap_input | scrap-input in Europese EAF-dataset | 1039–1232 | kg/tLS | EAF charge | S1 | zeer hoog | hoog | validation target only | oude EU-mix; niet representatief voor DRI-zware groene EAF |
| eaf_dri_input_eu_range | DRI/HBI-input in Europese EAF-dataset | 0–215 | kg/tLS | EAF charge | S1 | zeer hoog | midden | validation target only | bevestigt dat oude EU-data DRI-zware EAF niet goed dekken |
| eaf_batch_dri_hbi | CDRI/HBI als batch charge | tot ca. 30 | % totale charge | EAF | S6 | hoog | hoog | candidate input / sensitivity | hogere aandelen vragen continue feed |
| eaf_high_dri_continuous | hogere DRI/HBI/HDRI-aandelen vergen continue toevoer | kwalitatief; IEA cost case gebruikt 95% DRI-charge | class / % | EAF | S6 + S3 | hoog | midden | assumption / sensitivity | voor Tata Phase 1 alleen als scenario, niet als approved public truth |
| eaf_productivity_single | typische productiviteit per enkele EAF | 130–180 | t/h | EAF | S12 | midden | midden | validation target / candidate envelope | presentatiebron |
| eaf_tap_to_tap | moderne EAF’s mikken op | <60 | min/heat | EAF | S13 + literature review | midden | midden | validation target / later MILP refinement | batchkarakter verdwijnt in uur-LP |
| eaf_oxygen | zuurstofverbruik | 5–65 | m³/tLS | EAF | S1 | zeer hoog | hoog | later only | voor S2 materieel niet noodzakelijk |
| eaf_lime_dolomite | lime/dolomiet | 25–140 | kg/tLS | EAF auxiliary | S1 | zeer hoog | hoog | later only / validation | niet nodig voor minimale metalenbalans |
| eaf_carbonaceous | coal/anthracite/coke | 3–28 | kg/tLS | EAF auxiliary | S1 | zeer hoog | hoog | later only | idem |
| eaf_electrodes | grafietelektroden | 2–6 | kg/tLS | EAF auxiliary | S1 | zeer hoog | hoog | later only / validation | interessant voor latere OPEX |
| hdri_eaf_benefit_power | hot DRI verlaagt EAF-elektriciteit | 120–140 | kWh/tLS | EAF-HDRI route | S6 | hoog | midden | sensitivity | alleen bij echte hot link |
| hdri_eaf_benefit_prod | hot DRI verhoogt productiviteit | 15–20 of hoger | % | EAF-HDRI route | S6 | hoog | midden | sensitivity | niet toepassen zonder logistieke koppeling |
| eaf_interruptibility_structure | EAF is batchmatig en dus uur-equivalent, niet glad 0–100% continu | kwalitatief | class | EAF | S13 + S12 | midden | hoog | approved structure / later MILP refinement | binaire heat-logica later toevoegen |

### Casting / DSP / HSM / slab / WIP

| parameter_id | beschrijving | value_or_range | unit | proces / carrier | source_id | source quality | confidence | suitable use | caveat |
|---|---|---:|---|---|---|---|---|---|---|
| strip_casting_definition | near-net-shape strip casting | <15 | mm strip thickness | casting | S1 | zeer hoog | hoog | validation background only | vooral technologiereferentie |
| strip_casting_energy_order | dikke plaatgieter > dunne slab > twin-roll qua energie/emissies | kwalitatieve rangorde | class | casting | S1 | zeer hoog | midden | validation background only | geen directe Tata-route-input |
| dsp_definition | DSP integreert casting en rolling, vermijdt slab cooling voor transport en conventionele reheat furnace | kwalitatief | class | DSP/HSM | S15 | midden-hoog | midden | approved structure / candidate route logic | JRC-report via mirror gebruikt |
| hot_charging_energy_saving | hot charging energiebesparing | 0.06–0.21 | GJ/t rolled steel | slab→HSM | S9 | midden-hoog | midden | sensitivity / validation target | bron bundelt meerdere publicaties |
| hot_charging_productivity | hot charging productiviteitswinst | tot 6 | % | slab→HSM | S9 | midden-hoog | midden | sensitivity | lay-out- en schedule-afhankelijk |
| hot_charging_layout_condition | caster en reheating furnace moeten dicht bij elkaar liggen | kwalitatief | class | slab→HSM | S9 | midden-hoog | hoog | approved structure | cruciaal voor bufferlogica |
| reheating_variable_cost_share | aandeel aardgasreheating in variabele slab→coil-kosten | ca. 30 | % | HSM | S10 | midden | midden | validation target only | paperbron, niet sectorwijde survey |
| reheating_scale_loss | oxidatie-/scale-verlies in reheating furnace | typisch ca. 1 | % slab mass | HSM | S10 | midden | midden | assumption / sensitivity | staalsoort en furnace practice bepalen echte waarde |
| reheating_inertia | reheating furnace is hoog-inert en niet goed voor slab-to-slab temperatuurwissels | kwalitatief | class | HSM | S10 | midden | hoog | approved structure | sterke reden om slab stock niet als gratis flexibiliteit te modelleren |
| runout_table_cooling | na finish mill typisch snelle eerste koeling en vervolgens langzame coil cooling | ~250°C in ~10 s; resterende ~500°C in >24 h | thermal history | HSM/WIP | S10 | midden | midden | later only / structural warning | metallurgisch relevant, niet per se S2-mass balance |

### Buffers / stores

| parameter_id | beschrijving | value_or_range | unit | proces / carrier | source_id | source quality | confidence | suitable use | caveat |
|---|---|---:|---|---|---|---|---|---|---|
| hot_metal_mixer_capacity | moderne hot metal mixers | tot 2,000 | t | BF–BOF interface | S1 | zeer hoog | hoog | validation target / structural logic | equalisatiebuffer, geen grote arbitragevoorraad |
| cdri_storage_requirement | CDRI-opslag | koel en droog houden | qualitative | DRI store | S6 | hoog | hoog | approved structure | reoxidatierisico |
| hdri_storage_limit | HDRI-opslag | in praktijk geen echte opslag; direct lokaal gebruik | qualitative | HDRI | S6 | hoog | hoog | approved structure | alleen korte transfer, geen vrij bufferen |
| hbi_storage_behavior | HBI-opslag/transport | geen speciale voorzorg nodig; ook piles uncovered met drainage | qualitative | HBI store | S6 | hoog | hoog | approved structure | maakt HBI de meest robuuste externe DRI-buffer |
| dri_storage_safety | DRI >65°C vermijden in bins/silo’s; O₂ <3% | threshold | °C / % | DRI store | S11 | hoog | midden-hoog | approved structure / safety assumption | vooral veiligheids-/handlingregel |
| slab_stocking_effect | hot charging kan slab stocking verlagen | kwalitatief | class | slab yard | S9 | midden-hoog | midden | approved structure | ondersteunt expliciete, maar begrensde slab yard |
| slab_buffer_not_battery | koude of afgekoelde slab vergt later reheat + materiaalverlies + planningseffecten | kwalitatieve structurele regel | class | slab/WIP | S9 + S10 + S15 | midden-hoog | hoog | approved structure | dit is modelinterpretatie op basis van publieke techniekbeschrijvingen |
| scrap_store_logic | scrap is wel echte voorraad, maar met kwaliteits-/tramp-elementlimieten | kwalitatief | class | scrap | S1 + BOF/DRI literature | midden-hoog | midden | approved structure / sensitivity | geen thermische beperking, wel kwaliteitseffecten citeturn21search0turn50view0 |

De sterkste publieke tabeldata zitten dus in **BREF voor BF/BOF/EAF** en in **Midrex/IEA voor DRI**. Voor **downstream doorzettingssnelheden en turndown** is de publieke basis veel diffuser. Daarom is het voor S2 verstandiger om de downstream-route vooral met **jaar-naar-uur vertaalde uurcapaciteiten**, beperkte opslaglogica en eenvoudige yield-/reheat-aannames te modelleren, in plaats van pseudo-precieze lijnsnelheden te forceren. citeturn35view0turn34view0turn32view0turn54view0turn58view0

## Jaar-naar-uur vertaalmethode

De aanbevolen vertaalmethode is een **transparante vierstap**: scheid eerst jaarvolume, beschikbaarheid en benutting; vertaal daarna naar kalendergemiddelde en online-gemiddelde uurdoorzetting; construeer vervolgens een **uur-envelope** met aparte minima en maxima; en gebruik die envelope pas daarna in het LP. Het voordeel is dat dezelfde publieke jaarbron meerdere verdedigbare uur-profielen kan ondersteunen zonder te doen alsof een jaargetal een fysische uurgrens is. citeturn44view0turn42view0turn54view0turn58view0

Gebruik in S2 idealiter de volgende definities:

```text
H_cal = 8760  # kalenderuren per jaar
A_p   = beschikbaarheidsfactor van asset p
H_avail_p = A_p * H_cal

V_ann,p = publiek jaarvolume of jaarcapaciteit [t/yr]

q_avg_calendar,p = V_ann,p / H_cal
q_avg_online,p   = V_ann,p / H_avail_p
```

Als zowel een **publieke jaarcapaciteit** `C_ann,p` als een **publiek jaarvolume** `V_ann,p` beschikbaar zijn, voeg dan expliciet toe:

```text
U_calendar,p = V_ann,p / C_ann,p
q_nameplate_online,p = C_ann,p / H_avail_p
```

Daarmee worden meteen vier grootheden onderscheiden die in veel projecten door elkaar lopen:

| term | definitie | gebruik in S2 |
|---|---|---|
| nameplate annual capacity | publieke jaarcapaciteit van een asset of route | validatie-anker |
| average calendar throughput | `V_ann / 8760` | sanity check |
| average online throughput | `V_ann / H_avail` | centrale uurreferentie |
| operational hourly maximum | afgeleid uit jaarcapaciteit en beschikbaarheid, niet uit jaarvolume | uur-`max` in LP |

De kern van de methodiek is vervolgens dat het LP **niet** direct `q_t ≤ V_ann/8760` gebruikt. Dat zou een jaargemiddelde verwarren met een uurmaximum. Voor een BF, DRP of caster is dat vrijwel zeker te krap; voor een batchgedreven EAF of BOF kan het zelfs precies de verkeerde kant op vertekenen, omdat die assets juist in équivalente uren “aan/uit” clusters hebben. citeturn44view0turn42view0turn10search3turn10search8

Een praktische S2-vertaling is om drie envelope-varianten naast elkaar te definiëren:

| variant | beschikbaarheid | uur-`max` | uur-`min` | buffers | gebruik |
|---|---|---|---|---|---|
| conservatief | lagere `A_p` | gebaseerd op jaarcapaciteit bij lage `A_p` | relatief hoog voor continu-assets; nul of laag voor batch-equivalenten | klein / strak | robuuste feasibility check |
| centraal | midden `A_p` | centrale naamplaat-conversie | BF/DRP smalle band; BOF/EAF/downstream bredere equivalent-hour band | begrensd | standaard S2-run |
| flexibel | hogere `A_p` | iets ruimer | alleen als publiek-technisch verdedigbaar | begrensd maar actiever | sensitiviteit, geen baseline |

Voor **continuïteitsassets** zoals BF en DRP is een extra minimum nodig: niet omdat de literatuur één universeel publiek turndown-getal geeft, maar omdat publieke bronnen wel duidelijk maken dat dit soort installaties op **langdurige, stabiele operatie** is ontworpen en dat techno-economische studies typisch met hoge beschikbaarheid rekenen. De precieze turndown kan in S2 dus beter als **assumption/sensitivity** worden vastgelegd dan als “approved public parameter”. citeturn44view0turn42view0turn47view0

Voor **batch-equivalente assets** zoals BOF en EAF is het in S2 verdedigbaar om de uurdoorzetting als **uur-equivalent** te modelleren zonder binaries, mits twee regels worden gehanteerd. De eerste regel is dat de uur-`max` wordt afgeleid uit jaarcapaciteit en beschikbaarheid, niet uit het kalendergemiddelde. De tweede regel is dat een asset die in de LP “actief” lijkt, in werkelijkheid een cluster van heats representeert; die vertaalslag moet later in de MILP-laag worden verfijnd met batch- of semi-continu-logica. citeturn34view0turn32view0turn10search3turn10search8

Voor **downstream casting/rolling** moet de vertaling bovenop de jaar-naar-uurconversie nog één expliciete keuze krijgen: wordt warmtebehoud via **hot/direct charging** gemodelleerd als beschikbaar routevoordeel, of wordt alles via een koude slab-route met herverhitting gemodelleerd? Publieke bronnen laten zien dat hot charging juist alleen werkt wanneer caster en reheating furnace dicht bij elkaar liggen en wanneer de logistiek strak is. Daarom moet de LP de routekeuze onderscheiden tussen bijvoorbeeld `liquid steel → direct strip / hot slab route` en `liquid steel → slab yard → reheating → HSM`, met verschillende verliezen of penalties. citeturn54view0turn58view0turn53view0

De reden dat jaarwaarden **geen exacte uurlimieten** mogen worden, is dus vijfledig: jaarlijkse cijfers middelen over onderhoud en outages heen; ze maskeren productmix en grade scheduling; ze verbergen batchkarakter; ze zeggen niets over warm/koud routegebruik; en ze abstractiseren weg of er buffers aanwezig zijn. In een staalmodel zijn dat precies de factoren die bepalen of een uurprofiel fysiek plausibel is. citeturn44view0turn42view0turn34view0turn32view0turn54view0turn58view0

## Aanbevolen S2 materiaalstroom-LP

De kleinste verdedigbare S2-versie is een **deterministische uur-LP voor ijzer- en staalstromen**, niet voor energie-economie. Zij moet Wave B-topologie gebruiken, maar Wave C-coëfficiënten alleen in de vorm van **generieke kandidaatbanden**. De bedoeling is dus: eerst aantonen dat de publieke Tata-geïnspireerde netwerkstructuur op uurniveau massabalans-technisch haalbaar is; pas daarna financiële, energetische en marktlagen toevoegen. citeturn35view0turn34view0turn39view0turn32view0

Een compacte, verdedigbare S2-parameterkern ziet er als volgt uit:

| blok | minimuminhoud voor S2 | status |
|---|---|---|
| topology assets | BF6, resterende BOF-route, DRP, EAF, caster/DSP, HSM of geaggregeerde flat-output stap, DRI buffer, slab/WIP buffer | approved modelling structure |
| carriers | BF burden agglomerates, coke/reductant, hot metal, BOF scrap, DRI pellets, DRI, EAF scrap, liquid steel BOF, liquid steel EAF, slabs/hot band, finished flat steel, slag/loss sinks | approved modelling structure |
| BF parameters | uur `min/max`, sinter/pellet/coke/PCI-coëfficiënten, slag-coëfficiënt | candidate range |
| BOF parameters | uur-equivalent `max`, hot metal/scrap envelope, BOF slag sink | candidate range |
| DRP parameters | uur `min/max`, metallisatieband, carbon band, pellet→DRI omzetting als ore-quality-sensitive assumption | candidate range + assumption |
| EAF parameters | uur-equivalent `max`, DRI/scrap share envelope, eventueel hot-vs-cold DRI routeflag, slag sink | candidate range + sensitivity |
| casting/downstream | `max` per uur, routekeuze direct/hot versus slab-yard/reheat, eenvoudige massaloss/reheat-penalty indien koude route | candidate range + assumption |
| stores | `cap_DRI_cold`, `cap_HDRI~0 of klein`, `cap_slab_hot` klein, `cap_slab_cold` eindig | approved structure |
| inventory conditions | expliciete initial inventory en eindvoorraadeis per horizon | approved structure |
| production target | totaal ton finished flat steel of slabs over horizon | approved structure |
| validation checks | annualised HM, DRI, LS, slab, flat output; route shares; loss ratios; store cycling | approved structure |
| infeasibility diagnostics | tekort aan iron units, BOF/EAF mix-infeasibility, downstream bottleneck, endpoint-dumping, buffer-capaciteitstekort | approved structure |

Voor de **numerieke status** van parameters is de volgende indeling bruikbaar:

| parameterfamilie | approved structure | candidate numerical range | validation target only | assumption / sensitivity only | later binary / MILP refinement |
|---|---|---|---|---|---|
| BF uurcapaciteit | ja | ja | ja | beperkt | ja, voor outages/ramp |
| BF burdenmix | ja | ja | ja | ja | nee |
| BOF HM/scrap mix | ja | ja | ja | ja | ja, per-heat/logica |
| DRP metallisatie/C | ja | ja | ja | beperkt | nee |
| DRP turndown | ja | nee | nee | ja | ja |
| EAF SEC | nee voor S2-objective | nee | ja | ja | ja |
| EAF DRI/scrap shares | ja | beperkt | ja | ja | ja |
| hot-vs-cold DRI-route | ja | ja | beperkt | ja | later detail |
| slab reheat penalty | ja | beperkt | nee | ja | later detail |
| exact Tata operating coefficients | nee | nee | ja | nee | later only if publicly verified |
| market/energy/emissions layers | nee | nee | nee | nee | ja |

Als zo’n S2-LP goed staat, horen de **eerste validatiechecks** niet primair in de objective maar in de reconciliatie achteraf. Minimaal zouden moeten worden gecontroleerd: geannualiseerde BF hot metal, BOF liquid steel, DRP DRI, EAF liquid steel, downstream output, aandeel BOF versus EAF in de totale output, en gedragingen van DRI- en slabvoorraden tussen begin en eind van de horizon. Een model dat een mooi optimum vindt maar alleen haalbaar is door eind-horizon stores leeg te trekken of gratis op te bouwen, is nog niet gevalideerd. citeturn36view0turn34view0turn42view0turn54view0turn58view0

De **infeasibility-diagnostiek** moet ook fysiek leesbaar zijn. Als het model faalt, moet direct zichtbaar worden of dat komt door te weinig iron units, te krappe BOF scrap/HM-mix, te weinig EAF metallic feed, een downstream bottleneck, te strenge eindvoorraadregels of te agressieve vertaling van jaarwaarden naar uur-`max`. Dat is veel belangrijker in S2 dan een economische optimaliteitsscore. citeturn34view0turn32view0turn54view0

## Wat niet in S2 hoort en welke risico’s het grootst zijn

Wat nu **niet** in S2 hoort, volgt niet alleen uit projectscope maar ook uit de publieke techniek: de eerste laag moet fysieke materiaalhaalbaarheid aantonen voordat marktbiedingen, flexibiliteitsproducten of gedetailleerde energie-emissielagen worden toegevoegd. Batchgedrag van EAF/BOF en warmteafhankelijk downstream gedrag zijn op zichzelf al genoeg om een eerste LP te compliceren; daarbovenop DA-bieding, stochasticiteit of reserveproducten leggen zou de foutdiagnose vertroebelen. citeturn11search4turn10search8turn54view0turn58view0

| niet in S2 | waarom uitstellen |
|---|---|
| detailed WAG dispatch | eerst materiaalnetwerk valideren; energie-integratie hoort in Wave D |
| ETS / free allocation | vereist emissieboekhouding en allocatieregels buiten S2-scope |
| interne transferprijzen | fysiek model moet eerst zonder prijsfeedback werken |
| exact product-grade mix | veroorzaakt extra route-, yield- en kwaliteitsdimensies |
| exact uur-onderhoudslogica | publieke jaarinformatie is daarvoor te grof |
| EAF batch-binaries / BOF heat-logic | pas toevoegen nadat uur-equivalent LP stabiel is |
| mFRR / reserve-logica | pas logisch na gevalideerde fysieke flexibiliteit |
| DA stochastic bidding / CVaR / quarter-hour / D+4 | expliciet buiten deze wave-scope |

De grootste risico’s voor modelvervorming zijn inhoudelijk vrij duidelijk. Het eerste risico is **jaarwaarden als harde uurlimiet** gebruiken. Daarmee wordt een kalendergemiddelde verward met operationele deurzetting en verdwijnen outages, batching en scheduling uit beeld. Het tweede risico is **EAF als perfect continue “dimmer switch”** modelleren. Publieke bronnen laten juist zien dat de EAF batchgedreven is, met heat cycles, tap-to-tap-tijden en processtappen die niet netjes lineair over elk uur uitsmeren. citeturn44view0turn10search8turn10search3

Het derde risico is **inventories als gratis arbitrage** behandelen. Dat is vooral gevaarlijk voor cold DRI, HBI, slabs en WIP. DRI kent handling- en reoxidatiebeperkingen; hot DRI is juist alleen waardevol in korte, lokale transfer. Slabs verliezen warmte, hot charging vereist nabijheid en strakke synchronisatie, en herverhitting kost niet alleen energie maar ook tijd en meestal materiaalverlies door schaalvorming. Daarom moet elk buffertype een fysische interpretatie krijgen: `HDRI = bijna geen opslag`, `CDRI = beperkte operationele buffer`, `HBI = robuuste langere opslag`, `hot slab = korte synchronisatiebuffer`, `cold slab = echte voorraad maar met reheat-penalty`. citeturn39view0turn42view0turn48view0turn54view0turn58view0

Het vierde risico is **downstream onderschatten**. Zelfs wanneer upstream ijzer- en staalstromen massabalans-technisch kloppen, kan de combinatie van caster, slab route, reheating en HSM het echte knelpunt zijn. Juist omdat publieke DSP/hot-charging-bronnen laten zien dat warmtekoppeling waardevol maar logistiek fragiel is, moet downstream al in S2 aanwezig zijn, al is het geaggregeerd. Het vijfde risico is het gebruiken van **vertrouwelijke oude thesiswaarden als pseudo-publieke waarheid**. Wave C wijst er juist op dat de publieke basis sterk genoeg is voor ranges en validatie, maar niet voor niet-herleidbare exacte Tata-coëfficiënten. citeturn53view0turn54view0turn58view0

## Repo-handoff en openstaande vragen

De bevindingen hieronder zijn zo geformuleerd dat ze direct naar repo-artefacten kunnen worden vertaald, zonder nu al definitieve approved inputtabellen te forceren.

| repo-artefact | toe te voegen / updaten inhoud |
|---|---|
| source cards | S1–S15 opnemen; expliciet taggen als `public_generic_range`, `topology_anchor`, `validation_only`, `assumption_support` |
| parameter_universe | nieuwe parameter families: `bf_hourly_envelope`, `bof_metallic_mix_envelope`, `drp_quality_band`, `eaf_charge_envelope`, `downstream_route_penalty`, `store_physical_class` |
| public_parameter_candidates | BF sinter/pellet/coke/PCI, BF slag, BOF HM/scrap/slag, DRI metallisatie/C, DRI NG/H₂ range, EAF SEC broad range, EAF auxiliaries, hot charging gains, reheating scale loss |
| assumptions register | DRI turndown, pellet→DRI mass yield, direct-vs-cold slab route penalty, annual-to-hourly availability sets, EAF DRI-rich charge ranges voor Phase 1 |
| validation checks S2 | annualised production reconciliation, route-share reconciliation, inventory endpoint neutrality, no-free-battery checks voor DRI/slabs, downstream bottleneck flags |
| future approved-input table columns | `parameter_id`, `asset_scope`, `route_scope`, `unit`, `public_evidence_range`, `central_candidate`, `status`, `source_id`, `confidence`, `wave_approved_in`, `confidentiality_note` |

Voor **Wave D** blijft vooral nodig: publieke en semi-publieke evidentie over WAG-structuren, interne gas/steam/electriciteitsnetten, BF/BOF/DRP/EAF energiekoppelingen, afvalwarmte, en een eerste coherente emissieboekhouding. De logische aansluiting is dan niet eerst marktoptimalisatie, maar een uitbreiding van dezelfde procesnetwerklaag met energiedragers en emissiecoëfficiënten. citeturn35view0turn36view0turn44view0turn53view0

Voor **Wave E** blijven daarna: ETS-regels, CO₂-kosten, transport- en netaansluitkosten, interne prijszetting, heffingen/tarieven, en later pas reserve- en DA-marktlogica. Dat is precies de volgorde die het risico minimaliseert dat een economisch “optimum” gebouwd wordt op een fysisch dubieus procesprofiel. citeturn11search4turn10search8

Er blijven ook enkele **open vragen / beperkingen** over. De publieke basis voor **exacte turndown-ranges** van BF, DRP, caster en HSM is beperkt. De publieke basis voor **ore-specific pellet→DRI mass yield** is eveneens te zwak om nu als approved input te gebruiken. En voor **Tata-specifieke bufferdimensies, call-off rules en schedulerestricties** blijft Wave B-topologie publiek bruikbaar, maar niet als exacte coefficient truth. Dat zijn geen gaten die nu met giswerk moeten worden gevuld; het zijn expliciete posten voor aannameregister, sensitiviteit en latere validatie. citeturn42view0turn44view0turn54view0turn58view0

**Compacte handoff-samenvatting.**  
S2 moet een kleine deterministische uur-LP zijn voor het metallic netwerk, met expliciete BF-, BOF-, DRP-, EAF- en downstream-nodes, plus begrensde DRI- en slab/WIP-buffers. Gebruik publieke Tata/MER-gegevens alleen als topologie- en jaar-validatie-ankers. Vertaal jaarwaarden naar uurbanden via aparte beschikbaarheids- en benuttingsaannames. Behandel BF/DRP als continuïteitsassets, BOF/EAF als batch-equivalenten, en slab/WIP niet als gratis batterij. Houd energie, emissies, ETS en marktlogica nog buiten S2. De publiek sterkste kandidaatparameters komen uit JRC BREF voor BF/BOF/EAF en uit IEA/Midrex voor DRI; downstream krijgt in S2 vooral structuur, beperkte losses en route-penalties, niet schijnpreciese lijnsnelheden. citeturn35view0turn34view0turn39view0turn32view0turn54view0turn58view0