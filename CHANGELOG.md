# Changelog

All notable changes to this project will be documented in this file.

Format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.0] — 2026-07-17

**První běžný release — konec prereleasů.** HACS ho od teď nabídne normálně,
bez povolování skryté entity a hledání „Need a different version?".

Jednička neznamená „nic nechybí", ale „všechno, co slibuje, je ověřené na
reálném hardwaru" — a že se `coordinator.send_*` a entity API nebudou měnit
z rozmaru.

### Added — watchdog mrtvého linku

Wallbox drží TCP „ESTABLISHED", ale přestane posílat data. HA pak hlásí
`connected=True` a **tiše servíruje zastaralé hodnoty**. Pozorováno naživo:
link byl mrtvý **101 minut**, auto celou dobu nabíjelo a regulační automatika
řídila proud podle 100 minut starých čísel. Nic na to neupozornilo.

Watchdog to hlídá: á 60 s, a když nepřišla zpráva déle než 180 s, uvolní port
a postaví WS server znovu (samotné zavření session nestačí — wallbox si pamatuje
endpoint a vrátil by se na pořád poslouchající server). Cooldown 300 s proti
zacyklení; když si vypneš můstek, mlčí; hlásí zásah jako WARNING, takže je vidět
i na výchozí úrovni logování.

**Ověřeno v ostrém provozu, 17 zásahů za noc.** Všechny oprávněné — porovnáno
s telemetrií po 3 s: skutečné ticho 185–239 s, přesně jak watchdog tvrdil.

| | bez watchdogu | s watchdogem |
|---|---|---|
| jak často link umírá | ~1,9× za hodinu | ~1,2× za hodinu |
| jak dlouho je mrtvý | **8–19 min** (medián 15) | ~3 min detekce + ~108 s návrat ≈ **5 min** |

Wallbox se sice nakonec vzpamatuje sám — ale až po čtvrthodině. Watchdog zkrátí
výpadek zhruba na třetinu. Nezabere na druhou poruchu, kdy wallbox **odpadne ze
sítě úplně** (žádné TCP) — tam HA poctivě hlásí `unavailable` a pomůže jen
fyzický restart.

### Added — `wait` je slepá ulička, když auto proud nevezme

Wallbox `Authorize Start` **vždycky** přijme a session autorizuje → `wait`.
Když auto nenabíjí (typicky je plné), zůstane to ve `wait` viset — a odtud
odmítá **Start** (už autorizováno) i **Stop** (session neběží). Z HA není
východisko, pomůže jen přepojit kabel. Chybová hláška to teď řekne.

Tohle je i skutečné vysvětlení hlášení „Stop mi nejde", od kterého se celý
vývoj odpíchl.

### Ověřeno na reálném voze (Peugeot e-2008, FW `E3P3_H_1.1.1_R5190`)

- **Plný cyklus** `charging → Stop → finish → Start → wait → charging`, 2× po
  sobě, ACK do 0,3–0,4 s, výkon 7,6 kW → 0 → 10,7 kW.
- **PnC přepínač** za provozu (nabíjení to neshodí, jak se dalo čekat).
- **Zámek** oběma směry, včetně té zrádné inverze proti `binary_sensor`.
- **Můstek** vrátil zamrzlý link do ~40 s tam, kde dřív nepomohl ani reload.

### Známá omezení (vědomá, ne opomenutá)

- **Posunutí slideru „nabíjecí proud" spustí nabíjení.** `Authorize Start`
  zakládá session a wallbox jinou páku na proud nemá. S vypnutým PnC je to
  naopak jediná cesta, jak nabíjení z HA rozjet. V automatizaci vždy nejdřív
  ověř `power > 1 kW`.
- **Force-charge ze sítě integrace neumí.**
- `LoadBalance` zůstává statický na 14 600 W — je to jen building-level strop
  a wallbox si ho stejně resetuje zpět.
- Po zásahu watchdogu se wallbox obvykle vrátí do ~108 s, ale výjimečně to
  trvalo ~19 min. Příčina neznámá.

## [0.7.3] — 2026-07-16

Plný cyklus konečně otestován **na reálném nabíjejícím voze** (Peugeot e-2008,
9 kW, konektor 2). Výsledek vyvrátil tvrzení z v0.7.2 — opravujeme.

