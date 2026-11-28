# M1: lasso logistic regression

Inputs: **BASE + NORM + HOP + HIST**, lasso view (111 columns: f_slot15 as 16 hour groups, rain as log(1 + mm)), scaled with the mean and SD of each fit's rows. Solver: IRLS + coordinate descent (glmnet algorithm, `lassofit.py`; matches or beats scikit-learn's objective in `check_lassofit.md`); the intercept is not penalised. Final fit rows: 4,586,551 (train days, training roads, normal now), 46,422 onsets. lambda_max = 3.526e-02 per row.

## Choosing the penalty (forward-chaining inside the train days)

| lambda / lambda_max | lambda per row | inputs kept, fold 1 | fold 2 | PR-AUC fold 1 | PR-AUC fold 2 | mean |
|---|---|---|---|---|---|---|
| x 0.5 | 1.76e-02 | 2 | 2 | 0.2147 | 0.2447 | 0.2297 |
| x 0.2 | 7.05e-03 | 5 | 8 | 0.2535 | 0.3280 | 0.2907 |
| x 0.1 | 3.53e-03 | 9 | 12 | 0.2895 | 0.3438 | 0.3166 |
| x 0.03 | 1.06e-03 | 20 | 19 | 0.3045 | 0.3524 | 0.3284 |
| x 0.01 | 3.53e-04 | 33 | 36 | 0.3210 | 0.3657 | 0.3434 |
| x 0.003 | 1.06e-04 | 60 | 70 | 0.3281 | 0.3743 | 0.3512 |
| x 0.001 | 3.53e-05 | 83 | 86 | 0.3295 | 0.3760 | 0.3527 |
| x 0.0003 | 1.06e-05 | 99 | 96 | 0.3299 | 0.3761 | **0.3530** |
| x 0.0001 | 3.53e-06 | 102 | 102 | 0.3299 | 0.3760 | 0.3530 |
| no penalty (scikit-learn lbfgs) | 0 | 111 | 111 | 0.3299 | 0.3760 | 0.3530 |

Chosen: **lambda_max x 0.0003** (ties at 4 decimals go to the stronger penalty). On all train days it keeps **97 of 111** inputs. Mean predicted chance on the fit rows 0.0101 vs base rate 0.0101.

## Order in which the inputs enter (path on all train days)

| lambda / lambda_max | inputs kept | new inputs at this penalty |
|---|---|---|
| x 0.5 | 3 | `x_lowpers15`, `fe_dn_r1_low0`, `fe_dn_q0` |
| x 0.2 | 9 | `x_dpers10`, `fe_dn_r1_max0`, `fe_dn_r2_low0`, `fe_up_r1_low0`, `fe_up_q0`, `x_b1` |
| x 0.1 | 13 | `f_up_d0`, `f_dn_d0`, `x_log_rain15`, `fe_dn_r2_max0`, `fe_up_r1_max0`, `fe_up_r3_low0` |
| x 0.03 | 21 | `x_band0`, `fe_dn_r3_low0`, `fe_up_r2_max0`, `fe_up_r3_max0`, `fe_dn_r1_max10`, `fe_dn_r1_low10`, `fe_dn_r2_low10`, `fe_up_r2_low10` |
| x 0.01 | 51 | `f_d20`, `f_d25`, `f_d30`, `f_n_filled`, `f_up_d5`, `f_dn_d5`, `x_hour07`, `x_hour08`, `x_hour09`, `x_hour14`, `x_hour16`, `x_hour17`, `x_hour19`, `x_hour20`, `f_mon`, `f_fri`, `f_conn_in_d0`, `f_conn_out_d0`, `x_dnorm15`, `x_low0`, `x_low5`, `fe_dn_r3_max0`, `fe_dn_r2_max10`, `fe_dn_r3_low10`, `fe_up_r1_low10`, `fe_up_r2_max10`, `fe_up_r3_low10`, `fe_dn_q10`, `fe_dn_r3_none` |
| x 0.003 | 70 | `f_d10`, `f_d_change15`, `f_up_d30`, `f_dn_d10`, `f_dn_d15`, `f_dn_d25`, `x_log_rain30`, `x_hour06`, `x_hour11`, `x_hour12`, `x_hour18`, `x_hour21`, `f_tue`, `f_wed`, `f_conn_out_none`, `fe_norm_p0`, `x_dpers15`, `fe_dn_r3_max10`, `fe_up_r1_max10`, `fe_up_r3_max10`, `fe_dn_r2_none` |
| x 0.001 | 84 | `f_up_d10`, `f_up_none`, `f_dn_none`, `x_hour10`, `x_hour15`, `f_conn_in_d5`, `f_conn_in_d10`, `f_conn_in_d25`, `f_conn_out_d30`, `f_conn_in_none`, `f_conn_out_missing`, `fe_up_r2_low0`, `fe_up_r3_none` |
| x 0.0003 | 97 | `f_d5`, `f_up_d15`, `f_dn_d20`, `f_dn_d30`, `f_rain30_missing`, `f_conn_in_d30`, `f_conn_out_d5`, `f_conn_out_d15`, `f_conn_out_d25`, `f_conn_in_missing`, `fe_dn_r1_none`, `fe_up_r2_none` |
| x 0.0001 | 103 | `f_up_d20`, `f_up_d25`, `x_hour13`, `f_conn_in_d20`, `f_conn_out_d10`, `f_conn_out_d20`, `fe_up_r1_none` |

## Standardised coefficients of M1 (largest 30 by size; per 1 SD of the input)

| input | coefficient |
|---|---|
| `x_dpers10` | +0.393 |
| `x_b1` | +0.363 |
| `fe_dn_r1_max0` | +0.299 |
| `fe_dn_r2_max0` | +0.244 |
| `fe_dn_q0` | -0.229 |
| `x_log_rain15` | +0.170 |
| `fe_up_r1_max0` | +0.168 |
| `x_hour06` | -0.161 |
| `x_hour21` | -0.157 |
| `x_hour20` | -0.148 |
| `fe_up_r3_max0` | +0.141 |
| `fe_dn_r1_max10` | -0.140 |
| `fe_dn_r2_max10` | -0.139 |
| `fe_up_r2_max0` | +0.136 |
| `x_log_rain30` | -0.135 |
| `x_dpers15` | -0.132 |
| `f_dn_d0` | +0.126 |
| `fe_dn_q10` | -0.116 |
| `x_lowpers15` | +0.115 |
| `f_up_d0` | +0.108 |
| `fe_up_r2_max10` | -0.105 |
| `x_hour19` | -0.104 |
| `f_mon` | -0.102 |
| `fe_up_q0` | -0.094 |
| `x_hour07` | +0.087 |
| `fe_dn_r3_max0` | +0.079 |
| `x_hour12` | -0.078 |
| `fe_dn_r3_none` | +0.068 |
| `f_up_d5` | -0.066 |
| `f_dn_d5` | -0.065 |

Inputs set to exactly 0: `f_d0`, `f_d15`, `f_up_d20`, `f_up_d25`, `f_rain15_missing`, `x_hour13`, `f_thu`, `f_conn_in_d15`, `f_conn_in_d20`, `f_conn_out_d10`, `f_conn_out_d20`, `x_band0`, `fe_dn_qmove`, `fe_up_r1_none`.

## Validation week (scored in 07; quick look)

Training roads: PR-AUC M1 0.3220, plain LR 0.3219.
