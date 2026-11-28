# DRY RUN on the validation week (tests 10_test.py; must match 03-07)

Frozen at 2026-11-25T23:46:25+08:00 (results/freeze.json); secondary freezes: freeze_secondary_base 2026-11-26T00:42:54+08:00, freeze_secondary_lasso 2026-11-26T00:41:07+08:00, freeze_secondary_rf 2026-11-26T00:35:06+08:00, freeze_segments 2026-11-26T00:42:06+08:00. Plan-freeze tag: none (opened with OPEN_TEST_WEEK=yes).
Build of the test week: `build_data.py --now '2026-11-21 06:00' --out-root work/data_build` (git b11aae5, 114 of 114 build checks OK).

## Build checks

| check | result | detail |
|---|---|---|
| train.parquet (train + validate rows) identical to the published file | OK | 8,048,388 vs 8,048,388 rows |
| extra/norm.parquet identical (frozen from the train days; registry counters ignored) | OK |  |
| extra/links.parquet identical (frozen from the train days; registry counters ignored) | OK |  |
| extra/neighbours.parquet identical (frozen from the train days; registry counters ignored) | OK |  |
| extra/connectors.parquet identical (frozen from the train days; registry counters ignored) | OK |  |
| test.parquet holds Tue 10 - Fri 13 Nov only | OK | 1,647,272 rows |
| test week: next-link maximum from our series == the build's f_dn_d0 | OK | 0 differ |
| test week: next-link maximum from our series == the build's f_up_d0 | OK | 0 differ |
| dry run: B1 scores == the saved validation scores | OK | largest gap 0.0e+00 |
| dry run: B2 scores == the saved validation scores | OK | largest gap 0.0e+00 |
| dry run: Lasso scores == the saved validation scores | OK | largest gap 0.0e+00 |
| dry run: RF scores == the saved validation scores | OK | largest gap 4.4e-16 |

## Primary result: PR-AUC on onset rows, training roads (1,909 links)

1,178,466 rows, 13,883 onsets, base rate **0.0118** (the PR-AUC of a score that only guesses). 95% intervals: day-block bootstrap over the 5 test days, 2000 draws, paired for differences.

| model | PR-AUC | 95% interval | minus B2 (paired 95%) | minus B1 (paired 95%) |
|---|---|---|---|---|
| B1 time-of-week rate | 0.0688 | 0.0485 to 0.0938 | -0.0596 (-0.0939 to -0.0333) |  |
| B2 last observation | 0.1284 | 0.0911 to 0.1627 |  | +0.0596 (+0.0333 to +0.0939) |
| band persistence (reference) | 0.1710 | 0.1123 to 0.2084 | +0.0426 (+0.0239 to +0.0657) | +0.1022 (+0.0608 to +0.1411) |
| M1 lasso | 0.3220 | 0.2158 to 0.3844 | +0.1936 (+0.1247 to +0.2286) | +0.2532 (+0.1700 to +0.3054) |
| M2 random forest | 0.3482 | 0.2326 to 0.4177 | +0.2198 (+0.1415 to +0.2613) | +0.2794 (+0.1868 to +0.3365) |

M2 minus M1: +0.0262 (paired 95% +0.0173 to +0.0333).

## Transfer: AYE + CTE (689 links, never used to fit, tune or calibrate)

428,667 rows, 6,430 onsets, base rate **0.0150**.

| model | PR-AUC | 95% interval | minus B2 (paired 95%) | minus B1 (paired 95%) |
|---|---|---|---|---|
| B1 time-of-week rate | 0.0232 | 0.0148 to 0.0309 | -0.1199 (-0.1699 to -0.0509) |  |
| B2 last observation | 0.1431 | 0.0671 to 0.2008 |  | +0.1199 (+0.0509 to +0.1699) |
| band persistence (reference) | 0.1710 | 0.0937 to 0.2321 | +0.0279 (+0.0232 to +0.0319) | +0.1478 (+0.0776 to +0.2012) |
| M1 lasso | 0.3004 | 0.1462 to 0.3855 | +0.1573 (+0.0791 to +0.1873) | +0.2772 (+0.1300 to +0.3613) |
| M2 random forest | 0.3352 | 0.1662 to 0.4327 | +0.1921 (+0.0990 to +0.2386) | +0.3120 (+0.1500 to +0.4085) |

