# S46 — protokół forward paper trading (zamrożony 2026-09-15)

> **ANULOWANY 2026-09-15.** Pełny system (weto aplikowane przed
> `execute_cluster`, z przeliczoną arbitrażą wspólnego slotu pozycji) dał
> 231 transakcji, +$1,79 base / -$20,15 stress w 13 miesięcy —
> ~5500x poniżej celu $25/dzień, i stratę pod kosztami stress. Diagnostyka
> per-trade (S45c: β=-0,593R) nie przełożyła się na działający system po
> uwzględnieniu, że usunięcie transakcji zmienia, która inna transakcja
> wygrywa wspólny slot pozycji. **S46 odrzucone jako strategia handlowa.**
> Ten dokument pozostaje jako zapis zamrożonego, ale ostatecznie
> nieuruchomionego planu — poniższa treść nie jest już aktualnym planem
> działania.

Reguła: **S20 H1 + funding_rate < 0 → odrzuć sygnał**, nic więcej
(patrz `protocol.json` i `../../backend/l1_filter/order_block_oi_funding_veto_scalp.py`).
Charakterystyka historyczna (IN-SAMPLE/DISCOVERY-AFFECTED, nie bramka):
development PF 1,11, walidacja PF 1,50, retrospektywa PF 0,83 base/0,40
stress; łącznie 231 transakcji, +$1,79 base / -$20,15 stress w 13 miesięcy.

Ten dokument jest zamrożony **przed** zebraniem jakiejkolwiek transakcji
forward. Kod decyzyjny w `backend/backtest/s46_forward_decision.py` jest
jedynym kodem uprawnionym do wydania werdyktu — progi nie mogą być
zmieniane po rozpoczęciu zbierania danych.

## Dlaczego to zajmie miesiące, nie tygodnie

Historyczna częstość S46: **~0,58 transakcji/dzień** łącznie na
ETH/SOL/BNB (231 transakcji / 396 dni). Przy tej częstości:
- 30 transakcji ≈ 51 dni
- 100 transakcji ≈ 171 dni (~5,7 miesiąca)
- 200 transakcji ≈ ~342 dni (~11,2 miesiąca)

To nie jest szybki test. Jest to wprost konsekwencja tego, że S46 to
selektywna, rzadka strategia — nie da się tego przyspieszyć bez zmiany
samej strategii (czego świadomie nie robimy teraz).

## Harmonogram punktów kontrolnych

### Checkpoint A — wczesne ostrzeżenie (n≥30 LUB 60 dni kalendarzowych)
Wyłącznie do wykrycia katastrofy. **Nie jest punktem decyzyjnym GO.**
Jedyna możliwa akcja: KILL przez circuit breakery (patrz niżej).

### Circuit breakery — sprawdzane cały czas, niezależnie od checkpointów
- Skumulowany PnL ≤ **-$20** (gorzej niż najgorsze historyczne okno pod
  kosztami stress: -$11,90) → natychmiastowy KILL.
- Seria strat ≥ **13** transakcji z rzędu (historyczne maksimum: 9,
  development) → natychmiastowy KILL.

Te progi nie czekają na żaden checkpoint — działają od pierwszej
transakcji.

### Checkpoint B — główny punkt decyzyjny (n≥100 **ORAZ** ≥180 dni — czeka się na wolniejszy z dwóch warunków)
Liczone: PF rzeczywisty (z prawdziwych wypełnień paper), PF pod replay
kosztów stress (5/8/5/5 bps, ta sama skala co cały projekt), oraz
**tygodniowy block bootstrap** 95% CI dla średniego R (2000 resampli,
resampluje się całe tygodnie ISO, nie pojedyncze transakcje — to
bezpośrednia odpowiedź na ograniczenie, które sami wskazaliście przy
S45c: pojedyncze transakcje mogą być skorelowane w czasie).

| Wynik | Decyzja |
|---|---|
| PF>1,10 I PF_stress≥1,00 I dolna granica CI dla E[R] > 0 | **GO** |
| PF≤1,00 LUB górna granica CI dla E[R] ≤ 0 | **KILL** |
| Dodatni, ale niejednoznaczny (CI obejmuje zero) | **CONTINUE** → Checkpoint C |

### Checkpoint C — ostateczny (n≥200 **ORAZ** ≥360 dni), tylko jeśli B dało CONTINUE
Dokładnie ten sam test co w B. **Jedno przedłużenie, bez wyjątków.**
Jeśli tu wynik nadal nie spełnia progu GO → **FORCED_KILL**, niezależnie
od tego, jak "obiecująco" wygląda punktowy estymator. Zero dalszych
przedłużeń — to zamyka temat na dobre, zapobiegając nieskończonemu
"jeszcze trochę poczekajmy".

## Co NIE jest dozwolone w trakcie monitoringu

- Zmiana progu funding (np. -0,001%, magnitude, średnia krocząca).
- Łączenie z S44A (poprawka OI), S44C (filtr płynności) lub reżimem z S45.
- Zmiana sizingu/dźwigni przed osiągnięciem GO.
- Przesuwanie checkpointów albo progów PF/CI po zobaczeniu wyniku
  częściowego.
- Wybieranie "najlepszego" podzbioru symboli w trakcie monitoringu.

Każde z powyższych zniszczyłoby dokładnie to, co odróżnia S46 od
wszystkich 45 wcześniejszych wariantów w tym projekcie: regułę
zamrożoną przed zobaczeniem nowych danych.

## Wymagania operacyjne (nierozwiązane, do decyzji)

Zbieranie transakcji forward wymaga działającego trackera —
infrastruktura (`scalp_monitor`, Celery/Redis) została zbudowana
wcześniej w tym projekcie dla S20, ale napotkała problemy z pamięcią na
tym Macu (nierozwiązane w tej sesji). Do uruchomienia S46 forward trzeba:
1. zaktualizować logikę `scalp_monitor` o weto funding (jedna dodatkowa
   linia, analogicznie do `order_block_oi_funding_veto_scalp.py`),
2. rozwiązać problem Celery/Redis na tym Macu **albo** przenieść na
   Raspberry Pi.

To decyzja operacyjna, nie badawcza — czeka na wybór.

## Po GO

Dopiero wtedy: osobny, odrębny eksperyment sizingowy (0,5%/1%/1,5%/2%
ryzyka na trade, notional 2-6x equity, dźwignia 30x jako narzędzie
marginu a nie ekspozycji, Monte Carlo ruin/drawdown) — nie wcześniej,
zgodnie z ustaloną kolejnością: najpierw dowód przewagi, potem
skalowanie.
