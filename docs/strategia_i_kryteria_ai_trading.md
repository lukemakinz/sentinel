# Strategia Tradingowa — Kryteria L1 + Logika Agentów L2 + Egzekucja L3
**Uzupełnienie analizy systemu AI Multi-Agent dla Crypto Futures**
**Data:** 23.04.2026
**Źródła inspiracji:** Al Brooks (price action), Linda Raschke (momentum/swing), Peter Brandt (classical charting), ICT/Michael Huddleston (SMC), zasady systematic quant + perpetual futures research, klasyczne prawa rynku z Edwards & Magee

---

## Architektura 3-warstwowa (jak to teraz rozumiem)

```
┌─────────────────────────────────────────────────────────────────┐
│ L1: DETERMINISTIC PRE-FILTER (Python, 24/7 scan, mikrosekundy)  │
│ "Bramkarz" — 10-15 kryteriów w 3 grupach:                        │
│   A) Bias & Context (5 kryteriów)                                │
│   B) Setup Structure (5 kryteriów)                               │
│   C) Trigger Confirmation (3-5 kryteriów)                        │
│ Wynik: binary PASS/FAIL + TradeContext JSON                      │
└─────────────────────────────────────────────────────────────────┘
                              ↓ (gdy PASS)
┌─────────────────────────────────────────────────────────────────┐
│ L2: AI MULTI-AGENT DEEP ANALYSIS (LLM, sekundy)                  │
│ 4 agentów o różnych perspektywach + Supervisor:                  │
│   1. The Context Trader (SMC / price action narrative)            │
│   2. The Order Flow Quant (mikrostruktura, CVD, walls)            │
│   3. The Risk Manager (kapitał, korelacja, news, volatility)      │
│   4. The Devil's Advocate (szuka powodów do ODRZUCENIA)           │
│   → Supervisor (konsensus + tłumaczenie na decyzję TAK/NIE)      │
│ Wynik: binary APPROVE/REJECT + reasoning JSON                     │
└─────────────────────────────────────────────────────────────────┘
                              ↓ (gdy APPROVE)
┌─────────────────────────────────────────────────────────────────┐
│ L3: DETERMINISTIC EXECUTION (Python, milisekundy)                │
│ Deterministyczny kod liczy i wysyła do Binance:                  │
│   - Entry price (środek FVG / OB / retest level)                  │
│   - Stop Loss (ATR-based + structural)                            │
│   - Position size (% equity / (SL_distance × leverage))           │
│   - TP1/TP2/TP3 (laddered)                                       │
│   - Trailing logic (activated after TP1)                          │
│ Wynik: zlecenia LIMIT/STOP/OCO do Binance Futures API            │
└─────────────────────────────────────────────────────────────────┘
```

**Kluczowa zasada:** AI decyduje "CZY". Kod decyduje "ZA ILE, GDZIE, Z JAKIM RYZYKIEM".

---

## Część 1: Skondensowana mądrość top-traderów

Przed kryteriami — pięć kluczowych lekcji, które DOSŁOWNIE składają się na filozofię systemu:

### 1.1. Al Brooks (price action, >35 lat, >$100M trading volume)
- **"Kontekst przed świeczkami."** Tej samej formacji nigdy nie traktuj identycznie w trendzie i w rangingu.
- **"Większość zysków w pierwszych 2h sesji."** Reversale open-owe i trend breakouts. Druga połowa dnia to repeated reversals — trudniej grać.
- **Entry = stop order, nie limit.** Wchodź gdy rynek już idzie Twoją stronę (minimum 1 tick potwierdzenia).
- **Signal bar → Entry bar.** Świeca potwierdzająca MUSI być tuż przed wejściem; jeśli nie ma jej, nie wchodzisz.

**Translacja na kryterium**: `regime_filter_ok` (trend vs range) + `session_is_active_window` + `entry_uses_stop_breakout_of_signal_bar`.

### 1.2. Linda Raschke (Market Wizard, 4 dekady, momentum/swing)
Jej **4 niezmienne zasady zachowania ceny**:
1. **Trend ma wyższe prawdopodobieństwo kontynuacji niż odwrócenia.** (anti-mean-reversion bias na silnym momentum)
2. **Momentum poprzedza cenę.** (dywergencje RSI/MACD są opóźnione — szukaj **trust in volume** i Range Expansion)
3. **Trendy kończą się w klimaksie.** (parabolic moves → mean reversion to 20 EMA w 1-3 dni)
4. **Rynek alternuje: Range Contraction ↔ Range Expansion.**

