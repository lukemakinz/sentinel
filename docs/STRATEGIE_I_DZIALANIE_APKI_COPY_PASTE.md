# Sentinel — nasze strategie i sposób działania aplikacji

**Wersja:** 01.11.2026  
**Przeznaczenie:** samodzielny opis gotowy do skopiowania do nowej rozmowy,
specyfikacji produktu albo zadania dla programisty.  
**Ważne:** wyniki backtestów i shadow nie są obietnicą zysku. Handel live jest
obecnie twardo wyłączony.

---

## 1. Nasze strategie

Sentinel nie ma jednej „magicznej” strategii. Ma zamknięty rejestr strategii,
z których każda ma osobny kapitał, horyzont, reguły, status i kryterium promocji.
Model AI nie może wymyślać nowych strategii ani samodzielnie zmieniać parametrów.

Rejestr jest technicznie silnikiem pluginów. Nowa strategia dostarcza własny
wersjonowany kontrakt, detektor, dozwolone strefy i trigger, natomiast jakość
danych, ekonomia transakcji, ryzyko, P0/P1/P2, replay i raportowanie pozostają
wspólne. Plugin można wyłączyć konfiguracją bez utraty historii i bez zmiany
rdzenia aplikacji. Szczegóły: `docs/architecture/STRATEGY_PLUGIN_ENGINE.md`.

### Rejestr

| Strategia | Rola | Status |
|---|---|---|
| `BOOK_A_ALT_RM + RM_composite_v1` | spokojna renta trendowa na altach | zamrożony research + codzienny paper-forward |
| `S84_quiet_router` — Book B | kierunkowy breakout BTC w spokojnym reżimie | zamrożony paper-forward, **niezgodny z limitem ryzyka live** |
| `BENCH_AB_R2` | portfel $500: Book A $250 + Book B $250 | paper-forward od 27.10.2026; min. 90 dni przed oceną promocji |
| `FCM_SAFE25` | market-neutral funding carry | defensywny paper-forward; live najwcześniej po 18 miesiącach i 12 epizodach |
| `SAI1_*` | AI jako selektor setupów auction/price-action | wyłącznie shadow; nie składa zleceń |
| `SENTINEL_INTRADAY_V2` | właściwy day trading: 4h/1h kontekst, 15m setup, 5m/1m trigger, aktywne P1/P2 | prerejestrowany research/shadow |
| OB Liquidity Reversal / ICT-SMC | dziennik setupów i nauka prospektywna | retrospektywne S112–S114 odrzucone; bez live |

### A. Book A — Sentinel Trend Rent

Book A jest wolną, long-only strategią momentum na płynnych altach. Jej zadaniem
nie jest codzienny trading, lecz udział w szerokiej hossie przy małym turnoverze.

Reguły:

1. Kapitał referencyjny: **$250**.
2. Uniwersum zamrożonego benchmarku: `ETHUSDT`, `SOLUSDT`, `XRPUSDT`,
   `DOGEUSDT`, `BNBUSDT`. BTC jest filtrem reżimu, a nie pozycją w wariancie
   `BOOK_A_ALT_RM`.
3. Handel tylko wtedy, gdy zamknięcie BTC jest powyżej SMA200.
4. Dla każdego alta liczony jest dodatni momentum z 20 dni. Ujemny momentum
   oznacza brak pozycji.
5. Wybierane są najsilniejsze aktywa; wagi są odwrotnie proporcjonalne do ich
   zmienności.
6. Docelowa zmienność portfela: około 30% rocznie, bez skalowania ekspozycji
   powyżej 100%.
7. Rebalance raz w tygodniu, w poniedziałek UTC. Minimalna pozycja: $15.
8. Risk overlay `RM_composite_v1`:
   - mniej niż 35% altów powyżej SMA50 → gotówka;
   - percentyl zmienności BTC 75–92% → ekspozycja liniowo maleje;
   - percentyl zmienności BTC ≥92% → gotówka;
   - drawdown księgi ≥10% → połowa ekspozycji;
   - drawdown ≥18% → gotówka;
   - maksymalna ekspozycja brutto: 85% kapitału.
