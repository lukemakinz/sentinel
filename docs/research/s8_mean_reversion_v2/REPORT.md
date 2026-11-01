# S8v2 — mean-reversion po korekcie wejścia i geometrii wyjścia

Protokół został zapisany przed holdoutem w [`protocol.json`](protocol.json), a
wariant zamrożony w [`selection.json`](selection.json).

## Co zmieniono względem S8

- wejście dopiero po świecy odrzucenia poziomu VAL/VAH albo pasma VWAP,
- stop za knotem świecy odrzucenia plus bufor `0,12 ATR`,
- cel skrócony do `1,0–1,5 ATR`, w tej samej jednostce co stop,
- brak dokładania nowych wskaźników i brak zmian filtra reżimu.

W develop wszystkie warianty pozostały ujemne. Najmniej zły wariant,
`S8v2_mr_15m_tp100_hold60`, zamrożono przed testem sierpnia 2026.

## Holdout: sierpień 2026, 20x

Kapitał: 1000 USD na parę, ryzyko 0,3% na transakcję. Dźwignia wpływa na
wymaganą marżę, nie na budżet ryzyka.

| Para | Transakcje | Win rate | PF | Wynik | Max DD |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | 20 | 20,0% | 0,13 | −3,82% | 3,82% |
| ETHUSDT | 29 | 44,8% | 0,55 | −1,80% | 2,81% |
| SOLUSDT | 34 | 52,9% | 0,82 | −0,74% | 2,22% |
| BNBUSDT | 22 | 18,2% | 0,12 | −4,18% | 4,18% |
| **Portfel** | **105** | — | **0,39** | **−2,64%** | **2,64%** |

Scenariusz stresowy z poślizgiem 5 bps dał 79 transakcji, PF 0,35 i −2,11%.
Wyniki 20x i 30x są identyczne, bo pozycje ogranicza budżet ryzyka; zmienia się
wyłącznie blokowana marża.

## Werdykt

Korekta rozwiązała błąd koncepcyjny odległego celu, ale nie stworzyła przewagi.
Na holdoucie wszystkie cztery pary były ujemne, a reguła sukcesu (PF > 1 na co
najmniej 3 z 4 par) nie została spełniona. S8/S8v2 pozostają wyłącznie
eksperymentem badawczym i nie mogą zostać podłączone do handlu live.