**Jej Keltner Channels**: 20 EMA ± 2.5 × ATR. Gdy cena dotyka górnej wstęgi → overbought warning, dolnej → oversold. Klasyczny wejście: pullback do 20 EMA w trendzie.

**Momentum Pinball** (1-2 day setups): bardzo krótka konsolidacja + 3-bar triangle + range expansion breakout.

**Translacja na kryterium**: `range_contraction_detected` (narrow Bollinger Bands / ATR compression) → `breakout_confirmation`.

### 1.3. Peter Brandt (40+ lat, classical charting, aktywny w krypto)
- **"Tylko 30 minut dziennie na analizę wejść."** Reszta to monitoring plan.
- **"Rynki krypto przestrzegają klasycznych zasad chartingu (Edwards & Magee) lepiej niż większość rynków."** Zachowaj szacunek dla: Head & Shoulders, Double Bottoms, wedges, flags, rectangles.
- **Win rate ~35-40%**, ale RR 3:1+. Nie myl hit rate z profitability.
- **Disciplina > predykcja.** Jego przewaga to rygor wejść/wyjść, nie magiczne formacje.

**Translacja na kryterium**: Dodać wykrywanie klasycznych formacji (flag, wedge, H&S) jako jeden z gates; enforce RR ≥ 2.5.

### 1.4. ICT / Michael Huddleston (Smart Money Concepts)
- **Confluence = wszystko.** Jeden FVG to ziarnko. FVG + OB + Killzone + HTF liquidity = A+ setup.
- **Power of Three**: Accumulation → Manipulation (sweep) → Distribution. Sweep JEST kluczowym triggerem.
- **Premium/Discount (D/W range)**: kupuj tylko w discount (<50% zakresu), sprzedawaj w premium (>50%).
- **Killzones**:
  - London Open: 02:00–05:00 EST (07:00–10:00 UTC)
  - New York AM: 07:00–10:00 EST (12:00–15:00 UTC)
  - **Power Hour**: 15:00–16:00 EST (20:00–21:00 UTC)
  - Weekend/Asia sesja = szum w większości przypadków

**Translacja na kryterium**: `killzone_active` jako hard gate; `confluence_count >= 3` jako jakościowy filtr.

### 1.5. Quant trading lessons (systematic, crypto-specific)
- **Walk-forward > static backtest.** Re-optymalizacja co 1-3 miesiące na rolling window.
- **Funding rate JEST kosztem transakcji.** Long przy +0.05%/8h × 3 = 0.15%/dzień. Po tygodniu holdingu to 1%+ jedzenia edge'u.
- **On-chain signals jako filtr makro**: MVRV, SOPR, Puell Multiple (BTC tops/bottoms); whale flows do exchanges (distribution signal).
- **Regime models**: markets oscylują między momentum regime (trend-following works) a mean-reversion regime. Użyj ADX (>25 trend, <20 range) + realized volatility percentile do klasyfikacji.

### Lekcja "meta" ze wszystkich źródeł:
> **Nie istnieje jedna strategia, która działa zawsze.** System musi mieć **portfolio strategii** + regime detection, który aktywuje właściwą strategię do warunków.

Twoja aktualna spec ma 1 strategię ("Sweep & Absorption"). Dodaj minimum drugą ("Breakout & Continuation") dla trendów.

---

## Część 2: Deterministyczny Pre-Filter (L1) — 15 konkretnych kryteriów

System skanuje 24/7 listę top-30 par (BTC, ETH, SOL, + top alt-coiny według 30-day average volume). Dla każdej pary oblicza poniższe gates. **Wszystkie A + co najmniej 3 z B + co najmniej 2 z C = PASS do L2.**

### Grupa A: BIAS & CONTEXT (wszystkie muszą być PASS)

**A1. `killzone_active`** (czas sesji)
```python
ACTIVE_WINDOWS_UTC = [
    (7, 10),   # London Open
    (12, 15),  # NY Open overlap
    (20, 21),  # Power Hour (US close)
]
# Opcjonalnie: (0, 2) Asia Open dla pairs z dużym azjatyckim volume (SOL, DOGE)
```

**A2. `higher_timeframe_trend_aligned`** (1D bias)
```python
# 1D EMA50 > EMA200 = bullish bias → akceptuj tylko LONG signals
# 1D EMA50 < EMA200 = bearish bias → akceptuj tylko SHORT signals
# Cena w ±2% EMA200 = neutral → akceptuj obustronnie, ale z redukcją size o 50%
```