### ✅ Ověřený stavový automat

```
charging --Stop--> finish --Start--> wait --> charging
   ~4 s              ~4 s
```

Proběhlo **2× po sobě**, všechny čtyři příkazy `ACK result=true` do 0,3–0,4 s:

| Fáze | Výsledek |
|---|---|
| Stop při 7,59 kW / 10,81 A | `charging → finish`, výkon **0,00 kW** |
| Start | `finish → wait → charging`, **10,72 kW** |
| Stop podruhé | `charging → finish`, **0,00 kW** |
| Start (obnova) | `finish → wait → charging` |

### Fixed — v0.7.2 tvrdila nepravdu o stavu `finish`

Psali jsme: *„Ze stavu `finish` wallbox odmítá i Authorize Start — nabíjení už
z HA znovu rozjet nejde… Pomůže odpojit a znovu zapojit kabel."*

**Není to pravda.** Start z `finish` **funguje** a kabel přepojovat netřeba.
Ta věta by uživatele posílala k zásuvce úplně zbytečně.

Vzniklo to unáhleným zobecněním jediného hlášení: uživateli byl Start odmítnut,
když byl konektor ve `finish` — jenže tam session skončila proto, že **auto**
dosáhlo svého limitu SoC. Odmítal tedy vůz, ne stav. Stejný stav se dvěma
různými příčinami vypadá v `chargeStatus` identicky.

Chybová hláška u `finish` nově míří na skutečnou příčinu (limit SoC v autě)
místo doporučení přepojit kabel.

### Potvrzeno (beze změny kódu)
- **Doba hájení po Startu** (v0.6.2) je správně: `finish → wait → charging` trvá
  ~4 s, tedy hluboko pod 60s oknem. `wait` je opravdu jen přechodový.
- **Whitelist `is_on`** (v0.6.1): ve `finish` výkon 0 → switch `off`. Sedí.
- **Čtení `result` z ACK** (v0.6.0): všechny čtyři příkazy potvrzené a reálně provedené.

## [0.7.2] — 2026-07-16

Komplexní prohlídka dokumentace proti realitě — vyprovokovaná uživatelem:
*„ak dobre pozeram, tak nemate uplne aktualizovane tie premenne… nezodpovedaju
uplne tomu najnovsiemu stavu."* Měl pravdu. Plus objevený nový stav `finish`.

### 🔑 Nový stav: `finish` — a nemile překvapí

Slovník `chargeStatus` je nově **čtyřprvkový** (FW `E3P3_H_1.1.1_R5190`):

| Stav | Význam |
|---|---|
| `idle` | kabel odpojený |
| `wait` | **přechodně** po `Authorize Start`, než auto začne brát proud |
| `charging` | reálně nabíjí |
| **`finish`** | **session skončila, kabel zůstal v zásuvce** (auto na svém limitu SoC) |

**⚠️ Ze stavu `finish` wallbox odmítá i `Authorize Start`** — nabíjení už z HA
znovu rozjet nejde, ani po zvýšení limitu SoC v autě. Pomůže odpojit a znovu
zapojit kabel; spolehlivá cesta ven **není ověřená**.

> **❌ TOHLE TVRZENÍ JE NEPRAVDIVÉ — opraveno v v0.7.3.** Start z `finish`
> funguje a kabel přepojovat netřeba; ověřeno plným cyklem na reálném voze.
> Vzniklo unáhleným zobecněním jediného hlášení. Odstavec nechávám jako záznam
> toho, co jsme si tehdy mysleli.

Oprava `is_on` z v0.6.1/0.6.2 tím dostala potvrzení: `finish` je přesně ten stav,
který blacklist `!= 'idle'` hlásil jako „nabíjím" a kvůli kterému Stop selhával.
Whitelist ho správně hlásí jako `off` — ověřeno u uživatele.
(Dřívější domněnka, že tenhle stav je `wait`, byla mylná — `wait` je jen přechodový.)

### Changed
- **Chybová hláška radí podle stavu**, ne obecně. Ve `finish` vysvětlí, co se
  stalo a proč Start neprojde; v `idle` řekne, že je konektor prázdný; při
  `charging` + Start, že je příkaz zbytečný. Dřív bylo pro všechny stavy jedno
  obecné „příkaz nedává smysl", ze kterého uživatel nepoznal nic.
