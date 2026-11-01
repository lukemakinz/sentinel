# S88 — Hourly Strong Level Retest

Hash zamrożonego protokołu: `2b12b8d7420ced033258ed13605e3285328dbff59d3e5395ec2ca8f821fa9dfb`.

Jedna trasa zastępująca zbyt rzadką S87: 1h causalny order block, 
wielokrotnie potwierdzony S/R, score siły i limit oczekujący przed 
pierwszym re-testem. Badanie retrospektywne; brak zgody na live.

| Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD MTM |
|---|---:|---:|---:|---:|---:|---:|---:|
| development | base | 1 | 0.0% | 0.0 | $-0.50 | -0.200% | 0.200% |
| development | stress | 0 | 0.0% | — | $0.00 | 0.000% | 0.000% |
| development | severe | 0 | 0.0% | — | $0.00 | 0.000% | 0.000% |

**Decyzja: REJECTED_AT_DEVELOPMENT_GATE.**

Surowe setupy w oknach: {'development': 12, 'validation': 5, 'retrospective_evaluation': 3}.

Kapitał $250; ryzyko 0,20%; jeden globalny pending i jedna pozycja; 
notional maks. 1x equity; lewar maks. 5x. Brak siatki parametrów i 
brak wyboru „najmniej złej” wersji po wyniku.
