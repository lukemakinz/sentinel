# S44C — dynamiczny filtr płynności

## WYNIK (dopisane po uruchomieniu, 2026-09-15)

**Odrzucona na bramce walidacyjnej.**

| Okno | PF base | PF stress | Fille | Wynik $ |
|---|---:|---:|---:|---:|
| rozwojowe | 1,30 | 0,77 | 80 | +$5,29 |
| **walidacyjne** | **0,95** | 0,78 | 34 | -$0,35 |

Rozwojowe przeszło bramkę (>1,05), ale walidacja nie (wymagane >1,10).
Gorzej niż S43 z prymitywnym filtrem godzinowym (walidacja PF 1,48/1,04).

### Diagnostyka: PF grupy odfiltrowanej vs zachowanej (dokładnie ta, o
którą proszono)

Wszystkie kandydaty (order block + reżim + OBV + OI, bez bramki
płynności) puszczone razem przez silnik egzekucji, potem podzielone po
fakcie według tego, czy `liquidity_ok` było True czy False w chwili
wejścia:

| Okno | Grupa | PF | Win rate | Wynik $ |
|---|---|---:|---:|---:|
| rozwojowe | ZACHOWANA (liquidity_ok=True) | **1,90** | 56% | +$6,77 |
| rozwojowe | ODRZUCONA (liquidity_ok=False) | 0,97 | 35% | -$4,69 |
| **walidacyjne** | ZACHOWANA (liquidity_ok=True) | **1,11** | 45% | -$1,08 |
| **walidacyjne** | ODRZUCONA (liquidity_ok=False) | **2,91** | 60% | **+$2,13** |

**Podział całkowicie się odwraca między oknami.** W developmencie filtr
wygląda jak czysty rozdzielacz dobrych i złych transakcji (1,90 vs 0,97)
— dokładnie to, czego szukaliście. Ale w walidacji (dane nieużyte do
zbudowania filtra) grupa "odrzucona" radzi sobie **lepiej** niż grupa
"zachowana". To nie jest szum przy małej próbce z jednej strony — to
całkowita zamiana ról.

### Wniosek

Rozdzielczość filtra w developmencie nie jest stabilną właściwością
rynku — jest specyficzna dla okresu, na którym została zaobserwowana.
Dokładnie ten sam wzorzec regresji do średniej, widziany już wcześniej
w tym projekcie (S24→S28, S30, S40→S41, S43 retrospektywne). Hipoteza o
"realnej płynności jako lepszym filtrze niż godziny UTC" nie potwierdza
się w tych danych — nie dlatego, że sam pomysł jest zły, ale dlatego, że
`turnover_proxy`/`ATR%` w tym oknie 7-dniowym nie mierzy niczego, co
utrzymuje moc predykcyjną w czasie.

---

## Cel

Sprawdzić jedną konkretną hipotezę:

Czy słabość S43 wynika częściowo z tego, że filtr:

07:00–20:00 UTC

jest tylko przybliżeniem rzeczywistej płynności rynku?

S43 pokazało, że selekcja momentu wejścia ma znaczenie,
ale sztywne godziny UTC nie mierzą bezpośrednio aktywności rynku.

S44C zastępuje zegar filtrem opartym na aktualnych danych rynkowych.

---

## Zasada eksperymentu

Zmienia się tylko jedna rodzina warunków:

S43:

    session_start <= hour < session_end

S44C:

    turnover_proxy >= historyczny percentyl 60%

ORAZ

    ATR / price <= historyczny percentyl 90%

Pozostała logika strategii pozostaje bez zmian.

---

## Rynek

ETHUSDT
SOLUSDT
BNBUSDT

Binance perpetual futures.

---

## Interwał

Sygnały:

15 minut.

Trend:

4h.

ADX:

1h.

---

## Order block

Bez zmian względem S43.

Displacement:

>= 1.5 ATR

Wolumen:

>= 1.2 średniej 20 świec.

Strefa ważna:

32 x 15 minut

czyli około 8 godzin.

Tylko pierwszy retest strefy.

---

## Trend

Long:

cena 4h powyżej EMA200
i dodatnie nachylenie EMA.

Short:

cena 4h poniżej EMA200
i ujemne nachylenie EMA.

