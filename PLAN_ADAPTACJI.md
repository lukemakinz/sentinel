# SENTINEL — Plan Adaptacji Kodu
**AI Multi-Agent Crypto Futures Trading System**
_Ostatnia aktualizacja: 2026-04-23_

---

## Postęp ogólny

- [x] Etap 0 — Fundament Danych (Tydzień 1–2)
- [x] Etap 1 — Deterministyczny L1 Pre-Filter (Tydzień 2–5)
- [x] Etap 2 — 4 Agenci AI + Supervisor (Tydzień 5–8)
- [x] Etap 3 — Deterministyczna Egzekucja L3 (Tydzień 8–10)
- [x] Etap 4 — Risk Enhancements (Tydzień 10–12)
- [x] Etap 5 — Backtesting Engine (Tydzień 10–16, równolegle z Etapem 1)

---

## Natychmiastowe działania (przed Etapem 0)

- [x] Zmień `MAX_RISK_PER_TRADE = 0.02` → `0.005` w `backend/settings.py`
- [ ] Ustaw `BINANCE_TESTNET=True` w `.env` i uruchom paper trading
- [ ] Zaplanuj TimescaleDB w `docker-compose.yml` (migracja łatwiejsza na początku)

---

## Etap 0 — Fundament Danych

**Cel:** Mamy pełne dane zanim cokolwiek decydujemy. Bez zmian w logice tradingowej.

### aggTrade Ingestion

- [x] Dodać subskrypcję `{pair}@aggTrade` do `BinanceWebSocketClient._build_stream_url()`
- [x] Dodać metodę `_handle_aggtrade()` w `ingester/binance_ws.py`
- [x] Stworzyć model `AggTrade(symbol, timestamp, price, quantity, is_buyer_maker)` w `ingester/models.py`
- [x] Dodać migrację Django dla modelu `AggTrade`

### Whale Threshold

- [x] Stworzyć model `WhaleThreshold(symbol, timestamp, threshold_usd, percentile_95)` w `ingester/models.py`
- [x] Dodać Celery task `recalculate_whale_threshold()` w `ingester/tasks.py` — rolling 24h per para, aktualizacja co 1h
- [x] Dodać migrację Django dla modelu `WhaleThreshold`

### Whale/Retail CVD

- [x] Stworzyć model `WhaleCVD(symbol, timestamp, cumulative_delta)` w `ingester/models.py`
- [x] Stworzyć model `RetailCVD(symbol, timestamp, cumulative_delta)` w `ingester/models.py`
- [x] Implementować logikę podziału: `quantity × price >= WhaleThreshold` → Whale, reszta → Retail
- [x] Dodać aktualizację CVD w `_handle_aggtrade()` — obliczanie na bieżąco
- [x] Dodać migracje Django dla modeli CVD

### TimescaleDB (opcjonalne)

- [ ] Dodać serwis `timescaledb` do `docker-compose.yml`
- [ ] Skonfigurować osobne połączenie DB dla aggTrade/CVD (SQLite zostaje dla modeli Django)

### Weryfikacja Etapu 0

- [x] AggTrade stream aktywny, dane wpływają do DB
- [x] `WhaleThreshold` aktualizowany co godzinę
- [x] `WhaleCVD` i `RetailCVD` widoczne w Django admin
- [x] Testy jednostkowe dla `_handle_aggtrade()` i `recalculate_whale_threshold()`

---

## Etap 1 — Deterministyczny L1 Pre-Filter

**Cel:** 15 deterministycznych bram w 3 grupach (A/B/C). L1 produkuje `TradeContext` JSON.

### Struktura modułu `l1_filter/`

- [x] Stworzyć `backend/l1_filter/__init__.py`
- [x] Stworzyć `backend/l1_filter/gates_a.py`
- [x] Stworzyć `backend/l1_filter/gates_b.py`
- [x] Stworzyć `backend/l1_filter/gates_c.py`
- [x] Stworzyć `backend/l1_filter/scanner.py`
- [x] Stworzyć `backend/l1_filter/models.py`
- [x] Dodać `l1_filter` do `INSTALLED_APPS` w `settings.py`

