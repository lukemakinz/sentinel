# SENTINEL — Plan Poprawek
_Na podstawie code review: 2026-04-25_
_Aktualizacja 2026-04-25: dodano Signal Evaluator, anti-revenge rules, doprecyzowania_

---

## Priorytet 0 — Warunek wstępny (BLOKUJE live trading)

- [ ] **Backtest 3 lata danych** — Sharpe > 1.5, MaxDD < 20%, 300+ trade'ów
  - Bez tego WSZYSTKO INNE to wishful thinking
  - Potrzeba: pobranie historycznych klines z Binance (3 lata)
  - Narzędzie: `/backtest` → `run_backtest` task już gotowy
  - Decyzja po backtest: jeśli Sharpe < 1 → redesign gates, nie kontynuuj
  - **Doprecyzowanie założeń backtest:**
    - Walk-forward: rolling 6m train / 1m test (nie single split — overfitting risk)
    - Koszty: taker fee 0.04%, maker 0.02%, funding accrual co 8h dla pozycji trzymanych
    - Slippage: market orders 0.05% majors / 0.15% alty; limit fills tylko jeśli cena dotknęła + buffer 0.01%
    - Out-of-sample: minimum ostatnie 3m bez touchu w optymalizacji
    - Monte Carlo: 10k permutacji, ruin probability < 1% przy MAX_RISK_PER_TRADE = 0.005

---

## Priorytet 1 — Signal Evaluator (NOWE — fundament uczenia systemu)

> **Bez tego system jest ślepy.** Każda inna poprawka jest guesswork dopóki nie wiemy, co realnie działa.

### 1.0.1 Model `Signal` — pełen lifecycle

- [x] Stworzyć model `Signal` w `l1_filter/models.py` (lub osobny `evaluator/`):

```python
class Signal(models.Model):
    # Identity
    id, symbol, direction (LONG/SHORT), strategy (S1/S2/S3)
    created_at, expires_at  # expires_at = created_at + max_lifetime (np. 24h)

    # Setup
    entry_price, stop_loss, take_profit_1, take_profit_2, runner_active
    rr_planned  # planowane (TP1-entry)/(entry-SL)

    # L1 attribution
    gates_a_passed (JSON list), gates_b_passed (JSON), gates_c_passed (JSON)
    regime  # trending|ranging|squeeze
    session  # asian|london|ny|off
    htf_bias  # bullish|bearish|neutral

    # L2 attribution
    l2_decision  # APPROVE|REJECT|SHADOW (gdy L1 PASS, ale L2 nie ruszony)
    l2_size_multiplier  # 0.0-1.0
    agent_verdicts (JSON: {context, order_flow, risk, devils_advocate})
    agent_confidences (JSON)

    # Execution
    executed (bool)  # czy realnie otwarty na koncie
    shadow (bool)    # signal śledzony, ale nieotwarty (dla statystyk)
    position_size_usd

    # Lifecycle state
    state  # GENERATED → APPROVED/REJECTED → MONITORING → CLOSED
    closed_at, exit_price, exit_reason
    # exit_reason: SL | TP1 | TP2 | RUNNER_TRAIL | TIME_KILL | MANUAL | EXPIRED

    # Outcome
    outcome  # WIN | LOSS | BREAKEVEN | PARTIAL_WIN | EXPIRED
    pnl_r          # PnL w R (multiples of risk)
    pnl_usd
    max_favorable_excursion_r   # MFE — najdalej w stronę profit
    max_adverse_excursion_r     # MAE — najdalej w stronę loss
    time_in_trade_minutes
```

### 1.0.2 Shadow signal tracking (KRYTYCZNE)

- [x] **Każdy L1 PASS produkuje Signal**, niezależnie od L2 verdict
- [x] L2 REJECT → Signal.shadow=True, ale dalej tracking SL/TP outcome
- [x] Cel: po 200+ shadow signals porównaj win rate "L2 APPROVE" vs "L2 REJECT"
- [ ] Jeśli REJECT win rate > APPROVE win rate → L2 niszczy wartość, redesign
- [ ] Eksponować w dashboardzie: real PnL vs phantom PnL (gdyby brać wszystko)

### 1.0.3 Atrybucja per warstwa (statystyki)