- **Ikony: PnC už nevypadá jako zámek.** Obě PnC tlačítka měla `mdi:lock` /
  `mdi:lock-open-variant` — tedy k nerozeznání od západky konektoru, přestože
  jde o úplně jiný pojem (autorizace). Nově `mdi:flash-auto` (open) a
  `mdi:card-account-details` (close); switch PnC sjednocen na `mdi:flash-auto`.
- Chybová hláška u tlačítek tvrdila, že „zámek nejde ovládat bez zapojeného
  kabelu" — **nepravda**, ověřeno: wallbox zámek bez auta přijme. Odstraněno.

### Fixed — dokumentace neodpovídala realitě
- **`connector_N_power` a `meter_power`: README uvádělo `W`, správně je `kW`.**
  Pozůstatek stavu před v0.5.3. (Ověřeno strojově proti živým entitám: z 15
  senzorů seděly jednotky u 14.)
- **`..._status`: README tvrdilo „idle / charging / …"** — doplněn celý slovník.
- Doplněno, že **`suggested_unit_of_measurement` platí jen při vytvoření entity**,
  takže oprava jednotky z v0.5.4 (W → kW) **zabrala jen novým instalacím**. Kdo
  integraci provozoval dřív, může mít v registry zamrzlé `W` a `states()` mu vrací
  watty. Řešení: přepnout jednotku ručně v *Nastavení → Entity*.

## [0.7.1] — 2026-07-16

