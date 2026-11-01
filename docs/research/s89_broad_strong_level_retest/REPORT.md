# S89 — Broad Strong Level Retest

Hash zamrożonego protokołu: `328814890c93267089e0465c2c4db9e371704ed344a0d3ee94836c80bf9d546f`.

Jedna strategia na ośmiu płynnych rynkach. Niezależne limity mogą 
czekać równolegle, ale konto utrzymuje tylko jedną pozycję. 
Badanie retrospektywne; brak zgody na live.

| Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD MTM |
|---|---:|---:|---:|---:|---:|---:|---:|
| development | base | 22 | 27.3% | 0.6167502878812071 | $-3.05 | -1.220% | 1.271% |
| development | stress | 14 | 28.6% | 0.5287329794940938 | $-2.35 | -0.939% | 1.003% |
| development | severe | 2 | 50.0% | 1.3471282355786895 | $0.17 | 0.070% | 0.200% |

**Decyzja: REJECTED_AT_DEVELOPMENT_GATE.**

Surowe setupy: {'development': 33, 'validation': 17, 'retrospective_evaluation': 11}.

Wykonalne pierwsze re-testy: {'base': {'development': 25, 'validation': 15, 'retrospective_evaluation': 9}, 'stress': {'development': 25, 'validation': 15, 'retrospective_evaluation': 9}, 'severe': {'development': 20, 'validation': 11, 'retrospective_evaluation': 9}}.

Kapitał $250; ryzyko 0,20%; maksymalnie jedna otwarta pozycja; 
notional do 1x equity; lewar do 5x. Wynik odrzucony na dowolnej 
niezaliczonej bramce nie jest strojony ani wdrażany.