**A3. `btc_correlation_not_opposite`** (BTC macro check dla altów)
```python
# Dla altów: jeśli BTC 4H structure przeciwstawna (BOS w drugą stronę w ostatnich 24h)
# AND 30-day rolling correlation(alt, BTC) > 0.7 → BLOCK
```

**A4. `funding_rate_not_extreme`** (squeeze risk)
```python
# Binance 8h funding rate
# Jeśli signal = LONG and funding > +0.08% → BLOCK (overheated longs)
# Jeśli signal = SHORT and funding < -0.08% → BLOCK (overheated shorts)
# Normal range: ±0.01% to ±0.05%
```

**A5. `volatility_regime_compatible`** (strategia do reżimu)
```python
# ADX(14) na 4H
# ADX > 25 → trend regime → aktywuj strategie "Breakout & Continuation"
# ADX < 20 → range regime → aktywuj strategie "Sweep & Absorption" (reversal)
# 20 ≤ ADX ≤ 25 → transitional → tylko HTF A+ setups
```

### Grupa B: SETUP STRUCTURE (minimum 3 z 5 muszą być PASS)

**B1. `liquidity_sweep_detected`** (ICT core)
```python
# Na 15m lub 1H świeca wicku'je przez:
#   - Previous Day High/Low (PDH/PDL)
#   - Previous Week High/Low (PWH/PWL)
#   - Equal Highs/Lows clustering (tzw. double tops/bottoms)
# ALE zamyka się z POWROTEM poniżej/powyżej sweeped level
# Knot (wick) ≥ 50% body
```

**B2. `fvg_or_order_block_present`** (HTF POI)
```python
# W kierunku HTF bias, w zasięgu 2 × ATR(1H) od current price,
# musi być niewypełniony FVG (Fair Value Gap = imbalance 3-świecowy) 
# lub OB (ostatnia przeciwna świeca przed impulsem)
```

**B3. `premium_discount_zone_ok`** (ICT D/W range)
```python
# Oblicz D_range = (D_high - D_low)
# equilibrium = D_low + 0.5 × D_range
# Dla LONG: current_price < equilibrium (discount)
# Dla SHORT: current_price > equilibrium (premium)
```

**B4. `classical_pattern_present`** (Peter Brandt influence)
```python
# Skaner klasycznych formacji (user: pandas_ta lub ta-lib):
#   - Bull/bear flag (po silnym impulse move)
#   - Wedge (falling wedge bullish, rising wedge bearish)  
#   - Double bottom / top
#   - Head & Shoulders (reversal)
#   - Rectangle breakout
# Min. 1 formacja wykryta na 4H/1D
```

**B5. `range_compression_then_expansion`** (Raschke influence)
```python
# Bollinger Band Width na 1H w dolnym 20% percentylu ostatnich 100 świec
# PLUS current candle range > 1.5 × average_range(20)
# = compression → expansion transition
```

### Grupa C: TRIGGER CONFIRMATION (minimum 2 z 5 muszą być PASS)

**C1. `change_of_character`** (SMC/ICT - ChoCh)
```python
# Na 5m/15m struktura rynku się odwróciła:
# Dla LONG po sweep'ie downside: wybito ostatni 15m lower high
# Dla SHORT po sweep'ie upside: wybito ostatni 15m higher low
```

**C2. `momentum_divergence`** (Raschke - "momentum precedes price")
```python
# RSI(14) lub MACD histogram dywergencja względem price:
#   - Bullish div: cena niżej, RSI wyżej (dla potencjalnego LONG)
#   - Bearish div: cena wyżej, RSI niżej (dla potencjalnego SHORT)
# Min. 2 price points do porównania
```

**C3. `ema_confluence`** (trend alignment)
```python
# Na 1H: cena powyżej/poniżej 20 EMA i 50 EMA (zgodnie z bias)
# Bonus: 20 EMA > 50 EMA dla LONG, < dla SHORT (stacked EMAs)
```

**C4. `volume_confirmation`** (Wyckoff/Brooks)
```python
# Volume świecy trigger'owej > 1.5 × average_volume(20)
# = institutional interest, nie szum
```

**C5. `vwap_reclaim_or_rejection`** (daily VWAP)
```python
# Dla LONG: cena dotknęła, ale nie zamknęła się pod daily VWAP (support hold)
# Dla SHORT: cena dotknęła, ale nie zamknęła się nad daily VWAP (resistance hold)
```

### Kolejne ważne (bonus gates, raise jakości ale nie wymagane)