### Gate A — Bias & Context (wszystkie 5 muszą przejść)

- [x] **A1** — Killzone aktywna (Londyn 07:00–10:00 UTC lub NY 13:00–16:00 UTC)
- [x] **A2** — HTF Trend zgodny (Daily EMA 50/200 bullish/bearish)
- [x] **A3** — BTC dominance / korelacja: BTC nie w sprzecznym trendzie
- [x] **A4** — Funding rate w normie (nie > +0.1% ani < -0.1%)
- [x] **A5** — ADX > 20 (regime trending, nie ranging)

### Gate B — Setup Structure (min. 3 z 5 muszą przejść)

- [x] **B1** — Liquidity sweep (poprzedni swing high/low przebity i odrzucony)
- [x] **B2** — FVG lub Order Block na właściwym poziomie
- [x] **B3** — Cena w Premium (short) lub Discount (long) zone względem range
- [x] **B4** — Klasyczny pattern (H&S, double top/bottom, wedge) — opcjonalny bonus
- [x] **B5** — Range compression / volatility squeeze (ATR < 0.5 × ATR 20)

### Gate C — Trigger Confirmation (min. 2 z 5 muszą przejść)

- [x] **C1** — ChoCH (Change of Character) na 5m lub 15m
- [x] **C2** — Momentum divergence (RSI lub MACD divergence)
- [x] **C3** — EMA 9/21 crossover na właściwym timeframe
- [x] **C4** — Volume spike > 1.5× średniej 20-świecowej
- [x] **C5** — Cena ponad/poniżej Daily VWAP

### L1Scanner i TradeContext

- [x] Implementować `L1Scanner.scan(symbol) → TradeContext | None` w `scanner.py`
- [x] Stworzyć schema `TradeContext` JSON (para, timestamp, kierunek, gates_passed, ATR, FVG_zone, swept_level, nearest_liquidity, BTC_trend, funding_rate, daily_vwap, adx_value, regime)
- [x] Stworzyć modele DB: `TradeContext`, `L1Result` w `l1_filter/models.py`
- [x] Dodać migracje Django
- [x] Refaktoryzować Celery tasks: zamiast "always-on scoring" → `scan_all_symbols.delay()` co 1m, wywołujący `L1Scanner.scan()` per para

### Weryfikacja Etapu 1

- [x] Wszystkie 15 gates mają testy jednostkowe z mockami danych
- [x] `L1Scanner.scan()` produkuje poprawny `TradeContext` JSON lub `None`
- [x] `L1Result` zapisywany do DB dla każdego skanu
- [x] Django admin wyświetla historię L1 Results
- [x] Brak regresji w istniejących analitykach (działają równolegle, ale nie sterują egzekucją)

---

## Etap 2 — 4 Agenci AI + Supervisor

**Cel:** Zastąpić `LLMNarrativeAnalyst` czterema wyspecjalizowanymi agentami z deterministycznym Supervisorem.

### Struktura modułu `l2_agents/`

- [x] Stworzyć `backend/l2_agents/__init__.py`
- [x] Stworzyć `backend/l2_agents/context_trader.py`
- [x] Stworzyć `backend/l2_agents/order_flow_quant.py`
- [x] Stworzyć `backend/l2_agents/risk_manager_agent.py`
- [x] Stworzyć `backend/l2_agents/devils_advocate.py`
- [x] Stworzyć `backend/l2_agents/supervisor.py`
- [x] Stworzyć `backend/l2_agents/orchestrator.py`
- [x] Dodać `l2_agents` do `INSTALLED_APPS`

### Agent 1 — Context Trader (`context_trader.py`)

- [x] Prompt: SMC/price action narrative, analiza L1 TradeContext
- [x] Output JSON: `{verdict, confidence, reasoning, key_levels, narrative}`
- [x] Prompt zabrania generowania liczb entry/SL/TP
- [x] Może wywoływać `LLMNarrativeAnalyst` jako tool call

### Agent 2 — Order Flow Quant (`order_flow_quant.py`)

