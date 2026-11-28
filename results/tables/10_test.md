# THE TEST WEEK: Mon 16 - Fri 20 Nov 2026 (one run, frozen settings; data version 4)

Frozen at 2026-11-25T23:46:25+08:00 (results/freeze.json); secondary freezes: freeze_secondary_base 2026-11-26T00:42:54+08:00, freeze_secondary_lasso 2026-11-26T00:41:07+08:00, freeze_secondary_rf 2026-11-26T00:35:06+08:00, freeze_segments 2026-11-26T00:42:06+08:00. Plan-freeze tag: none (opened with OPEN_TEST_WEEK=yes).
Build of the test week: `build_data.py --now '2026-11-21 06:00' --out-root work/data_build` (git c09858e, 114 of 114 build checks OK).

## Build checks

| check | result | detail |
|---|---|---|
| train.parquet (train + validate rows) identical to the published file | OK | 8,048,388 vs 8,048,388 rows |
| extra/norm.parquet identical (frozen from the train days; registry counters ignored) | OK |  |
| extra/links.parquet identical (frozen from the train days; registry counters ignored) | OK |  |
| extra/neighbours.parquet identical (frozen from the train days; registry counters ignored) | OK |  |
| extra/connectors.parquet identical (frozen from the train days; registry counters ignored) | OK |  |
| test.parquet holds Mon 16 - Fri 20 Nov only | OK | 2,294,381 rows |
| test week: next-link maximum from our series == the build's f_dn_d0 | OK | 0 differ |
| test week: next-link maximum from our series == the build's f_up_d0 | OK | 0 differ |

## Primary result: PR-AUC on onset rows, training roads (1,909 links)

1,636,522 rows, 20,499 onsets, base rate **0.0125** (the PR-AUC of a score that only guesses). 95% intervals: day-block bootstrap over the 5 test days, 2000 draws, paired for differences.

| model | PR-AUC | 95% interval | minus B2 (paired 95%) | minus B1 (paired 95%) |
|---|---|---|---|---|
| B1 time-of-week rate | 0.0810 | 0.0640 to 0.0999 | -0.0835 (-0.1059 to -0.0592) |  |
| B2 last observation | 0.1645 | 0.1519 to 0.1759 |  | +0.0835 (+0.0592 to +0.1059) |
| band persistence (reference) | 0.2062 | 0.1908 to 0.2198 | +0.0418 (+0.0370 to +0.0469) | +0.1253 (+0.1029 to +0.1482) |
| M1 lasso | 0.3700 | 0.3513 to 0.3953 | +0.2055 (+0.1884 to +0.2248) | +0.2890 (+0.2614 to +0.3199) |
| M2 random forest | 0.3900 | 0.3780 to 0.4090 | +0.2255 (+0.2118 to +0.2408) | +0.3090 (+0.2844 to +0.3346) |

M2 minus M1: +0.0200 (paired 95% +0.0122 to +0.0273).

## Transfer: AYE + CTE (689 links, never used to fit, tune or calibrate)

596,159 rows, 7,086 onsets, base rate **0.0119**.

| model | PR-AUC | 95% interval | minus B2 (paired 95%) | minus B1 (paired 95%) |
|---|---|---|---|---|
| B1 time-of-week rate | 0.0250 | 0.0148 to 0.0446 | -0.1367 (-0.1584 to -0.1064) |  |
| B2 last observation | 0.1617 | 0.1232 to 0.1882 |  | +0.1367 (+0.1064 to +0.1584) |
| band persistence (reference) | 0.2074 | 0.1693 to 0.2417 | +0.0457 (+0.0243 to +0.0611) | +0.1824 (+0.1525 to +0.2006) |
| M1 lasso | 0.3260 | 0.2637 to 0.3676 | +0.1643 (+0.1405 to +0.1970) | +0.3010 (+0.2469 to +0.3495) |
| M2 random forest | 0.3669 | 0.3041 to 0.4038 | +0.2052 (+0.1806 to +0.2248) | +0.3419 (+0.2853 to +0.3803) |

By road:

