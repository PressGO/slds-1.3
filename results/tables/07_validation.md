# Validation week: model choice, calibration, alert share (then frozen)

Validation days: Tue 10 Nov, Wed 11 Nov, Thu 12 Nov, Fri 13 Nov (Mon 9 Nov is a public holiday). Scored rows: normal now (U = False). M1 and M2 were fitted on the train days only (no refit). 'band persistence' is a reference score, not one of the decided baselines: the drop the link would have at t + 10 and t + 15 if its band stayed the same (min of the two).

## PR-AUC and precision / recall at the top share of links per update

| model | rows | base rate | PR-AUC | precision / recall at 0.5% | precision / recall at 1% | precision / recall at 2% |
|---|---|---|---|---|---|---|
| B1 time-of-week rate | training roads (main) | 0.0118 | 0.0688 | 0.106 / 0.048 | 0.092 / 0.080 | 0.079 / 0.137 |
| B1 time-of-week rate | AYE + CTE (transfer) | 0.0150 | 0.0232 | 0.019 / 0.008 | 0.018 / 0.013 | 0.017 / 0.023 |
| B2 last observation | training roads (main) | 0.0118 | 0.1284 | 0.256 / 0.116 | 0.194 / 0.170 | 0.138 / 0.237 |
| B2 last observation | AYE + CTE (transfer) | 0.0150 | 0.1431 | 0.230 / 0.094 | 0.197 / 0.140 | 0.148 / 0.205 |
| band persistence (reference) | training roads (main) | 0.0118 | 0.1710 | 0.297 / 0.135 | 0.233 / 0.204 | 0.166 / 0.287 |
| band persistence (reference) | AYE + CTE (transfer) | 0.0150 | 0.1710 | 0.274 / 0.112 | 0.231 / 0.164 | 0.176 / 0.245 |
| M1 lasso | training roads (main) | 0.0118 | 0.3220 | 0.353 / 0.160 | 0.289 / 0.253 | 0.220 / 0.379 |
| M1 lasso | AYE + CTE (transfer) | 0.0150 | 0.3004 | 0.278 / 0.113 | 0.254 / 0.180 | 0.206 / 0.286 |
| M2 random forest | training roads (main) | 0.0118 | 0.3482 | 0.370 / 0.168 | 0.299 / 0.262 | 0.225 / 0.389 |
| M2 random forest | AYE + CTE (transfer) | 0.0150 | 0.3352 | 0.312 / 0.127 | 0.279 / 0.198 | 0.225 / 0.313 |

**Final model: M2 random forest** (best validation PR-AUC on the training roads among M1 and M2).

## Operating share (set on validation: best F1 of the final model)

| share | precision | recall | F1 | alerts per update (1,909 links) |
|---|---|---|---|---|
| 0.25% | 0.435 | 0.104 | 0.168 | 4.3 |
| 0.5% | 0.370 | 0.168 | 0.231 | 8.2 |
| 1% | 0.299 | 0.262 | 0.280 | 15.8 |
| 2% | 0.225 | 0.389 | 0.285 | 31.2 |
| 3% | 0.184 | 0.475 | 0.266 | 46.5 |
| 5% | 0.136 | 0.580 | 0.220 | 77.2 |

Chosen operating share: **2%**.

## Calibration (training roads)

Platt map on the logit scale, fitted on the validation week. The 'cross-fitted' columns fit the map on 3 validation days and apply it to the 4th, so they are honest; the test week uses the map fitted on all 4.

| model | mean raw | mean cross-fitted | observed | Brier raw | Brier cross-fitted | Brier of the base rate | map |
|---|---|---|---|---|---|---|---|
| B1 time-of-week rate | 0.0096 | 0.0119 | 0.0118 | 0.01131 | 0.01133 | 0.01164 | a = -0.164, b = 0.909 |
| M1 lasso | 0.0118 | 0.0118 | 0.0118 | 0.00948 | 0.00947 | 0.01164 | a = -0.098, b = 0.967 |
| M2 random forest | 0.0600 | 0.0117 | 0.0118 | 0.02152 | 0.00924 | 0.01164 | a = -2.297, b = 0.996 |

## By day (training roads, PR-AUC)

| day | rows | base rate | B1 time-of-week rate | B2 last observation | band persistence (reference) | M1 lasso | M2 random forest |
|---|---|---|---|---|---|---|---|
| Tue 10 Nov | 316,227 | 0.0128 | 0.0953 | 0.1630 | 0.2078 | 0.3890 | 0.4245 |
| Wed 11 Nov | 317,902 | 0.0087 | 0.0957 | 0.1352 | 0.2113 | 0.3638 | 0.3941 |
| Thu 12 Nov | 237,758 | 0.0150 | 0.0437 | 0.0742 | 0.0897 | 0.1668 | 0.1796 |
| Fri 13 Nov | 306,579 | 0.0115 | 0.0551 | 0.1624 | 0.2047 | 0.3684 | 0.3946 |

## Day-block bootstrap (4 days: tests the code only; too few days for a real interval)

| model | PR-AUC | 95% interval | minus B2 (paired interval) |
|---|---|---|---|
| B1 time-of-week rate | 0.0688 | 0.0485 to 0.0938 |  |
| B2 last observation | 0.1284 | 0.0911 to 0.1627 |  |
| band persistence (reference) | 0.1710 | 0.1123 to 0.2084 | +0.0426 (+0.0239 to +0.0657) |
| M1 lasso | 0.3220 | 0.2158 to 0.3844 | +0.1936 (+0.1247 to +0.2286) |
| M2 random forest | 0.3482 | 0.2326 to 0.4177 | +0.2198 (+0.1415 to +0.2613) |

## Event level at the operating share (2%), training roads

An episode starts at s when U(s) = 1 and U(s - 5) = 0. It is warned when the link was alerted at s - 15 or s - 10 (10-15 minutes ahead). A false alarm is an alert whose y is 0; per hour over the 1,909 links (16 hours a day).

| model | episodes | warned 10-15 min ahead | false alarms per hour |
|---|---|---|---|
| B1 time-of-week rate | 7,481 | 13.9% | 344 |
| B2 last observation | 7,481 | 8.4% | 323 |
| band persistence (reference) | 7,481 | 15.7% | 312 |
| M1 lasso | 7,481 | 31.0% | 292 |
| M2 random forest | 7,481 | 30.3% | 290 |
