# FCM-1M — monthly filtered funding carry

Hash protokołu zamrożonego przed pobraniem cen: `cc7bf5a9e15c25c19bf819d9949152250e161334ab4e5139820146a952b34008`.

Ten replay usuwa najważniejsze uproszczenie S11: spot, perpetual execution i perpetual mark są trzema osobnymi seriami. Wynik zawiera więc rzeczywisty historyczny basis PnL, a nie sztuczne anulowanie całego price PnL.

| Okno | Koszty | Decyzje z pozycją | Epizody | Funding | Basis price PnL | Fees | Slippage | Net | Zwrot | Max DD MTM |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| development | base | 11/24 | 8 | $61.02 | $-0.81 | $2.66 | $0.44 | $57.10 | 22.840% | 2.159% |
| development | stress | 11/24 | 8 | $60.99 | $-0.81 | $3.33 | $2.22 | $54.64 | 21.855% | 2.163% |
| validation | base | 10/18 | 8 | $13.21 | $0.50 | $1.90 | $0.32 | $11.48 | 4.592% | 0.230% |
| validation | stress | 10/18 | 8 | $13.20 | $0.49 | $2.38 | $1.59 | $9.73 | 3.893% | 0.376% |
| retrospective_evaluation | base | 8/26 | 7 | $4.74 | $-0.07 | $1.72 | $0.29 | $2.67 | 1.066% | 0.353% |
| retrospective_evaluation | stress | 8/26 | 7 | $4.74 | $-0.07 | $2.15 | $1.43 | $1.09 | 0.435% | 0.567% |
| all_available | base | 29/68 | 23 | $78.97 | $-0.40 | $6.29 | $1.05 | $71.23 | 28.493% | 2.159% |
| all_available | stress | 29/68 | 23 | $78.94 | $-0.40 | $7.86 | $5.24 | $65.44 | 26.177% | 2.163% |

Decyzja: **REJECTED_BY_STRESS_SAFETY_GATE**.

## Co dokładnie rozliczono

- Każde wejście kupuje spot za $100 i sprzedaje shortem identyczną liczbę jednostek bazowych; nie wymusza fałszywie równej wartości obu nóg przy niezerowym basis.
- Ledger obejmuje zakup/sprzedaż spot, blokadę/zwolnienie $100 futures margin, variation PnL shorta, każdy funding według mark price i cztery osobne opłaty.
- Stress to pełne 50 bps round trip: 10/5 bps fee i 5/5 bps slippage dla spot/perpetual na każdą stronę.
- Braki godzinowe surowych archiwów są jawne w `data_quality.json`. Najpierw używany jest dokładny timestamp z publicznego 1m; pozostały brak mark może użyć kolejno tego samego godzinowego perpetual, spot lub ostatniego kauzalnego mark wyłącznie do MTM. Spot/perp bez realnego baru nie mogą być fillem; miesięczna akcja czeka najwyżej 168 godzin na wspólny realny open.
- Najniższa diagnostyczna wartość collateral shorta: $-383.96; maksymalna dźwignia mark: 6575.84x. To nie zastępuje dokładnego modelu maintenance margin/liquidation tiers.

## Granica wniosku

To protokół-frozen badanie retrospektywne, nie dowód przyszłego zysku. Nawet dodatni wynik wszystkich bramek dopuszcza wyłącznie paper-forward; wymagane jest co najmniej 12 miesięcy i 12 niezależnych zamkniętych epizodów prospektywnych.
