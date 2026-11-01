# S7: wynik implementacji i backtestów

**Kierunek badawczy zamknięty. Po >150 przetestowanych wariantach (ta runda +
liquidity sweep/absorption/exhaustion/breakout/squeeze/ICT FVG + finalny
wariant trend-only, patrz [raport finalny](s7_trend_only/REPORT.md)) żaden nie
utrzymał profit factor >1 po kosztach na holdout na większości par. Zgodnie z
pre-zarejestrowaną regułą stop dalsze poszukiwanie nowych kombinacji
wskaźników w tym schemacie zostało zaniechane.**

## Co zostało sprawdzone

- 9 konfiguracji: reclaim przy Volume Profile, hybryda reclaim + kontynuacja,
  benchmark momentum bez profilu; 5m/15m; progi 2/3/4 z 5; trailing vs stałe wyjścia.
- 4 pary: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, kontrakty Binance USD-M.
- Dane 1m: grudzień 2025–marzec 2026 oraz rozgrzewka koniec lipca i sierpień 2026.
- 108 przebiegów symulacji, 15 608 zamkniętych transakcji łącznie z powtórzeniami
  między wariantami i scenariuszami kosztów — **nie** 15 608 niezależnych obserwacji.
- Train: 3 grudnia–31 stycznia; validation: luty; holdout: marzec.
  Po ujemnych wynikach aktywnych wariantów sprawdzono dodatkowy, wcześniej
  nieanalizowany sierpień, bez zmiany parametrów.
- Wszystkie 193 testy modułów `backtest` i `l1_filter` przeszły, w tym 14 nowych
  testów egzekucji, rozliczania kosztów i braku wpływu przyszłych świec na sygnały.

## Częstotliwość została osiągnięta w lutym, ale ze stratą

Hybryda 5m, 3/5, z trailingiem. Wynik procentowy względem osobnego konta 10 000 USD
na parę; ryzyko maksymalnie 0,25% na wejście, nominał do wartości kapitału.

| Para | Wejścia w lutym | Średnio / dobę | Dni z ≥3 wejściami | Wynik netto | Maks. obsunięcie |
|---|---:|---:|---:|---:|---:|
| BTC | 151 | 5,39 | 67,9% | −11,30% | 11,66% |
| ETH | 176 | 6,29 | 75,0% | −8,47% | 10,40% |
| SOL | 171 | 6,11 | 75,0% | −10,61% | 11,36% |
| BNB | 147 | 5,25 | 67,9% | −6,61% | 7,40% |

Hybryda 15m miała w lutym 2,86–3,18 wejścia na dobę, ale również straty:
od −0,86% do −4,37%. Samo wolniejsze wejście nie naprawiło strategii.

## Późniejszy test: sierpień 2026

Ta sama hybryda 5m, bez dopasowywania parametrów do sierpnia:

| Para | Wejścia | Średnio / dobę | Dni z ≥3 wejściami | Wynik netto | Maks. obsunięcie |
|---|---:|---:|---:|---:|---:|
| BTC | 74 | 2,39 | 38,7% | −3,86% | 4,07% |
| ETH | 91 | 2,94 | 51,6% | −5,02% | 5,06% |
| SOL | 124 | 4,00 | 51,6% | −10,40% | 10,42% |
| BNB | 78 | 2,52 | 38,7% | −6,48% | 6,85% |

Benchmark momentum bez lokalizacji przy profilu dawał w sierpniu 4,61–7,58
wejścia na dobę, lecz stracił 9,84–18,84%. Pokazuje, że można zwiększyć liczbę
wejść, ale nie oznacza to poprawy wyniku. Hybryda 15m również była ujemna.

## Dlaczego nie rekomenduję live

1. **Brak przewagi po kosztach.** W lutym aktywna hybryda 5m miała na wszystkich
   parach ujemny PnL już po samym poślizgu, przed prowizjami. Prowizje dodatkowo
   kosztowały około 596–649 USD na parę. To nie jest wyłącznie problem taryfy opłat.
2. **Obowiązkowe dywergencje są zbyt rzadkie.** Bazowy reclaim 5m dawał w grudniu
   i styczniu 3–6 transakcji na parę przez 60 dni. Diagnostyczny „zwycięzca” selekcji
   to niemal nieaktywny reclaim 15m, który stracił najmniej. Nie spełnia celu
   częstotliwości i nie ma wystarczającej próby, żeby oceniać jego skuteczność.
