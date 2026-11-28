# Diagnostics: lasso stability and failure cases

## A. Lasso coefficient bootstrap (16 train days resampled as blocks; 20 refits at the frozen penalty)

The x_b1 input keeps its original leave-own-day-out values in every refit (an approximation).

| input | M1 coefficient | kept in refits | 90% range |
|---|---|---|---|
| `x_dpers10` | +0.393 | 100% | +0.370 to +0.434 |
| `x_b1` | +0.363 | 100% | +0.355 to +0.384 |
| `fe_dn_r1_max0` | +0.299 | 100% | +0.280 to +0.313 |
| `fe_dn_r2_max0` | +0.244 | 100% | +0.208 to +0.263 |
| `fe_dn_q0` | -0.229 | 100% | -0.261 to -0.209 |
| `x_log_rain15` | +0.170 | 100% | +0.119 to +0.299 |
| `fe_up_r1_max0` | +0.168 | 100% | +0.144 to +0.183 |
| `x_hour06` | -0.161 | 100% | -0.291 to -0.050 |
| `x_hour21` | -0.157 | 90% | -0.173 to +0.000 |
| `x_hour20` | -0.148 | 100% | -0.205 to -0.093 |
| `fe_up_r3_max0` | +0.141 | 100% | +0.111 to +0.157 |
| `fe_dn_r1_max10` | -0.140 | 100% | -0.151 to -0.126 |
| `fe_dn_r2_max10` | -0.139 | 100% | -0.170 to -0.104 |
| `fe_up_r2_max0` | +0.136 | 100% | +0.123 to +0.142 |
| `x_log_rain30` | -0.135 | 100% | -0.264 to -0.081 |
| `x_dpers15` | -0.132 | 100% | -0.182 to -0.103 |
| `f_dn_d0` | +0.126 | 100% | +0.118 to +0.137 |
| `fe_dn_q10` | -0.116 | 100% | -0.133 to -0.093 |
| `x_lowpers15` | +0.115 | 100% | +0.097 to +0.125 |
| `f_up_d0` | +0.108 | 100% | +0.101 to +0.116 |
| `fe_up_r2_max10` | -0.105 | 100% | -0.113 to -0.087 |
| `x_hour19` | -0.104 | 100% | -0.126 to -0.031 |
| `f_mon` | -0.102 | 100% | -0.159 to -0.031 |
| `fe_up_q0` | -0.094 | 100% | -0.111 to -0.072 |
| `x_hour07` | +0.087 | 100% | +0.045 to +0.148 |
| `fe_dn_r3_max0` | +0.079 | 100% | +0.033 to +0.097 |
| `x_hour12` | -0.078 | 95% | -0.087 to +0.000 |
| `fe_dn_r3_none` | +0.068 | 100% | +0.039 to +0.086 |
| `f_up_d5` | -0.066 | 100% | -0.076 to -0.044 |
| `f_dn_d5` | -0.065 | 100% | -0.074 to -0.054 |
| `x_hour11` | -0.065 | 80% | -0.090 to +0.000 |
| `x_hour14` | +0.065 | 90% | -0.002 to +0.167 |
| `fe_norm_p0` | -0.064 | 100% | -0.101 to -0.018 |
| `fe_up_r3_low0` | +0.060 | 100% | +0.037 to +0.079 |
| `f_n_filled` | -0.059 | 100% | -0.074 to -0.016 |
| `x_low0` | -0.058 | 100% | -0.064 to -0.047 |
| `f_d30` | +0.054 | 100% | +0.046 to +0.065 |
| `f_fri` | +0.052 | 90% | +0.000 to +0.130 |
| `f_d10` | +0.050 | 100% | +0.038 to +0.060 |
| `fe_up_r1_max10` | -0.050 | 100% | -0.075 to -0.029 |

Inputs kept in 20-80% of the refits (unstable choice): `f_d5`, `f_d15`, `f_d_change15`, `f_dn_d20`, `f_dn_d30`, `f_rain15_missing`, `f_rain30_missing`, `x_hour11`, `x_hour13`, `x_hour15`, `f_tue`, `f_wed`, `f_thu`, `f_conn_in_d15`, `f_conn_in_d20`, `f_conn_out_d5`, `f_conn_out_d10`, `f_conn_out_d15`, `f_conn_out_d20`, `f_conn_out_d25`, `f_conn_in_missing`, `fe_up_r2_none`.

## B. Failure cases, validation week (training roads; M2 random forest at the operating share 2%)

13,883 onsets; caught (alerted at t, 15 min ahead): 38.9%.