9. Niewykorzystany kapitał pozostaje gotówką. Nie wolno renormalizować wag do
   100%, bo usuwałoby to działanie risk overlay.

Book A nie ma klasycznego stopa na każdą pozycję. Ryzykiem sterują reżim,
zmienność, breadth, ograniczona ekspozycja i tygodniowy rebalance. Dlatego przed
jakimkolwiek live potrzebuje osobnego, zamrożonego limitu ryzyka dla portfela
bez stopów.

### B. Book B — Sentinel Quiet Breakout

Book B jest szybszą, kierunkową strategią na BTC, która ma zarabiać w innych
momentach niż Book A. Nie jest scalpem i nie handluje cały czas.

Reguły bazowe:

1. Kapitał referencyjny: **$250**.
2. Instrument: `BTCUSDT`, long albo short.
3. Sygnał powstaje po zamknięciu świecy 1h poza wcześniejszym kanałem
   Donchiana z 10 godzin i tylko przy `ADX ≥ 25`.
4. Maksymalnie jeden nowy sygnał na dobę UTC.
5. Stop: 1 ATR od wejścia. Maksymalny czas pozycji: 24h. Techniczny limit celu:
   8R; w praktyce dominują stop albo wyjście czasowe.
6. Jedna pozycja jednocześnie. Zamrożone ryzyko: $6 na transakcję.
7. Handel wymaga BTC powyżej SMA200 oraz spokojnego reżimu:
   - wariant v1: percentyl zmienności BTC ≤55% i breadth altów ≥40%;
   - wariant v2: percentyl zmienności BTC ≤45%, breadth ≥50% i maksymalnie
     dwie transakcje tygodniowo;
   - router wybiera surowszy v2 przy szerokim rynku albo bardzo niskiej
     zmienności, w pozostałych dopuszczonych przypadkach v1.
8. Trzy serie strat albo limit dziennej straty blokują dalsze wejścia.

Book B pozostaje **niepromowalny do live**, ponieważ $6 ryzyka to 1,2% jego
księgi i przekracza obecny limit 0,5% otwartego ryzyka portfela. Zmniejszenie
ryzyka nie może być zrobione po cichu — wymaga nowego ID strategii i nowego
paper-forward.

### C. BENCH_AB_R2 — portfel badawczy A+B

Portfel dzieli $500 po równo między Book A i Book B. Na nietkniętym wcześniej
oknie 01.09–26.10.2026 scenariusz kosztowy stress osiągnął historycznie
**+$15,43, czyli $0,275/dzień, przy max DD 1,84%**. DSR po uwzględnieniu 133
wcześniejszych prób wyniósł tylko **0,02**, więc wynik mógł obalić strategię,
ale nie potwierdza jeszcze trwałej przewagi.

Od 27.10.2026 działa zamrożony paper-forward. Reguły oceny:

- mniej niż 30 pełnych dni: `INSUFFICIENT`;
- 30–89 dni: maksymalnie `OBSERVE`;
- `ON_TRACK` dopiero po co najmniej 90 dniach, dodatnim PnL, wyniku co najmniej
  50% referencji $0,14/dzień, większości dodatnich miesięcy, braku rewizji danych
  i braku naruszenia 10% drawdownu;
- nawet `ON_TRACK` nie promuje całego A+B, dopóki Book B łamie limit ryzyka.

### D. FCM_SAFE25 — Funding Carry

Strategia neutralna kierunkowo: mała pozycja spot long i dokładnie taka sama
ilość perpetual short. Zarobek ma pochodzić z dodatniego fundingu, nie z ruchu
ceny.

Reguły:

1. Kapitał $250: maks. $25 spot, $200 izolowanego marginu futures i $25 rezerwy.
2. Uniwersum: ETH, SOL, BNB.
3. Decyzja raz w miesiącu na podstawie zakończonego poprzedniego miesiąca.
4. Warunki: suma fundingu ≥50 bps, dodatni 30-dniowy zwrot spot i cena powyżej
   EMA50. Wybierany jest kwalifikujący się rynek z najwyższym fundingiem.
5. Obie nogi mają identyczną ilość bazowego aktywa, zaokrągloną w dół do
   wspólnego kroku giełdowego. Zakazane są top-up i dynamiczny rehedge.
6. Awaryjne zamknięcie następuje przy zbyt małym buforze futures lub zbyt dużej
   dźwigni liczonej konserwatywnie z rzeczywistych mark-price highs.

Historyczny gate został zaliczony, lecz najnowsza przewaga była bardzo mała.
Strategia jest tylko kandydatem paper-forward; live wymaga minimum 18 miesięcy,
12 zamkniętych epizodów, dodatniego wyniku po rzeczywistych kosztach i braku
naruszeń bezpieczeństwa.

### E. Sentinel Auction Intelligence — AI shadow

To nie jest autonomiczny trader. Kod najpierw wykrywa mechanicznego kandydata,
a dopiero potem AI może go ocenić. Dozwolone hipotezy:

- `SAI1_FAILED_AUCTION` — sweep silnego poziomu i powrót do poprzedniej aukcji;
- `SAI1_IFVG_FLIP` — odwrócenie/flip strefy FVG;
- `SAI1_TREND_RETEST` — retest struktury zgodny z trendem.

AI zwraca wyłącznie `PASS`, `WAIT` albo `ARM`. Nie może zwrócić `ENTER`, ustalić
wielkości pozycji, dźwigni ani przesuwać stopa. Geometrię, koszty, wejście,
inwalidację i wynik liczy kod. Ten sam kandydat jest równolegle rozliczany przez
mechaniczny baseline, więc mierzymy wartość dodaną AI, a nie sam wynik rynku.

Każdy snapshot zawiera deterministyczny `Trend State v1` dla
`5m/15m/1h/4h/1d`: kierunek, siłę 0–100, strukturę `HH_HL/LH_LL/MIXED`,
nachylenie EMA20 wyrażone w ATR, odległość EMA20–EMA50 w ATR oraz percentyl
zmienności. Interwał 1d jest liczony wyłącznie z kompletnych dni UTC mających
sześć zamkniętych świec 4h. Trend służy do nauki i pomiaru; nie daje prawa do
wejścia.

Wartość selekcji mierzymy w trzech torach na dokładnie tych samych epizodach:

- `M0` — zamrożony mechaniczny baseline;
- `M1` — M0 plus zamrożony filtr trendu 1h/4h/1d; veto tylko przy silnej
  opozycji (`aligned_score < -0,25`), brak danych oznacza `PASS`;
- `M2` — recenzent AI, który może potwierdzić kandydata albo zwrócić
  `PASS/WAIT`.
- `M3` — M0 plus zamrożony Global Context v1.3: BTC/ETH, relatywna siła
  ETH/BTC i breadth zamrożonego koszyka 20 altów. TOTAL2/TOTAL3/TOTAL3ES/BTC.D
  są jawnie `unavailable`, dopóki nie istnieje replayowalne źródło.

M1, M2 i M3 nie tworzą nowych „transakcji”. `PASS/WAIT` dostaje 0R na tym samym
przyszłym wyniku M0, a kompletne `NO_TRIGGER/PRE_INVALIDATION` zostaje w
mianowniku jako 0R. M3 rozdziela brak danych od prawdziwego globalnego veto.

Minimum do pierwszej analizy statystycznej to około 100 zamkniętych planów.
Do tego czasu każda decyzja AI jest wyłącznie obserwacją badawczą.

### F. SENTINEL Intraday v2 — docelowy day trading

M0/SAI1 Failed Auction został na dużej próbie odrzucony i pozostaje kontrolą.
Nie próbujemy ratować go samym AI ani stroić na tej samej historii. Nowy tor
intraday ma osobny kontrakt:

- 4h/1h opisuje reżim, ale nie zmienia transakcji w swing;
- setup powstaje na 15m, potwierdzenie na 5m, wejście i zarządzanie na
  zamkniętych świecach 1m;
- maksymalny czas pozycji to 4h i nie ma pozycji kierunkowej przez zmianę dnia
  UTC;
- wymagany jest naturalny stop strukturalny 0,40–1,25% oraz stress koszt ≤0,25R;
- limit-first po potwierdzeniu; brak filla jest lepszy niż pogoń marketem;
- badamy trzy różne mechanizmy: trend pullback, session expansion po kompresji
  oraz failed auction wyłącznie w prawdziwym range z potwierdzeniem flow.

Zamrożone zarządzanie:

- `P1_STRUCTURAL`: TP1 0,75R na 50%, następnie stop kosztowy BE lub lepsza
  zamknięta struktura 1m, reszta do 1,5R;
- `P2_HYBRID`: po 0,5R redukcja otwartego ryzyka do −0,5R; TP1 0,75R na 40%,
  TP2 1,25R na 30%, runner 30% z trailingiem 0,5R.

Stop przesuwa się wyłącznie w stronę redukcji ryzyka i zaczyna obowiązywać od
następnej świecy. Każdy partial płaci własny koszt, a jednoczesny stop/TP jest
liczony stop-first. Częsty TP nie jest celem samym w sobie: awans wymaga
dodatniej expectancy netto, nie wysokiego odsetka zielonych wyjść.

Pełny test zarządzania na starym M0 dla SOL (2024–09.2026, 3 988 filli) odrzucił
oba warianty: P0 −0,908R/trade, P1 −0,928R, P2 −0,952R. P1/P2 pozostają gotową
infrastrukturą do testowania z nowymi wejściami Intraday v2, ale nie mogą być
dalej strojone na M0.

Pełny kontrakt: `docs/strategies/SENTINEL_INTRADAY_V2.md`.

### G. Setupy OB / Liquidity Reversal / ICT-SMC

Pełne testy S112–S114 nie potwierdziły przewagi. Na szerokim held-out universe
warianty STRICT, EXTERNAL i ABSORB_CVD zostały odrzucone. Nie uruchamiamy
kolejnych wariantów retrospektywnych na tych samych danych.

System nadal zapisuje setupy prospektywnie co 15 minut — sweep, MSS, FVG,
absorpcję, porę dnia, kontekst BTC i dziewięć wariantów wejścia/wyjścia. Po około
100 zamkniętych przypadkach można postawić nową, zamrożoną hipotezę. Nie wolno
promować strategii na podstawie kilku efektownych screenów.

---

## 2. Jak aplikacja ma działać

### Cel

Sentinel ma być automatycznym laboratorium i systemem kontroli ryzyka, który
pracuje 24/7: zbiera dane, wyszukuje kandydatów, porównuje AI z algorytmem,
prowadzi paper-forward i blokuje ryzyko przy awarii. AI jest recenzentem setupu,
nie właścicielem pieniędzy.

### Przepływ działania

1. **Zbieranie danych**
   - Binance Futures WebSocket dostarcza świece 1m/5m/15m/1h/4h, aggTrades,
     funding/mark price, likwidacje oraz top-20 order book.
   - BTC i ETH są zawsze pobierane jako kontekst globalny.
   - Open interest jest odświeżany przez REST co 5 minut.
   - Order book jest zapisywany co około 5 sekund, aggTrades paczkami co sekundę.

2. **Kontrola jakości**
   - Każdy snapshot ma timestampy, kompletność i flagi jakości.
   - Brak świeżych świec, order booka, OI albo CVD oznacza deterministyczny
     `PASS`; AI nie jest wtedy wywoływane.
   - Feed starszy niż 5 minut przełącza system w `CLOSE_ONLY`. Po prawdziwym
     powrocie danych blokada feedu może zostać automatycznie zdjęta.