- [x] Endpoint `/api/evaluator/stats` z breakdown:
  - **Per strategy** (S1/S2/S3): win_rate, avg_R, expectancy, count
  - **Per session** (asian/london/ny): jw.
  - **Per regime** (trending/ranging/squeeze)
  - **Per direction** (long/short)
  - **Per gate** (np. trade'y gdzie A4 PASS vs A4 borderline)
  - **Per symbol**
  - **Per time-of-day** (binowane co godzinę)
  - **Per agent confidence bucket** (50-60, 60-70, 70-80, 80-100): faktyczny win rate vs declared confidence
- [x] **Calibration plot per agent**: jeśli agent mówi "APPROVE 80" a faktyczny win rate to 45% → agent overconfident → deweight
- [ ] **Brier score per agent** — miara kalibracji predykcji probabilistycznych

### 1.0.4 MFE/MAE tracking — optymalizacja TP/SL

- [x] Co świecę 1m aktualizuj `max_favorable_excursion_r` i `max_adverse_excursion_r`
- [ ] Po 100+ trade'ach analiza:
  - Jeśli średnie MFE = 4R, ale TP1=1.5R → potencjalnie zostawiamy kasę na stole
  - Jeśli średnie MAE losers = -0.3R → SL za szeroki, można zacieśnić
  - Jeśli średnie MAE winners = -0.8R → SL OK, nie zacieśniaj
- [ ] To jest fundament tuningu TP/SL, nie heurystyki

### 1.0.5 Learning loop (długoterminowo)

- [ ] Po 500 sygnałach: rolling weights per gate
  - Gates z najwyższym contribution → keep
  - Gates z near-zero contribution → kandydaci do usunięcia
- [ ] Per-agent weighting w supervisor based on rolling Brier score
- [ ] **Nie autoML — manualne review co miesiąc**, żeby uniknąć overfittingu na noise

---

## Priorytet 1.1 — Anti-Revenge & SL Discipline (NOWE — krytyczne dla automatyzacji)

> **Stop loss w pełnej automatyzacji to święte. Żadnego "dajmy mu jeszcze trochę miejsca".**

### 1.1.1 SL nigdy nie jest przesuwany dalej od entry

- [x] **Twarda reguła w `paper_engine.py` i przyszłym live executor:**
  - Dozwolone: SL → BE (po TP1), SL trailing CLOSER do entry (tightening po nowym swing HL/LH)
  - Zabronione: SL przesunięty w stronę dalszą od entry — assert w kodzie, log warning
- [x] Jeśli cena dotknęła SL → close natychmiast, koniec dyskusji
- [x] **Nie ma "kontynuacji przez przesunięcie SL"** — to jest no-go w automatyce

### 1.1.2 Re-entry logic (osobny trade, nie kontynuacja)

- [x] Po SL hit dozwolony NOWY trade na ten sam symbol jeśli:
  - Pełen L1 + L2 cycle PASS na czysto (nie skrót)
  - Cooldown ≥ 30 min od SL hit
  - Max 1 re-entry per setup (twardy licznik)
  - Statystycznie: pierwszy trade = LOSS, drugi = osobny WIN/LOSS (nie "uratowanie")
- [ ] Pole `Signal.is_reentry_of` (FK do poprzedniego signal_id) dla atrybucji

### 1.1.3 Eskalujące blokady po stratach

- [x] **Per symbol:**
  - 2 SL z rzędu na tym samym symbolu w 24h → blokada symbolu na 24h
  - 3 SL z rzędu (rzadkie) → blokada symbolu na 7 dni + alert do review
- [x] **Per portfolio:**
  - 3 SL z rzędu w portfelu (różne symbole) → daily soft halt (no new entries, otwarte zostają)
  - Reset licznika po pierwszym WIN
- [x] **Per session:**
  - Loss > 2R w jednej sesji (London/NY) → blokada do końca sesji

### 1.1.4 TP1 management — doprecyzowanie

- [x] **Obecne (`paper_engine.py`):** po TP1 SL → BE (statyczny do TP2)
- [ ] **Lepsze:** po TP1 SL → BE + fees, potem **trailing pod kolejne swing low (LONG) / high (SHORT)**
  - Statyczny BE marnuje runner gdy cena idzie dalej dynamicznie
  - Adaptacyjny trailing łapie więcej R z runnera
- [ ] Reguła: po TP1, SL = max(BE+fees, last_swing_low - 0.1×ATR) dla LONG

### 1.1.5 Rate limiting na decyzjach

- [x] Max 1 trade per symbol per 4h
- [ ] Max 5 trade'ów per portfolio per 24h (anti-overtrading)
- [ ] Te limity są oddzielne od MAX_OPEN_POSITIONS (concurrent) — to są flow limits

---

## Priorytet 2 — Natychmiastowe (wysokie ROI, mała praca)

### 2.1 Dead code — wytnij

- [ ] Usuń `analysts/` folder (momentum, sentiment, structure, volume_flow, cross_asset, llm_narrative)
  - Nie wpływa na egzekucję, tylko noise w logach i zasobach
  - Wyekstrahuj `compute_rsi`, `detect_fvg`, `detect_swing` → do `l1_filter/utils.py` (już tam są)
- [ ] Usuń `ConsensusEngine` z decision path (zostaw modele dla historii)
- [ ] Usuń `B4 Classical patterns` (double top/bottom) — redundantny wobec B1+B2
- [ ] Zastąp `C3 EMA9/21 crossover` → **Delta Candle** (taker_buy_volume − taker_sell_volume) — unikalny signal
- [ ] Wytnij `hardcoded _EVENTS_2026` z news_calendar.py
  - **UWAGA do API:** Forex Factory nie ma oficjalnego API (tylko scraping XML, fragile)
  - Rekomendacja: Trading Economics API (płatne, stabilne) **lub** CoinMarketCal (darmowe, crypto-specific: token unlocks, halving, mainnet launches)
  - Fallback: ręczna lista YAML aktualizowana co tydzień (mniej elastyczne niż API, ale lepsze niż hardcoded 2026)

### 2.2 WhaleCVD — fix (volume-weighted, nie count-based)

- [ ] **Bug krytyczny:** cumulative_delta = +1/-1 zamiast ±quantity (USD value)
  - Obecne: każdy trade liczy się jednakowo niezależnie od rozmiaru
  - Poprawione: delta = +usd_value (buy) lub -usd_value (sell)
  - To zabija skuteczność całego S2 strategy

### 2.3 Slippage w paper engine

- [ ] Paper engine zamyka po `close price 1m candle` — zero slippage
  - Market order: 0.05-0.15% slippage na majors
  - Dodać do `_close_position`: `exit_price *= (1 + SLIPPAGE)` dla LONG, `(1 - SLIPPAGE)` dla SHORT
  - Paper performance jest zawyżony bez tego

---

## Priorytet 3 — Architektura gates (wysoki wpływ na alpha)

### 3.1 FVG — właściwa implementacja

- [x] **Obecne:** `high[i] < low[i+2]` — to jest zwykły gap, nie FVG
- [x] **Wymagane:**
  - Displacement candle: ciało świecy > 1.5×ATR (impulsive move)
  - Volume spike na displacement (>1.5× avg volume)
  - Mitigation tracking: FVG "filled" gdy cena wróciła do 50%+ głębokości
  - Dodać `FVGZone(symbol, top, bottom, direction, filled, created_at)`
  - Entry tylko w niefilled FVG z potwierdzeniem reaction (reversal candle)
- [x] **Uwaga: kolizja logiczna z B5 (squeeze).** Squeeze = ATR contraction, displacement = ATR expansion.
  - Rozwiązanie: B5 (squeeze) i poprawne FVG działają w **różnych strategiach**:
    - S1 (SMC Sweep) → wymaga FVG z displacement (B2 strict)
    - S3 (Classic TA) → korzysta z B5 squeeze przed breakout
  - Strategia per gate-set, nie wszystko razem

### 3.2 Liquidity Sweep — strukturalne poziomy (NAJWIĘKSZY ROI)

- [ ] Nowy moduł: `l1_filter/liquidity.py`
  - Persistuj per symbol: PDH/PDL, PWH/PWL, Asian Range H/L, equal highs/lows
  - Model `LiquidityLevel(symbol, level_type, price, timestamp, swept)`
  - B1 sweep = wick przebija KONKRETNY liquidity level, zamknięcie po przeciwnej stronie + volume spike
  - Nie: 5-candle lookback (to hammer candle, nie sweep)
- [ ] **Equal highs/lows detection:** 2+ swingi w odstępie ≤ 0.1% ceny (resting liquidity)
- [ ] **Inducement detection:** mały sweep (np. 5m swing) PRZED prawdziwym sweepem (1H/4H swing)
  - Filtruj false-positive sweeps — najczęstszy "false break" w SMC

### 3.3 TP do najbliższego liquidity pool

- [ ] L3Calculator TP target = `nearest_unswept_liquidity_level` powyżej entry (LONG)
  - Mechaniczne 1.5R/3R w próżni → TP do następnego real resistance
  - Jeśli brak liquidity level w rozsądnym zasięgu → reject trade
  - To może być single największy improvement alpha
- [ ] **Hierarchia targetów (po kolei):**
  - TP1: najbliższy intraday liquidity (Asian high/low, recent swing)
  - TP2: PDH/PDL lub HTF swing
  - Runner: PWH/PWL lub większa struktura
- [ ] **Minimum RR check** zostaje (TP1 ≥ 1.2R), ale TP1 LEVEL = liquidity, nie 1.5R w próżni

### 3.4 CHoCH vs BOS — właściwe rozróżnienie + hierarchia

- [x] **Obecne:** fallback `price > last_swing_high` = BOS, nie CHoCH
- [x] **CHoCH** = pierwszy LH po serii HH (zmiana charakteru, reversal)
- [x] **BOS** = nowy HH w trendzie (kontynuacja)
- [ ] **Hierarchia (KRYTYCZNE):**
  - HTF (1H/4H) BOS musi być POTWIERDZONY w kierunku trade'a → trade-along-trend
  - LTF (5m/15m) CHoCH staje się trigger entry'ego DOPIERO po HTF BOS
  - Standalone LTF CHoCH bez HTF context = noise, nie signal
- [ ] C1 gate: rozróżnij i użyj w odpowiedniej kombinacji per strategia
  - S1 (SMC Sweep): wymaga HTF BOS + LTF CHoCH after sweep
  - S2 (Order Flow): wymaga HTF BOS + delta divergence (nie potrzebuje CHoCH)
  - S3 (Classic): może działać bez CHoCH, na samej strukturze EMA + volume

### 3.5 Premium/Discount — prawdziwy SMC

- [x] **Obecne:** percentyl 10 ostatnich świec (local extreme, nie P/D)
- [x] **Prawdziwe SMC P/D:** 50% retracement HTF swinga
  - Swing endpoints: ostatni HH i ostatni HL na 4H (bullish) lub LH/LL (bearish)
  - Algorytm: `detect_swing_points(candles_4h, lookback=10)` → najnowszy major swing
  - OTE zone: 62-79% retracement (Golden Pocket Fib)
  - Discount = price < 50% of HTF range → long bias
  - Premium = price > 50% of HTF range → short bias
- [ ] Wymaga: HTF swing detection na min. 4H, fallback 1D jeśli za mało 4H struktury

### 3.6 HTF Trend — struktura, nie EMA

- [x] **Obecne:** EMA50/200 crossover (1995 TA, opóźniony)
- [x] **Lepsze:** Higher Highs / Higher Lows na 1D + position vs PDA
  - Bullish structure: **minimum 3 swing pairs (HH+HL)** w ostatnich 30 candles 1D
  - Bearish structure: **minimum 3 swing pairs (LH+LL)** w ostatnich 30 candles 1D
  - Mniej niż 3 → "neutral/transition", brak HTF bias → A2 FAIL (nie wchodzimy)
  - A2 gate: structural bias, nie EMA bias
- [ ] EMA może zostać jako **secondary confirmation** (zgodność EMA i struktury → bonus confidence), nie primary

### 3.7 ADX → Choppiness Index

- [ ] **Obecne:** ADX > 20 (false positives w choppy markets)
- [ ] **Lepsze:** `CI = 100 × log10(sum(ATR[1..n]) / (max_high - min_low)) / log10(n)`
  - CI < 38.2 = strong trend
  - CI > 61.8 = choppy/ranging
  - Lub: `regime_ratio = ATR(14) / ATR(50)` — szybszy proxy
- [ ] Output regime → routing na różne strategie:
  - Trending → S1/S2 active, S3 muted
  - Ranging → S3 active z mean-reversion variant, S1/S2 muted
  - Squeeze → wszystkie muted, czekamy na breakout

---

## Priorytet 4 — Agent diversity (eliminacja pseudo-consensusu)

### 4.1 Orthogonal inputs per agent

- [ ] **Obecne:** 4 agenci widzą TEN SAM TradeContext → skorelowane verdicts
- [ ] **Nowe:** każdy agent ma własny narrowed-down input:

```python
# Agent 1: HTF Bias / Context
context = {
    '1d_structure': htf_bias,     # HH/HL vs LH/LL
    'weekly_structure': ...,
    'btc_dominance': ...,
    'dxy_trend': ...,
    'major_levels': [PWH, PWL, monthly_open],
}
# Może: APPROVE/REJECT czy trade jest "with HTF flow"

# Agent 2: Order Flow
context = {
    'whale_cvd': cvd_data,        # volume-weighted
    'oi_trend': oi_data,
    'funding_rate': funding,
    'liquidation_clusters': liq_clusters,
    'order_book_imbalance': ...,  # bid/ask top 10
    # NIE widzi cen / candles / structure
}

# Agent 3: Execution / Timing
context = {
    '5m_structure': ...,
    '15m_structure': ...,
    'entry_zone': fvg_zone,
    'nearest_liquidity': liq_levels,
    'session': killzone_state,     # AMD phase
    'time_to_session_end': minutes,
    # NIE widzi macro/funding/portfolio
}

# Agent 4: Risk / Devil's Advocate (META-agent)
context = {
    'consolidated_thesis': summary_z_agent_1_2_3,  # widzi co inni twierdzą
    'portfolio_dd': current_dd,
    'correlation_heat': btc_beta,
    'macro_calendar': next_event,
    'historical_winrate_similar_setups': lookup,   # z Signal Evaluator
    'recent_losses_streak': ...,
}
# Rola: red-team z full kontekstem; może wezwać hard veto
```

- [ ] **Devil's Advocate / Risk = jedna funkcja meta-agenta** (zamiast dwóch nakładających się ról)
  - Widzi consolidated thesis trójki (agent 1+2+3)
  - Może hard-veto (Risk side) lub soft-veto (DA — penalizuje size)
  - Korzysta z Signal Evaluator: "podobne setupy w przeszłości miały win rate X%"

### 4.2 Calibration loop (sprzężenie z 1.0.5)

- [ ] Co tydzień: per agent oblicz Brier score na ostatnich 100 sygnałach
- [ ] Supervisor weight per agent = 1 / (1 + brier_score) — agenci skalibrowani mają większą wagę
- [ ] Jeśli agent ma brier > 0.4 (gorzej niż random) przez 3 tygodnie → wymusza review prompta

---

## Priorytet 5 — Nowe sources of edge

### 5.1 Open Interest Analytics

- [ ] `/fapi/v1/openInterestHist` — pull co 5m (już jest periodic task, rozbuduj)
- [ ] Gate nowy (D-gates): OI direction filter
  - OI rośnie + cena rośnie = świeże longi (zdrowe, ok LONG)
  - OI spada + cena rośnie = short covering (słabe, avoid LONG)
  - OI rośnie + cena spada = świeże shorty (zdrowe, ok SHORT)
  - Funding +0.15% + OI rośnie = crowded longs = contrarian SHORT signal

### 5.2 Liquidation Clusters jako poziomy

- [ ] `forceOrder` już streamowany, NIGDZIE nieużywany w gates
- [ ] Agreguj 1h windows: `LiquidationCluster(symbol, hour, long_liq_usd, short_liq_usd, price_level)`
- [ ] Użyj w B1 sweep: prawdziwy sweep = przebicie liquidation cluster (tu czekają stop losses)
- [ ] TP target: najbliższy liquidation cluster powyżej (LONG) — często price magnetyczny

### 5.3 Order Book Imbalance

- [ ] Binance: `{symbol}@depth20@100ms` WebSocket
- [ ] `imbalance = sum(bid_qty[0:10]) / sum(ask_qty[0:10])`
  - > 1.5 = bid-heavy = buying pressure
  - < 0.67 = ask-heavy = selling pressure
- [ ] Dodać jako feature do Order Flow agent (nie jako hard gate — zbyt szybki)

### 5.4 AMD Power of 3 Framework (CRYPTO-specific times)

- [ ] **Asian Range:** 22:00-06:00 UTC (Tokyo + early HK; nie 20:00-00:00 jak w pierwszej wersji)
  - Define high/low z tego okna jako kluczowe poziomy płynności na resztę dnia
- [ ] **London Manipulation:** 07:00-10:00 UTC (oczekuj sweep Asian Range, najczęściej fake move)
  - W tym oknie wysokie prawdopodobieństwo false breakouts — tu szukamy SWEEP, nie breakout
- [ ] **NY Distribution:** 13:00-17:00 UTC (true move, najczęściej kontynuacja kierunku po London sweep)
  - Tu są największe trade'y dnia historycznie
- [ ] Killzony jako stany maszyny stanowej, nie binary on/off
- [ ] **W L1 dodaj A6 (nowy gate):** trade musi być w "active phase" z odpowiednim AMD context

### 5.5 Funding Rate — contrarian signal

- [ ] **Obecne:** funding > ±0.1% → block (binary)
- [ ] **Lepsze:** funding jako directional signal
  - Funding +0.15% = overcrowded longs = PREFER SHORT setupy (bonus confidence)
  - Funding -0.15% = overcrowded shorts = PREFER LONG setupy (bonus confidence)
  - Zamiast blokować, zmień size_multiplier per direction
- [ ] **Skrajny funding (±0.25%+) zostaje jako block** — nieprzewidywalny squeeze risk

---

## Priorytet 6 — Parametry i execution

### 6.1 SL cap — dynamiczny per strategia + MIN SL

- [ ] **Obecne:** hard cap 3% (za szeroki dla intraday)
- [ ] **Nowe:** per-strategia + adaptive
  - **MIN SL** (nigdy ciaśniej): max(0.3%, 0.5×ATR) — chroni przed noise stops
  - **MAX SL per strategia:**
    - S1 (SMC Sweep, scalp): cap 1.0% lub 1.5×ATR (whichever smaller)
    - S2 (Order Flow, intraday swing): cap 1.5% lub 2×ATR
    - S3 (Classic TA, swing): cap 2.5% lub 2.5×ATR
  - **Adaptive:**
    - ATR percentile w 80+ (volatile) → cap obniżyć o 30%
    - ATR percentile w 30- (squeeze) → użyj absolutny cap, nie ATR (bo ATR za niski)
- [ ] Formuła final: `SL = max(MIN_SL, min(structural_sl, ATR_based_sl, MAX_SL_strategia))`

### 6.2 Entry point — OTE zamiast 25%

- [ ] **Obecne:** `entry = fvg_bottom + 0.25 × (fvg_top - fvg_bottom)` — arbitralne
- [ ] **Lepsze:** dwa warianty per strategia:
  - **Aggressive (S1):** entry = mid-FVG (50%)
  - **Conservative (S2/S3):** entry = OTE zone (62-79% depth)
- [ ] Limit orders — fill tylko jeśli cena dotknie + buffer; jeśli nie dotknie w 4h, signal expires

### 6.3 Same-day force close

- [ ] **Hard close:** wszystkie pozycje o 22:00 UTC (przed Asian session, po wszystkich newsach US)
- [ ] **Soft cutoff:** brak nowych entry po 18:00 UTC (mało czasu na full play)
- [ ] **Kolizja z FOMC 19:00 UTC:** news_calendar już blokuje 2h przed/1h po — soft cutoff 18:00 UTC pokrywa case
- [ ] Wyjątek: jeśli runner (TP3) jest w profitcie > 2R i trail stop jest ciasno → opcja override (max 24h trzymania)

### 6.4 Live execution

- [ ] Binance Futures REST: order placement (POST /fapi/v1/order), partial fills handling
- [ ] OCO simulation (Binance Futures nie ma natywnego OCO — trzeba własna logika SL+TP jako 2 osobne reduce-only orders)
- [ ] Reconciliation z exchange state co 60s (porównaj DB vs realne pozycje)
- [ ] Retry/backoff przy API errors (rate limits 1200/min, mniejsza ostrożność dla ordering)
- [ ] WebSocket user data stream (ORDER_TRADE_UPDATE) dla real-time fills
- [ ] ~2-3 tygodnie pracy, MUSI być przed live capital

---

## Co usunąć (dead code, refactor)

| Co | Akcja | Powód |
|----|-------|-------|
| `analysts/` folder | Usuń lub archiwizuj | Dead code, nie wpływa na egzekucję |
| `ConsensusEngine` | Wytnij z pipeline | Pseudo-sygnały bez real edge |
| `B4` Classical patterns | Usuń gate | Redundant wobec B1+B2 |
| `C3` EMA crossover | Zastąp Delta Candle | Duplicate info z A2 |
| `C5` VWAP | Rozważ usunięcie | Duplicate info z A2+B3 |
| `sentiment.py` | Usuń | Placeholder bez danych |
| `_EVENTS_2026` hardcoded | API lub usunąć | Katastrofa na surprise event |

---

## Kolejność realizacji (zaktualizowana)

```
Tydzień 1: Signal Evaluator + Anti-revenge rules + dead code cleanup
           (fundament — bez tego nie wiemy co działa, a anti-revenge zabezpiecza
           przed blowupem przy każdej kolejnej zmianie)

Tydzień 2: WhaleCVD volume-weighted fix + slippage w paper engine
           (krytyczne bugi które fałszują wyniki)

Tydzień 3: Liquidity tracker (PDH/PDL/PWH/PWL/Asian Range/equal highs)
           + TP do liquidity pool (single largest alpha improvement)

Tydzień 4: FVG displacement + CHoCH/BOS hierarchia + P/D na HTF swing

Tydzień 5: Backtest 3 lata na nowej logice — DECYZJA GO/NO-GO
           (po wszystkich kluczowych poprawkach, mierzymy realny edge)

Miesiąc 2: OI analytics + liquidation clusters + agent diversity refactor
           + calibration loop sprzężony z Signal Evaluator

Miesiąc 3: AMD Power of 3 framework + live execution + reconciliation

Miesiąc 4: Paper trading minimum 3m z tracking dywergencji vs backtest;
           dopiero po tym live capital (start z 5-10% planowanego sizingu)
```

---

## Definicje "DONE" per priorytet

- **P0 (Backtest):** Sharpe > 1.5, MaxDD < 20%, 300+ trades, walk-forward stable, MC ruin prob < 1%
- **P1 (Signal Evaluator):** 200+ sygnałów w DB, dashboard działa, shadow tracking aktywny, kalibracja per agent obliczana
- **P1.1 (Anti-revenge):** assert w kodzie blokuje SL widening, eskalacja losses działa, re-entry logic z licznikiem
- **P2 (Cleanup):** brak dead code, nowa struktura imports clean, news API podłączony LUB ręczna lista YAML
- **P3 (Gates):** wszystkie nowe gates mają unit testy + integration test na sample setupach historycznych
- **P4 (Agents):** każdy agent ma orthogonal input, calibration plot per agent generowany co tydzień
- **P5 (Edge):** OI/liquidations/depth feed używane w gates, AMD framework jako routing
- **P6 (Execution):** live executor przeszedł testnet 30 dni, zero rozbieżności z DB

---

## Priorytet 7 — Machine Learning na bazie Signal Evaluator (FUTURE — po P0-P6)

> **Wymagania wstępne:** Signal Evaluator z 500+ sygnałami, backtest Sharpe > 1.5, stabilna kalibracja agentów (P4.2), paper trading min. 3 miesiące. **Bez tego ML tylko ukryje brak edge'u pod black-boxem.**

### 7.0 Filozofia — dlaczego NIE pełen Reinforcement Learning

- [ ] **NIE wdrażamy DQN/PPO/A3C jako primary decision maker.** Powody:
  - Sample size: ~300 trade'ów/rok vs RL needs 100k+ episodes
  - Non-stationarity: crypto regime shift co 3-6 miesięcy
  - Reward hacking: każda funkcja reward jest exploitable
  - Sim-to-real gap: RL trained on backtest fills crashuje na live
  - Black box: niemożliwe do audytu / wytłumaczenia / debugowania po blowupie
  - Catastrophic interference: jeden weekend flash crash niszczy 6-miesięczny model
- [ ] **Filozofia:** ML siedzi NA WIERZCHU deterministycznego stack'a (L1/L2/L3), nie zastępuje go
  - Determinizm zostaje dla auditability, ML dodaje calibration & sizing nuances

### 7.1 Calibration loop (już zdefiniowane w P1.0.5 i P4.2 — to ETAP 0 ML)

- [x] Brier score per agent (P4.2)
- [x] Bayesian weight update w supervisorze
- [x] Per-agent confidence calibration plot
- To jest "RL lite" — online learning bez pathologii, działa od 100 sygnałów

### 7.2 ETAP 1 — Supervised meta-classifier (uruchomić przy 500+ sygnałach)

- [ ] **Model:** LightGBM lub XGBoost (gradient boosting)
  - **Powód wyboru:** interpretable (`feature_importances_`), robust na małych danych, brak RL pathologies
- [ ] **Features (input):**
  - Gates state: `[a1..a5, b1..b5, c1..c5]` jako binary vector (15 bitów)
  - Regime: one-hot `{trending, ranging, squeeze}`
  - Session: one-hot `{asian, london_kz, ny_am, ny_pm, off}`
  - HTF context: `htf_bias`, `htf_struct_strength` (z liczby HH/HL)
  - Agent verdicts + confidences: 4 × (verdict_one_hot + confidence_float)
  - Macro: `funding_rate`, `oi_change_pct`, `btc_correlation_30d`, `dxy_change_pct`
  - Calendar: `time_of_day`, `day_of_week`, `hours_to_next_news`
  - Portfolio state: `current_dd_pct`, `recent_trades_pnl_avg`, `correlation_heat`
  - Price: `atr_percentile`, `volume_percentile`, `spread_pct`
- [ ] **Target:** binary `outcome ∈ {WIN=1, LOSS=0}` (BREAKEVEN i PARTIAL_WIN klasyfikowane per pnl_r ≥ 0)
- [ ] **Walk-forward training:** train na miesiącu N, test na N+1, retrain co tydzień
- [ ] **Output:** `P(win | features)` ∈ [0, 1]
- [ ] **Integracja w pipeline:**
  - **Filter:** `P(win) < 0.45` → REJECT mimo APPROVE od agentów (defensywny)
  - **Size scaler:** `size_multiplier *= (P(win) - 0.5) × 2` (clipped do [0, 1.5])
  - **Logged jako separate field** w `Signal.meta_classifier_score` dla atrybucji
- [ ] **Walidacja:**
  - AUC-ROC > 0.55 na out-of-sample (powyżej random)
  - Brier score < 0.24 (lepiej niż naiwne)
  - Calibration plot: predicted vs actual win rate w binach
  - Feature importances stabilne tydzień-do-tygodnia (jeśli tańczą = overfitting)
- [ ] **Failsafe:**
  - Auto-disable jeśli rolling 50-trade win rate filtrowanych signali < unfiltered win rate
  - Manualne review co miesiąc, czy model się nie psuje

### 7.3 ETAP 2 — Thompson Sampling dla strategy/gate-combo selection (12+ miesięcy)

- [ ] **Konfiguracja jako contextual bandit** (nie pełny MDP):
  - **Arms:** kombinacje `(strategia × regime × session)`
    - Np. `(S1, trending, london_kz)`, `(S2, ranging, ny_am)`, ...
    - ~3 strategie × 3 regimes × 4 sessions = 36 arms
  - **Posterior:** Beta(α, β) per arm, gdzie α = wins+1, β = losses+1
  - **Sampling:** thompson — sample win rate z posterior każdego arm, wybierz arm z najwyższym sample
- [ ] **Reward:** realized R per trade (clipped do [-1, +5] żeby outliers nie dominowały)
- [ ] **Update:** po każdym closed trade, posterior arm[k].update(reward)
- [ ] **Dlaczego nie pełny RL:**
  - Brak state-transitions → brak credit assignment problem
  - Brak reward hacking (reward jest realized, naturalnie ograniczony)
  - Sample-efficient (działa od 30 trade'ów per arm)
  - Tłumaczalny: "wybrałem S1 bo posterior win rate 0.62 vs S2 0.51"
- [ ] **Output:** zamiast egzekutować KAŻDY APPROVE od supervisora, system samplujе który arm gra w obecnym regime
- [ ] **Cold start:** pierwsze 30 trade'ów per arm = pure exploration (random sampling z prior)

### 7.4 ETAP 3 — Lightweight policy gradient (24+ miesięcy, OPCJONALNE)

> **Tylko jeśli ETAP 1+2 udowodniły wartość, mamy 2000+ trade'ów, i Sharpe stable.**

- [ ] **Action space MINIMALNA:**
  - `size_multiplier` ∈ [0, 1.5] (continuous)
  - `entry_timing_buffer` ∈ [0, 30] minut (delay limit order placement)
  - **NIE entry/SL/TP** — te zostają deterministic (auditability)
- [ ] **Algorithm:** PPO z małymi step sizes (lr=1e-5), KL constraint
- [ ] **NIE deep RL** — płytki network (2 layers × 64 neurons), nie LSTM, nie attention
- [ ] **State:** features z meta-classifier + jego output P(win)
- [ ] **Reward:** realized R - 0.1 × max_drawdown_during_trade (penalty za drawdown w trakcie)
- [ ] **Constraints:**
  - Auto-rollback do poprzedniej wersji wag jeśli rolling 30-trade Sharpe spadnie o 30%
  - Hard kill switch: jeśli 5 trade'ów z rzędu loss > 1R → freeze wagi, alert
  - A/B test: 50% trade'ów wykonuje RL policy, 50% baseline (deterministic) — porównanie equity curves

### 7.5 Co NIE robimy

- [ ] ❌ RL na poziomie gates (np. "RL uczy się kiedy A2 PASS") — za granular, za mało danych
- [ ] ❌ RL na tick-level execution — sim-to-real gap kills you
- [ ] ❌ Deep RL (DQN, A3C, SAC) — too sample-hungry, too unstable
- [ ] ❌ Replace deterministic L1/L3 RL-em — deterministic stack zostaje dla auditability
- [ ] ❌ RL zanim mamy backtest Sharpe > 1.5 — RL nie zrobi z słabej strategii dobrej, tylko ukryje to pod black-boxem

### 7.6 Tabela ML hierarchy

| Etap | Technika | Min. trade'ów | Czas implementacji | Ryzyko |
|------|----------|---------------|---------------------|--------|
| 0 | Calibration loop (Brier + Bayesian) | 100 | 1 tydzień | Niskie |
| 1 | Supervised meta-classifier (LightGBM) | 500 | 2-4 tygodnie | Niskie |
| 2 | Thompson Sampling bandit | 1000 | 2 tygodnie | Średnie |
| 3 | Policy gradient (lightweight PPO) | 2000+ | 2-3 miesiące | Wysokie |

### 7.7 Definicja "DONE" dla P7

- **7.2 Done:** Meta-classifier ma AUC > 0.55 OOS, calibration plot OK, działa w produkcji 3 miesiące, signal.meta_classifier_score logged
- **7.3 Done:** Thompson Sampling zoperowany, posteriors per arm stabilne, system pokazuje regime-specific arm preferences
- **7.4 Done:** PPO A/B-tested vs baseline na 200+ trade'ach, Sharpe RL ≥ Sharpe baseline (jeśli mniej — wyłączamy)
