# SENTINEL — Zasady działania systemu
_Wersja: 2026-04-25 | Strategia S1 aktywna | Backtest 60d: 13 trade'ów, 62% WR, +1.16%_

---

## 1. Co system robi

Sentinel skanuje rynek Binance Futures co minutę i identyfikuje high-probability trade'y spełniające zestaw deterministycznych kryteriów (L1 Pre-Filter), następnie przekazuje je do 4 niezależnych agentów AI (L2) i finalnie oblicza precyzyjne parametry wejścia (L3). Użytkownik otwiera pozycję **ręcznie na Binance** po otrzymaniu sygnału. System monitoruje pozycję i informuje o warunkach wyjścia.

---

## 2. Pipeline sygnału

```
Binance WebSocket (real-time)
  ↓ co 1 minutę
L1 Pre-Filter (15 deterministycznych bram)
  ↓ jeśli wszystkie A + 2+ B + CHoCH C1 przejdą
L2 AI Agents (4 agenci równolegle, ~10-15s)
  ↓ jeśli Supervisor APPROVE
L3 Calculator (deterministyczne entry/SL/TP)
  ↓
Karta sygnału na dashboardzie
  ↓ użytkownik decyduje czy wchodzi
Ręczne wejście na Binance → "Wchodzę" w aplikacji
  ↓
Monitoring pozycji co 30s
```

---

## 3. Strategia S1 — SMC Sweep (jedyna aktywna po backtestach)

### Filozofia
Instytucjonalni gracze "polują" na stop lossy retail traderów przez przebicie kluczowych poziomów płynności (previous highs/lows), zbierają tam pozycje, po czym odwracają kierunek. System wykrywa ten mechanizm i wchodzi po stronie instytucji.

### Warunki wejścia — Gate A (wszystkie 5 muszą przejść)

| Gate | Warunek | Dlaczego |
|------|---------|----------|
| A1 | Aktywna sesja London (07-10 UTC) lub NY (13-16 UTC) | Instytucje działają tylko w swoich oknach |
| A2 | HTF struktura: Higher Highs + Higher Lows (LONG) lub LH+LL (SHORT) | Gramy z trendem wyższego TF, nie przeciwko |
| A3 | BTC nie jest w przeciwnym trendzie | Crypto koreluje — kontra BTC = ryzyko |
| A4 | Funding rate < ±0.1% | Ekstremalny funding = tłum po jednej stronie |
| A5 | Choppiness Index < 61.8 (rynek trending, nie ranging) | Gates B/C są bezużyteczne w ranging |

### Warunki wejścia — Gate B (B1 + B2 obowiązkowe)

| Gate | Warunek | Dlaczego |
|------|---------|----------|
| **B1** | **Liquidity Sweep** — wick przebił PDH/PDL/Asian Range/Equal Highs | Core SMC: instytucje zebrały płynność |
| **B2** | **Fair Value Gap** z displacement candle (ciało > 1.5×ATR + volume spike) | Prawdziwy FVG = impuls instytucjonalny, nie przypadkowa luka |
| B3 | Cena w Discount zone (LONG < 50% HTF range) lub Premium (SHORT > 50%) | Gramy z value, nie przepłacamy |
| B5 | ATR Squeeze (current ATR < 50% avg 20-period ATR) | Kompresja zmienności poprzedza ruch |

### Warunki wejścia — Gate C (C1 obowiązkowy)

| Gate | Warunek | Dlaczego |
|------|---------|----------|
| **C1** | **CHoCH** (Change of Character) — pierwsza HL po serii LL (LONG) | Potwierdzenie że sweep się skończył i kierunek zmieniony |
| C2 | RSI Divergence — cena lower low, RSI higher low | Momentum słabnie → odwrót bliski |
| C3 | Delta Candle pozytywna (taker buy > taker sell) | Buyers dominują na tym poziomie |
| C4 | Volume spike > 1.5× average | Instytucjonalne wejście widoczne w wolumenie |
| C5 | Cena powyżej VWAP (LONG) | Momentum po właściwej stronie |

### Parametry wejścia (L3 Calculator)

```
Entry:   50% głębokości FVG (OTE — Optimal Trade Entry)
         lub nearest unswept liquidity level jeśli brak FVG

SL:      swept_level - 0.2×ATR(14)
         minimum 0.3% od entry (noise protection)
         maksimum 1.5% od entry (S1 hard cap)

TP1:     +1.5R od entry (40% pozycji) → po TP1: SL → breakeven + fees
TP2:     +3.0R od entry (40% pozycji) lub nearest liquidity pool powyżej
         alternatywnie: TP do pierwszego untapped PDH/PWH/Equal High

Runner:  20% pozycji → chandelier trailing stop
         chandelier = highest_high(22) - 3×ATR(14)
         update co każde zamknięcie świecy 1H

Time-kill: jeśli pozycja > 8h i nie uderzyła w 1R → close market
EOD:    wszystkie pozycje zamykane o 22:00 UTC
```