3. **Archiwum i odtwarzalność**
   - Order book i aggTrades są codziennie archiwizowane do Parquet z manifestem
     i SHA-256.
   - Retencja usuwa dane z bazy wyłącznie po potwierdzeniu poprawnego archiwum.
   - Backtest, baseline i AI muszą dostać dane możliwe do późniejszego
     odtworzenia. Brakujący dzień nie może być uzupełniany syntetycznie.

4. **Warstwa mechaniczna L1**
   - Skaner najpierw liczy reżim, trend, momentum, strefy, sweep, MSS, FVG,
     wolumen, CVD, OI, funding, likwidacje i order book.
   - Co 15 minut prowadzi dziennik do 60 rynków i zapisuje stan setupu:
     `WAIT_SWEEP`, `WAIT_MSS`, `WAIT_RETEST`, gotowy kandydat albo `NO_SETUP`.
   - Zamrożone strategie Book A/B są liczone osobnym, deterministycznym kodem.
   - `Trend State v1` klasyfikuje 5m/15m/1h/4h/1d nawet wtedy, gdy nie ma
     transakcji; dashboard pokazuje go jako materiał edukacyjny `research only`.

5. **Snapshot dla AI**
   - AI nie dostaje przypadkowego screena. Otrzymuje zwarty, niezmienny JSON:
     kontekst BTC/ETH, dane instrumentu na kilku interwałach, strukturę, strefy,
     przepływ, OI/funding, order book, jakość danych i zamknięty rejestr strategii.
   - Snapshot jest hashowany i zapisywany razem z decyzją oraz wersją promptu.

6. **Bramka przed OpenAI**
   - Najpierw mechaniczny baseline musi znaleźć kandydata.
   - Brak kandydata = brak wywołania AI i koszt $0.
   - Ten sam epizod jest oceniany przez AI najwyżej raz na 4 godziny.
   - Dzienny budżet AI jest twardo ograniczony; po jego wyczerpaniu wynik to
     fail-closed `PASS`.

7. **Decyzja i pomiar M0/M1/M2/M3**
   - Dozwolone odpowiedzi: `PASS`, `WAIT`, `ARM` w ścisłym JSON.
   - Każdy argument AI musi wskazywać istniejące pole snapshotu; odpowiedź
     niespełniająca schematu jest odrzucana.
   - M0, M1, M2 i M3 są rozliczane na tym samym kandydacie i tym samym przyszłym
     ruchu ceny. `PASS`/`WAIT` oznacza 0 PnL dla danej polityki, a nie usunięcie
     niewygodnej obserwacji. `DATA_INELIGIBLE` nie jest liczone jako trafne veto.

8. **Paper i shadow execution**
   - Kod, nie AI, wyznacza stop, target, TTL, maksymalny czas pozycji, fee i
     slippage.
   - Jeśli w jednej świecy wystąpi stop i target, wynik jest liczony
     konserwatywnie: stop pierwszy.
   - Każdy zakończony plan liczy równolegle P0, P1 i P2 na tej samej ścieżce
     ceny. P1/P2 obejmują partiale, kosztowy BE, redukcję ryzyka i trailing;
     zmiana stopa obowiązuje dopiero od kolejnej zamkniętej świecy 1m.
   - Tor intraday zamyka pozycję najpóźniej po czterech godzinach i przed zmianą
     dnia UTC. Nie ma averaging down ani odsuwania stopa.
   - Book A+B jest codziennie przeliczany na pełnych, checksumowanych archiwach.
     Jeśli oficjalne archiwum jeszcze nie istnieje, system czeka i ponawia próbę;
     nie udaje wyniku na niepełnej dobie.

