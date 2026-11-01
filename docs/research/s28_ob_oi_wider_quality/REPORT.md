# S28 — Wyższy próg jakości OB na szerszym uniwersum (6 symboli)

Hash zamrożonego protokołu: `e4b42952648e8547164e5afb323bdc71c47984e128ca3b4deb4db6f6013f8793`.

To badanie retrospektywne. S24 dało najlepszy PF sesji (1,32) ale za mało filli (22, próg 40) na 3 symbolach — ten protokół testuje ten sam wyższy próg jakości na 6 symbolach.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD MTM |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S28_wider_stronger_structure | development | base | 39 | 38.5% | 0.9863203245522759 | $-0.15 | -0.062% | 2.779% |
| S28_wider_stronger_structure | development | stress | 41 | 36.6% | 0.5492988241899106 | $-5.53 | -2.214% | 3.409% |
| S28_wider_stronger_structure | development | severe | 41 | 34.1% | 0.4983481912596893 | $-6.23 | -2.491% | 2.946% |

- Decyzja dla `S28_wider_stronger_structure`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 80, 'validation': 24, 'retrospective_evaluation': 74}.
- Fille per symbol (development/base): {'ETHUSDT': 11, 'SOLUSDT': 4, 'BNBUSDT': 6, 'XRPUSDT': 6, 'ADAUSDT': 7, 'DOGEUSDT': 5}.

| S28_wider_moderate_both | development | base | 72 | 43.1% | 0.9445929514934216 | $-1.00 | -0.399% | 2.065% |
| S28_wider_moderate_both | development | stress | 73 | 38.4% | 0.5560237039786335 | $-8.70 | -3.480% | 3.693% |
| S28_wider_moderate_both | development | severe | 76 | 32.9% | 0.46062102529689997 | $-11.03 | -4.413% | 4.452% |

- Decyzja dla `S28_wider_moderate_both`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 128, 'validation': 43, 'retrospective_evaluation': 83}.
- Fille per symbol (development/base): {'ETHUSDT': 17, 'SOLUSDT': 13, 'BNBUSDT': 12, 'XRPUSDT': 10, 'ADAUSDT': 13, 'DOGEUSDT': 7}.

## Interpretacja

Trasa przegrywająca bramkę development nie jest strojona dalej ani wybierana jako „najmniej zła”.

Kapitał: $250; jeden wspólny cash/pending/position na klaster 6 symboli. Base 2/5/2 bps (maker/taker/slippage), stress 5/8/5, severe 10/10/10.