---

## 4. Risk Management (nienaruszalne reguły)

### Position sizing
```
Risk per trade = 0.5% kapitału × DD multiplier × signal conviction
DD multiplier:
  0% DD    → 1.0× (pełny rozmiar)
  -5% DD   → 0.75×
  -10% DD  → 0.5×
  -15% DD  → 0.25×
  -20% DD  → HALT (zero nowych pozycji)
```

### Daily/Weekly halts
- **Daily drawdown > 3%** → stop na resztę dnia
- **Weekly drawdown > 7%** → stop na resztę tygodnia
- **Session loss > 2R** → stop na resztę sesji (London lub NY)

### Anti-revenge rules (automatyczne blokady)
- SL hit → 30 min cooldown na tym symbolu
- 2 SL z rzędu na tym symbolu w 24h → blokada 24h
- 3 consecutive SL w portfelu → soft halt (brak nowych wejść)
- Max 5 trade'ów / 24h portfela
- Max 1 trade / 4h na tym samym symbolu

### Portfolio heat
- Max 2× BTC-beta exposure (BTC=1.0, ETH=0.9, SOL=0.85)
- Jeden symbol = jedna aktywna pozycja jednocześnie

### News blackout
- Blokada 2h przed i 1h po FOMC / CPI / NFP
- ⚠️ Lista hardcoded — podłączyć API przed live tradingiem

---

## 5. AI Agents (L2) — co oceniają

Każdy sygnał L1 jest oceniany przez 4 agentów AI (Claude Haiku lub GPT-4o-mini). Każdy agent widzi inne dane:

| Agent | Fokus | Veto power |
|-------|-------|-----------|
| **Context Trader** | SMC narrativa, struktura, FVG, sweep jakość | NIE |
| **Order Flow Quant** | Whale CVD, Retail CVD, OI trend, absorption | NIE |
| **Risk Manager** | DD, portfolio heat, news, SL width | **TAK** (twarde veto) |
| **Devil's Advocate** | Kontrariański red-team, potencjalne pułapki | Częściowe (confidence > 70% → size ×0.5) |

**Supervisor (deterministyczny, bez LLM):**
- Risk Manager REJECT → całkowity REJECT niezależnie od innych
- 3+ APPROVE → pełny rozmiar (1.0×)
- 2 APPROVE → 75% rozmiaru
- Devil's Advocate REJECT z confidence > 70% → size ×0.5

---

## 6. Wyniki backtestów — wszystkie strategie (60 dni, 1H resolution, 2025-05-01 → 2025-07-01)

### BTCUSDT

| Strategia | Trade'y | Win Rate | Sharpe | Max DD | PnL ($10k) | Ocena |
|-----------|---------|----------|--------|--------|------------|-------|
| **S1 SMC Sweep** | 13 | **62%** | 0.28 | 0.8% | **+$116** | ✅ Wstępnie pozytywna |
| S2 Order Flow | 9 | 44% | 0.17 | 0.4% | +$38 | ⚠️ Poniżej break-even WR |
| S3 Classic TA | 15 | 13% | -0.81 | 2.8% | **-$281** | ❌ Destruktywna w tym okresie |

### SOLUSDT