3. **Trailing nie naprawił wejść.** Porównanie z tym samym wariantem 5m bez
   przesuwania stopa nie wykazało dodatniego wyniku. Nie można na tej podstawie
   uznać żadnej polityki wyjścia za zyskowną.
4. **Częstotliwość zależy od okresu.** Nawet średnia 4/dobę na SOL oznaczała
   w sierpniu 8 dni bez wejścia. Nie jest to minimalna liczba każdego dnia.

## Założenia i ograniczenia

Opłata 0,05% oraz poślizg 0,02% na stronę; dodatkowo historyczny funding.
Przetestowano też 0,05% poślizgu na stronę. Filtr kosztowy działa ponownie w
scenariuszu stresowym, więc liczba transakcji może się zmniejszyć.

Profil wolumenu jest przybliżony ze świec 1m, a nie rekonstruowany z transakcji
tickowych. Funding wykorzystuje otwarcie minuty jako przybliżenie mark price.
Brakuje modelu order booka, opóźnień i odrzuceń giełdowych. Testy są niezależne
dla par, nie przedstawiają wyniku wspólnego portfela. Szczegóły w specyfikacji.

## Finalny test: trend-only VP reclaim (dodatek po decyzji o zamknięciu)

Zamiast kolejnej rundy nowych wskaźników wykonano jeden ostatni, zdyscyplinowany
test z regułą stop ustaloną z góry: obowiązkowy trend 4h bez wyjątku na
odwrócenie, jedna reguła wejścia (reclaim VAL/VAH zgodny z trendem, bez
zliczania punktów), bez celu liczby transakcji, na nowym oknie holdout
(kwiecień–lipiec 2026, nieużywanym wcześniej w S7).

Wynik: BTCUSDT nie zawarł żadnej transakcji w 4 miesiącach holdout. Pozostałe
pary miały nieliczne wejścia (0–21/miesiąc zależnie od dźwigni/scenariusza) z
profit factor 0,39–1,19 — bez spójnej przewagi. Warunek stop ("PF>1 dla ≥3 z 4
par") nie został spełniony. Szczegóły: [raport](s7_trend_only/REPORT.md).

**To potwierdza zamknięcie kierunku.** Mechanizm jest strukturalny, nie tylko
kwestią próby: wymóg zgodności z trendem i reguła reclaim (typowo zachowanie
zakresu/odwrócenia) w dużej mierze się wykluczają, a tam gdzie sygnały jednak
przeszły, wynik był ujemny, nie tylko rzadki.

## Rekomendacja

Nie kontynuować szukania nowych kombinacji wskaźników/price-action w schemacie
S7. Sensowną alternatywą na inny profil ryzyka (bliższy "autonomicznemu,
niezachłannemu" celowi) byłaby strategia typu funding rate harvesting / basis
trade zamiast handlu kierunkowego — wymaga to jednak osobnego badania od zera,
z innym modelem ryzyka (funding flip, ryzyko giełdy, zarządzanie hedgem), a nie
kontynuacji obecnego kodu S7.

Nie zmieniono skanera live ani egzekutora. Moduł S7 można uruchamiać niezależnie
z poleceń opisanych w specyfikacji, wyłącznie w celach badawczych/archiwalnych.

## Pliki

- [Specyfikacja i polecenia odtworzenia](../s7.md)
- [Pełne wyniki pierwszego eksperymentu](s7_scalping/REPORT.md)
- [Wyniki dodatkowego sierpnia](s7_forward/REPORT.md)
- [Finalny test trend-only i formalne zamknięcie kierunku](s7_trend_only/REPORT.md)
- [Parametry eksperymentu](s7_scalping/protocol.json)
- [Wybór przed marcowym testem](s7_scalping/selection.json)
- [Pochodzenie i sumy kontrolne danych](s7_scalping/data_manifest.json)

W katalogach wyników zapisano każdą transakcję, wyjścia częściowe, prowizje,
funding, dobowe liczby wejść i próbki equity. Surowe archiwa w cache są poza repozytorium.