Onsets by incident:

| incident | onsets | share | caught |
|---|---|---|---|
| no incident within 1 km | 8,962 | 64.6% | 35.3% |
| incident already listed at t (within 1 km) | 3,485 | 25.1% | 48.4% |
| incident starts inside the 15-min window | 1,436 | 10.3% | 37.8% |

Onsets by the drop now:

| drop now | onsets | share | caught |
|---|---|---|---|
| a little slower than normal (0 < drop < 2) | 5,789 | 41.7% | 33.5% |
| at or above normal (drop <= 0) | 4,825 | 34.8% | 16.6% |
| already low now (not yet 2 updates) | 3,269 | 23.5% | 81.2% |

Onsets by a queue downstream:

| queue | onsets | share | caught |
|---|---|---|---|
| low link <= 500 m downstream | 6,688 | 48.2% | 58.8% |
| no low link within 3 km downstream | 4,657 | 33.5% | 22.2% |
| low link 0.5-3 km downstream | 2,538 | 18.3% | 16.8% |

Onsets by 'band persistence says unusual' (the same band would be low at t+10 and t+15):

| band persistence | onsets | share | caught |
|---|---|---|---|
| no: a new slowdown | 9,433 | 67.9% | 19.2% |
| yes: the usual level rises ahead while the band is already low | 4,450 | 32.1% | 80.7% |

Incidents starting inside the window, by type:

| type | onsets | caught |
|---|---|---|
| Heavy Traffic | 447 | 36.7% |
| Accident | 427 | 31.9% |
| Vehicle breakdown | 398 | 45.5% |
| Roadwork | 119 | 36.1% |
| Obstacle | 31 | 48.4% |
| Miscellaneous | 9 | 0.0% |
| Unattended Vehicle | 5 | 80.0% |

False alarms (18,547 alerts with y = 0, 77.5% of alerts), by situation:

| situation at t | false alarms | share |
|---|---|---|
| other | 7,007 | 37.8% |
| queue <= 500 m downstream did not arrive | 6,104 | 32.9% |
| low now, recovered within 15 min | 4,193 | 22.6% |
| normal level rises ahead (band persistence says low) | 1,243 | 6.7% |

## B. Failure cases, test week (training roads; M2 random forest at the operating share 2%)

20,499 onsets; caught (alerted at t, 15 min ahead): 38.1%.

Onsets by incident:

| incident | onsets | share | caught |
|---|---|---|---|
| no incident within 1 km | 12,638 | 61.7% | 34.3% |
| incident already listed at t (within 1 km) | 5,549 | 27.1% | 47.6% |
| incident starts inside the 15-min window | 2,312 | 11.3% | 36.0% |

Onsets by the drop now:

| drop now | onsets | share | caught |
|---|---|---|---|
| a little slower than normal (0 < drop < 2) | 8,345 | 40.7% | 32.7% |
| at or above normal (drop <= 0) | 6,837 | 33.4% | 16.8% |
| already low now (not yet 2 updates) | 5,317 | 25.9% | 73.9% |

Onsets by a queue downstream:

| queue | onsets | share | caught |
|---|---|---|---|
| low link <= 500 m downstream | 10,177 | 49.6% | 54.8% |
| no low link within 3 km downstream | 6,641 | 32.4% | 24.2% |
| low link 0.5-3 km downstream | 3,681 | 18.0% | 16.8% |

Onsets by 'band persistence says unusual' (the same band would be low at t+10 and t+15):

| band persistence | onsets | share | caught |
|---|---|---|---|
| no: a new slowdown | 13,542 | 66.1% | 18.5% |
| yes: the usual level rises ahead while the band is already low | 6,957 | 33.9% | 76.1% |

Incidents starting inside the window, by type:

| type | onsets | caught |
|---|---|---|
| Heavy Traffic | 808 | 32.1% |
| Vehicle breakdown | 702 | 35.0% |
| Accident | 639 | 36.2% |
| Roadwork | 134 | 64.2% |
| Miscellaneous | 14 | 21.4% |
| Obstacle | 12 | 58.3% |
| Road Block | 2 | 50.0% |
| Unattended Vehicle | 1 | 0.0% |

False alarms (25,370 alerts with y = 0, 76.5% of alerts), by situation:

| situation at t | false alarms | share |
|---|---|---|
| other | 9,883 | 39.0% |
| queue <= 500 m downstream did not arrive | 9,493 | 37.4% |
| low now, recovered within 15 min | 4,478 | 17.7% |
| normal level rises ahead (band persistence says low) | 1,516 | 6.0% |