9. **Uczenie na błędach**
   - System klasyfikuje rezultat przez MFE, MAE, fill, koszty, reżim i powód
     wyjścia: zły sygnał, złe wejście, złe zarządzanie albo brak edge.
   - Po zakończeniu pełnego okna pozycji tworzy jeden niezmienny
     `auction-postmortem-v3-intraday-management`: `SUCCESS`, `SIGNAL_FAILURE`, `ENTRY_QUALITY`,
     `MANAGEMENT_GIVEBACK`, `COST_DRAG`, `NO_FOLLOW_THROUGH`,
     `PATH_AMBIGUITY`, `NO_TRIGGER`, `PRE_INVALIDATION` albo
     `DATA_INCOMPLETE`.
   - Na tych samych świecach zapisuje zamrożone kontrfakty: market z targetem
     1R/1,5R/2R, limit po potwierdzeniu ważny pięć minut oraz intraday P1/P2.
     Każdy wariant ma te same koszty i konserwatywną zasadę `stop-first`.
   - Kontrfakty są diagnostyką, nie optymalizacją. Dashboard pokazuje średnie i
     liczbę przypadków, ale system nie wybiera automatycznie najlepszego targetu.
   - AI może raz w tygodniu zaproponować hipotezę w formacie: mechanizm → test →
     oczekiwany efekt.
   - AI nie może samodzielnie zmieniać kodu strategii, parametrów ani promptu
     produkcyjnego. Każda zmiana wymaga nowego ID, zamrożonego protokołu i nowych
     danych prospektywnych.

10. **Risk engine**
    - Stan operacyjny: `NORMAL → CAUTION → DEFENSIVE → CLOSE_ONLY → HALT`.
    - System może automatycznie tylko zwiększać ostrożność.
    - Bazowe limity: 0,20% ryzyka na transakcję, 0,60% dziennego stopu, 1,80%
      tygodniowego stopu, maks. dwie pozycje i 5x dźwigni.
    - Dodatkowo kontrolowane są: otwarte ryzyko do stopów, ekspozycja beta do
      BTC, gross exposure, margin, bufor likwidacyjny i świeżość danych.
    - Rozbieżność z giełdą lub drawdown ≥10% oznacza ręcznie odblokowywany HALT.

11. **Egzekucja live — dopiero po promocji**
    - Giełda docelowa: KuCoin Futures.
    - Przed jedynym POST-em zapisywana jest trwała intencja z deterministycznym
      `clientOid`, stroną, dokładną ilością po zaokrągleniu i stopem.
    - Wejście i katastroficzny stop są wysyłane atomowo przez `/api/v1/st-orders`.
      Nie ma fallbacku do wejścia bez stopa.
    - Timeout/5xx nie powoduje ponownego POST. System wykonuje wyłącznie lookup
      po `clientOid`; nieudowodniony wynik przechodzi w `UNCERTAIN` i HALT.
    - Zamknięcie jest przeciwstawnym market orderem z `reduceOnly=true`.
    - Watchdog co 60 sekund synchronizuje pozycje i zlecenia, gdy live jest
      włączony. Nieznana pozycja, brak pozycji lokalnej, błędny rozmiar/strona,
      brak ochronnego stopa lub utrata widoczności konta blokują nowe wejścia.

12. **Obsługa i raportowanie**
    - Niezależne procesy: `ingester`, `risk_watchdog`, opcjonalny Telegram oraz
      dashboard. Bezpieczeństwo nie zależy od Telegrama ani Celery.
    - Telegram: `/status`, `/scan`, `/raport`, `/koszt`, `/paper`, `/pauza`,
      `/wznow`, `/stop`.
    - Telefon nie może włączyć live ani zwolnić ręcznego HALT.
    - Raport pokazuje osobno: M0 baseline, M1 filtr trendu, M2 AI, ich uplift
      na wspólnej próbie, koszty, drawdown, $/dzień, lukę do celu i jakość próby.

### Niezmienne zasady bezpieczeństwa

