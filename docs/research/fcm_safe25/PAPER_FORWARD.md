# FCM_SAFE25 paper-forward runbook

Status: enabled for observation only. No code path in `carry_monitor` submits an order.

The first valid new decision after protocol freeze is 2026-11-01 00:00 UTC, with paper entry or reset at 01:00 UTC. The task uses only completed October funding and completed daily spot closes.

## Frozen paper behavior

- Universe: ETHUSDT, SOLUSDT, BNBUSDT.
- Qualify only when prior-month funding is at least 50 bps, the completed 30-day spot return is positive, and the latest completed daily close is above EMA50.
- Select the qualified symbol with the highest prior-month funding.
- Cap spot notional at $25, round down to the current common spot/futures quantity step, and paper-short exactly the same base quantity.
- Attribute $200 to isolated futures margin and retain the remainder as operational reserve. Never top up and never dynamically rehedge.
- Close and reopen both paper legs monthly, including when the selected symbol is unchanged.
- Every minute, inspect the latest completed mark 1m high. Paper-unwind both legs on the next observation if exit-ready futures equity is below $125 or mark leverage is above 0.75x; remain in cash until the next monthly decision.
- Store base, stress-50-bps and severe-80-bps PnL separately. Positive funding never increases the safety buffer; adverse funding reduces it.

## Promotion rule

Live trading remains disabled for at least 18 calendar months and until at least 12 closed prospective episodes exist. Promotion additionally requires positive aggregate stress PnL, no safety event, reconciled funding and prices, and observed costs no worse than the frozen stress allowance. Historical results cannot replace this waiting period.