| road | rows | base rate | B1 time-of-week rate | B2 last observation | band persistence (reference) | M1 lasso | M2 random forest |
|---|---|---|---|---|---|---|---|
| Ayer Rajah Expressway | 353,670 | 0.0108 | 0.0235 | 0.1591 | 0.2044 | 0.3301 | 0.3705 |
| Central Expressway | 242,489 | 0.0134 | 0.0275 | 0.1668 | 0.2125 | 0.3220 | 0.3630 |

## Precision / recall among the top share of links at each update (operating share 2%, set on validation)

| model | 0.5% | 1% | 2% (operating) |
|---|---|---|---|
| B1 time-of-week rate | 0.121 / 0.051 | 0.101 / 0.083 | 0.084 / 0.135 |
| B2 last observation | 0.270 / 0.115 | 0.207 / 0.169 | 0.145 / 0.234 |
| band persistence (reference) | 0.314 / 0.134 | 0.245 / 0.201 | 0.175 / 0.284 |
| M1 lasso | 0.368 / 0.157 | 0.298 / 0.244 | 0.223 / 0.360 |
| M2 random forest | 0.385 / 0.163 | 0.313 / 0.257 | 0.235 / 0.381 |

## Event level at the operating share (2%), training roads

Episode start s: U(s) = 1 after U(s - 5) = 0. Warned = alerted at s - 15 or s - 10. False alarm = alert with y = 0.

| model | episodes | warned 10-15 min ahead | false alarms per hour (1,909 links) |
|---|---|---|---|
| B1 time-of-week rate | 9,763 | 15.8% | 380 |
| B2 last observation | 9,763 | 8.8% | 355 |
| band persistence (reference) | 9,763 | 15.9% | 342 |
| M1 lasso | 9,763 | 30.6% | 322 |
| M2 random forest | 9,763 | 31.5% | 317 |

## Calibration on the test week (maps frozen on validation)

| model | mean predicted | observed | Brier | Brier of the true base rate (hindsight) |
|---|---|---|---|---|
| B1 time-of-week rate | 0.0120 | 0.0125 | 0.01195 | 0.01237 |
| M1 lasso | 0.0115 | 0.0125 | 0.00964 | 0.01237 |
| M2 random forest | 0.0112 | 0.0125 | 0.00936 | 0.01237 |

## By day (training roads, PR-AUC)

| day | rows | base rate | B1 time-of-week rate | B2 last observation | band persistence (reference) | M1 lasso | M2 random forest |
|---|---|---|---|---|---|---|---|
| Mon 16 Nov | 319,932 | 0.0202 | 0.1026 | 0.1756 | 0.2127 | 0.3554 | 0.3781 |
| Tue 17 Nov | 324,930 | 0.0134 | 0.1070 | 0.1499 | 0.1962 | 0.3576 | 0.3793 |
| Wed 18 Nov | 326,223 | 0.0123 | 0.0955 | 0.1746 | 0.2240 | 0.4094 | 0.4231 |
| Thu 19 Nov | 331,872 | 0.0082 | 0.0582 | 0.1442 | 0.1787 | 0.3465 | 0.3829 |
| Fri 20 Nov | 333,565 | 0.0088 | 0.0570 | 0.1809 | 0.2252 | 0.3966 | 0.4011 |

## Subgroups (training roads; PR-AUC with each group's own base rate)