- [x] Prompt: analiza Whale/Retail CVD, Order Book Imbalance, Open Interest, absorption
- [x] Output JSON: `{verdict, confidence, reasoning, whale_cvd_trend, retail_cvd_trend, oi_trend, absorption_detected}`
- [x] Czyta `WhaleCVD`, `RetailCVD` z DB

### Agent 3 — Risk Manager Agent (`risk_manager_agent.py`)

- [x] Prompt: ocena ryzyka — DD, korelacja portfela, news, IV, szerokość SL
- [x] Output JSON: `{verdict, confidence, reasoning, portfolio_heat, news_risk, sl_width_ok, dd_current}`
- [x] Integracja z `risk/` modułem

### Agent 4 — Devil's Advocate (`devils_advocate.py`)

- [x] Prompt: kontrariański red-teaming, historical win rate analogicznych setupów
- [x] Output JSON: `{verdict, confidence, reasoning, counter_thesis, historical_win_rate, risk_factors}`

### Supervisor (`supervisor.py`) — deterministyczna logika, nie LLM

- [x] Implementować hierarchię veto:
  - [ ] Risk Manager REJECT → cały trade REJECT (twarde veto)
  - [ ] Devil's Advocate REJECT przy confidence > 70 → zmniejsz size o 50%
  - [ ] 3+ agentów APPROVE → pełny size
  - [ ] 2 APPROVE, 1 NEUTRAL → 75% size
  - [ ] 1 APPROVE lub mniej → REJECT
- [x] Obliczać `size_multiplier` (0.0–1.0)
- [x] Produkować `L2Decision`: `{action: APPROVE|REJECT, size_multiplier, agents_summary}`

### L2Orchestrator (`orchestrator.py`)

- [x] Implementować `L2Orchestrator.run(trade_context_id) → L2Decision`
- [x] Wywoływać 4 agentów równolegle (asyncio/Celery group)
- [x] Przekazać wyniki do Supervisor
- [x] Zapisać `L2Decision` do DB
- [x] Dodać Celery task: `run_l2_analysis.delay(trade_context_id)` — wywołany tylko gdy L1 PASS

### Integracja z istniejącym kodem

- [x] `ConsensusEngine` zostaje jako monitoring (nie steruje egzekucją)
- [x] `LLMNarrativeAnalyst` przeniesiony jako tool w `context_trader.py`

### Weryfikacja Etapu 2

- [x] Każdy agent produkuje poprawny JSON schema (walidacja Pydantic)
- [x] Supervisor poprawnie implementuje wszystkie reguły veto
- [x] L2Orchestrator nie wywołuje się gdy L1 REJECT
- [x] Czas wykonania 4 × LLM call < 30s
- [x] Testy integracyjne z mock LLM responses

---

## Etap 3 — Deterministyczna Egzekucja L3

**Cel:** Refaktoryzacja `executor/` — precyzyjne obliczenia entry/SL/TP na bazie `TradeContext` + `L2Decision`.

### L3Calculator (`executor/l3_calculator.py`)

- [x] Stworzyć `executor/l3_calculator.py`
- [x] Implementować `entry_zone = FVG_mid | OB_mid` z `TradeContext`
- [x] Implementować `final_sl = min(sl_atr_based, sl_structural, sl_cap_3pct)`
- [x] Implementować TP levels: `TP1 = 1.5R (40%)`, `TP2 = 3.0R (40%)`, `TP3 = runner trailing (20%)`
- [x] Implementować minimum RR check: jeśli `TP1 < 1.2R` → REJECT
- [x] Safety assertion: `liquidation_price >= entry ± 2 × SL_distance`

### Chandelier Exit w `paper_engine.py`

- [x] Implementować trailing stop po osiągnięciu TP1: przesuń SL na breakeven
- [x] Runner (20% pozycji): `chandelier = highest_high(22) – 3 × ATR`, aktualizacja co zamknięcie 1H świecy
- [x] Time-based kill: jeśli pozycja > 8h i nie uderzyła 1R → zamknij po rynku

### Aktualizacje istniejącego kodu

- [x] Zmienić TP ratio w `paper_engine.py`: `1R → 1.5R` dla TP1, `2R → 3R` dla TP2
- [x] Integracja `L3Calculator` z `paper_engine.py` — `execute_trade(trade_context, l2_decision)`
- [x] Usunąć stare hardcoded entry/SL/TP z `paper_engine.py`

