# The course's tree tools on our data: pruning, out-of-bag error, ranking the inputs (28 Nov)

Train and validation days only; the test week is not read. Rules fixed in the script header before the run.

## 1. One decision tree, pruned by cost-complexity

CART (Gini, min_samples_leaf 20) on every onset + 10% of the other fit rows (500,598 rows), the 96 inputs. The pruning path of the tree grown on all train rows has 3,411 steps; 16 sizes were compared. Each size was scored by the windowing validation (6 windows, adding 2 days at a time), growing and pruning inside each window. 'Train' is the PR-AUC on the tree's own fit rows.

| alpha | leaves (all train rows) | depth | train | windowing mean | standard error | the six windows |
|---|---|---|---|---|---|---|
| 0.00e+00 | 6,216 | 51 | 0.8584 | 0.2390 | 0.0155 | 0.200 0.235 0.203 0.244 0.304 0.248 |
| 1.40e-06 | 3,096 | 31 | 0.8412 | 0.2401 | 0.0156 | 0.204 0.234 0.201 0.244 0.305 0.252 |
| 4.20e-06 | 1,709 | 22 | 0.8120 | 0.2514 | 0.0204 | 0.201 0.237 0.202 0.273 0.334 0.261 |
| 7.11e-06 | 963 | 21 | 0.7911 | 0.2671 | 0.0231 | 0.202 0.241 0.228 0.285 0.361 0.285 |
| 1.05e-05 | 536 | 21 | 0.7726 | 0.2753 | 0.0240 | 0.203 0.249 0.239 0.289 0.372 0.300 |
| 1.51e-05 | 282 | 15 | 0.7541 | 0.2841 | 0.0229 | 0.203 0.271 0.253 0.298 0.370 0.309 |
| 2.15e-05 | 147 | 13 | 0.7417 | 0.2807 | 0.0218 | 0.201 0.273 0.256 0.284 0.361 0.308 |
| 3.82e-05 | 83 | 10 | 0.7301 | **0.2873** | 0.0187 | 0.228 0.286 0.254 0.294 0.362 0.300 (minimum error) |
| 6.87e-05 | 47 | 8 | 0.7163 | **0.2804** | 0.0179 | 0.231 0.273 0.243 0.290 0.354 0.292 (one standard error) |
| 1.40e-04 | 28 | 7 | 0.6941 | 0.2568 | 0.0144 | 0.220 0.250 0.222 0.264 0.315 0.270 |
| 2.80e-04 | 16 | 5 | 0.6745 | 0.2431 | 0.0149 | 0.203 0.243 0.203 0.255 0.298 0.257 |
| 5.20e-04 | 10 | 5 | 0.6506 | 0.2296 | 0.0131 | 0.196 0.229 0.195 0.230 0.280 0.248 |
| 1.30e-03 | 6 | 4 | 0.6002 | 0.1913 | 0.0184 | 0.134 0.157 0.178 0.205 0.262 0.212 |
| 2.99e-03 | 4 | 2 | 0.5356 | 0.1652 | 0.0249 | 0.094 0.134 0.113 0.198 0.250 0.203 |
| 4.19e-03 | 3 | 2 | 0.4776 | 0.1261 | 0.0090 | 0.094 0.134 0.113 0.123 0.159 0.134 |
| 1.59e-02 | 2 | 1 | 0.3813 | 0.0844 | 0.0062 | 0.065 0.078 0.073 0.088 0.101 0.101 |

- **Minimum-error rule:** alpha 3.82e-05, 83 leaves, mean 0.2873 (standard error 0.0187).
- **One-standard-error rule:** alpha 6.87e-05, 47 leaves, mean 0.2804: the smallest tree within one standard error of the best.
- The unpruned tree (6,216 leaves) scores 0.8584 on its own fit rows but 0.2390 on later days: it overfits.

## 2. The pruned trees against the forest (validation week)

| model | leaves | PR-AUC, training roads | PR-AUC, AYE + CTE | ROC-AUC, training roads |
|---|---|---|---|---|
| pruned tree, minimum-error rule | 83 | 0.2683 | 0.2483 | 0.923 |
| pruned tree, one-standard-error rule | 47 | 0.2582 | 0.2377 | 0.916 |
| random forest (frozen) | 400 trees | 0.3482 | 0.3352 | 0.942 |