| Strategia | Trade'y | Win Rate | Sharpe | Max DD | PnL | Ocena |
|-----------|---------|----------|--------|--------|-----|-------|
| **S1 SMC Sweep** | 2 | 100% | 22.97 | 0.0% | +$50 | ⚠️ Za mało danych (2 trade'y) |
| S2 Order Flow | 0 | — | — | — | — | ❌ Brak sygnałów (brak hist. CVD) |
| S3 Classic TA | 0 | — | — | — | — | ❌ Brak sygnałów |

### Analiza wyników

**S1 (SMC Sweep) — najlepsza z trzech:**
- Jedyna z dodatnim PnL i WR > 50% na BTC
- SOL: tylko 2 trade'y — za mało danych, wyniki statystycznie nieistotne
- Sharpe 0.28 za niski — ale to tylko 60 dni; potrzeba 1-2 lat dla stabilnej oceny

**S2 (Order Flow) — częściowo działa:**
- 44% WR to poniżej progu opłacalności (potrzeba > 50% przy R:R 1.5:1)
- **Krytyczny problem:** S2 wymaga historycznych danych WhaleCVD (Whale vs Retail CVD split) — system zbiera je od momentu uruchomienia. Brak historii CVD = brak kontekstu order flow. Backtest S2 będzie wiarygodny dopiero po 3-6 miesiącach zbierania danych.
- SOLUSDT: 0 sygnałów — potwierdza brak CVD historii

**S3 (Classic TA) — eliminacja:**
- WR 13% na BTC = katastrofa. EMA crossover + RSI + S/R w tym specyficznym 60-dniowym oknie był kompletnie niepredyktywny
- Możliwe że S3 lepiej działa w innych warunkach (ranging market), ale na trending BTC (maj-lipiec 2025) był destruktywny
- **Rekomendacja: S3 wyłączyć do dalszych badań**

### Analiza per sesja (kluczowy wniosek od pro tradera)

| Sesja | Trade'y | WR | R:R | PnL | Ocena |
|-------|---------|-----|-----|-----|-------|
| **NY 13-16 UTC** | 5 | **80%** | 1.02 | +$67 | ✅ Primary |
| Post-NY (po 16 UTC) | 2 | 100% | — | +$74 | ✅ Continuation |
| London 07-10 UTC | 6 | 33% | 1.44 | -$24 | ⚠️ Judas Swing risk |
| **Asian 02-05 UTC** | 6 | 67% | **0.32** | -$14 | ❌ Asian Range Trap |

**Asian session USUNIĘTA** z pipeline — "Asian to amunicja, nie okno handlu". Azja buduje Asian Range, który Londyn/NY sweepuje. System używa Asian High/Low jako liquidity targets, nie jako punkty wejścia.

**London wymaga dodatkowego filtra** — hipoteza: akceptować London trade tylko gdy B1 sweep trafił w Asian High/Low.

### Wniosek z backtestów

```
Aktywna do paper tradingu: S1 (SMC Sweep) na BTCUSDT / NY session primary
Wymaga danych (6+ mies.):  S2 (Order Flow)
Wyłączona do dalszych badań: S3 (Classic TA)
Usunięta sesja: Asian (02-05 UTC) — R:R=0.32, Asian Range Trap
```

**Uwaga o statystyce:** 60 dni i 13-15 trade'ów to za mało dla pewności (potrzeba min. 300 trade'ów). Wyniki są **wskazujące**, nie **ostateczne**. Kontynuować paper trading przez minimum 3 miesiące przed jakimikolwiek wnioskami.

---

## 7. Czego system NIE robi

- ❌ Nie otwiera pozycji automatycznie (paper-only, live execution nie jest zaimplementowane)
- ❌ Nie zarządza pozycją automatycznie po wejściu (monitoring + alerty tylko)
- ❌ Nie używa ML ani automatycznej optymalizacji parametrów
- ❌ Nie handluje podczas ekstremalnych warunków rynkowych (fat tail events)
- ❌ Nie handluje parami bez wystarczających danych historycznych
- ❌ Nie gwarantuje zysku — edge statystyczny może się zmienić

---

## 8. Przed live trading — checklist

- [ ] Backtest Sharpe > 1.5 na 3 latach danych (każda strategia osobno)
- [ ] MaxDD < 20% w backtestach
- [ ] Trade count > 300 na 3 lata
- [ ] Monte Carlo ruin probability < 1%
- [ ] Paper trading ≥ 3 miesiące z rozbieżnością < 20% vs backtest
- [ ] News Calendar API podłączone (zastąpić hardcoded _EVENTS_2026)
- [ ] Live execution zaimplementowane (Binance REST API)
- [ ] MAX_RISK_PER_TRADE = 0.005 (nie zmieniać bez kolejnego backtestu)
- [ ] BINANCE_TESTNET=False tylko po wszystkich powyższych

---

## 9. Potencjalne ulepszenia (backlog)

### Wysokie ROI
- **Liquidation clusters jako TP target** — forceOrder streamowany ale nie używany; agregacja poziomów likwidacji wskazuje gdzie cena "magnetycznie" dąży
- **Agent diversity** — 4 agenci widzą ten sam TradeContext; należy rozdzielić na orthogonal views (HTF only / Order Flow only / Execution / Risk)
- **OI jako gate** — OI rośnie + cena rośnie = świeże longi (zdrowe); OI spada + cena rośnie = covering (słabe)
- **AMD Power of 3** — Asian Range accumulation → London manipulation (sweep) → NY distribution; killzony jako maszyna stanowa

### Średnie ROI
- **Entry: OTE 62-79%** zamiast 50% mid-FVG (złoty pocket Fibonacciego)
- **SL dynamiczny** — ATR percentile rank zamiast stałego 0.2× (tight w squeeze, wider w trending)
- **Inducement filter** — fake sweep przed prawdziwym sweepem; drugi sweep w 60 min = bait, nie signal

### Kluczowe (bloker live)
- **Live execution** — Binance Futures REST API: order placement, OCO, partial fills, reconciliation (~2-3 tygodnie)
- **News Calendar API** — Trading Economics lub CoinMarketCal zamiast hardcoded list

---

_Dokument generowany przez Claude Code. Przegląd co miesiąc. Zmiany parametrów TYLKO po walidacji backtestowej._