**D1. `whale_cvd_supportive`**: na 1m/5m Whale CVD (>95 percentyl trade size rolling 24h) w kierunku setup'u.
**D2. `retail_cvd_contrarian`**: Retail CVD (<50 percentyl) w przeciwnym kierunku = absorption signal.
**D3. `open_interest_confirming`**: OI rośnie w kierunku setup'u (new positions building).
**D4. `orderbook_walls_persistent`**: walls po stronie przeciwnej do exit (protecting entry) utrzymane >30s.
**D5. `no_major_news_risk`**: brak Fed meeting / CPI / NFP / Binance listing w najbliższych 2h.

### Wynik L1:
```json
{
  "pair": "SOLUSDT",
  "timestamp": "2026-04-23T13:37:15Z",
  "direction": "LONG",
  "l1_pass": true,
  "gates_passed": {
    "A": ["killzone_active", "higher_timeframe_trend_aligned", "btc_correlation_not_opposite", "funding_rate_not_extreme", "volatility_regime_compatible"],
    "B": ["liquidity_sweep_detected", "fvg_or_order_block_present", "premium_discount_zone_ok"],
    "C": ["change_of_character", "volume_confirmation"]
  },
  "bonus_gates": ["whale_cvd_supportive", "retail_cvd_contrarian"],
  "raw_data": {
    "current_price": 167.23,
    "atr_1h": 2.45,
    "fvg_zone": [165.80, 167.10],
    "swept_level": 164.50,
    "nearest_liquidity_above": 172.40,
    "btc_1h_trend": "bullish",
    "funding_rate": 0.015,
    "daily_vwap": 166.90
  }
}
```

**DOPIERO TERAZ** budzimy agentów L2.

---

## Część 3: Agenci L2 — prompty + narzędzia

Każdy agent dostaje:
- `TradeContext JSON` z L1
- Swoje specyficzne narzędzia (tools)
- Ściśle zdefiniowany output schema (JSON, nie wolna proza!)

**Kluczowa zasada**: każdy agent odpowiada strukturalnym JSON-em z polami `verdict: "APPROVE"|"REJECT"|"NEUTRAL"`, `confidence: 0-100`, `reasoning: string`, `risk_flags: list[string]`.

### Agent 1: The Context Trader (Al Brooks + ICT)

**System Prompt:**
```
Jesteś 40-letnim weteranem price action i SMC, wyszkolonym w metodologiach 
Al Brooksa i ICT. Twoja specjalność to OCENA KONTEKSTU — czy setup jest 
"w miejscu gdzie rozsądnie gra ten setup" czy "w miejscu wbrew rynkowi".

Dostajesz TradeContext po spełnieniu warunków technicznych L1. Twoje 
zadanie: ocenić narrację rynku. Nie generujesz liczb. Nie podajesz 
entry/SL/TP. Odpowiadasz na 4 pytania:

1. Czy bieżący reżim (trend/range/expansion/contraction) SENSOWNIE 
   wspiera ten typ setup'u?
2. Czy na wyższych timeframe'ach (1D, 1W) jest "wiatr w plecy" 
   czy "pod wiatr"?
3. Czy to setup A+ (5/5 confluence) czy B/C (marginal)?
4. Jakie są 2-3 główne sposoby, w jakie ten trade MOŻE SIĘ ZEPSUĆ?

Zwróć JSON:
{
  "verdict": "APPROVE"|"REJECT"|"NEUTRAL",
  "setup_grade": "A+"|"A"|"B"|"C",
  "narrative": "Krótki opis 'dlaczego rynek miałby w tej chwili zrobić 
                to co zakładamy'",
  "htf_bias_alignment": "Strong"|"Moderate"|"Weak"|"Against",
  "failure_modes": ["mode1", "mode2", "mode3"],
  "confidence": 0-100
}
```

**Tools**: `get_multi_timeframe_structure(pair, ["1W", "1D", "4H", "1H"])`, 
`get_recent_swings(pair, lookback_bars)`, `get_session_statistics(pair, session)`.

### Agent 2: The Order Flow Quant (Axia Futures / orderflow desk style)