The one-standard-error tree uses 14 of the 96 inputs: `f_d0`, `f_d10`, `f_dn_d0`, `f_rain15`, `f_slot15`, `fe_dn_q0`, `fe_dn_qmove`, `fe_dn_r1_max0`, `fe_dn_r2_low0`, `fe_dn_r2_max0`, `fe_up_q0`, `x_b1`, `x_band0`, `x_dpers10`.

Its first splits (a row goes left when the condition holds; `class` is the majority class in the node, on the fit rows, where 10% of the other rows are kept):

```
|--- fe_dn_q0 <= 593.74
|   |--- x_dpers10 <= 1.75
|   |   |--- f_dn_d0 <= 0.25
|   |   |   |--- x_b1 <= 0.02
|   |   |   |   |--- truncated branch of depth 4
|   |   |   |--- x_b1 >  0.02
|   |   |   |   |--- truncated branch of depth 3
|   |   |--- f_dn_d0 >  0.25
|   |   |   |--- x_b1 <= 0.02
|   |   |   |   |--- truncated branch of depth 4
|   |   |   |--- x_b1 >  0.02
|   |   |   |   |--- truncated branch of depth 3
|   |--- x_dpers10 >  1.75
|   |   |--- x_dpers10 <= 2.75
|   |   |   |--- class: True
|   |   |--- x_dpers10 >  2.75
|   |   |   |--- class: True
|--- fe_dn_q0 >  593.74
|   |--- x_dpers10 <= 1.75
|   |   |--- x_dpers10 <= 0.75
|   |   |   |--- x_b1 <= 0.02
|   |   |   |   |--- truncated branch of depth 5
|   |   |   |--- x_b1 >  0.02
|   |   |   |   |--- truncated branch of depth 5
|   |   |--- x_dpers10 >  0.75
|   |   |   |--- fe_up_q0 <= 1625.91
|   |   |   |   |--- truncated branch of depth 4
|   |   |   |--- fe_up_q0 >  1625.91
|   |   |   |   |--- truncated branch of depth 5
|   |--- x_dpers10 >  1.75
|   |   |--- fe_up_q0 <= 1662.92
|   |   |   |--- x_b1 <= 0.03
|   |   |   |   |--- class: True
|   |   |   |--- x_b1 >  0.03
|   |   |   |   |--- class: True
|   |   |--- fe_up_q0 >  1662.92
|   |   |   |--- class: True
```

## 3. Out-of-bag error

A forest of 50 trees with the frozen settings (max_features 0.6, leaf 20), fitted on the same rows as the tree (every onset + 10% of the other rows; the validation rows are sampled the same way, so the level is not comparable with the tables above): PR-AUC on the fit rows 0.868, out of bag 0.791, on the validation week 0.737. The out-of-bag score is too optimistic here: a row left out of a tree still has its neighbours in time (the same link, 5 minutes apart) inside that tree's sample. The notes warn that ordinary row-level resampling assumes independent rows. Forward validation by whole days does not have this problem.

## 4. Ranking the inputs (frozen forest)

Two measures, as in the notes. Impurity: the mean decrease in Gini over the forest's splits (sums to 1). Permutation: the drop in validation PR-AUC when one input is shuffled (sample PR-AUC 0.3412). Spearman correlation of the two rankings over the 96 inputs: 0.77.