### Fixed
- **Tlačítka tiše polykala odmítnutí wallboxu.** `async_press()` zahazovalo
  návratovou hodnotu — přestože `press_fn` je typovaná jako `Awaitable[bool]`.
  Od v0.6.0, kdy `send_*` vrací **skutečné potvrzení** z ACK, to znamenalo, že
  odmítnutý příkaz vypadal jako úspěšný: tlačítko zhaslo, nic se nestalo, nikde
  ani slovo. Switche přitom na totéž hlásí chybu — **stejná akce, dvě různá
  chování**. Je to tatáž třída chyby, jakou v0.6.0 opravovala u slideru proudu;
  v tlačítkách jen zůstala.
  **Fix:** tlačítko při `result: false` vyhodí `HomeAssistantError` a připojí
  aktuální stav konektorů. (Chyba se hlásí jen na **explicitní** odmítnutí —
  `None` = „nevíme" křičet nemá proč.)

Vyplynulo z diskuze nad v0.7.0 — jestli po přidání přepínačů nemají tlačítka
zmizet. **Nemají a nezmizí:** tlačítko je bezstavové a přepínač si stav nedrží
(čte ho z telemetrie), takže obojí je jen ovládací plocha nad týmž příkazem
a týmž zdrojem pravdy — rozejít se nemůžou. Ověřeno naživo: stisk *tlačítka*
Lock přepnul *switch* na `on`, Unlock zpátky na `off`.
Za tu otázku dík — bez ní bychom tuhle chybu nenašli.

### Changed
- `coordinator.status_summary()` je nově veřejná (volá ji i `button.py`).

## [0.7.0] — 2026-07-16

Na přání uživatele integrace: *„nez budem preprogramovavat cele templaty —
existuje sanca, ze tie ON/OFF buttony budu niekedy k dispozicii vo verzii
Switch? Teda ze ho bude mozne Toggle?"* Ano, existuje. Tady je.

### Added — zámek a Plug-and-Charge jako přepínače

Dosud šly ovládat jen dvojicí tlačítek (*Lock* + *Unlock*, *PnC open* +
*PnC close*), takže na kartě musely být dva prvky a stav se musel tahat zvlášť
z `binary_sensor`. Nově jedna entita, která ukazuje stav i ovládá:

| Entity (CS HA) | `on` znamená |
|---|---|
| `switch...zamek_konektor_{1,2}` | **zamčeno** |
| `switch...plug_and_charge_konektor_{1,2}` | **nabíjení začne po zapojení samo** (bez autorizace) |

(Na anglickém HA `switch...connector_{1,2}_lock` / `..._plug_and_charge` —
entity_id je lokalizované, viz README.)

**Tlačítka zůstávají.** Nejsou deprecated a nikam nemizí — kdo si na nich
postavil šablony, nemusí sahat na nic. Přepínače přibyly vedle.

Platí pro ně stejné pravidlo jako pro zbytek integrace: **nepřepínají se
optimisticky.** Stav se změní, až ho potvrdí telemetrie wallboxu; když wallbox
příkaz odmítne, přijde chyba a stav se nehne.

> **⚠️ Zámek je oproti `binary_sensor..._lock` schválně obrácený.** Ten má
> `device_class: lock`, kde HA konvence znamená `on` = **odemčeno** (device
> classy mají „problem semantic" — `on` = abnormální stav). U switche uživatel
> čeká `on` = zamčeno. Obě entity proto ukazují opačnou hodnotu a obě mají
> pravdu. Ověřeno na živém wallboxu.

> **Poznámka k PnC:** wire protokol tomu říká `open` (bez autorizace) a `close`
> (autorizace nutná), což je matoucí — switch to překládá na on/off. `off` je
> scénář „nabíjej jen na povel z HA".

## [0.6.2] — 2026-07-16

Znovu díky reportu uživatele: *„Status sa po stlaceni ukazal, pisal WAIT, potom
Charging."* Ta jedna věta doplnila slovník `chargeStatus` a odhalila, že whitelist
z v0.6.1 sice opravil starý bug, ale zavedl nový (kosmetický).

### 🔑 Slovník `chargeStatus` (FW `E3P3_H_1.1.1_R5190`)

Není nikde zdokumentovaný, tak ho zapisujeme, jak ho pozorujeme:

| Stav | Význam |
|---|---|
| `idle` | kabel odpojený, nic neběží |
| `wait` | kabel zapojený, ale **neteče proud** — **dva různé významy**, viz níže |
| `charging` | reálně nabíjí |

**`wait` je zrádný — znamená dvě věci, které od sebe podle stavu nerozeznáš:**
1. **přechodně** po `Authorize Start`, než auto začne brát proud (`idle → wait → charging`),
2. **trvale**, když session skončila a kabel zůstal v zásuvce (auto na svém limitu SoC).

Tohle je i vysvětlení původního bugu z v0.6.0: blacklist `!= 'idle'` hlásil význam (2)
jako „nabíjím", uživatel dal Stop a wallbox ho odmítl — žádná session neběžela.

### Fixed
- **Switch po stisknutí ON krátce cvakl zpět na OFF.** Regrese z v0.6.1: whitelist
  `== 'charging'` je proti významu (2) správný, ale přechodný `wait` (význam 1) tím
  spadl na `off` — uživatel stiskne zapnout, přepínač se vrátí, a než naskočí
  `charging`, vypadá to, že příkaz selhal.
  **Fix:** po **potvrzeném** Startu se `on` drží po dobu hájení (60 s) i přes `wait`.
  Rozlišit oba významy `wait` podle stavu nejde — jen podle toho, jestli jsme právě
  dali Start. Po vypršení rozhoduje zase telemetrie: když auto nabíjet nezačne,
  switch poctivě spadne na `off`. `Stop` dobu hájení okamžitě zahodí.
  Pokryto testem 14 scénářů (rozjezd, auto se nerozjelo, mrtvá session, Stop za
  chodu, konec na limitu SoC, neznámý stav, bez telemetrie).

## [0.6.1] — 2026-07-16

Vyšlo pár hodin po v0.6.0 díky uživateli, který start/stop hned vyzkoušel na
reálném voze a poslal, co se dělo. Bez toho reportu bychom o chybě nevěděli.

### ✅ Start/stop nabíjení JE OVĚŘENÝ NA REÁLNÉM VOZE

v0.6.0 to poctivě přiznávala jako neotestované. **Teď už otestované je** —
uživatel opakovaně potvrdil Start i Stop přes switch, s **vypnutým PnC**
(scénář „nabíjej jen na povel z HA"). Firmware `E3P3_H_1.1.1_R5190`.

Zároveň z toho vyplynulo něco, co jsme netušili: **`Authorize Start` zakládá
session, nejen škrtí proud.** S vypnutým PnC je to jediný způsob, jak nabíjení
rozjet z HA. ⚠️ **Důsledek: pohyb sliderem „nabíjecí proud" spustí nabíjení.**
(Automatizace typu PV modulace to nepotká, pokud má skip při `power < 1 kW`.)

### Fixed
- **Switch nabíjení hlásil „nabíjí", i když se nenabíjelo → Stop pak selhal.**
  `is_on` se odvozovalo blacklistem `chargeStatus != 'idle'`. Jenže slovník má
  i mezistavy: když auto samo ukončí session (dosáhne svého limitu SoC) a kabel
  zůstane v zásuvce, stav **není** `idle` — switch tedy svítil „nabíjím",
  uživatel dal stop a wallbox ho odmítl (`result: false`), protože žádná session
  neběžela. Přesně tenhle scénář uživatel nahlásil.
  **Fix:** whitelist — `on` výhradně pro `chargeStatus == 'charging'`. Odolné
  i proti stavům, které ještě neznáme: co není prokazatelně nabíjení, je vypnuto.
  Telemetrie má nově přednost před optimistickou hodnotou, takže switch nezůstane
  viset na `on`, když auto nabíjet nezačne nebo samo skončí.
- **Chybová hláška u odmítnutého příkazu mátla.** Tvrdila „nejčastěji proto, že
  v zásuvce není auto" — jenže u reportujícího uživatele kabel v autě byl.
  Nově vysvětluje i variantu „session sama skončila (auto dosáhlo limitu SoC)"
  a **vypisuje aktuální `chargeStatus`** konektoru.

### Changed — logování (aby příště nebylo potřeba hádat)
- **Přechody `chargeStatus` se logují na INFO:** `Konektor 2: chargeStatus idle → charging`.
  Slovník chargeStatus není zdokumentovaný a wallbox odmítá `Authorize` právě
  v neznámých mezistavech — dosud se stav nikde nezaznamenával, takže z hlášení
  „nejde to" se nedalo zjistit vůbec nic.
- **Odmítnutý příkaz je v logu konečně čitelný.** Dřív: `Wallbox odmítl Authorize
  (uid=…): result=false` — Start i Stop vypadaly stejně. Nově:
  `Wallbox ODMÍTL Authorize(purpose=Stop, connectorId=2, current=6) … Stav
  konektorů: k1=idle, k2=charging`.
- `coordinator.connector_status(id)` — jedno místo pro čtení stavu konektoru
  (switch si ho už neodvozuje sám).

## [0.6.0] — 2026-07-16

Verze vznikla z jednoho dotazu — „umí integrace vypnout a zapnout nabíjení?".
Odpověď byla ne, a při ověřování na živém wallboxu vyplavaly dvě chyby, které
tam byly od začátku.

### ⚠️ Start/stop nabíjení NENÍ FYZICKY OTESTOVÁNO

> **Poznámka dodatečně (v0.6.1):** už otestované je — viz v0.6.1 výše. Text níže
> popisuje stav v době vydání v0.6.0 a nechávám ho nedotčený jako záznam toho, co
> jsme tehdy věděli a co ne.

Bez servítek, ať je to jasné dřív, než se na to někdo spolehne:

- Nové switche `Nabíjení konektor 1/2` **nikdy neběžely proti reálně nabíjejícímu vozu.**
  V době vývoje nebylo auto v zásuvce.
- `Authorize` s `purpose="Stop"` je převzatý z reverse engineeringu
  [matemat13/ha_s-charge](https://github.com/matemat13/ha_s-charge). Tahle integrace
  dosud posílala **výhradně** `purpose="Start"` (škrcení proudu, `number.py`).
  **Stop nebyl na tenhle hardware nikdy odeslán.**
- Co je ověřené: wallbox zprávu **přijme, rozparsuje a odpoví do ~0,3 s**. Při
  odpojeném autě vrací `result: false` na Stop **i na Start** — a Start je příkaz,
  který denně prokazatelně funguje. Z toho plyne, že `result: false` znamená
  „nemám session/auto", ne „neznám ten příkaz".
- Co ověřené **není**: jestli Stop reálně přeruší probíhající nabíjení, jestli ho
  Start rozjede zpět, a jestli po Stopu nebude potřeba přepojit kabel.

**Pojistka:** switch se **nikdy nepřepne optimisticky**. Přepne se výhradně po
`result: true` od wallboxu; jinak vyhodí `HomeAssistantError` a stav nechá být.
Radši viditelná chyba než tiché tvrzení, že se něco stalo. Ověření proběhne, až
bude vůz v zásuvce.

### Added
- **`switch.wallbox_s_charge_nabijeni_konektor_{1,2}`** — start/stop nabíjení přes
  `Authorize Start` / `Authorize Stop`. Proud bere z posledního wallboxem
  potvrzeného (`coordinator.last_authorized_current`), default 16 A.
- **`coordinator.last_authorized_current`** — poslední **potvrzený** proud per konektor.

### Fixed
- **Můstek neuvolňoval port → wallbox si zamrzl na ~3 minuty.** `pause_bridge()`
  zastavil broadcast a zavřel session, ale **WS server nechal poslouchat** na 41515.
  Wallbox si ale pamatuje poslední endpoint a dobývá se tam bez ohledu na to, kdo
  broadcastuje. HA jeho spojení přijímal a neobsluhoval → **napozorováno ~95 spojení
  ve `FIN_WAIT1`** a mrtvý link, dokud nevypršely TCP timeouty. Toggle OFF→ON to
  nespravil, reload integrace taky ne — muselo se čekat.
  **Fix:** `pause_bridge()` teď WS server zastaví a port uvolní, `resume_bridge()`
  ho nastartuje zpět. Wallbox dostane na reconnecty RST, přestane hromadit a
  poslechne další broadcast. **Ověřeno: připojí se do ~20 s.**
  Týká se to i noční automatizace typu „reinit = toggle můstku" — ta až dosud mohla
  link naopak shodit.
- **`number...nabijeci_proud` ukazoval jako nejnižší hodnotu 0 místo 6.** *(díky za report —
  nahlášeno uživatelem integrace.)* Wallbox posílá `reserveCurrent = 0`, když na konektoru
  neběží session (typicky odpojené auto). Nula ale není platný proud — rozsah je 6–32 A.
  Entita ji reportovala jako svůj stav, takže hlásila hodnotu mimo vlastní `min`/`max` a UI
  slider spadl na 0.
  **Fix:** `native_value` vrací `None` (= neznámo), když hodnota není v rozsahu 6–32.
- **Integrace nečetla `result` z ACK — příkazy „procházely", i když je wallbox odmítl.**
  `_send_message()` vracel `True` ve chvíli, kdy bajty odešly do socketu; pole
  `result` se nikdy nečetlo (ACK spadl do debug logu a zahodil se). Důsledek:
  `number...nabijeci_proud` si nastavil `_optimistic_value` a **hlásil proud, který
  wallbox odmítl** — slider lhal. Totéž `send_loadbalance`.
  **Fix:** ACK se páruje přes `uniqueId` (`_send_and_wait`, timeout 5 s) a
  `send_authorize` / `send_loadbalance` / `send_electronic_lock` / `send_pnc_set`
  vracejí **skutečné potvrzení wallboxu**. Když spadne WS nebo se pauzne můstek,
  čekající příkazy selžou hned, místo čekání do timeoutu.

### Changed
- **BREAKING (interní API):** návratová hodnota `coordinator.send_*` už neznamená
  „odesláno", ale „**wallbox potvrdil**". Volající, kteří brali `True` jako jistotu
  doručení, teď dostanou `False` u odmítnutých i nezodpovězených příkazů. Je to
  záměr — právě tohle maskovalo lhoucí slider.
- `number...nabijeci_proud` nastaví `_optimistic_value` až po potvrzení. Automatika
  `wallbox_amp_feedback` se nemění a chová se stejně; jen přestane věřit odmítnutým zápisům.

### Nezměněno
`LoadBalance` zůstává statický na 14 600 W (je to jen building-level strop, ne
per-session throttle). Force-charge ze sítě integrace neumí a tahle verze na tom nic nemění.

## [0.5.4] — 2026-04-24

### Fixed
- **Výkon konektoru zobrazován ve W místo kW** — HA s `native_unit=KILO_WATT` bez explicitního `suggested_unit_of_measurement` auto-konvertuje na W pro malé hodnoty. `states()` pak vracelo W hodnotu (4010), šablona zobrazovala „4010.0 kW" a entity karta „4 010 W".
- **Fix:** Přidáno `suggested_unit_of_measurement=UnitOfPower.KILO_WATT` pro `c_{1,2}_power` a `meter_power`. HA zachová jednotku kW → `states()` vrací „4.01", entity karta zobrazí „4.01 kW" s 2 des. místy.

## [0.5.3] — 2026-04-24

### Fixed
- **Definitvní oprava jednotky výkonu konektoru** — wallbox posílá `power` v **kW** jako desetinné číslo (např. 3.94 kW při 5.96A × √3 × 400V × 0.95 PF ≈ 3.92 kW ✓). `native_unit_of_measurement=UnitOfPower.KILO_WATT` je správně. v0.5.2 omylem revertovalo zpět na `WATT`, entity karta pak zobrazovala „3.94 W" místo „3.94 kW" a Jinja2 šablona vracela špatnou hodnotu. Opraveno zpět na `KILO_WATT` pro `c_{1,2}_power` i `meter_power`.

## [0.5.2] — 2026-04-24

### Fixed
- ~~**Regrese jednotky výkonu z v0.5.1**~~ — tato verze obsahovala chybu (viz v0.5.3). `suggested_display_precision=2` pro power senzory přidáno správně.

## [0.5.1] — 2026-04-24

### Fixed
- **`number.wallbox_s_charge_konektor_{1,2}_nabijeci_proud` zaseknutý na 0** — wallbox nereportuje `reserveCurrent` ve `SynchroStatus` konzistentně (často 0), takže number.native_value byla vždy 0 → zavírací smyčka s PCC feedback automatikou nefungovala (condition `target != current` byla pořád true, nic se neměnilo).
- **Fix:** Optimistic tracking v `SchargeChargeCurrent`. Po úspěšném `Authorize Start` si entity pamatuje hodnotu lokálně (`_optimistic_value`) a vrací ji v `native_value` (fallback na `reserveCurrent` jen pokud optimistic není).
- PCC feedback automatika teď správně konverguje bez potřeby wallboxu echo-back.
- **`suggested_display_precision=2`** pro `c_{1,2}_power` a `meter_power` — zobrazení na 2 des. místa (10.75 kW).

## [0.5.0] — 2026-04-23

### Added
- **`Authorize` command** (`actions.make_authorize`, `coordinator.send_authorize`) — Start/Stop nabíjecí session s přesně zadaným proudem (A). Reverzováno z [matemat13/ha_s-charge](https://github.com/matemat13/ha_s-charge).
- **Per-connector `number.wallbox_s_charge_connector_{1,2}_charge_current`** — slider 6-32 A v HA UI. Posílá `Authorize Start` s novým proudem → wallbox mění aktuálně nabíjecí proud auta.
- Real per-session throttle, **nezávislý na `LoadBalance`** (ta je building-level ceiling).

### Why
LoadBalance (W) jsme dosud používali jako jediný throttle, ale testování ukázalo že wallbox ji často resetuje zpět na 14600 W a proto auto tahá svou OBC max (11 kW) bez ohledu na LB. Authorize příkaz s `current` parameterem reálně řídí proud na PWM signálu ke autu.

### Design
- `native_value` čte `reserveCurrent` ze `SynchroStatus` (target v A)
- `async_set_native_value(A)` pošle `Authorize(connector_id, "Start", A)` — funguje i během aktivního charging, throttluje za chodu

## [0.4.1] — 2026-04-19

### Added
- **Kompletní překlady entit** — všech 38 entit (sensors, binary_sensors, buttons, number, switch) má `translation_key` + záznamy v `cs.json`/`en.json`.
  Dříve byl přeložený jen config flow; entity názvy byly anglicky.
  Teď má HA v češtině názvy jako „Konektor 1 napětí", „Počet session", „Můstek HA", „Omezení výkonu" apod.

## [0.4.0] — 2026-04-19

### Added
- **Bridge switch** (`switch.wallbox_s_charge_bridge`) — umožňuje dočasně uvolnit wallbox pro mobilní aplikaci S-charge.
  Wallbox drží jen jednu aktivní WebSocket session — když je HA připojený, mobil se nepřipojí.
  OFF → HA zastaví UDP broadcast a zavře aktivní WS. Wallbox je uvolněn pro mobilní app. Entity se přepnou na `unavailable`.
  ON *(default)* → HA obnoví broadcast, wallbox se do ~3 s vrátí zpět k HA.
  Switch je v kategorii CONFIG (zobrazuje se u konfiguračních entit integrace).

## [0.3.1] — 2026-04-19

### Fixed
- **Connector Lock binary_sensor invertovaný** — HA konvence `BinarySensorDeviceClass.LOCK` znamená `on = odemčeno, off = zamčeno` (problem-state semantika).
  Wallbox ale reportuje `lock_status = True` když je fyzicky zamčený → po zamčení se na dashboardu zobrazovalo „Odemčeno" a naopak.
  Oprava: `value_fn` invertuje `lock_status` před předáním HA. Commandy (`ElectronicLock lock/unlock`) byly po celou dobu správné, jen zobrazení bylo obrácené.

## [0.3.0] — 2026-04-19

### ⚠️ Breaking changes
- **Konektory přejmenovány `main`/`vice` → `1`/`2`.** Všechny entity IDs změněny:
  - `sensor.scharge_main_*` → `sensor.scharge_1_*`
  - `sensor.scharge_vice_*` → `sensor.scharge_2_*`
  - Stejně pro `binary_sensor.*`, `button.*`.
- Display názvy: `Main Voltage` → `Connector 1 Voltage` atd.
- Pokud máš automation odkazující na staré entity IDs, bude je potřeba přemapovat.
- Wire protokol (`connectorMain`/`connectorVice` v JSONu wallboxu) zůstává beze změny — jen UI názvy.

### Fixed
- **Kritický bug:** `coordinator.async_stop` čekal infinite na `ws_server.wait_closed()`,
  protože wallbox nezavírá WS graceful. Teď má timeout 3 s na server close +
  2 s na active WS close. Bez fixu bylo reload/unload integrace nemožné.
- `README.md`: odstraněn inline changelog block (duplicita s CHANGELOG.md).
  README nyní odkazuje na CHANGELOG.md.

## [0.2.0] — 2026-04-19

### Changed
- `coordinator.py`: "Overwriting existing WS session" downgraded from WARNING to DEBUG log level.
  To je normální chování — wallbox občas reconnectuje před tím, než starý WS session graceful-closes.
  Zbytečný warning spam v HA logu.

### Added
- `CHANGELOG.md` — od teď budeme udržovat živý changelog.

### Notes
- Verze je stále **prerelease** (čeká na testování s reálným nabíjením Peugeot e-2008).
- Monitoring telemetrie ověřen (DeviceData, SynchroStatus, SynchroData).
- `LoadBalance` command ověřen (change 14600→12000→14600 W za ~10 s).
- Start/Stop session a `ElectronicLock`/`PnCSet` ještě nebylo testováno s reálným autem.

## [0.1.0] — 2026-04-19

### Added
- První verze HA custom integrace pro wallbox Joint Tech JNT-EVCD2 / Schlieger S-charge.
- WebSocket server + UDP broadcast discovery (`ocpp1.6` subprotocol).
- Protokol kompletně reverzovaný (BLE snoop + WiFi tcpdump).
- Config flow přes HA UI (IP + S/N, CS + EN překlady).
- 12 sensorů: voltage, current, power, energy per konektor, meter, RSSI, FW, ...
- 8 binary sensorů: connected, lock, PnC per konektor, NWire.
- `LoadBalance` slider (4000-14600 W) pro PV-driven modulaci.
- 8 buttons: Lock/Unlock/PnC open/close pro oba konektory.
- HACS-compatible struktura (hacs.json, icon, logo, dokumentace).

### Reverse-engineering artefacts
- Pcap z HCI snoop logu (BLE, 70 JSON zpráv).
- Pcap z WiFi capture (WebSocket + ocpp1.6).
- 60/60 unit testů protokolu pass (v WallBox/pico/tests/).