**System Prompt:**
```
Jesteś tape reader'em z futures trading floor, 15 lat doświadczenia z 
footprint chartami i Delta analysis. Nie interesują Cię formacje ze 
świec — interesuje Cię KTO KUPUJE i KTO SPRZEDAJE i CZY JEDNA STRONA 
JEST ABSORBOWANA.

Dostajesz TradeContext. Twoje zadanie: ocenić mikrostrukturę.

Kluczowe pytania:
1. Czy podczas sweep'u Retail CVD gwałtownie przyspieszył w jedną 
   stronę (tłum dosiada trend/kupuje szczyt)?
2. Czy równolegle Whale CVD MALAŁ/STAGNOWAŁ (instytucje ABSORBOWAŁY 
   ten popyt limit ordersami)?
3. Czy w orderbooku są persistent walls chroniące naszą stronę 
   (nie flip-flop)?
4. Czy Open Interest rośnie w kierunku setup'u (new conviction) czy 
   maleje (pozamykanie)?

Sygnał absorpcji = Retail push + Whale fade + OI up + wall persistence.

Zwróć JSON:
{
  "verdict": "APPROVE"|"REJECT"|"NEUTRAL",
  "absorption_detected": true|false,
  "whale_retail_divergence": "Strong"|"Moderate"|"None",
  "orderbook_quality": "Clean"|"Spoofed"|"Thin",
  "oi_signal": "Building"|"Distributing"|"Neutral",
  "reasoning": "...",
  "confidence": 0-100
}
```

**Tools**: `get_whale_cvd(pair, window)`, `get_retail_cvd(pair, window)`, 
`get_orderbook_depth(pair, levels)`, `get_wall_persistence(pair, level, duration)`, 
`get_open_interest_trend(pair, window)`, `get_liquidation_map(pair)`.

### Agent 3: The Risk Manager (Risk Desk / PM style)

**System Prompt:**
```
Jesteś dyrektorem ryzyka funduszu. Twoja kariera zależy od tego, żebyś 
przegrywał kontrolowane straty i NIGDY nie dopuścił do tail risk event. 
Zakładasz że Context Trader i Order Flow Quant są zbyt optymistyczni — 
Twoja rola to szukać powodów do BLOCK.

Dostajesz TradeContext + raporty Agenta 1 i Agenta 2. Sprawdzasz:

1. Czy bieżący drawdown konta dopuszcza nowy trade (> -10% DD → redukuj 
   size; > -15% DD → BLOCK)?
2. Czy ilość otwartych pozycji + ich korelacja nie przekracza limitów 
   (max 3 jednoczesne; max effective BTC beta = 2x)?
3. Czy w najbliższych 2h nie ma high-impact news (FOMC, CPI, NFP, 
   major listing/unlock)?
4. Czy implied volatility (z options) nie jest anormalnie wysoka (crisis)?
5. Czy proponowany SL (ATR-based) jest realistyczny (SL za szeroki → size 
   tak mały że fees zżerają edge; SL za wąski → noise stop-out)?

Zwróć JSON:
{
  "verdict": "APPROVE"|"REJECT"|"SIZE_DOWN",
  "size_multiplier": 0.0-1.0,
  "portfolio_conflicts": [...],
  "news_calendar_risk": true|false,
  "iv_regime": "Low"|"Normal"|"Elevated"|"Crisis",
  "sl_width_assessment": "Tight"|"Normal"|"Wide",
  "blockers": [...],
  "confidence": 0-100
}
```

**Tools**: `get_account_drawdown()`, `get_current_positions()`, 
`get_correlation_matrix(pairs)`, `get_economic_calendar(hours_ahead=2)`, 
`get_iv_from_options(pair)`, `get_current_atr(pair, tf)`.

### Agent 4: The Devil's Advocate (contrarian red-teamer)

**System Prompt:**
```
Twoim JEDYNYM ZADANIEM jest znaleźć powód, dla którego ten trade NIE 
ZADZIAŁA. Nie interesuje Cię bycie grzecznym. Nie boisz się odrzucić 
setup'u, który wygląda na A+.

Twój playbook:
1. Czy to "textbook" setup, który WSZYSCY widzą (=stop hunt risk)?
2. Czy sweep mógł być fake'iem (rynek powtórnie wróci do zsweep'owanego 
   poziomu w ciągu 2-6h)?
3. Czy jesteśmy w "wrong side of week" — setup LONG w piątkowy 
   afternoon przed weekend drawdown?
4. Czy istnieje lepsza kontr-interpretacja tego co widzimy 
   (np. to nie absorpcja, tylko distribution)?
5. Jaki jest historyczny win rate TEGO konkretnego setup'u w 
   ostatnich 100 przypadkach (z backtestu)?

Zwróć JSON:
{
  "verdict": "APPROVE_RELUCTANTLY"|"REJECT",
  "strongest_counter_argument": "...",
  "alternative_interpretation": "...",
  "historical_win_rate_this_setup": 0.0-1.0,
  "red_flags": [...],
  "confidence_in_rejection": 0-100
}
```