### Weryfikacja Etapu 3

- [x] `L3Calculator` ma testy jednostkowe dla edge case'ów (np. SL > 3%, TP1 < 1.2R)
- [x] Chandelier trailing stop działa poprawnie na testowych danych OHLCV
- [x] Time-based kill zamyka pozycję po 8h braku ruchu
- [x] Leverage safety check blokuje trade przy zbyt bliskiej cenie likwidacji

---

## Etap 4 — Risk Enhancements

**Cel:** Uzupełnić brakujące mechanizmy ryzyka z dokumentacji.

### Kill Switches — DD-based scaling (`risk/kill_switches.py`)

- [x] Zastąpić logikę `consecutive_losses` logiką `drawdown_based`
- [x] Implementować DD-based size multiplier:
  - [ ] 0% DD → `size_multiplier = 1.0`
  - [ ] -5% DD → `size_multiplier = 0.75`
  - [ ] -10% DD → `size_multiplier = 0.5`
  - [ ] -15% DD → `size_multiplier = 0.25`
  - [ ] -20% DD → `HALT` (zatrzymaj trading)

### Strategy Monitor (`risk/strategy_monitor.py`)

- [x] Stworzyć `risk/strategy_monitor.py`
- [x] Implementować rolling 30-trade win rate
- [x] Implementować rolling Sharpe ratio (30 trade'ów)
- [x] Auto-halt gdy `rolling_sharpe < 0` przez 20 kolejnych trade'ów
- [x] Eksponować metryki przez `dashboard_api`

### News Calendar (`risk/news_calendar.py`)

- [x] Stworzyć `risk/news_calendar.py`
- [x] Integracja z CoinGecko Events API lub ręczna lista FOMC/CPI/NFP
- [x] Blokada tradingu 2h przed i 1h po evencie makroekonomicznym
- [x] Celery task: `update_news_calendar()` co 6h

### Portfolio Heat (`risk/portfolio_heat.py`)

- [x] Stworzyć `risk/portfolio_heat.py`
- [x] Implementować korelacyjną mapę portfela (rolling 30d korelacja par)
- [x] Obliczać efektywną ekspozycję BTC-beta
- [x] Hard limit: efektywna ekspozycja BTC-beta max `2×`
- [x] Blokować nowe pozycje gdy limit przekroczony

### Tax Logging

- [x] Stworzyć model `TaxEvent(trade_id, open_price, close_price, pnl_pln, timestamp, pair)` w `executor/models.py`
- [x] Automatycznie tworzyć `TaxEvent` przy zamknięciu każdej pozycji
- [x] Eksport CSV `TaxEvent` przez `dashboard_api` (do PIT-38)

### Weryfikacja Etapu 4

- [x] DD-based scaling działa — HALT przy -20% DD
- [x] Strategy monitor zatrzymuje trading przy 20 ujemnych Sharpe trade'ów
- [x] News calendar blokuje trading przed FOMC/CPI/NFP
- [x] Portfolio heat blokuje przy BTC-beta > 2×
- [x] `TaxEvent` tworzone dla każdego zamkniętego trade'u

---

## Etap 5 — Backtesting Engine

> **WAŻNE:** Uruchom równolegle z Etapem 1. Backtesting jest blokerem dla live tradingu.

### Struktura modułu `backtest/`

- [x] Stworzyć `backend/backtest/__init__.py`
- [x] Stworzyć `backend/backtest/data_loader.py`
- [x] Stworzyć `backend/backtest/simulator.py`
- [x] Stworzyć `backend/backtest/slippage_model.py`
- [x] Stworzyć `backend/backtest/metrics.py`
- [x] Stworzyć `backend/backtest/walk_forward.py`
- [x] Stworzyć `backend/backtest/monte_carlo.py`

### Data Loader (`data_loader.py`)

- [x] Replay tick-by-tick z TimescaleDB lub SQLite
- [x] Obsługa wielu par równolegle
- [ ] Pobieranie danych historycznych Binance (min. 3 lata)

### Simulator (`simulator.py`)

- [x] Symulacja pełnego pipeline: L1 → L2 (mock) → L3 na danych historycznych
- [x] Obsługa pozycji (entry, TP1, TP2, runner, SL, time-kill)
- [x] Śledzenie equity curve

### Slippage Model (`slippage_model.py`)

- [x] Market orders: 0.1% slippage
- [x] Limit orders: 0.02% maker fee
- [x] Taker orders: 0.05% taker fee

### Metrics (`metrics.py`)

- [x] Sharpe ratio (annualized)
- [x] Calmar ratio
- [x] Max Drawdown
- [x] Win rate
- [x] Expected Value (EV) per trade
- [x] Trade count

### Walk-Forward (`walk_forward.py`)

- [x] Rolling window re-optimization
- [x] Out-of-sample validation

### Monte Carlo (`monte_carlo.py`)

- [x] 10,000 permutacji sekwencji trade'ów
- [x] Worst-case 5% scenario
- [x] Ruin probability przy różnych `MAX_RISK_PER_TRADE`

### Weryfikacja Etapu 5 (Minimum przed live)

- [ ] Sharpe > 1.5 po kosztach (3 lata danych)
- [ ] MaxDD < 20%
- [ ] Trade count > 300
- [ ] Calmar > 0.5
- [ ] Monte Carlo: ruin probability < 1% przy `MAX_RISK_PER_TRADE = 0.005`
- [ ] Walk-forward pokazuje stabilne wyniki (brak overfittingu)

---

## Checklist Gotowości do Live Tradingu

Każdy punkt musi być odhaczony przed pierwszym real-money trade'em:

- [x] `MAX_RISK_PER_TRADE = 0.005` ustawiony
- [x] AggTrade ingestion aktywny, Whale/Retail CVD zbierane
- [x] L1 Pre-Filter (min. A1–A5 + B1–B3) zaimplementowany i przetestowany
- [x] ADX regime detection aktywny
- [x] 4 agenci AI z Supervisorem działają, produkują structured JSON
- [x] Chandelier trailing stop + time-based kill zaimplementowane
- [ ] Backtesting: Sharpe > 1.5, MaxDD < 20%, 300+ trade'ów na 3 latach
- [ ] Paper trading ≥ 3 miesiące, rozbieżność < 20% vs backtest
- [x] Daily HALT -3%, weekly HALT -7% aktywne
- [x] DD-based size scaling aktywny
- [x] News calendar integration aktywna
- [x] Strategy degradation monitor aktywny
- [x] Tax logging aktywny
- [ ] Binance Testnet przetestowany — znana faktyczna latencja

---

## Pliki — Mapa Zmian

### Bez zmian (lub kosmetyczne)
- `ingester/binance_rest.py`
- `analysts/momentum.py`, `sentiment.py`, `structure.py`, `volume_flow.py`, `cross_asset.py`
- `consensus/engine.py` (zostaje jako monitoring)
- `risk/models.py`, `risk/admin.py`
- `dashboard_api/` (rozbudowa API, nie przepisanie)
- `frontend/` (nie ruszamy do etapu 3+)

### Modyfikowane
- `ingester/binance_ws.py` — dodać `_handle_aggtrade()`
- `ingester/models.py` — dodać `AggTrade`, `WhaleCVD`, `RetailCVD`, `WhaleThreshold`
- `ingester/tasks.py` — dodać `recalculate_whale_threshold()`
- `executor/paper_engine.py` — chandelier exit, time-kill, integracja L3Calculator
- `risk/kill_switches.py` — DD-based scaling
- `docker-compose.yml` — TimescaleDB (opcjonalnie)
- `backend/settings.py` — `MAX_RISK_PER_TRADE = 0.005`

### Nowe moduły
- `l1_filter/` — cały moduł (Etap 1)
- `l2_agents/` — cały moduł (Etap 2)
- `executor/l3_calculator.py` (Etap 3)
- `risk/strategy_monitor.py` (Etap 4)
- `risk/news_calendar.py` (Etap 4)
- `risk/portfolio_heat.py` (Etap 4)
- `backtest/` — cały moduł (Etap 5)
