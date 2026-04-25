# Krytyczna analiza systemu AI Multi-Agent dla Crypto Futures
**Autor analizy:** Claude (konsultacja w oparciu o wiedzę z quant trading, market microstructure i produkcji systemów ML)
**Data:** 23.04.2026
**Przedmiot:** Specyfikacja 2.0 (Mastermind Verified) — system oparty na SMC + Order Flow dla Binance Futures

---

## TL;DR (zarząd się nie czyta)

Specyfikacja jest **powyżej średniej** jakościowo w porównaniu do typowych "AI trading bot" projektów — widać świadomość SMC, order flow i zarządzania ryzykiem. Jest jednak **kilka krytycznych luk**, które w realnym tradingu zamienią Cię z inwestora w dawcę kapitału:

1. **Brak backtestów i walidacji statystycznej** — to #1 powód, dla którego 95% projektów AI trading pali kapitał.
2. **LLM-y (GPT-4o, Claude) nie są kwantami** — dają im decyzje, których nie powinny podejmować (liczbowe, arbitrażowe).
3. **Position sizing 2.5% equity per trade jest zabójczo agresywny** dla systemu o nieznanym edge.
4. **Brak wykrywania reżimu rynkowego** — strategia Sweep & Absorption działa w rangingu/reversalu, w silnym trendzie będzie masakrą.
5. **Założenie, że "day trading zawsze lepszy" jest fałszywe** — więcej trade'ów = więcej opłat + slippage + podatków, edge musi być odpowiednio duży.

Zanim pójdziesz live: **3–6 miesięcy paper tradingu + backtest na min. 3 latach danych (2022 bear, 2023 recovery, 2024 bull, 2025)**. Bez tego to hazard z dodatkowymi krokami.

---

## 1. Co zrobiłeś dobrze (mocne strony)

### 1.1. Architektura warstwowa (Deterministic → AI → UI)
Podział na warstwę deterministyczną (tani pre-filter) i AI (droga decyzja na wyselekcjonowanych setupach) jest **architektonicznie poprawny**. To standardowy pattern w instytucjach — nie chcesz płacić za inference LLM dla każdej 1-sekundowej świecy. To też sposób na utrzymanie low-latency dla większości czasu.

### 1.2. Rozdzielenie Whale CVD / Retail CVD
To bardzo dobry pomysł. Większość open-source crypto-botów patrzy na surowy CVD i ginie na szumie botów gridowych (jest ich dużo na Binance). `aggTrade` z filtrem wielkości to właściwe narzędzie. **Ale próg 50k USDT jest arbitralny** — patrz sekcja Słabych Stron.

### 1.3. Killzones (okna czasowe)
Krytyka "Context Tradera" jest słuszna. W krypto rzeczywiście **London Open (07:00 UTC), NY Open (13:30 UTC), CME Close (22:00 UTC piątek)** to okna podwyższonej instytucjonalnej aktywności. To zmniejsza częstotliwość sygnałów, ale podnosi ich jakość.

### 1.4. Korelacja z BTC jako gate dla altów
Absolutnie kluczowe. Alt-coiny mają 70–90% beta do BTC w większości reżimów. **Long SOL podczas break down BTC = prawie gwarantowana strata.** Risk Manager z `get_btc_market_structure()` to must-have.

### 1.5. ATR dla kalkulacji SL i position sizing
Standard branżowy, poprawnie wdrożone. Plus: wspomniałeś `1.5x ATR` jako minimum — rozsądnie unika się stop-huntingu.

### 1.6. Stack techniczny
Django Channels + Redis + TimescaleDB + Canvas dla tape/orderbook = właściwe wybory. Canvas zamiast DOM dla heatmapy to **konieczność**, nie opcja (przy >60fps rendering DOM zabije przeglądarkę).

### 1.7. Panic Sell i konteneryzacja
Dojrzały DevOps — hardware kill-switch jest niezbędny. `docker compose up` jako MVP = dobrze.

### 1.8. Funding Rate jako filtr
Super że to jest. Extreme funding (>0.1% per 8h) to klasyczny kontr-wskaźnik — tłum przepłaca za lewar, bliska mean-reversion/squeeze.

---

## 2. Krytyczne słabe strony (gdzie to pęknie)