1. AI nie ustala wielkości pozycji, dźwigni ani samodzielnie nie składa zleceń.
2. Nie ma wejścia live bez działającego stopa po stronie giełdy.
3. Nie ma blind retry po niejednoznacznym wyniku POST.
4. Nie promujemy strategii na podstawie backtestu, kilku screenów ani wysokiego
   `confidence` modelu.
5. Gotówka i `PASS` są pełnoprawnymi decyzjami.
6. Brak danych lub awaria AI zawsze zmniejszają ryzyko, nigdy go nie zwiększają.
7. Każda strategia i zmiana parametrów ma własny protokół, hash i forward test.

### Stan bieżący na 01.11.2026

- Ingester i watchdog działają w odłączonych procesach.
- Feed potrafi przejść w `CLOSE_ONLY` przy awarii DNS i sam wrócić do `NORMAL`
  dopiero po odzyskaniu świeżych danych.
- Paper-forward A+B działa, lecz ma status `INSUFFICIENT`; oficjalne archiwa po
  27.10 nie były jeszcze opublikowane, więc system prawidłowo nie dopisuje dni.
- AI shadow jest gotowe technicznie, ale jego działanie zależy od dostępnego
  budżetu/API OpenAI.
- `Trend State v1`, Global Context v1.3 i prospektywne porównanie M0/M1/M2/M3
  są wdrożone; wyniki wymagają nowych, kompletnie rozliczonych epizodów i nie
  są jeszcze dowodem przewagi.
- Retrospektywny replay M0 na BTC/ETH/SOL/AVAX jest jednoznacznie ujemny.
  M0 zostaje kontrolą, a post-mortem v3 mierzy P1/P2; nie przedstawiamy tej
  zmiany jako dowodu, że strategia zaczęła zarabiać.
- Live pozostaje podwójnie zablokowany:
  `LIVE_TRADING_ENABLED=False` oraz
  `EXCHANGE_SIDE_STOPS_IMPLEMENTED=False`.
- Następny krok live to wyłącznie read-only preflight, a później ręcznie
  nadzorowany test minimalnego kontraktu na odseparowanym subkoncie KuCoin.

---

## Krótka wersja do wklejenia

Sentinel to wielowarstwowy system tradingowy, w którym kod wykrywa setupy,
liczy ryzyko i egzekucję, a AI tylko ocenia wcześniej znalezionych kandydatów.
Główna strategia Book A to tygodniowy long-only momentum na płynnych altach z
filtrem BTC>SMA200, breadth, zmienności i drawdownu. Book B to selektywny
breakout BTC po 1h Donchian-10 i ADX≥25 w spokojnym reżimie; pozostaje
paper-only, bo obecne $6 ryzyka przekracza limit portfela. FCM_SAFE25 to
defensywny, miesięczny funding carry: mały spot long i równa ilość perpetual
short. Warstwa SAI ocenia w shadow tylko trzy zamknięte hipotezy auction i może
zwrócić PASS/WAIT/ARM; nie może składać zleceń ani dobierać wielkości pozycji.

Aplikacja 24/7 zbiera Binance candles, trades, order book, funding, OI i
likwidacje, kontroluje jakość, archiwizuje dane z checksumami, prowadzi skaner i
dziennik setupów, porównuje AI z mechanicznym baseline oraz codziennie liczy
zamrożony paper-forward. Dla każdego rynku pokazuje edukacyjny trend
5m/15m/1h/4h/1d i mierzy M0 baseline, M1 baseline+trend, M2 AI oraz M3
baseline+global context na tej samej próbie. Risk engine przełącza stany
NORMAL–HALT i blokuje nowe
wejścia przy starym feedzie, drawdownie lub rozbieżności z giełdą. Przyszłe live
na KuCoin wymaga trwałej intencji zapisanej przed POST, atomowego entry+stop,
deterministycznego clientOid, zakazu blind retry, reduceOnly close i cyklicznej
rekoncyliacji. Dziś live jest twardo wyłączony; najpierw potrzebne są nowe dane
forward oraz ręcznie nadzorowany test minimalnego kontraktu na subkoncie.