| rank (permutation) | input | group | permutation importance | impurity importance | rank (impurity) |
|---|---|---|---|---|---|
| 1 | `x_dpers10` | NORM: normal level ahead | 0.0692 | 0.1930 | 2 |
| 2 | `fe_dn_q0` | HOP: queue distance downstream | 0.0461 | 0.3528 | 1 |
| 3 | `x_b1` | HIST: usual onset rate | 0.0363 | 0.0546 | 4 |
| 4 | `x_lowpers15` | NORM: normal level ahead | 0.0281 | 0.0788 | 3 |
| 5 | `fe_up_q0` | HOP: upstream rings | 0.0224 | 0.0328 | 6 |
| 6 | `f_slot15` | time of day | 0.0083 | 0.0191 | 8 |
| 7 | `fe_dn_qmove` | HOP: queue distance downstream | 0.0081 | 0.0154 | 10 |
| 8 | `x_dpers15` | NORM: normal level ahead | 0.0077 | 0.0340 | 5 |
| 9 | `x_band0` | NORM: normal level ahead | 0.0057 | 0.0061 | 15 |
| 10 | `fe_dn_r2_max0` | HOP: downstream rings | 0.0055 | 0.0103 | 14 |
| 11 | `f_dn_d0` | next links | 0.0053 | 0.0113 | 13 |
| 12 | `fe_up_r2_low0` | HOP: upstream rings | 0.0052 | 0.0043 | 21 |
| 13 | `fe_dn_r1_max0` | HOP: downstream rings | 0.0046 | 0.0242 | 7 |
| 14 | `fe_dn_r2_low0` | HOP: downstream rings | 0.0034 | 0.0145 | 11 |
| 15 | `fe_up_r3_max0` | HOP: upstream rings | 0.0034 | 0.0034 | 26 |
| 16 | `fe_up_r3_low0` | HOP: upstream rings | 0.0029 | 0.0043 | 22 |
| 17 | `f_d0` | own drops | 0.0027 | 0.0055 | 16 |
| 18 | `f_rain15` | rain | 0.0023 | 0.0116 | 12 |
| 19 | `fe_up_r2_low10` | HOP: upstream rings | 0.0023 | 0.0023 | 37 |
| 20 | `fe_up_r2_max0` | HOP: upstream rings | 0.0020 | 0.0033 | 27 |

Top 10 by impurity: `fe_dn_q0` (0.353; permutation rank 2), `x_dpers10` (0.193; permutation rank 1), `x_lowpers15` (0.079; permutation rank 4), `x_b1` (0.055; permutation rank 3), `x_dpers15` (0.034; permutation rank 8), `fe_up_q0` (0.033; permutation rank 5), `fe_dn_r1_max0` (0.024; permutation rank 13), `f_slot15` (0.019; permutation rank 6), `fe_dn_r1_low0` (0.018; permutation rank 23), `fe_dn_qmove` (0.015; permutation rank 7).

By group (importance summed over the group's inputs; shuffling one input at a time understates a group whose inputs can stand in for each other):

| group | inputs | impurity importance (sum) | permutation importance (sum of single shuffles) |
|---|---|---|---|
| HOP: queue distance downstream | 3 | 0.373 | 0.0544 |
| NORM: normal level ahead | 8 | 0.318 | 0.1117 |
| HOP: downstream rings | 15 | 0.088 | 0.0169 |
| HOP: upstream rings | 16 | 0.071 | 0.0451 |
| HIST: usual onset rate | 1 | 0.055 | 0.0363 |
| next links | 16 | 0.032 | 0.0074 |
| own drops | 9 | 0.020 | 0.0043 |
| time of day | 1 | 0.019 | 0.0083 |
| rain | 4 | 0.016 | 0.0028 |
| day of week | 5 | 0.006 | 0.0008 |
| joining roads | 18 | 0.001 | -0.0005 |

## 5. Ranking by the lasso (frozen M1)

Standardised coefficients: one standard deviation more of the input multiplies the odds of an onset by the odds ratio, the other inputs held fixed.

| rank | input | coefficient per 1 SD | odds ratio per 1 SD |
|---|---|---|---|
| 1 | `x_dpers10` | +0.393 | 1.48 |
| 2 | `x_b1` | +0.363 | 1.44 |
| 3 | `fe_dn_r1_max0` | +0.299 | 1.35 |
| 4 | `fe_dn_r2_max0` | +0.244 | 1.28 |
| 5 | `fe_dn_q0` | -0.229 | 0.80 |
| 6 | `x_log_rain15` | +0.170 | 1.19 |
| 7 | `fe_up_r1_max0` | +0.168 | 1.18 |
| 8 | `x_hour06` | -0.161 | 0.85 |
| 9 | `x_hour21` | -0.157 | 0.86 |
| 10 | `x_hour20` | -0.148 | 0.86 |
| 11 | `fe_up_r3_max0` | +0.141 | 1.15 |
| 12 | `fe_dn_r1_max10` | -0.140 | 0.87 |
| 13 | `fe_dn_r2_max10` | -0.139 | 0.87 |
| 14 | `fe_up_r2_max0` | +0.136 | 1.15 |
| 15 | `x_log_rain30` | -0.135 | 0.87 |
