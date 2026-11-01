# Book A — risk overlay research

Hash: `7309879733b54143cd5414e1260d25f135f479d2260c238b28013bc1c307de6f`.

## Wskaźniki vs forward 5d (equal-weight alty)

- `btc_vol_percentile`: -0.1365
- `equity_drawdown`: nan
- `pct_days_bull`: 0.6879
- `mom_dispersion`: -0.1135
- `breadth_sma50`: 0.0947
- `btc_vol20_ann`: -0.0635
- `mean_fwd5_when_bull`: 0.0031
- `mean_fwd5_when_bear`: -0.0010

Cel **$5.0/dzień** @ $250.

| Wariant | Okno | PnL | $/dzień | Max DD | Gap $5 |
|---|---|---:|---:|---:|---:|
| baseline | development | $180.91 | $1.182 | -12.5% | $3.82 |
| baseline | validation | $-19.10 | $-0.208 | -17.0% | $5.21 |
| RM_breadth_only | development | $199.75 | $1.306 | -10.6% | $3.69 |
| RM_breadth_only | validation | $-3.86 | $-0.042 | -11.1% | $5.04 |
| RM_vol_only | development | $199.75 | $1.306 | -10.6% | $3.69 |
| RM_vol_only | validation | $-19.10 | $-0.208 | -17.0% | $5.21 |
| RM_drawdown_only | development | $199.75 | $1.306 | -10.6% | $3.69 |
| RM_drawdown_only | validation | $-19.10 | $-0.208 | -17.0% | $5.21 |
| RM_composite_v1 | development | $199.75 | $1.306 | -10.6% | $3.69 |
| RM_composite_v1 | validation | $-3.86 | $-0.042 | -11.1% | $5.04 |
| RM_composite_tight | development | $180.11 | $1.177 | -10.6% | $3.82 |
| RM_composite_tight | validation | $-3.86 | $-0.042 | -11.1% | $5.04 |