### 2.1. ❌ BRAK BACKTESTÓW — zabójca #1
**Nigdzie nie wspominasz o backtestingu, walk-forward analysis, out-of-sample testing ani paper tradingu.** To jest absolutnie dyskwalifikujące. Bez tego nie wiesz:
- Czy Twój edge istnieje (hit rate, payoff ratio)
- Czy przeżyje change of regime
- Czy parametry (ATR=14, Killzones, 1.5x SL) nie są overfittowane
- Ile kosztów (fee + slippage + funding) zżera faktyczny PnL

**Przykład liczbowy:** Strategia z win rate 55%, RR 1:2, wygląda świetnie (EV = +0.65R/trade). Dodaj 0.04% fee taker × 2 (wejście + wyjście) × 10x leverage = 0.8% opłat w nocy. Przy ATR rzędu 1.5% to zjada ~30% edge. Bez backtestu **tego nie zobaczysz**.

### 2.2. ❌ LLM jako decision maker — nie do tego służą
"The Supervisor" w prompcie ma **generować precyzyjne punkty wejścia, SL i TP**. To jest błąd designu:

- LLM-y **halucynują w arytmetyce** — wielokrotnie udokumentowane (spójrz choćby na OpenAI's own papers o Math benchmark).
- LLM nie ma deterministycznego cache dla "ostatniego High" czy "najbliższej FVG" — policzy to z rzadkim błędem.
- Nie wiesz kiedy "obaj się zgadzają" bo prompt nie ma hard schema — dostaniesz `"yes_but_with_concerns"`.

**Właściwy wzorzec:**
- **Deterministyczny kod** oblicza entry, SL, TP, size.
- **LLM ma prawo VETO** na bazie kontekstu (newsy, sentyment, anomalie nie widziane wcześniej).
- **LLM nigdy nie generuje liczb, które idą do exchange API.**

### 2.3. ❌ Brak detekcji reżimu rynkowego
Strategia "Sweep & Absorption" jest strategią **reversal/mean-reversion**. W silnym trendzie (BTC 2024 Q1, SOL Nov 2024) **każdy sweep jest kontynuacją, nie odwróceniem**. Agent będzie shortował szczyty, które robią +20% w dobę.

**Co dodać:**
- **Regime filter**: ADX > 25 = trend (wyłącz mean-reversion), ADX < 20 = range (włącz). Albo:
- **Realized volatility regime**: rolling 30d realized vol > historical median → ekspansja, strategie momentum; inaczej → kompresja, strategie reversal.
- **Multi-timeframe trend alignment**: jeśli 1D EMA50 > EMA200 (bull), dopuść tylko LONG sweeps, blokuj SHORT (i vice versa).

### 2.4. ❌ Próg Whale CVD = 50k USDT jest arbitralny
- Dla BTCUSDT (cena ~$80k) transakcja 50k to mniej niż 1 BTC. To **nie jest whale**, to średniak.
- Dla obscure alta z $100M market cap 50k USDT to **rzeczywiście whale**.
- 50k jest arbitralne i statyczne → zignoruje adaptację rynku.

**Fix:** Dynamiczny próg = **95 percentyl rolling 24h aggTrade size** dla danej pary. Re-kalkulacja co godzinę.

### 2.5. ❌ Position sizing 2.5% per trade jest kamikaze
Z kalkulacji **ryzyka ruiny** (Kelly, Thorp):
- 2.5% × 40 kolejnych stratnych = -100% konta (pomijając compounding)
- Dla systemu z nieznanym, nie-zwalidowanym edge to **loteria**.
- Standard w systematic trading: **0.25–1% per trade**.
- Kelly fractional (1/4 Kelly) przy win rate 55%, RR 1:2 → ~4.4% × 0.25 = **1.1% per trade max**.

**Dla day tradingu z wieloma pozycjami jednocześnie:** jeszcze mniej, bo korelacja portfela zwiększa realne ryzyko.

### 2.6. ❌ Brak limitu strat dziennych/tygodniowych
**Najważniejsza zasada zarządzania ryzykiem dla systemu**: Daily Stop Out. Jeśli stracisz X% w ciągu dnia, **system sam się wyłącza do północy UTC**. Klasyczne progi:
- Daily max loss: -3% equity → HALT
- Weekly max loss: -7% equity → HALT
- Drawdown from peak > 10% → zmniejsz size o 50%
- Drawdown > 20% → full halt, manualne review

Bez tego **jeden "zły dzień" (flash crash, black swan, bug w kodzie)** może Cię zabić.

### 2.7. ❌ Brak modelowania kosztów realnych
Spec nigdzie nie liczy:
- **Fees** (Binance futures: 0.02% maker / 0.05% taker, z VIP/BNB niższe)
- **Slippage** (dla market orders na 50k USDT w szczycie volatilu → 0.05–0.2%)
- **Funding rate paid** (long przy funding +0.03% × 3 × dzień = 0.09%/dzień kosztu)
- **Spread crossing** dla TP/SL

**Konsekwencja:** Strategia, która w backteście robi +30% rocznie, live daje +8% bo "zapomnieli" o 2bps × 2 × 10 trade'ów/dzień = 4% miesięcznie opłat.

### 2.8. ❌ Manipulacja orderbookiem — spoofing/layering
W crypto bardzo częste. Ściana limit orders po Twojej stronie? Może być fałszywa — cancel w milisekundzie przed dojściem ceny. "Get_orderbook_walls()" musi wykrywać **persistence walls** (utrzymane >30s) a nie migawki.

**Fix:**
- Analizuj **cancellation rate** na danym levelu
- Warstwy >3 deep w książce (przestawne przy aktywnej cenie są bardziej realne niż 50 pipsów od ceny)
- Cross-reference z **footprint** z aggTrade (czy ściana się zjadła czy wyparowała)

### 2.9. ❌ Latencja Python + Django + Redis dla order execution
Przy Sweep → ChoCh → Entry masz okno **2–5 sekund**. Twój pipeline:
1. WebSocket tick (10ms)
2. Python parsing (5ms)
3. Redis write + smc_engine (20ms)
4. Celery task spawn (50–500ms ⚠️)
5. 3x LLM call (2–15s każdy ⚠️⚠️)
6. Decision → Frontend WebSocket (10ms)
7. User click (0.5–2s)
8. REST API do Binance (100–300ms)

**Razem: 15–45 sekund.** Sweep & Absorption setupy wymagają wejścia w ciągu kilku sekund od ChoCh. To nie jest problem dla swing (4H+), ale dla intraday z małymi SL to zabija RR.

**Fix:**
- Deterministyczny fast-path (bez LLM) dla klasycznych setupów, LLM tylko jako po-fakt weryfikacja i learning
- Albo: LLM pre-generuje "ready signals" w tle, a execution jest hardkodowany na ostrych warunkach
- Rozważ Rust/Go dla execution engine (Python tylko dla orchestracji)

### 2.10. ❌ "Take Profit = najbliższa nienaruszona płynność" jest chwiejne
Co jeśli nie ma płynności w zasięgu RR 1:2.5? Co jeśli płynność jest daleko? Deterministyczne TP muszą mieć fallback:
- TP1: 1.5R (40% pozycji)
- TP2: 3R lub najbliższa HTF liquidity (40%)
- TP3: trailing stop, biegnie aż skończy się trend (20%)

### 2.11. ❌ Brak monitoringu degradacji strategii
Strategia, która działa dziś, za 6 miesięcy może przestać działać (markets adapt, MM machines learn). **Musisz mierzyć:**
- Rolling 30-trade win rate
- Rolling 30-trade Sharpe
- Expectancy drift (EV jest stabilne czy spada?)
- **Kill-switch**: jeśli rolling Sharpe < 0 przez 20 trade'ów → auto-halt, manual review

### 2.12. ❌ Brak planu dla walk-forward i re-optymalizacji parametrów
Parametry typu ATR(14), EMA(200), Killzone windows — **kto i jak będzie je dostrajał**? Bez walk-forward optimization parametry są static i będą overfittowane albo stale. Plan: co kwartał re-optymalizacja na rolling 2-year window, OOS test na ostatnich 3 mies.

### 2.13. ❌ Brak wersji paper/simulacji
Spec od razu mówi "wysyłamy zlecenia na Binance". **Nie.** Pierwsze 3–6 miesięcy: **Binance Testnet** (ma futures testnet) lub internal paper-trading z realnym data feed. Zmierz:
- Real slippage vs. expected
- Latencję faktyczną
- Rozbieżność backtest vs paper
- Zachowanie pod stresem (flash crashes)

### 2.14. ❌ Single exchange = single point of failure
Binance może być offline (było już kilka razy), API może zwrócić stale data, konto może być zablokowane (KYC, region). **Minimum:** drugie konto/giełda gotowe do awaryjnej likwidacji (Bybit, OKX mają kompatybilne API).

### 2.15. ❌ Brak obsługi podatku i audytu
W PL każdy trade = zdarzenie podatkowe. Przy 20 trade'ach dziennie to ~5000 trade'ów rocznie. **Musisz logować:**
- Każdą transakcję (open/close) z timestampami i kursem PLN
- FIFO queue dla matchingu long/short
- Export do druczka PIT-38 lub integracja z cryptotax tools (Koinly, CoinLedger API)

### 2.16. ⚠️ Multi-timeframe — spec wspomina, ale nie wymusza alignmentu
Pytałeś o 1H/4H/1D/1W. Dobra hierarchia:
- **1W**: trend makro (filter, nie trigger)
- **1D**: structural bias — trend up/down/range
- **4H**: konfluencja — POI (Points of Interest), HTF liquidity levels
- **1H**: setup trigger — sweep, FVG, OB retest
- **15m/5m**: execution refinement
- **1m**: entry confirmation (ChoCh, ostateczny mikro-sweep)

**Bez HTF bias** łatwo trade'ować przeciw trendowi — statystycznie 30–40% więcej fałszywych sygnałów.

### 2.17. ⚠️ Leverage nie jest określony
Futures = leverage. Spec nie mówi ile. **Kluczowe:**
- Leverage powinien być tak dobrany, żeby liquidation price > stop loss × 2 (bufor bezpieczeństwa)
- Typowo: 3x–5x dla swing, 10x–20x tylko dla scalpów z ciasnym SL
- **Isolated margin per trade**, nigdy cross

---

## 3. Ulepszenia zarządzania ryzykiem (to co Cię pytałeś)

### 3.1. Trailing Stop Loss — strategie

Zebrałem kilka podejść; możesz je mieszać w zależności od trade'a:

**(A) Breakeven shift po 1R**
- Gdy pozycja zarobi 1R (1× początkowy risk), przestaw SL na entry price + 0.1R (pokrywa fees)
- **Efekt**: od tego momentu trade jest "risk-free"
- Najprostsze, najczęściej stosowane. Twój przykład z Solaną = to właśnie.

**(B) Fixed R-multiple laddering**
- 1R → SL na BE
- 2R → SL na 1R (zablokowany profit)
- 3R → SL na 2R
- I tak dalej, maksymalizuje runners

**(C) Chandelier Exit (ATR-based)**
- SL = najwyższe High z ostatnich N świec − (k × ATR)
- Parametry: N=22, k=3 (klasyczne)
- Płynnie śledzi wolatylność, nie zostaje "zassany" szumem

**(D) Structure-based trailing (SMC-friendly)**
- Po każdym nowym HH (higher high) na wybranym TF → przestaw SL pod ostatni swing low (HL)
- Najbardziej "naturalny" dla SMC — obcina trade dopiero przy CHoCH (change of character) z rynku na niekorzyść
- **Problem**: może być za szeroki przy volatile alts

**(E) Supertrend / Donchian**
- Mechaniczne, łatwe do automatyzacji
- Dobre dla trendowych pozycji z opcji "zostaw część, reszta zamknięta TP1"

**(F) Time-based stop**
- Jeśli trade nie osiągnął 1R w ciągu X godzin → zamknij market
- Dla day tradingu: jeśli trade trwa >8h, prawdopodobnie setup "nie zagrał"
- Oszczędza margin dla nowych setupów

### 3.2. Skalowanie wyjść (partial take profits) — Twój pomysł ✓
Masz rację. Konkretny szablon:

```
ENTRY (100% pozycji)
├── TP1 @ 1.5R  → zamknij 40% (zabezpieczasz fees + trochę zysku, reszta to profit)
├── TP2 @ 3R    → zamknij 40% (większość zysku)
│                  ↓
│               jednocześnie przesuń SL reszty na 1.5R (locked profit)
└── TP3 (runner, 20%) → trailing stop strukturalny
```

Dla Twojego scenariusza z SOL i "dane wskazują na długoterminowy wzrost": TP1 = 40%, TP2 = 40%, reszta 20% leci na pivot/target daily/weekly.

### 3.3. Portfolio-level risk

Krytyczne, bo **suma korelacji = realna ekspozycja**:

- **Max 3 jednoczesne pozycje** (na początku, zanim masz dane)
- **Max correlated exposure**: jeśli 3 alty mają korelację >0.85 z BTC, traktuj je jako 1 pozycję BTC
- **Heat map korelacji** liczona rolling 30d, aktualizowana co godzinę
- **Sektor exposure**: nie bierz 3 shortów na AI-coins jednocześnie (FET, AGIX, RNDR)

### 3.4. Kelly fractional dla sizing

```
Kelly % = (p × RR − q) / RR
gdzie:
  p = hit rate (np. 0.55)
  q = 1 − p (0.45)
  RR = średni payoff ratio (np. 2.0)

Kelly% = (0.55 × 2 − 0.45) / 2 = 0.325 = 32.5% (pełny Kelly, NIGDY nie używaj!)

Fractional Kelly: 0.25 × 32.5% = ~8% ekspozycji (nie risk, ekspozycji)
Risk per trade: ~1% konta (dopasowane do Kelly z odpowiednim leverage)
```

### 3.5. Drawdown-based sizing adjustment
- 0% DD: 100% normal size
- -5% DD: 75% size
- -10% DD: 50% size
- -15% DD: 25% size
- -20% DD: HALT, manual review

Zapobiega **revenge tradingowi** i cięciu strat, gdy system ma slabą passę (regime shift).

### 3.6. Stress test / Monte Carlo
Przed live: uruchom **10,000 permutacji** historycznych trade'ów. Jeśli w 5% gorszych scenariuszy drawdown przekracza 40%, to **size jest za duży** → obniż.

### 3.7. Hedge overlay (opcjonalny)
Podczas ekstremalnego funding rate (>+0.08%/8h) w alt-longach: short BTC z 20% wartości ekspozycji alt-longów. Neutralizuje kierunkowe ryzyko squeeze'a na całym rynku.

---

## 4. Moja własna wizja — "jak bym to zrobił na produkcji"

To jest moja subiektywna rekomendacja oparta na tym, co działa w realnych systematic trading shopach. Opcjonalne, ale jeśli mnie pytasz — *nie poszedłbym live według spec 2.0 w jej obecnym kształcie*.

### 4.1. Faza 0 — Fundament (miesiące 1–2)
**Cel**: zbudować infrastrukturę, mieć DANE zanim cokolwiek decydujesz.

- Postaw **Data Ingester** i zapisuj WSZYSTKIE aggTrade + klines + funding + OI + liquidations do TimescaleDB.
- Zbuduj **backtesting engine** (Python: `vectorbt`, `backtrader` albo custom na polars/numpy). Musi umieć:
  - Replay tick-by-tick z prawdziwym slippage modelem
  - Fee modeling (maker/taker)
  - Funding rate accruing
  - Multi-pair, multi-timeframe
- Historic data: min **3 lata** (2023–2026), wszystkie pary które planujesz tradeować.
- **Brak tradingu, brak AI, brak frontu** (na razie).

### 4.2. Faza 1 — Deterministyczna strategia (miesiące 2–4)
**Cel**: udowodnić że edge istnieje **bez AI**. AI tylko zaciemnia.

- Zaimplementuj `smc_engine.py` + Killzones + ATR + BTC correlation filter
- Backtest **czystej strategii** (bez LLM) na 3 latach
- Walk-forward: trening 2023–2024, test 2025, retrain rolling 6mies
- Metryki do zmierzenia:
  - Sharpe > 1.5 (po fee)
  - Max DD < 20%
  - Trade count > 200 (żeby statystycznie znaczące)
  - Win rate × avg win > loss rate × avg loss (pozytywne EV)
  - Calmar ratio (CAGR / MaxDD) > 0.5

**Jeśli deterministyczna strategia nie działa solo — AI też jej nie uratuje.** Wiele "AI trading systems" to deterministyczne systemy, które same w sobie mają ujemny edge, a AI nie robi z nich profitu, tylko wygląda lepiej.

### 4.3. Faza 2 — Paper trading (miesiące 4–5)
- **Binance Testnet** lub shadow mode (signals generated, but no real execution)
- Porównuj paper vs backtest — jeśli **rozbieżność >30%**, Twój backtest ma bug/bias (look-ahead, survivorship itp.)
- Mierz prawdziwą latencję, prawdziwy slippage

### 4.4. Faza 3 — AI jako warstwa VETO (miesiące 5–7)
Tutaj dopiero wchodzi AI, ale w **ograniczonej roli**:

- Signal generacja: **deterministyczna** (kod)
- Entry/SL/TP: **deterministyczne** (kod)
- AI layer 1 (Veto): **LLM dostaje kontekst** (news z ostatnich 30 min, Fed calendar, token unlocks, sentyment z Twittera) i ma prawo **odrzucić trade** z uzasadnieniem
- AI layer 2 (Logging): **LLM generuje post-trade narrative** ("dlaczego ten trade zadziałał / nie zadziałał") do journal, który używasz do improvement

### 4.5. Faza 4 — Live z minimalnym kapitałem (miesiące 7+)
- Start: **$500–$1000** (żeby fees były realne), nigdy więcej na start
- Risk per trade: **0.5% (pół standardowego)**
- Daily loss limit: -2% (HALT)
- Weekly review: cotygodniowo siądź z metrykami
- Skalowanie kapitału dopiero po **3 miesiącach pozytywnego live PnL** (nie paper, nie backtest — **live**)

### 4.6. Stack techniczny — co bym zmienił

| Element | Twój spec | Moja rekomendacja | Dlaczego |
|---|---|---|---|
| Framework AI | Agno Swarm | **Własna prosta orchestracja** (LangGraph lub czysty asyncio) | Agno to młode, niepewne API. Mniej zależności zewnętrznych. |
| LLM | GPT-4o / Claude 3.5 | **Claude 3.5 Sonnet** (lepszy w rozumowaniu) + **Haiku** dla tanich tasków | Sonnet > GPT-4o w reasoning benchmarks, Haiku 10× tańszy |
| Execution engine | Python + Celery | **Python dla decyzji + Rust/Go dla execution path** | Latencja. Celery dodaje 100–500ms. |
| Backtester | — (brak) | **`vectorbt` + custom slippage model** | Bez backtestu nie ma projektu. |
| Monitoring | — (brak) | **Grafana + Prometheus + custom KPI dashboard** | Musisz widzieć zdegenerowanie strategii w real-time. |
| Alerting | — (brak) | **PagerDuty/Discord webhook dla HALT events** | Jak system się sam wyłączy, musisz wiedzieć. |
| Paper trading | — (brak) | **Binance Testnet + shadow mode** | Obowiązkowe przed live. |

### 4.7. Minimalny viable product (MVP) jakbym go budował

Zamiast full spec 2.0 na start:

**v0.1 (działa za 4 tygodnie):**
1. Data ingester (aggTrade + klines dla BTCUSDT, ETHUSDT, SOLUSDT)
2. Jedna prosta strategia: **Liquidity Sweep + FVG return** na 15m, tylko w Killzones
3. Backtester z realnym slippage modelem
4. Paper trading feed (bez wykonania)
5. Dashboard (nawet brzydki) pokazujący sygnały + equity curve paper

**v0.2 (po 4 tygodniach):**
- Dodaj ATR-based sizing
- Dodaj BTC correlation filter
- Dodaj trailing SL (chandelier albo R-multiple)

**v0.3 (po kolejnych 4 tygodniach):**
- Dodaj Whale/Retail CVD split
- Dodaj regime detection (ADX)
- Zacznij Testnet live

**v0.4 (AI entry, po 3 miesiącach pozytywnego paper):**
- LLM Veto layer z newsami
- LLM post-trade journal

**v1.0 (live, po 6 miesiącach):**
- Minimalny kapitał ($500–1k), 0.5% risk/trade
- Pełny monitoring, HALT logic, panic sell

### 4.8. Psychologia i realizm

Nawet najlepszy system ma **drawdown 15–25% raz na 6–12 miesięcy**. Pytanie nie brzmi "czy", tylko "kiedy". Musisz:

- Mieć **kapitał, który możesz stracić w 100%**. Futures to leverage — 1 glitch, flash crash, exploit Binance i widzisz 0.
- Mieć **plan B** na przypadek gdy system przestanie zarabiać na 3 miesiące.
- Zakładać **realistyczny ROI: 20–60% rocznie** dla dobrego systematic systemu. Każdy, kto obiecuje 300%+ rocznie, albo kłamie, albo ryzykuje ruiną.
- **Day trading jest trudniejszy niż swing**. Więcej fee, więcej decyzji, więcej noise. "Day trading zawsze lepszy niż czekać" to mit — **long gamma trades** (trzymanie przez ruch) mają statystycznie lepszy Sharpe od 10 scalpów dziennie. Twoje założenie "otwieram i zamykam tego samego dnia, chyba że dane wskazują długoterminowo" jest **rozsądne**, ale wymaga algorithmic heuristic "kiedy trzymać": np. HTF trend alignment + realized volatility compression + funding neutral → trade może być trend-following multi-day.

---

## 5. Checklist "gotowości do live" (print it, pin it)

Przed pierwszym real-money trade'em muszę mieć **wszystkie** poniższe:

- [ ] Backtest na min. 3 latach, Sharpe > 1.5 po kosztach
- [ ] Walk-forward analysis na co najmniej 4 okresach OOS
- [ ] Paper trading 3 miesiące, rozbieżność < 20% vs backtest
- [ ] Realny model slippage, fee, funding w backtescie
- [ ] Daily max loss (-3%) + Weekly max loss (-7%) auto-halt
- [ ] Drawdown-based sizing adjustment
- [ ] Breakeven SL shift po 1R + trailing strategia
- [ ] Multi-TF alignment (1D bias, 4H structure, 1H trigger)
- [ ] Regime detection (trend vs range)
- [ ] BTC correlation filter dla altów
- [ ] Dynamic Whale CVD threshold (nie statyczne 50k)
- [ ] Persistence check dla orderbook walls (anty-spoof)
- [ ] Panic sell button (hardware key + GUI)
- [ ] Multi-exchange failover (minimum 1 fallback)
- [ ] Tax logging + PIT-38 export
- [ ] Monitoring / alerting (Grafana + Discord)
- [ ] Kill-switch na rolling Sharpe < 0 przez N trades
- [ ] Documented incident response playbook

---

## 6. Pytania, które sobie zadaj zanim przekażesz deweloperom

1. **Jakie mam dane historyczne?** Jeśli tylko 6 miesięcy — backtest jest meaningless (nie uchwyci bear, bull, chop).
2. **Ile jestem w stanie stracić?** Odpowiedź mniejsza niż kapitał startowy = redukuj kapitał.
3. **Czy widzę deterministic edge?** Bez AI, goły kod — ma dodatni EV po kosztach? Jeśli nie, AI nic nie pomoże.
4. **Kto będzie nadzorował system live?** 24/7 trading = ktoś musi reagować na anomalie. Pager rotation?
5. **Jaki mam KPI sukcesu?** "Dużo zarobić" = nie KPI. "Sharpe > 1.2, MaxDD < 15%, 12-miesięczny positive" = KPI.
6. **Kiedy wyłączę system?** Zdefiniuj to teraz — dużo łatwiej niż przy DD 30% kiedy jesteś emocjonalnie inwestowany.

---

## 7. Podsumowanie jednym akapitem

Twoja specyfikacja to **solidny szkielet**, który z poprawkami może stać się realnym systemem — ale **nie w kształcie 2.0 i nie bez fazy walidacji**. Najważniejsze natychmiastowe zmiany: (1) Dodaj backtesting engine i zobowiąż się do 3–6 miesięcy paper tradingu przed live, (2) Zredukuj rolę LLM do warstwy Veto + journaling, nie do generowania liczb, (3) Obniż risk per trade do 0.5% i dodaj daily loss limit, (4) Dodaj regime detection — strategia Sweep & Absorption żyje w konkretnych warunkach rynkowych, (5) Multi-timeframe alignment jako wymóg, nie sugestia. Budowanie "od razu v2.0" to klasyczny błąd perfekcjonizmu — ship MVP, mierz, iteruj. System ma **codziennie generować zysk** tylko wtedy, gdy ma udowodniony edge; bez backtestów to wishful thinking, nie quant.

*Ostatnia rada: jeżeli po przeczytaniu tego wciąż chcesz to budować — super, rób to. Ale rozważ pokazanie finalnej wersji spec'i komuś, kto ma realny live track record w systematic crypto (np. quant z Galaxy, FalconX, Wintermute — wielu ma konta na Twitterze). Druga para oczu od kogoś z blizinami po prawdziwym tradingu jest bezcenna.*
