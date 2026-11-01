# S114 amendment 1 — data handling only (before any result was seen)

The first full run stopped with `InvalidMarketDataError` on OMUSDT before any
aggregate result was produced. Binance kept publishing flat, zero-volume 1m
candles after the contract stopped trading (the whole 2026-04..09 window had
zero volume). Per the protocol's intent ("simulated until their data ends"), a
trailing run of >= 24 hours without any traded volume is now treated as the end
of that symbol's data. Strategy rules, universe, windows, costs and gates are
unchanged. Implemented in `backend/backtest/broad_universe.py::load_available_minutes`.
