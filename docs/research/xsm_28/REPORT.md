# XSM-28 — cross-sectional beta-neutral momentum

Hash zamrożonego protokołu: `d7dbc97812ddbee754106ee60c8ed199bd49b715a5ae3138622a0b3029d494c3`.

ETH/SOL/BNB są co tydzień rangowane po 28-dniowym return/vol. Para powstaje tylko wtedy, gdy lider ma dodatni zwrot, a maruder ujemny; wagi neutralizują 60-dniową betę do BTC. Obie nogi są jednym epizodem w jednym ledgerze.

| Okno | Koszty | Cele tygodniowe | Epizody | WR | PF | PnL | Zwrot | Max DD | Funding | Opłaty |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| development | base | 28 | 14 | 28.6% | 0.6865834540757667 | $-3.58 | -1.432% | 2.296% | $-0.19 | $0.42 |
| development | stress | 28 | 14 | 28.6% | 0.703150711058703 | $-3.39 | -1.354% | 2.322% | $-0.19 | $0.67 |

Decyzja: **REJECTED_AT_DEVELOPMENT_GATE**.

## Interpretacja

- Stop i target są liczone na łącznym, kosztowym PnL pary po zamknięciu baru 5m; obie nogi wychodzą dopiero na następnym open 5m.
- Funding historyczny, opłata i poślizg są księgowane osobno dla obu nóg.
- Wariant, który nie przejdzie development, nie otwiera kolejnych okien.
- Przejście historycznych bramek oznaczałoby wyłącznie paper-forward; nie jest zgodą na handel live ani obietnicą zysku.
- Mały, trzyaktywowowy przekrój i współdzielone czynniki ryzyka ograniczają siłę wniosku nawet przy dłuższym okresie kalendarzowym.