Dodatkowo:

ADX 1h >= 20.

---

## OBV

Long:

OBV > EMA9 OBV.

Short:

OBV < EMA9 OBV.

---

## Open Interest

W czystym eksperymencie S44C zachowujemy dokładnie logikę S43.

Long:

OI change >= 0.

Short:

OI change <= 0.

Jest to celowe.

S44A przetestowało osobno zmianę OI i nie poprawiło wyniku.

Nie wolno jednocześnie zmienić OI i filtra płynności,
jeśli chcemy wiedzieć, który element odpowiada za wynik.

---

# Nowy filtr S44C

## Turnover proxy

Dla każdej świecy 15m:

    turnover = close * volume

Następnie obliczany jest 60 percentyl turnover
z poprzednich 7 dni.

Bieżąca świeca NIE uczestniczy w obliczeniu własnego progu.

Kod używa:

    shift(1)

przed rolling quantile.

Warunek:

    current turnover >= historical p60

---

## Volatility shock filter

Obliczamy:

    ATR_pct = ATR / close

Następnie wyznaczamy 90 percentyl ATR_pct
z poprzednich 7 dni.

Warunek:

    current ATR_pct <= historical p90

Czyli strategia nie handluje podczas najbardziej
ekstremalnych około 10% warunków zmienności.

---

## Dlaczego dwa warunki?

Duży wolumen sam w sobie nie musi oznaczać
dobrego execution.

Ogromny wolumen może pojawić się podczas:

- likwidacji,
- flash move,
- news shock,
- panic move.

Dlatego wymagamy:

wysokiej aktywności

ALE

bez ekstremalnego volatility shock.

---

## Lookback

7 dni:

    672 świece 15m.

Minimum historii przed aktywacją filtra:

    192 świece

czyli 2 dni.

---

# Zarządzanie pozycją

Bez zmian względem S43 / S20 H1.

Initial stop:

za order blockiem + 0.15 ATR.

Przy:

    +1.5R

aktywowany jest breakeven / trailing.

Trailing:

    2.5 ATR.

Twardy target:

    +8R.

Maximum holding:

    240 minut.

---

# Kapitał

Kapitał testowy:

    $250.

Risk per trade:

    $0.50.

Czyli:

    0.2% equity.

Leverage podczas testu edge:

    5x.

Nie zwiększamy leverage podczas tego eksperymentu.

Powód:

zmiana sizingu zmieniłaby wynik finansowy,
ale nie odpowiedziałaby na pytanie,
czy filtr poprawia expectancy strategii.

---

# Kryteria decyzji

S44C nie jest oceniane na podstawie samego zysku w dolarach.

Najpierw:

1. Profit Factor base.
2. Profit Factor stress.
3. Liczba transakcji.
4. Wynik na poszczególnych symbolach.
5. Max drawdown.
6. Expectancy w R.
7. Stabilność w kolejnych oknach czasowych.
8. Koncentracja zysku.

---

## Minimalny warunek zainteresowania

Development:

    PF base > 1.10

oraz sensowna liczba transakcji.

Stress:

preferowane:

    PF stress >= 1.00

Jeszcze lepiej:

    PF stress > 1.10.

---

## Najważniejsza bramka

Strategia nie może zostać zaakceptowana tylko dlatego,
że działa w development.

Musi przejść:

development

-> validation

-> retrospective / unseen

-> forward paper trading.

---

# 30x

30x NIE jest częścią S44C.

Jeśli S44C pokaże stabilny edge,
kolejny eksperyment powinien dotyczyć osobno execution/sizing.

Wtedy można testować:

exchange leverage:

    30x

ale realny notional powinien być liczony:

    position_notional =
        risk_usd / stop_distance_pct

a nie:

    equity * 30.

Przykład:

equity:

    $250

risk:

    1% = $2.50

stop:

    0.5%

notional:

    2.50 / 0.005
    = $500

czyli:

    2x equity

mimo że kontrakt może mieć ustawione leverage 30x.

30x służy wtedy do efektywności marginu,
a nie do ryzykowania całego konta.

---

# Najważniejsza zasada

Najpierw udowadniamy edge.

Potem skalujemy edge.

Nigdy odwrotnie.
