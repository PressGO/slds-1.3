# Baselines B1 and B2 (train and validation days; data version 4)

Reproduces the baseline numbers of 18 Nov exactly (asserted to 4 decimals in the script).

## B1: m by forward-chaining inside the train days

| m | fold 1 | fold 2 | mean |
|---|---|---|---|
| 0 | 0.0292 | 0.0475 | 0.0384 |
| 12 | 0.0404 | 0.0583 | 0.0493 |
| 48 | 0.0404 | 0.0595 | 0.0500 |
| 192 | 0.0343 | 0.0574 | 0.0458 |
| 768 | 0.0233 | 0.0424 | 0.0329 |
| slot rate only | 0.0185 | 0.0255 | 0.0220 |

Chosen m = **48**. B2 on the same folds: 0.1423 and 0.1693.

## Validation week (Tue 10 - Fri 13 Nov)

| Rows | Scored rows | Onsets | Base rate | B1 PR-AUC | B2 PR-AUC | B1 / B2 precision at top 0.5% | B1 / B2 precision at top 1% | B1 / B2 precision at top 2% |
|---|---|---|---|---|---|---|---|---|
| training roads (main) | 1,178,466 | 13,883 | 0.0118 | 0.0688 | 0.1284 | 0.106 / 0.256 | 0.092 / 0.194 | 0.079 / 0.138 |
| AYE + CTE (transfer) | 428,667 | 6,430 | 0.0150 | 0.0232 | 0.1431 | 0.019 / 0.230 | 0.018 / 0.197 | 0.017 / 0.148 |
