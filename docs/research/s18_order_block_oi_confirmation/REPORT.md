# S18 — Order block + potwierdzenie open interest / top-trader positioning

Hash zamrożonego protokołu: `1c8e52ca106c8ab4dd55109eeeb432114b44a8287c1df9f13dd4768ba55a542f`.

To badanie retrospektywne. Nowa rodzina dowodów: open interest i pozycjonowanie top-traderów z publicznego archiwum Binance (metrics), nigdy wcześniej nie użyte w tym pipeline. Reżim/struktura/flow/egzekucja identyczne jak w S17.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD MTM |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| oi | development | base | 140 | 52.1% | 0.8839398746657235 | $-3.38 | -1.353% | 4.707% |
| oi | development | stress | 142 | 46.5% | 0.6402097297843035 | $-10.80 | -4.320% | 5.331% |
| oi | development | severe | 126 | 37.3% | 0.455427063391715 | $-14.75 | -5.901% | 6.029% |

- Decyzja dla `oi`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 196, 'validation': 62, 'retrospective_evaluation': 158}.

| oi_toptrader | development | base | 119 | 52.9% | 0.7938056458011241 | $-5.24 | -2.096% | 4.268% |
| oi_toptrader | development | stress | 120 | 46.7% | 0.5311534439655418 | $-12.06 | -4.824% | 5.092% |
| oi_toptrader | development | severe | 113 | 37.2% | 0.3856529849419126 | $-14.77 | -5.910% | 6.036% |

- Decyzja dla `oi_toptrader`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 157, 'validation': 50, 'retrospective_evaluation': 137}.

## Interpretacja

Trasa przegrywająca bramkę development nie jest strojona dalej ani wybierana jako „najmniej zła”. Toptrader (H2) jest ściśle podzbiorem OI base (H1).

Kapitał: $250; jeden wspólny cash/pending/position; stałe ryzyko $0,50; notional do $125; dźwignia do 5x. Base 2/5/2 bps (maker/taker/slippage), stress 5/8/5, severe 10/10/10.
