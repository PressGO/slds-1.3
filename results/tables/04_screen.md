# Feature screen (forward-chaining inside the train days; training roads; onset rows)

Fold 1: fit 16-23 Oct, check 26-30 Oct (base rate 0.0098). Fold 2: fit 16-30 Oct, check 2-6 Nov (base rate 0.0148).
LR = plain logistic regression on the lasso view (hour groups, log rain), scaled on the fit rows. RF = 150 trees, {'max_features': 0.35, 'min_samples_leaf': 80}, 10% of the y = False fit rows.

| inputs | n | LR fold 1 | LR fold 2 | LR mean | RF fold 1 | RF fold 2 | RF mean |
|---|---|---|---|---|---|---|---|
| BASE | 53 | 0.2292 | 0.2687 | **0.2490** | 0.2372 | 0.2892 | **0.2632** |
| BASE+HIST | 54 | 0.2466 | 0.2950 | **0.2708** | 0.2520 | 0.3120 | **0.2820** |
| BASE+HOP | 87 | 0.2730 | 0.3168 | **0.2949** | 0.2757 | 0.3263 | **0.3010** |
| BASE+HOP+HIST | 88 | 0.2923 | 0.3436 | **0.3179** | 0.2877 | 0.3497 | **0.3187** |
| BASE+NORM | 61 | 0.2742 | 0.3147 | **0.2945** | 0.2888 | 0.3400 | **0.3144** |
| BASE+NORM+HIST | 62 | 0.2842 | 0.3265 | **0.3053** | 0.2930 | 0.3481 | **0.3206** |
| BASE+NORM+HOP | 95 | 0.3164 | 0.3608 | **0.3386** | 0.3325 | 0.3800 | **0.3563** |
| BASE+NORM+HOP+HIST | 96 | 0.3299 | 0.3760 | **0.3530** | 0.3370 | 0.3889 | **0.3630** |

Rule (fixed before the run): groups tried in the order NORM, HOP, HIST; a group is kept when it raises that family's mean by at least 0.002.

Chosen: lasso (M1) **BASE + NORM + HOP + HIST**; random forest (M2) **BASE + NORM + HOP + HIST**.
