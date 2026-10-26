# Book A — S73 + BTC (ZAMROŻONE)

**Strategy ID:** `BOOK_A_S73_BTC` (research: S73, S78)  
**Kapitał:** $250 (dedykowana księga)  
**Decyzja:** **FREEZE** — nie optymalizować parametrów bez nowego protokołu. Forward / paper only.

## Co to jest

Codzienny **time-series momentum** na koszyku altów + **noga BTC**, z **filtrem makro**: handel long tylko gdy **BTC close &gt; SMA(200)**. Poza hossą — gotówka (zero alt longów).

To nie scalp SOL/XRP z nitki S47–S67.

## Uniwersum (jak w S73 scratchpad)

- Panel ~14 altów spełniających **min notional ~$5** i **min pozycja $15** przy książce $250.
- Ranking: momentum / trend score (TSMOM), **top 6** pozycji.
- **Long only** (shorty w S74–S76 traciły OOS).
- **Vol targeting:** ~30% rocznej vol na portfel (skaluje wielkość pozycji).

## Reguły wejścia / wyjścia

| Element | Reguła |
|---------|--------|
| Bramka makro | Jeśli BTC &lt; SMA200 → **0%** ekspozycja na altach; noga BTC według wariantu S78 |
| Wariant zamrożony | **S73 + BTC** (BTC w portfelu jako dodatkowa noga trendu, nie tylko filtr) |
| Rebalance | **Cotygodniowy** (nie daily churn) |
| Min rozmiar pozycji | **$15** |
| Max slotów | 6 altów + BTC (wg implementacji S78) |

## Koszty (backtest reference)

| Scenariusz | Koszt obrotu (per side, model) |
|------------|--------------------------------|
| `mexc_taker` | 4 bps |
| `binance` | 7 bps |
| `stress` | 20 bps |

Funding: modelowany osobno w symulacji daily (`simulate()`), nie wliczony w powyższe bps jako „hold fee”.

## Wyniki referencyjne (holdout — nie obietnica live)

Źródło: scratchpad S70–S78 (panel daily, multi-coin). **Nie** w głównym repo w momencie zamrożenia.

| Wariant | ~$/dzień @ $250 | Max DD (orient.) | Uwagi |
|---------|----------------:|------------------|--------|
| S73 H1 | ~0,22 | ~−36% | Bez nogi BTC |
| **S73 + BTC (S78)** | **~0,27** | **~−36%** | **Wariant zamrożony** |
| S73 + BTC + ETH | ~0,31 | ~−42% | Odrzucone vs freeze (większy DD) |
| 2× size | ~0,43 | ~−53% | Odrzucone (DD) |

**Gap do celu portfela $5/dzień:** ~**$4,73/dzień** (przy założeniu Book B = $0).

## Luki znane

- **2022 / długi bear:** ~$0 — strategia słusznie wyłączona przez SMA200.
- **2025 chop:** słabsze okresy; zależność od breadth altów.
- **Execution:** rebalance tygodniowy wymaga dyscypliny; slippage na altach może być &gt; modelu 7 bps.

## Operacja (docelowo)

1. Osobne konto / portfel **$250**.
2. Cotygodniowy rebalance wg sygnału (niedziela 00:00 UTC lub stały dzień).
3. Log: pozycje, turnover, funding PnL, **$/dzień** od ostatniego rebalance.

## Czego NIE robić w Book A

- Nie dokładać shortów, funding routera (S77), ani „bounce poza hossą” bez nowego ID strategii.
- Nie scalać z Book B na jednym marginie.
- Nie szukać $5/dzień przez zwiększanie size — już przetestowane (2× → DD −53%).

## Risk overlay (zalecane)

Zamrożony **RM_composite_v1** — breadth + vol BTC + drawdown throttle.  
Szczegóły: [BOOK_A_RISK_OVERLAY_FROZEN.md](./BOOK_A_RISK_OVERLAY_FROZEN.md).

## Powiązanie z repo

- Poprzednik odrzucony: `docs/research/s58_daily_tsmom/` (3 coiny, inny risk frame).
- Kod S73: do przeniesienia z scratchpada → `backend/backtest/` (task osobny).

**Hash protokołu:** _pending po imporcie kodu i `protocol.json`._