**Tools**: `get_setup_historical_win_rate(setup_type, pair, lookback_days)`, 
`get_recent_failed_setups(pair, similar_to=current)`, `get_day_of_week_performance(setup_type)`.

### Supervisor (meta-agent, orchestration)

**System Prompt:**
```
Otrzymujesz 4 raporty. Nie jesteś "przegłosowaniem większości". 
Twoje decyzje:

1. Jeśli Risk Manager = REJECT → FINAL REJECT (risk ma prawo veto).
2. Jeśli Devil's Advocate = REJECT i jego confidence > 80 → FINAL REJECT.
3. Jeśli Context Trader = REJECT i Order Flow Quant = REJECT → FINAL REJECT.
4. W pozostałych przypadkach: APPROVE z poniższym size multiplier:
   - Base size = Risk_Manager.size_multiplier
   - Jeśli setup_grade = "A+" → × 1.0
   - Jeśli setup_grade = "A"  → × 0.75
   - Jeśli setup_grade = "B"  → × 0.50
   - Jeśli setup_grade = "C"  → REJECT
5. Jeśli confluence między agentami jest niska (1 APPROVE vs 3 NEUTRAL) → 
   paper trade only (log but don't execute).

Zwróć JSON:
{
  "final_verdict": "APPROVE"|"REJECT"|"PAPER_ONLY",
  "effective_size_multiplier": 0.0-1.0,
  "consensus_summary": "...",
  "primary_approval_reasons": [...],
  "primary_risk_concerns": [...],
  "override_reason": null | "..."
}
```

---

## Część 4: Deterministyczna Egzekucja (L3)

Gdy Supervisor zwraca `APPROVE`, **KOD**, nie LLM, liczy dokładne parametry:

### 4.1. Entry Zone
```python
# Dla LONG setup'u po sweep'ie z powrotem do FVG:
entry_zone_low  = fvg_low
entry_zone_mid  = (fvg_low + fvg_high) / 2
entry_zone_high = fvg_high

# Execution: limit order na entry_zone_mid, 
# fallback market order jeśli cena cross'uje entry_zone_high bez fill
# timeout: jeśli nie ma fill w ciągu 15 minut → cancel (setup się nie realizuje)
```

### 4.2. Stop Loss
```python
# Multi-level SL, bierze maksimum (najbezpieczniejszy):
sl_atr_based      = entry - 1.5 * atr_1h              # Volatility buffer
sl_structural     = swept_level - 0.3 * atr_1h        # Pod sweep wick
sl_percentage     = entry * 0.97                       # Max 3% loss cap

final_sl = min(sl_atr_based, sl_structural, sl_percentage)  # dla LONG (najniższy)
# Dla SHORT: max(...) zamiast min()

# Sanity check: SL distance >= 0.5% entry (nie za ciasno)
#               SL distance <= 3%   entry (nie za szeroko)
```

### 4.3. Position Size (ATR-based + Kelly fractional)
```python
account_equity   = get_equity()
risk_per_trade   = 0.005 * account_equity  # 0.5% per trade
risk_per_trade  *= supervisor.effective_size_multiplier

sl_distance_pct  = abs(entry - final_sl) / entry
position_notional = risk_per_trade / sl_distance_pct
leverage         = min(10, calculate_safe_leverage(sl_distance_pct))  
position_size    = position_notional / entry

# Safety: sprawdź że liquidation_price jest min. 2x SL distance daleko
liq_price = binance.calculate_liq_price(...)
assert abs(entry - liq_price) >= 2 * abs(entry - final_sl)
```

### 4.4. Take Profits (Laddered)
```python
risk_distance = abs(entry - final_sl)

tp1 = entry + 1.5 * risk_distance  # 40% pozycji
tp2 = entry + 3.0 * risk_distance  # 40% pozycji  
# tp3 = runner, trailing stop (20% pozycji)

# Walidacja: czy TP1 nie zderza się z HTF liquidity jako pierwszy opór?
nearest_liquidity_above = find_nearest_liquidity_pool(pair, direction="above", from_price=entry)
if nearest_liquidity_above < tp1:
    tp1 = nearest_liquidity_above - 0.5 * atr_1h  # just below the wall

# Walidacja RR:
if (tp1 - entry) / risk_distance < 1.2:  # minimum RR
    final_verdict = "REJECT"  # nie ma sensu grać
```

