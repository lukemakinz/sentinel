# S70 — ta sama para SOL/XRP, bez codziennego obrotu

Hash protokołu: `a68b8e8fbf1e84cbc64919233dfab939ec265be53cae66bb7d195b0aac28f680`.

Sygnał bez zmian względem S68 (20 dni, spread 3%). Zmienia się tylko to, kiedy para jest zamykana. S68 development: około $59 brutto, $38 opłat, $21 netto.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Opłaty | $/dzień | Max DD | $5? |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| hold_until_flip | development | base | 27 | 48.1% | 1.083081415093816 | $15.31 | $4.41 | $0.10 | 23.879% | nie |
| hold_until_flip | development | stress | 27 | 48.1% | 1.0494309830228592 | $9.08 | $6.91 | $0.06 | 23.971% | nie |
| hold_until_flip | development | severe | 26 | 46.2% | 1.1078019794482055 | $20.63 | $8.68 | $0.13 | 20.542% | nie |
| hold_until_flip | validation | base | 5 | 40.0% | 0.9116061392214981 | $-2.06 | $0.65 | $-0.02 | 19.670% | nie |
| hold_until_flip | validation | stress | 5 | 40.0% | 0.8813787134218627 | $-2.77 | $1.03 | $-0.03 | 19.522% | nie |
| hold_until_flip | validation | severe | 5 | 40.0% | 0.8482117343836317 | $-3.56 | $1.26 | $-0.04 | 19.347% | nie |

- Decyzja dla `hold_until_flip`: **REJECTED_AT_VALIDATION_GATE**.

| monday_hold | development | base | 34 | 47.1% | 0.8935947810101069 | $-18.59 | $4.78 | $-0.12 | 25.377% | nie |
| monday_hold | development | stress | 34 | 47.1% | 0.8777033194065557 | $-20.11 | $7.13 | $-0.13 | 25.832% | nie |
| monday_hold | development | severe | 34 | 47.1% | 0.85599879906401 | $-22.30 | $7.87 | $-0.15 | 26.350% | nie |
| monday_hold | validation | base | 5 | 60.0% | 0.695019930097406 | $-4.94 | $0.87 | $-0.05 | 7.262% | nie |
| monday_hold | validation | stress | 5 | 60.0% | 0.6377596951025957 | $-5.94 | $1.38 | $-0.06 | 7.284% | nie |
| monday_hold | validation | severe | 5 | 60.0% | 0.574892574373745 | $-7.06 | $1.69 | $-0.08 | 7.353% | nie |

- Decyzja dla `monday_hold`: **REJECTED_AT_DEVELOPMENT_GATE**.

Nie jest to zgoda na live.
