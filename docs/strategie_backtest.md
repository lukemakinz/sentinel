# Sentinel — Specyfikacje Strategii do Backtestu

_Zaakceptowane: 2026-04-24_

---

## Wspólne reguły (wszystkie strategie)

- **Max hold time**: 8h lub EOD (16:00 UTC), co pierwsze
- **Time-kill**: jeśli pozycja > 8h i nie uderzyła 1R → close market
- **TP1**: 1.5R, zamknij 40% pozycji → przesuń SL na breakeven
- **TP2**: 3.0R, zamknij 40% pozycji
- **Runner**: ostatnie 20% → chandelier trailing stop (highest_high(22) - 3×ATR)
- **SL cap**: max 3% od entry (twarda granica)
- **Leverage**: max 5× (ustawione w settings)
- **Liquidation safety**: liquidation_price musi być ≥ 2×R od entry

---

## S1 — SMC Sweep (ICT/Smart Money)

**Filozofia:** Instytucjonalny flow — gramy ze smart money po zebraniu przez nich płynności.

### Warunki wejścia (L1 Gates)
- **Wszystkie Gate A** muszą przejść (killzone, HTF trend, BTC correlation, funding, ADX>20)
- **Gate B obowiązkowe**: B1 (liquidity sweep) + B2 (FVG/OB) — bez nich setup nie istnieje
- **Gate B dodatkowe**: min 1 z pozostałych (B3/B4/B5) → łącznie ≥ 3/5
- **Gate C**: C1 (ChoCH) obowiązkowy + min 1 z pozostałych → ≥ 2/5

### Parametry entry/SL
- **Entry**: limit @ `fvg_bottom + 0.25 × (fvg_top - fvg_bottom)` (dla LONG)
- **SL**: `swept_level - 0.2 × ATR(14)` (dla LONG), z cap 3%
- **Invalidacja sweepа**: jeśli sweep > 1.5×ATR → anuluj setup
- **Invalidacja sweepа v2**: jeśli sweep przebija 2 poprzednie swingowe dołki → anuluj

### Backtesting notes
- Spodziewany Win Rate: 45–55% (SMC ma wysokie R:R, niższy WR)
- Najlepszy na: BTC, ETH (większa płynność = czystsze sweepy)
- Ryzyko: false sweeps na SOL/BNB (wyższa zmienność)

---

## S2 — Order Flow Quant (CVD + OI)

**Filozofia:** Quantitative — gramy na podstawie danych order flow, bez price action.

### Warunki wejścia
- **Gate A obowiązkowe**: A1 (killzone) + A4 (funding rate w normie) + A5 (ADX>20)
- **Gate B**: luźniejsze — wystarczy 2/5 (B3 premium/discount + jeden z pozostałych)
- **Gate C**: wystarczy 1/5 (C4 volume spike lub C5 VWAP)
- **Trigger dodatkowy**: WhaleCVD diverguje w kierunku trade + OI rośnie

### Parametry entry/SL
- **Entry**: market order w momencie ChoCH potwierdzonym przez 5m close
- **SL**: `last_swing_level - 0.2 × ATR` (LONG) lub `last_swing_level + 0.2 × ATR` (SHORT)
- **Dodatkowy warunek**: funding rate < ±0.05% (mniej ekstremalny niż S1)

### Backtesting notes
- Spodziewany Win Rate: 55–65% (order flow ma lepszy WR w konsolidacjach)
- Najlepszy na: SOL, BNB (wyższy wolumen, czystszy CVD signal)
- Ryzyko: fałszywe sygnały w strong trending markets

---

## S3 — Classic TA (EMA + RSI + S/R)

**Filozofia:** Tradycyjny trader — bez SMC, czysta techniczna analiza.

### Warunki wejścia
- **Gate A**: A1 (killzone) + A2 (EMA200 trend filter) obowiązkowe
- **Gate C**: C3 (EMA 9/21 crossover) + C2 (RSI z oversold/overbought) obowiązkowe
- **Gate B**: B3 (premium/discount jako S/R proxy) obowiązkowy

### Szczegółowe reguły
- **Trend filter**: cena powyżej EMA 200 na 4h (LONG) lub poniżej (SHORT)
- **Trigger**: EMA20 cross EMA50 W KIERUNKU trendu + RSI(14) wraca z <35 (LONG) lub >65 (SHORT)
- **S/R filter**: sygnał ważny tylko w strefie ±1.5% od zdefiniowanego poziomu S/R

### Parametry entry/SL
- **Entry**: limit @ poziom S/R ±1.5%
- **SL**: `swing_level - 0.15 × ATR` (mniejszy bufor — S/R jako anchor)

### Backtesting notes
- Spodziewany Win Rate: 40–50% (klasyczny TA — niższy WR, prostszy do automatyzacji)
- Problem: może mieć za mało setupów (3 warunki rzadko zbiegają się)
- Rozwiązanie jeśli < 100 trade'ów/rok: rozluźnić S/R do ±2%

---

## Backtest — parametry techniczne

- **Timeframe**: 2023-01-01 → 2026-04-24 (3+ lat)
- **Pary**: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT
- **Capital**: $10,000, risk/trade = 0.5%
- **Slippage**: 0.1% market, 0.02% limit maker, 0.05% limit taker
- **Silnik**: własny Python (Etap 5) replay z DB
- **L2 agents w backtest**: pominięte (za drogie LLM), zastąpione deterministyczną logiką

## Kryteria sukcesu przed live tradingiem
- [ ] Sharpe > 1.5 po kosztach (każda strategia osobno)
- [ ] MaxDD < 20%
- [ ] Trade count > 300 na 3 lata (każda para × strategia)
- [ ] Calmar > 0.5
- [ ] Monte Carlo: ruin probability < 1% przy risk=0.5%