### 4.5. Trailing Stop Logic
```python
# Activated AFTER TP1 fill:
# Method A: Breakeven shift (konserwatywne)
if tp1_filled:
    update_sl(new_sl = entry + 0.1 * risk_distance)  # locked fees + small profit

# Method B: R-multiple laddering (po osiągnięciu każdego kolejnego R, 
#           przesuń SL na poprzedni R)
# Method C: Chandelier Exit (dla runner):
# SL = highest_high(22) - 3 * atr_1h
# Update co 1H candle close

# Time-based kill switch:
# Jeśli pozycja otwarta > 8h i nie osiągnęła 1R → zamknij market close
# Jeśli pozycja przekroczyła dzień handlowy → re-evaluate na HTF
```

---

## Część 5: Przykładowy walkthrough (SOLUSDT LONG, 23.04.2026)

**13:30 UTC** — NY Open Killzone startuje. Scanner działa.

**13:37 UTC** — SOLUSDT 15m candle zamyka się:
- SOL wicknął do $164.50 (PDL z 22.04) i zamknął się na $167.23 (sweep downward)
- Poprzednia świeca 1H miała 20 EMA = $166.10; 200 EMA = $158.40 → bullish HTF
- BTC 4H w uptrend, nie przełamał support → correlation OK
- Funding rate SOL = +0.015% → neutralny
- ADX(14) na 4H = 28 → trend regime → oczekujemy "Breakout & Continuation"... ALE
- Sweep & Absorption signal jest wystarczająco silny że przebija regime filter (5/5 A + 4/5 B + 3/5 C)

**L1 Wynik**: PASS. `TradeContext` trafia do kolejki Celery, budzi agentów.

**13:37:02 UTC** — Agent 1 (Context Trader): "A+ setup. 1D trend bullish, sweep PDL po retestie OB z 22.04, SOL ostatnio outperforms BTC. Failure modes: (1) BTC może sprzedać się w najbliższej hour na news, (2) sweep może się okazać continuation down jeśli volume trigger nie utrzyma." → APPROVE, grade A+, confidence 82.

**13:37:05 UTC** — Agent 2 (Order Flow Quant): "Whale CVD był płaski podczas sweep'u ($164.50→$165.20), ale Retail CVD gwałtownie negatywny. Gdy cena odbiła, Whale CVD wystartował. W orderbooku ściana $166.50 short utrzymana 45s. OI rośnie. Absorpcja potwierdzona." → APPROVE, absorption=true, confidence 78.

**13:37:06 UTC** — Agent 3 (Risk Manager): "Account DD = -2%. Open positions: 1 (ETH long). SOL-BTC correlation = 0.78. No news w 2h. IV normal. ATR = $2.45, SL proposal 1.5 × ATR = $3.68 distance = 2.2% z entry. Akceptowalne. Size = 0.5% × 1.0 = 0.5% risk." → APPROVE, size_multiplier 1.0, confidence 85.