By road:

| road | rows | base rate | B1 time-of-week rate | B2 last observation | band persistence (reference) | M1 lasso | M2 random forest |
|---|---|---|---|---|---|---|---|
| Ayer Rajah Expressway | 257,144 | 0.0152 | 0.0261 | 0.1427 | 0.1719 | 0.3059 | 0.3366 |
| Central Expressway | 171,523 | 0.0147 | 0.0202 | 0.1441 | 0.1701 | 0.2932 | 0.3335 |

## Precision / recall among the top share of links at each update (operating share 2%, set on validation)

| model | 0.5% | 1% | 2% (operating) |
|---|---|---|---|
| B1 time-of-week rate | 0.106 / 0.048 | 0.092 / 0.080 | 0.079 / 0.137 |
| B2 last observation | 0.256 / 0.116 | 0.194 / 0.170 | 0.138 / 0.237 |
| band persistence (reference) | 0.297 / 0.135 | 0.233 / 0.204 | 0.166 / 0.287 |
| M1 lasso | 0.353 / 0.160 | 0.289 / 0.253 | 0.220 / 0.379 |
| M2 random forest | 0.370 / 0.168 | 0.299 / 0.262 | 0.225 / 0.389 |

## Event level at the operating share (2%), training roads

Episode start s: U(s) = 1 after U(s - 5) = 0. Warned = alerted at s - 15 or s - 10. False alarm = alert with y = 0.

| model | episodes | warned 10-15 min ahead | false alarms per hour (1,909 links) |
|---|---|---|---|
| B1 time-of-week rate | 7,481 | 13.9% | 344 |
| B2 last observation | 7,481 | 8.4% | 323 |
| band persistence (reference) | 7,481 | 15.7% | 312 |
| M1 lasso | 7,481 | 31.0% | 292 |
| M2 random forest | 7,481 | 30.3% | 290 |

## Calibration on the test week (maps frozen on validation)

| model | mean predicted | observed | Brier | Brier of the true base rate (hindsight) |
|---|---|---|---|---|
| B1 time-of-week rate | 0.0117 | 0.0118 | 0.01131 | 0.01164 |
| M1 lasso | 0.0118 | 0.0118 | 0.00946 | 0.01164 |
| M2 random forest | 0.0117 | 0.0118 | 0.00921 | 0.01164 |

## By day (training roads, PR-AUC)

| day | rows | base rate | B1 time-of-week rate | B2 last observation | band persistence (reference) | M1 lasso | M2 random forest |
|---|---|---|---|---|---|---|---|
| Tue 10 Nov | 316,227 | 0.0128 | 0.0953 | 0.1630 | 0.2078 | 0.3890 | 0.4245 |
| Wed 11 Nov | 317,902 | 0.0087 | 0.0957 | 0.1352 | 0.2113 | 0.3638 | 0.3941 |
| Thu 12 Nov | 237,758 | 0.0150 | 0.0437 | 0.0742 | 0.0897 | 0.1668 | 0.1796 |
| Fri 13 Nov | 306,579 | 0.0115 | 0.0551 | 0.1624 | 0.2047 | 0.3684 | 0.3946 |

## Subgroups (training roads; PR-AUC with each group's own base rate)