| group | rows | base rate | B1 time-of-week rate | B2 last observation | band persistence (reference) | M1 lasso | M2 random forest |
|---|---|---|---|---|---|---|---|
| peak (07:00-09:59, 17:00-19:59) | 601,265 | 0.0243 | 0.1007 | 0.1912 | 0.2381 | 0.4107 | 0.4280 |
| off-peak | 1,035,257 | 0.0057 | 0.0386 | 0.1251 | 0.1503 | 0.2663 | 0.2922 |
| rain in the last 30 min | 124,091 | 0.0498 | 0.1726 | 0.2054 | 0.2446 | 0.4077 | 0.4234 |
| dry | 1,512,431 | 0.0095 | 0.0705 | 0.1530 | 0.1963 | 0.3545 | 0.3758 |
| Aljunied West Flyover | 5,285 | 0.0044 | 0.0058 | 0.0181 | 0.0180 | 0.0208 | 0.0291 |
| Bukit Timah Expressway | 144,103 | 0.0150 | 0.0679 | 0.1778 | 0.2094 | 0.3497 | 0.3910 |
| East Coast Parkway | 203,020 | 0.0096 | 0.1070 | 0.1824 | 0.2302 | 0.4227 | 0.4428 |
| Kallang Bahru Flyover | 4,189 | 0.0232 | 0.0591 | 0.1402 | 0.1492 | 0.2562 | 0.2314 |
| Kallang Paya Lebar Expressway | 174,459 | 0.0071 | 0.0567 | 0.1351 | 0.2341 | 0.3083 | 0.3505 |
| Kranji Expressway | 115,390 | 0.0041 | 0.0248 | 0.0869 | 0.0933 | 0.2044 | 0.2357 |
| Marina Coastal Expressway | 67,334 | 0.0046 | 0.0796 | 0.1806 | 0.1402 | 0.3802 | 0.4315 |
| Pan Island Expressway | 564,063 | 0.0169 | 0.0824 | 0.1754 | 0.2109 | 0.3809 | 0.4006 |
| Seletar Expressway | 157,822 | 0.0155 | 0.0780 | 0.1752 | 0.1995 | 0.3700 | 0.3584 |
| Tampines Expressway | 200,857 | 0.0114 | 0.1200 | 0.1464 | 0.2272 | 0.3844 | 0.3986 |

## PR-AUC on all rows (secondary metric: also rows already unusual now), training roads

| model | PR-AUC (base rate 0.0282) |
|---|---|
| B1 time-of-week rate | 0.1281 |
| B2 last observation | 0.4966 |
| band persistence (reference) | 0.5141 |
| M1 lasso | 0.6442 |
| M2 random forest | 0.6462 |

## Secondary analyses (fixed in advance; frozen models)

### Horizon (training roads, PR-AUC)

| horizon | rows | base rate | B1 | B2 | M1 lasso | M2 forest |
|---|---|---|---|---|---|---|
| 5 min | 1,666,141 | 0.0059 | 0.0413 | 0.7651 | 0.8628 | 0.8422 |
| 10 min | 1,635,297 | 0.0099 | 0.0578 | 0.2763 | 0.4698 | 0.4911 |
| 15 min (main) | 1,636,522 | 0.0125 | 0.0810 | 0.1645 | 0.3700 | 0.3900 |
| 30 min | 1,625,295 | 0.0175 | 0.1167 | 0.0750 | 0.2442 | 0.2591 |

### Inputs left out, and the leave-own-day-out normal level (PR-AUC)

| model inputs | lasso: training roads | lasso: AYE + CTE | forest: training roads | forest: AYE + CTE |
|---|---|---|---|---|
| all chosen inputs (M1 / M2) | 0.3700 | 0.3260 | 0.3900 | 0.3669 |
| without joining roads (f_conn_*) | 0.3700 | 0.3256 | 0.3904 | 0.3673 |
| without neighbour inputs (f_up/f_dn and HOP) | 0.2963 | 0.2530 | 0.3144 | 0.2936 |
| without both | 0.2960 | 0.2521 | 0.3141 | 0.2938 |
| without HIST (the B1 rate as an input) | 0.3432 | 0.3364 | 0.3761 | 0.3845 |
| the 53 build inputs, normal level with the own day | 0.2506 | 0.2410 | 0.2759 | 0.2661 |
| the 53 build inputs, normal level without the own day (LODO) | 0.2509 | 0.2408 | 0.2760 | 0.2661 |

### 1 km segments (374 segments; PR-AUC on segment onset rows)

| roads | rows | onsets | base rate | B1 | B2 | M1 lasso | M2 forest |
|---|---|---|---|---|---|---|---|
| training roads | 229,807 | 1,657 | 0.0072 | 0.0476 | 0.2802 | 0.3737 | 0.3625 |
| AYE + CTE | 82,020 | 625 | 0.0076 | 0.0153 | 0.3212 | 0.3623 | 0.3871 |
