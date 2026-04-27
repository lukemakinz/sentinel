# S1C Reclaim Baseline — 2026-04-27

Ten plik jest checkpointem strategii po serii ulepszeń:
- top-down bias `1D -> 4H -> 1H -> 15m`
- `S1C` reclaim profile
- `regular + hidden divergence`
- `OBV confirmation`
- `price action displacement trigger`
- `FVG freshness: fresh / partial / stale`
- runner-heavy exits dla `S1C`

Jeśli kolejne zmiany pogorszą wyniki, to ten stan traktujemy jako nowy punkt startowy do rollbacku logicznego.

## Aktualny preferowany profil

- strategia: `S1C`
- stop profile: `tight`
- konto testowe: `$100`
- risk per trade: `0.5%`
- margin mode: `isolated`
- leverage: `10x` default, `20x` tylko high conviction

## Growth Variant

Dodatkowy wariant wzrostowy, który traktujemy jako nowy punkt odniesienia dla dalszych prób:

- strategia: `S1C`
- stop profile: `tight`
- konto testowe: `$100`
- risk per trade: `2.0%`
- margin mode: `isolated`
- leverage: `10x` default, `20x` tylko high conviction
- top-quality reclaim może dostać:
  - większy `size_multiplier`
  - większy `margin_cap_multiplier`
  - większą koncentrację kapitału w portfolio

## Wyniki referencyjne

### Krótsze okno

- zakres: `2025-05-01` do `2025-07-01`
- `S1C tight`
- trade'y: `10`
- win rate: `100.00%`
- PnL: `+$6.24`
- max drawdown: `0.00%`
- Sharpe: `0.81`
- expected value: `+0.62`

### Dłuższe okno

- zakres: `2024-01-01` do `2025-07-01`
- `S1C tight`
- trade'y: `12`
- win rate: `91.67%`
- PnL: `+$6.58`
- max drawdown: `0.48%`
- Sharpe: `0.626`
- expected value: `+0.55`

### Multi-Symbol Snapshot

Zakres `2025-05-01` do `2025-07-01`, profil `S1C tight`:

- `BTCUSDT`: `10` trade'ów, `PnL +$6.24`, `WR 100.00%`
- `ETHUSDT`: `3` trade'y, `PnL +$2.04`, `WR 100.00%`
- `SOLUSDT`: `0` trade'ów, `PnL $0.00`
- `BNBUSDT`: `0` trade'ów, `PnL $0.00`

Zakres `2024-01-01` do `2025-07-01`, profil `S1C tight`:

- `BTCUSDT`: `12` trade'ów, `PnL +$6.58`, `WR 91.67%`
- `ETHUSDT`: `3` trade'y, `PnL +$7.48`, `WR 100.00%`
- `BNBUSDT`: `2` trade'y, `PnL +$2.16`, `WR 100.00%`
- `SOLUSDT`: `0` trade'ów, `PnL $0.00`
- `XRPUSDT`: brak danych w bazie

### Full Calendar Month Snapshot

Zakres `2026-03-01` do `2026-04-01`, profil `S1C tight`:

- `BTCUSDT`: `2` trade'y, `PnL +$2.01`, `WR 100.00%`
- `ETHUSDT`: `3` trade'y, `PnL +$2.47`, `WR 100.00%`
- `SOLUSDT`: `14` trade'ów, `PnL +$5.86`, `WR 100.00%`
- `BNBUSDT`: `12` trade'ów, `PnL +$3.94`, `WR 100.00%`

### Portfolio Snapshot

Zakres `2026-03-01` do `2026-04-01`, `portfolio = BTCUSDT + ETHUSDT + SOLUSDT + BNBUSDT`, profil `S1C tight`, kapitał dzielony równo:

- łączna liczba trade'ów: `31`
- win rate: `96.77%`
- łączny PnL: `+$3.56`
- Sharpe: `0.965`
- expected value: `+0.11`

Wkład per symbol:

- `BTCUSDT`: `+$0.50`
- `ETHUSDT`: `+$0.62`
- `SOLUSDT`: `+$1.46`
- `BNBUSDT`: `+$0.98`

### Growth Snapshot

Zakres `2026-03-01` do `2026-04-01`, profil `S1C tight`, `risk per trade = 2.0%`:

Standalone `$100` na symbol:

- `BTCUSDT`: `2` trade'y, `PnL +$8.91`, `WR 100.00%`
- `ETHUSDT`: `3` trade'y, `PnL +$11.83`, `WR 100.00%`
- `SOLUSDT`: `14` trade'ów, `PnL +$20.74`, `WR 100.00%`
- `BNBUSDT`: `9` trade'ów, `PnL +$7.57`, `WR 100.00%`

Portfolio `$100`, kapitał dzielony równo:

- łączna liczba trade'ów: `28`
- win rate: `100.00%`
- łączny PnL: `+$12.27`
- Sharpe: `1.046`
- max drawdown: `0.00%`

Portfolio `$100`, wariant `alts_focus`:

- wagi: `BTC 12%`, `ETH 18%`, `SOL 40%`, `BNB 30%`
- łączna liczba trade'ów: `29`
- win rate: `100.00%`
- łączny PnL: `+$13.45`
- Sharpe: `0.999`
- max drawdown: `0.00%`

Robustness check dla `2024-01-01` do `2025-07-01`, `risk per trade = 2.0%`:

- portfolio równe: `16` trade'ów, `PnL +$8.34`, `WR 93.75%`
- portfolio `alts_focus`: `12` trade'ów, `PnL +$3.87`, `WR 91.67%`

Wniosek:

- `alts_focus` pomaga w aktywnym miesiącu altów
- na dłuższym oknie przegrywa z równym portfelem
- to powinien być tryb reżimowy, nie stały default

## Najważniejsze ograniczenia tego baseline'u

- trade count nadal jest niski
- większość edge'u pochodzi z reclaim quality, nie z continuation
- system jest dodatni, ale nadal daleko do docelowego wzrostu kapitału
- `XRPUSDT` nie ma obecnie danych w bazie, więc nie wolno porównywać go z pozostałymi parami bez doładowania historii
- `SOLUSDT` i częściowo `BNBUSDT` są nadal zbyt mocno blokowane przez obecną logikę gate'ów i wymagają osobnej optymalizacji pod alts

## Pliki kluczowe dla tego stanu

- `backend/l1_filter/scanner.py`
- `backend/l1_filter/gates_b.py`
- `backend/l1_filter/gates_c.py`
- `backend/l1_filter/fvg.py`
- `backend/l1_filter/mtf.py`
- `backend/executor/l3_calculator.py`
- `backend/backtest/simulator.py`

## Zasada pracy od tego punktu

- jeśli nowe zmiany poprawiają PnL i nie psują sensownie trade count, idziemy dalej
- jeśli nowe zmiany pogarszają wyniki, wracamy logicznie do tego checkpointu i budujemy następną gałąź ulepszeń od tego miejsca
