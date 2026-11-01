# S8 — Value Area Mean-Reversion Scalp (maker-first)

Protokół: [`protocol.json`](protocol.json). Wybór przed holdout: [`selection.json`](selection.json).

## Koncepcja

Odwrotność S7 trend-only: handel WYŁĄCZNIE w reżimie zakresu/chopu (ADX(14) 1h
≤20, cena zawarta w ostatnich 24h bez nowego ekstremum), zlecenia limit
(maker) przy VAL/POC/VAH i VWAP±1σ zamiast market/taker, małe częste cele
(0,6-0,8× szerokości Value Area) zamiast dużego R:R. Ryzyko 0,3%/trade
niezależne od dźwigni — dźwignia wpływa tylko na wymaganą marżę.

**Korekta wykonawcza względem specyfikacji:** stop 0,25×ATR blokował 100%
sygnałów na etapie wejścia (istniejący silnik `scalp_simulator` ma twardy
próg minimalnej szerokości stopu 0,5×ATR). Podniesiono do 0,6×ATR, żeby
logika w ogóle mogła zostać przetestowana.

**Ryzyko vs dźwignia — zweryfikowane na realnych transakcjach:** ta sama
pozycja przy 20x i 30x dała identyczną wielkość (0,016465 BTC) i identyczny
PnL (−3,00 USD), różny tylko wymagany depozyt (55,99 USD vs 37,33 USD).
Potwierdza to, że ryzyko na transakcję jest w symulatorze poprawnie
rozdzielone od dźwigni.

## Develop (train grudzień-styczeń, walidacja luty-marzec)

Wszystkie 7 wariantów (5m/15m × TP 0,6/0,7/0,8 szerokości VA, plus limit
czasu 60 min) ujemne na obu etapach. Wybrany (najmniej zły, zgodnie z
protokołem): `S8_mr_15m_tp80` — train −29,4%, walidacja −11,0%, PF≈0,42-0,48.

## Holdout (kwiecień-lipiec 2026, nieużywany wcześniej w S7/S8)

| Para | Transakcje/mies. (śr.) | Win rate | Wynik/mies. (śr.) | PF (zakres) |
|---|---:|---:|---:|---:|
| BTC | ~36 | ~26% | −4,8% | 0,22–0,68 |
| ETH | ~41 | ~29% | −3,7% | 0,42–0,65 |
| SOL | ~53 | ~18% | −6,7% | 0,30–0,64 |
| BNB | ~42 | ~23% | −5,1% | 0,18–0,76 |

**16 z 16 par-miesięcy ujemne.** Win rate 16-32%, profit factor nigdzie
blisko 1,0. Cel częstotliwości (4-10 transakcji/dzień łącznie na portfelu)
został osiągnięty — problemem nie jest brak okazji, tylko ich jakość.

## Dlaczego nie zadziałało

Stop 0,6×ATR (interwał wejściowy) jest wielokrotnie mniejszy niż cel
0,6-0,8× dziennej szerokości Value Area. To, co wygląda na atrakcyjne R:R
na papierze, w praktyce oznacza, że zwykły szum przy granicy zakresu wybija
ciasny stop dużo częściej niż cena dociera do odległego celu. Logika
mean-reversion sama w sobie działa poprawnie (testy jednostkowe na
syntetycznym procesie mean-reverting przechodzą), ale realne dane rynkowe
są zbyt szumiące dla tak asymetrycznej relacji stop/target przy tym
horyzoncie.

## Werdykt

**Brak przewagi. Zgodnie z regułą stop ustaloną w protokole, kierunek S8
zamyka się bez dalszych wariantów.** Nic nie trafiło do skanera live ani
egzekutora.

## Pliki

- `backend/l1_filter/mean_reversion_scalp.py` — logika sygnałów.
- `backend/backtest/run_s8_research.py` — harness train/validation/holdout.
- `backend/backtest/tests/test_scalp.py` — testy nowej logiki (29/29 przechodzi).
- Wyniki: `protocol.json`, `selection.json`, `develop_portfolio.json`,
  `develop_summary.json`, `holdout_portfolio.json`, `holdout_summary.json`,
  surowe transakcje `.json.gz` per para/miesiąc/scenariusz.