**13:37:08 UTC** — Agent 4 (Devil's Advocate): "Historic win rate tego setup'u (sweep & absorption w NY Open, ADX > 25) na SOL = 0.61 ostatnie 50 wystąpień. Counter: BTC dominance rośnie = altcoiny underperform w najbliższych dniach. Nie jest to killing blow. Red flags: brak." → APPROVE_RELUCTANTLY, confidence_in_rejection 25.

**13:37:10 UTC** — Supervisor: "4/4 APPROVE z grade A+. Risk Manager nie ma blokerów. Size multiplier = 1.0."

**13:37:11 UTC** — L3 kalkuluje:
```
entry_zone    = [$166.80, $167.40], limit mid $167.10
sl            = $163.50 (pod sweep wick $164.50, 1.5 × ATR buffer)
risk_distance = $3.60 (2.15% of entry)
position_size = (0.5% × $10,000) / ($3.60) = 13.88 SOL
leverage      = 5x (liq price ~$133, safe)
tp1           = $172.50 (1.5R), close 40% (5.55 SOL)
tp2           = $178.00 (3R), close 40%
tp3           = runner (20%), chandelier exit
```

**13:37:12 UTC** — Limit order wysłany do Binance Futures. WebSocket do React UI wypycha sygnał. User widzi "AI EXECUTED SOL LONG @ $167.10" z pełnym rozumowaniem agentów.

**15:20 UTC** — TP1 $172.50 trafiony. Automatycznie: close 40%, SL na $167.30 (breakeven + fees).

**17:45 UTC** — TP2 $178.00 trafiony. Close 40%. Runner 20% trailing chandelier.

**19:30 UTC** — Trailing SL aktywowany na $181.20 (chandelier). Pozycja zamknięta na $181.20.

**Podsumowanie trade'u**:
- Entry: $167.10
- Avg exit: (172.50 × 0.4 + 178.00 × 0.4 + 181.20 × 0.2) = $176.44
- Return na pozycji: +5.59% × 5x leverage = **+27.96% ROE**
- Ryzyko w kapitale: 0.5% (zdefiniowane SL)
- Actual realized RR: 2.6R

---

## Część 6: Backtest priorytety (zanim to pójdzie live!)

Przed jakimkolwiek real-money tradem, musisz statystycznie udowodnić edge. Kolejność testów:

1. **Pojedyncze gates**: każdy z 15 L1 gates testowany osobno. Które naprawdę filtrują sygnały z dodatnim EV?
2. **Kombinacja A+B+C gates (bez AI)**: pure deterministic → jaki jest Sharpe po fees?
3. **Add AI layer**: porównaj z/bez AI. Jeśli różnica < 20% uplift, AI nie warto (koszt LLM calls).
4. **Per-pair analysis**: strategia może działać na BTC/ETH a nie na SOL/DOGE. Curate listę par.
5. **Per-session**: London vs NY vs Power Hour — gdzie największy edge?
6. **Monte Carlo 10,000 permutacji**: jaki drawdown w 5% najgorszych scenariuszy?

**Cel minimum przed live**: Sharpe > 1.5, MaxDD < 20%, Calmar > 0.5, trade count > 300.

---

## Część 7: "Co musisz zapytać najlepszych traderów" (pytania do konsultacji ludzkiej)

Poniższy dokument to synteza **publicznie dostępnych** nauk. Prawdziwe insights przyjdą z bezpośredniej rozmowy. Lista pytań do zadania doświadczonemu crypto-traderowi:

1. Który z 15 L1 gates w Twoim doświadczeniu jest **najbardziej szumny** (false positive)?
2. Czy widziałeś w praktyce tę konkretną strategię ("Sweep & Absorption") — jaki jest realny live win rate (nie YouTube claims)?
3. Które timeframe'y w crypto dają najczystsze sygnały dla day tradingu? (Większość traderów odpowiada: 15m trigger, 1H confirm, 4H bias)
4. Jak radzisz sobie z weekendami (niższa likwidność → większe sweeps)?
5. Czy masz konkretny "kill-switch" dla swojego systemu po stratach?
6. Jakie pary absolutnie NIGDY nie tradeujesz w futures (za cienkie, za manipulowane)?

**Gdzie znaleźć takich ludzi**: Twitter (CryptoCred, LukeMartinSSL, Tradingriot, cantgetrightx, Peter Brandt bezpośrednio), Discord communities (Tradingriot Bootcamp, Axia Futures), Reddit r/algotrading (quant perspective).

---

## Część 8: Podsumowanie (jednym akapitem)

Strategia musi być portfolio setupów (minimum 2: Sweep & Absorption + Breakout & Continuation), zarządzana przez regime detector (ADX), filtrowana przez 15 deterministycznych gates w 3 grupach (Bias/Structure/Trigger), poddawana debacie 4 agentów AI (Context, Order Flow, Risk, Devil's Advocate) z Supervisor'em syntetyzującym, i egzekwowana przez deterministyczny kod liczący dokładne ceny i wielkości w oparciu o ATR i structural levels. Trailing stop 3-stopniowy (breakeven po 1R, R-multiple laddering, chandelier dla runner'a). Position sizing 0.5% per trade, daily halt -3%, weekly halt -7%, DD-based size reduction. **Wszystko to zmontowane, ale przed live — 3–6 miesięcy paper tradingu na Testnet i backtestów na 3 latach danych**. Bez tego to nadal hazard, tylko ładniej ubrany.

---

## Źródła referencyjne

- Al Brooks — Brooks Trading Course, *Trading Price Action* (trilogia)
- Linda Raschke — *Street Smarts* (z Connorsem), Linda Raschke website (10 Trading Rules)
- Peter Brandt — *Diary of a Professional Commodity Trader*, factor-trading.com blog
- ICT / Michael Huddleston — YouTube channel, Mentorship materials
- Edwards & Magee — *Technical Analysis of Stock Trends* (klasyka klasyk)
- *Quantitative Trading* — Ernest Chan (procedura walidacji strategii)
- Binance Futures API docs, CME Bitcoin futures specs
- Glassnode Academy (on-chain metrics)
- Axia Futures community (order flow methodology)