| group | rows | base rate | B1 time-of-week rate | B2 last observation | band persistence (reference) | M1 lasso | M2 random forest |
|---|---|---|---|---|---|---|---|
| peak (07:00-09:59, 17:00-19:59) | 409,874 | 0.0199 | 0.0955 | 0.1482 | 0.2048 | 0.3708 | 0.4005 |
| off-peak | 768,592 | 0.0074 | 0.0292 | 0.1075 | 0.1285 | 0.2500 | 0.2701 |
| rain in the last 30 min | 79,630 | 0.0351 | 0.1064 | 0.1670 | 0.1846 | 0.3449 | 0.3680 |
| dry | 1,098,836 | 0.0101 | 0.0661 | 0.1215 | 0.1702 | 0.3161 | 0.3435 |
| Aljunied West Flyover | 3,617 | 0.0102 | 0.0194 | 0.1439 | 0.1484 | 0.4193 | 0.3789 |
| Bukit Timah Expressway | 103,812 | 0.0154 | 0.0570 | 0.1494 | 0.1920 | 0.3308 | 0.3573 |
| East Coast Parkway | 147,649 | 0.0095 | 0.0976 | 0.1104 | 0.1716 | 0.3047 | 0.3251 |
| Kallang Bahru Flyover | 2,889 | 0.0235 | 0.1186 | 0.2322 | 0.2443 | 0.4699 | 0.4544 |
| Kallang Paya Lebar Expressway | 122,662 | 0.0062 | 0.0776 | 0.1230 | 0.1942 | 0.3156 | 0.3645 |
| Kranji Expressway | 81,412 | 0.0061 | 0.0218 | 0.0573 | 0.0794 | 0.1716 | 0.1836 |
| Marina Coastal Expressway | 46,657 | 0.0036 | 0.0828 | 0.1081 | 0.0935 | 0.2917 | 0.3177 |
| Pan Island Expressway | 403,364 | 0.0164 | 0.0770 | 0.1450 | 0.1968 | 0.3458 | 0.3841 |
| Seletar Expressway | 118,269 | 0.0142 | 0.0751 | 0.1418 | 0.1636 | 0.3572 | 0.3602 |
| Tampines Expressway | 148,135 | 0.0070 | 0.0456 | 0.0927 | 0.1154 | 0.2205 | 0.2096 |

## PR-AUC on all rows (secondary metric: also rows already unusual now), training roads

| model | PR-AUC (base rate 0.0227) |
|---|---|
| B1 time-of-week rate | 0.1034 |
| B2 last observation | 0.4088 |
| band persistence (reference) | 0.4331 |
| M1 lasso | 0.5660 |
| M2 random forest | 0.5880 |

## Secondary analyses (fixed in advance; frozen models)

### Horizon (training roads, PR-AUC)

| horizon | rows | base rate | B1 | B2 | M1 lasso | M2 forest |
|---|---|---|---|---|---|---|
| 5 min | 1,226,893 | 0.0060 | 0.0342 | 0.6797 | 0.8218 | 0.8046 |
| 10 min | 1,178,443 | 0.0095 | 0.0470 | 0.2087 | 0.4099 | 0.4311 |
| 15 min (main) | 1,178,466 | 0.0118 | 0.0688 | 0.1284 | 0.3220 | 0.3482 |
| 30 min | 1,170,454 | 0.0158 | 0.1028 | 0.0609 | 0.2114 | 0.2316 |

### Inputs left out, and the leave-own-day-out normal level (PR-AUC)

| model inputs | lasso: training roads | lasso: AYE + CTE | forest: training roads | forest: AYE + CTE |
|---|---|---|---|---|
| all chosen inputs (M1 / M2) | 0.3220 | 0.3004 | 0.3482 | 0.3352 |
| without joining roads (f_conn_*) | 0.3218 | 0.3003 | 0.3483 | 0.3352 |
| without neighbour inputs (f_up/f_dn and HOP) | 0.2551 | 0.2314 | 0.2670 | 0.2547 |
| without both | 0.2549 | 0.2309 | 0.2678 | 0.2558 |
| without HIST (the B1 rate as an input) | 0.2935 | 0.3081 | 0.3349 | 0.3494 |
| the 53 build inputs, normal level with the own day | 0.2090 | 0.2293 | 0.2374 | 0.2582 |
| the 53 build inputs, normal level without the own day (LODO) | 0.2098 | 0.2296 | 0.2360 | 0.2541 |

### 1 km segments (374 segments; PR-AUC on segment onset rows)

| roads | rows | onsets | base rate | B1 | B2 | M1 lasso | M2 forest |
|---|---|---|---|---|---|---|---|
| training roads | 160,228 | 879 | 0.0055 | 0.0470 | 0.2635 | 0.3624 | 0.3842 |
| AYE + CTE | 57,863 | 514 | 0.0089 | 0.0121 | 0.3263 | 0.3907 | 0.4289 |
