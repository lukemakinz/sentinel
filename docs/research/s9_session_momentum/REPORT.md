# S9 — Session VWAP/EMA Momentum Scalp

S9 to nowa, przyczynowa strategia badawcza na 5m/15m. Trend i reżim wyznacza
1h bias + ADX, lokalizację daje pullback do EMA20 lub VWAP sesyjnego, a wejście
wymaga zamkniętej świecy reakcji. RSI(5), EMA9/20, przyrost CVD i względny
wolumen tworzą próg `x z 4`; nie zastępują obowiązkowego triggera ceny.

Pełny protokół: [`protocol.json`](protocol.json). Przetestowano 16 wariantów:
5m/15m, 2/4 lub 3/4 potwierdzeń, market/limit i TP 1,0R/1,25R.

## Wynik development

Wszystkie warianty były ujemne na train. Najmniej zły wariant,
`S9_session_pullback_15m_2of4_limit_tp100`, osiągnął:

| Okno | Transakcje | Wynik portfela | PF | Dodatnie pary |
|---|---:|---:|---:|---:|
| Train (sie 2025–sty 2026) | 754 | −7,69% | 0,47 | 0/4 |
| Validation (lut–mar 2026) | 183 | −0,70% | 0,75 | 2/4 |

Na walidacji ETH i SOL były lekko dodatnie, ale BTC i szczególnie BNB pozostały
ujemne. Wysoki surowy win rate części par (do około 72%) nie wystarczył, bo
średnia wygrana po kosztach była za mała wobec pełnego stopa.

## Ograniczona próba bliższych celów

Sprawdzono dodatkowo TP 0,60R/0,75R/0,90R, czas 45/75 minut, bez częściowego
wyjścia i trailing stopu. Wszystkie sześć kombinacji ponownie straciło na train
i validation; najlepsza walidacja miała −0,54% i PF 0,77. Szczegóły są w
[`geometry_probe.json`](geometry_probe.json).

## Decyzja

S9 został odrzucony już w development, więc nie zużyto sierpniowego holdoutu na
wybór „najmniej złego” wariantu. Kod i wyniki pozostają do audytu, ale strategia
nie kwalifikuje się nawet do paper tradingu.
