# S87 — Strong Level Retest

Hash zamrożonego protokołu: `a9f405c584eee5687cf5a9c0c84d2c540adbd47fa4a31eb03472c501c34b518a`.

Jedna trasa: 4h order block + wielokrotnie potwierdzony S/R + jawna 
ocena siły. Limit czeka przed pierwszym re-testem. Badanie jest 
retrospektywne i nie dopuszcza strategii do live.

| Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD MTM |
|---|---:|---:|---:|---:|---:|---:|---:|
| development | base | 1 | 100.0% | Infinity | $1.33 | 0.532% | 0.225% |
| development | stress | 1 | 100.0% | Infinity | $1.18 | 0.472% | 0.207% |
| development | severe | 1 | 100.0% | Infinity | $1.02 | 0.407% | 0.187% |

**Decyzja: REJECTED_AT_DEVELOPMENT_GATE.**

Surowe setupy w dostępnych oknach: {'development': 1, 'validation': 1, 'retrospective_evaluation': 2}.

Kapitał $250; ryzyko 0,20% na trade; jeden globalny pending i jedna 
pozycja; notional maks. 1x equity; lewar maks. 5x. Brak strojenia po 
wynikach. Odrzucony kandydat pozostaje odrzucony.
