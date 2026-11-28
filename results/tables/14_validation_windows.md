# Did we cross-validate properly? The windowing method, as taught, against what we did (28 Nov)

Train days and training roads only; the validation and test weeks are not read. Rules fixed in the script header before the run. PR-AUC unless stated. Every model is fitted on earlier days only and checked on the days that follow (forward validation); nothing is shuffled.

## 1. The windows

W2 = the two frozen windows (each adds a week). W6 = an expanding window that starts with 4 days and adds 2 days at a time.

| scheme | window | fit days | check days | check rows | onset rate | B2 last observation |
|---|---|---|---|---|---|---|
| W2 | 1 | 6 | 26 Oct - 30 Oct | 1,500,002 | 0.0098 | 0.1423 |
| W2 | 2 | 11 | 02 Nov - 06 Nov | 1,463,148 | 0.0148 | 0.1693 |
| W6 | 1 | 4 | 22 Oct - 23 Oct | 580,829 | 0.0050 | 0.1338 |
| W6 | 2 | 6 | 26 Oct - 27 Oct | 611,657 | 0.0081 | 0.1383 |
| W6 | 3 | 8 | 28 Oct - 29 Oct | 590,651 | 0.0111 | 0.1329 |
| W6 | 4 | 10 | 30 Oct - 02 Nov | 569,545 | 0.0105 | 0.1617 |
| W6 | 5 | 12 | 03 Nov - 04 Nov | 600,680 | 0.0119 | 0.1780 |
| W6 | 6 | 14 | 05 Nov - 06 Nov | 590,617 | 0.0196 | 0.1695 |

## 2. The lasso penalty

**W2**

| lambda / lambda_max | inputs kept per window | mean of the window PR-AUCs | standard error | pooled PR-AUC | pooled deviance per row |
|---|---|---|---|---|---|
| x 0.5 | 2 / 2 | 0.2297 | 0.0150 | 0.2398 | 0.10708 |
| x 0.2 | 5 / 8 | 0.2907 | 0.0373 | 0.2962 | 0.09303 |
| x 0.1 | 9 / 12 | 0.3166 | 0.0271 | 0.3210 | 0.08661 |
| x 0.03 | 20 / 19 | 0.3284 | 0.0239 | 0.3326 | 0.08360 |
| x 0.01 | 33 / 36 | 0.3434 | 0.0223 | 0.3472 | 0.08199 |
| x 0.003 | 60 / 70 | 0.3512 | 0.0231 | 0.3551 | 0.08119 |
| x 0.001 | 83 / 86 | 0.3527 | 0.0233 | 0.3566 | 0.08109 |
| x 0.0003 | 99 / 96 | 0.3530 | 0.0231 | 0.3568 | 0.08111 |
| x 0.0001 | 102 / 102 | 0.3530 | 0.0231 | 0.3568 | 0.08113 |

Chosen: mean of the windows (ours): **x 0.0003**; pooled PR-AUC: **x 0.0003**; pooled deviance: **x 0.001**; one-standard-error rule: **x 0.01**.

**W6**

| lambda / lambda_max | inputs kept per window | mean of the window PR-AUCs | standard error | pooled PR-AUC | pooled deviance per row |
|---|---|---|---|---|---|
| x 0.5 | 2 / 2 / 2 / 2 / 2 / 2 | 0.2271 | 0.0129 | 0.2434 | 0.09741 |
| x 0.2 | 6 / 5 / 7 / 8 / 8 / 8 | 0.2928 | 0.0200 | 0.2989 | 0.08429 |
| x 0.1 | 10 / 9 / 10 / 10 / 13 / 13 | 0.3148 | 0.0178 | 0.3204 | 0.07889 |
| x 0.03 | 19 / 20 / 18 / 18 / 20 / 21 | 0.3248 | 0.0177 | 0.3307 | 0.07620 |
| x 0.01 | 39 / 33 / 39 / 37 / 41 / 42 | 0.3377 | 0.0188 | 0.3431 | 0.07487 |
| x 0.003 | 67 / 60 / 70 / 71 / 69 / 69 | 0.3441 | 0.0195 | 0.3498 | 0.07426 |
| x 0.001 | 85 / 83 / 92 / 87 / 91 / 90 | 0.3444 | 0.0196 | 0.3500 | 0.07429 |
| x 0.0003 | 97 / 99 / 103 / 98 / 102 / 100 | 0.3438 | 0.0197 | 0.3495 | 0.07439 |
| x 0.0001 | 99 / 102 / 105 / 101 / 104 / 104 | 0.3435 | 0.0197 | 0.3492 | 0.07444 |

Chosen: mean of the windows (ours): **x 0.001**; pooled PR-AUC: **x 0.001**; pooled deviance: **x 0.003**; one-standard-error rule: **x 0.03**.

## 3. The forest settings (150 trees)

| setting | W6: mean of the windows | standard error | W6: pooled | W6: the six windows | W2: mean of the windows |
|---|---|---|---|---|---|
| sqrt(p) = 9 inputs, leaf 20 | 0.3624 | 0.0185 | 0.3687 | 0.324 0.347 0.315 0.378 0.440 0.371 | 0.3623 |
| max_features 0.35, leaf 20 | 0.3690 | 0.0187 | 0.3758 | 0.327 0.352 0.325 0.384 0.448 0.378 | 0.3712 |
| max_features 0.6, leaf 20 | 0.3683 | 0.0190 | 0.3754 | 0.325 0.353 0.322 0.385 0.448 0.377 | 0.3712 |
| all 96 inputs (bagging), leaf 20 | 0.3607 | 0.0198 | 0.3691 | 0.313 0.338 0.317 0.380 0.442 0.373 | 0.3666 |
| max_features 0.35, leaf 80 | 0.3613 | 0.0192 | 0.3685 | 0.318 0.345 0.315 0.376 0.442 0.372 | 0.3630 |
| max_features 0.6, leaf 80 | 0.3615 | 0.0194 | 0.3688 | 0.315 0.346 0.317 0.376 0.443 0.372 | 0.3643 |

Best on W6 by the mean of the windows: **max_features 0.35, leaf 20**; by the pooled score: **max_features 0.35, leaf 20**. Best on W2 (the 12 frozen settings plus sqrt(p) and bagging), by the mean: **max_features 0.35, leaf 20**.

W2 for the 12 settings of the tuning grid repeats the forests of `06_random_forest.py` (the same rows, settings and seeds).
