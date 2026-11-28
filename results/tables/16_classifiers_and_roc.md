# The course's classification tools on our data (28 Nov)

Train and validation days only; the test week is not read. Rules fixed in the script header before the run.

## 1. Logistic regression: quality of fit (deviance and AIC)

Plain logistic regression (no penalty) on the 4,586,551 train rows of the training roads. Null deviance (intercept only): 518,815. AIC = residual deviance + 2 x (independent columns + 1); smaller is better. Validation deviance per row of the intercept-only model: 0.12806.

| inputs | columns | parameters | residual deviance | deviance explained | AIC | validation deviance per row | validation PR-AUC | validation ROC-AUC |
|---|---|---|---|---|---|---|---|---|
| BASE | 68 | 66 | 373,384 | 28.0% | 373,516 | 0.09783 | 0.2089 | 0.856 |
| BASE + NORM | 76 | 72 | 352,816 | 32.0% | 352,960 | 0.09261 | 0.2573 | 0.873 |
| BASE + NORM + HOP | 110 | 105 | 318,529 | 38.6% | 318,739 | 0.08520 | 0.2934 | 0.914 |
| BASE + NORM + HOP + HIST | 111 | 106 | 307,894 | 40.7% | 308,106 | 0.08188 | 0.3219 | 0.927 |

The frozen lasso (M1) on the same rows: residual deviance 307,904 with 97 non-zero coefficients, against 307,894 for the unpenalised fit: with 4.6 M rows the penalty costs almost nothing in fit.
The rows are not independent (a link's updates 5 minutes apart), so the deviance and AIC differences are far larger than what a formal test could trust; the held-out columns are the evidence we rely on.

## 2. Lasso, ridge and elastic net (windowing validation W6: 4 days, then 2 days at a time)

| model | inputs kept per window | mean of the 6 windows | standard error | pooled PR-AUC |
|---|---|---|---|---|
| lasso, lambda / lambda_max = 0.1 | 10 / 9 / 10 / 10 / 13 / 13 | 0.3148 | 0.0178 | 0.3204 |
| lasso, lambda / lambda_max = 0.01 | 39 / 33 / 39 / 37 / 41 / 42 | 0.3377 | 0.0188 | 0.3431 |
| lasso, lambda / lambda_max = 0.001 | 85 / 83 / 92 / 87 / 91 / 90 | 0.3444 | 0.0196 | 0.3500 |
| lasso, lambda / lambda_max = 0.0003 | 97 / 99 / 103 / 98 / 102 / 100 | 0.3438 | 0.0197 | 0.3495 |
| elastic net, each part = 0.1 | 13 / 12 / 13 / 13 / 14 / 13 | 0.3171 | 0.0178 | 0.3230 |
| elastic net, each part = 0.01 | 41 / 33 / 39 / 37 / 41 / 43 | 0.3377 | 0.0187 | 0.3430 |
| elastic net, each part = 0.0003 | 97 / 99 / 103 / 98 / 102 / 100 | 0.3438 | 0.0197 | 0.3495 |
| ridge, lambda2 = 0.1 | all | 0.3014 | 0.0148 | 0.3042 |
| ridge, lambda2 = 0.01 | all | 0.3377 | 0.0179 | 0.3416 |
| ridge, lambda2 = 0.0001 | all | 0.3439 | 0.0196 | 0.3493 |
| LDA | all | 0.2760 | 0.0287 | 0.2866 |
| QDA (reg_param 0.01) | all | 0.0782 | 0.0097 | 0.0796 |

## 3. Every score on the validation week: PR-AUC, ROC-AUC, and the confusion matrix at our operating rule

Training roads: 1,178,466 rows that are normal now, 13,883 onsets (onset rate 0.0118). Alerts = the top 2% of links at each update. Sensitivity = share of onsets alerted (recall); specificity = share of non-onsets not alerted; accuracy = share of rows classified correctly. A rule that never alerts has accuracy 0.9882.

| score | PR-AUC | ROC-AUC (lowest-highest day) | TP | FP | FN | TN | sensitivity | specificity | precision | accuracy |
|---|---|---|---|---|---|---|---|---|---|---|
| B1 time-of-week rate | 0.0688 | 0.770 (0.679-0.864) | 1,902 | 22,042 | 11,981 | 1,142,541 | 0.137 | 0.9811 | 0.079 | 0.9711 |
| B2 last observation | 0.1284 | 0.771 (0.725-0.798) | 3,295 | 20,649 | 10,588 | 1,143,934 | 0.237 | 0.9823 | 0.138 | 0.9735 |
| pruned tree (one-standard-error rule) | 0.2582 | 0.916 (0.844-0.941) | 4,998 | 18,946 | 8,885 | 1,145,637 | 0.360 | 0.9837 | 0.209 | 0.9764 |
| pruned tree (minimum-error rule) | 0.2683 | 0.923 (0.857-0.945) | 5,021 | 18,923 | 8,862 | 1,145,660 | 0.362 | 0.9838 | 0.210 | 0.9764 |
| LDA | 0.2711 | 0.916 (0.841-0.941) | 5,011 | 18,933 | 8,872 | 1,145,650 | 0.361 | 0.9837 | 0.209 | 0.9764 |
| QDA | 0.0823 | 0.893 (0.845-0.921) | 1,897 | 22,047 | 11,986 | 1,142,536 | 0.137 | 0.9811 | 0.079 | 0.9711 |
| M1 lasso | 0.3220 | 0.927 (0.861-0.950) | 5,266 | 18,678 | 8,617 | 1,145,905 | 0.379 | 0.9840 | 0.220 | 0.9768 |
| M2 random forest | 0.3482 | 0.942 (0.884-0.959) | 5,397 | 18,547 | 8,486 | 1,146,036 | 0.389 | 0.9841 | 0.225 | 0.9771 |

## 4. Thresholds from unequal costs (the forest's calibrated probability)

If a missed onset costs r false alarms, the expected cost is lowest when we alert on p > 1 / (1 + r) (notes, section 4.5). r = 1 is the 0-1 loss with the threshold 0.5. Probabilities: the forest's, calibrated on 3 validation days and applied to the 4th. Cost = (false alarms + r x missed onsets) per 1,000 rows.

| r | threshold | alerts | alerts per update | sensitivity | specificity | precision | cost with this threshold | cost of the top-2% rule | cost of never alerting |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.500 | 2,503 | 3.3 | 0.126 | 0.9993 | 0.697 | 10.94 | 22.94 | 11.78 |
| 5 | 0.167 | 17,606 | 22.9 | 0.433 | 0.9900 | 0.341 | 43.24 | 51.74 | 58.90 |
| 10 | 0.091 | 33,777 | 44.0 | 0.573 | 0.9778 | 0.236 | 72.21 | 87.75 | 117.81 |
| 20 | 0.048 | 62,303 | 81.1 | 0.697 | 0.9548 | 0.155 | 116.09 | 159.76 | 235.61 |
| 50 | 0.020 | 122,516 | 159.5 | 0.826 | 0.9046 | 0.094 | 196.91 | 375.78 | 589.03 |
