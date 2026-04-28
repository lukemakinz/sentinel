# Automatyzacja Giełdy — Notatka Decyzyjna

Data: `2026-04-28`

## Krótki wniosek

Jeśli celem jest szybkie zrobienie sensownego auto-tradingu pod futures / leverage, lepszym pierwszym wyborem jest `KuCoin`, nie `MEXC`.

## Dlaczego

### KuCoin

Plusy:
- jawnie wspiera futures API,
- ma osobny futures REST i futures websocket,
- wspiera `ISOLATED` / leverage w order payload,
- ma rozbudowane rate limits,
- ma sub-accounts i API keys dla sub-accounts,
- ma sensownie udokumentowane środowisko developerskie.

### MEXC

Plusy:
- ma API,
- ma websocket,
- ma sub-accounts,
- ma proste wejście dla spot API.

Minusy:
- brak sandboxa,
- futures API wymaga przynajmniej KYC i dodatkowego procesu aplikacyjnego,
- dokumentacja i access path są mniej przewidywalne niż dla KuCoin.

## Co to oznacza dla tego repo

Najbardziej sensowna ścieżka:

1. Zbudować `exchange adapter interface`
2. Najpierw zaimplementować `KuCoinFuturesAdapter`
3. Dopiero potem ewentualnie dodać `MEXCAdapter`

## Minimalny zakres pierwszej integracji

- create order
- cancel order
- get open orders
- get open positions
- sync fills
- get mark / last price
- mapowanie precision / tick size / min qty
- isolated margin + leverage config
- healthcheck i reconnect websocket

## Czego nie robić na start

- nie robić naraz `MEXC + KuCoin`,
- nie robić live tradingu zanim paper/backtest semantics nie będą bliżej siebie,
- nie dawać withdrawal permissions botowi.
