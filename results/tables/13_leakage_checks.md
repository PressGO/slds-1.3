# Leakage checks (26 Nov)

Run on the train and validation days only; the test week was not read again (only the dates of the saved test scores). OK = passed, FAIL = failed, NOTE = a measurement to read, not a pass/fail check.

| # | check | result | detail |
|---|---|---|---|
| A1 | each split's rows lie on its own days | OK | train 2026-10-16 to 2026-11-06 (16 days); validate 2026-11-10 to 2026-11-13 (4); test scores 2026-11-16 to 2026-11-20 (5 days); no day in two splits |
| A4 | frozen model files unchanged since their freeze; every freeze before the test opening | OK | main freeze 25 Nov 23:46, test opened 26 Nov 01:05; main models changed: none; secondary models changed: none; secondary freezes after the opening: none |
| A4b | code files changed after the main freeze (models unaffected; for the record) | NOTE | `08_secondary.py` (last changed 25 Nov 23:48, before the test opening); `10_test.py` (last changed 25 Nov 23:50, before the test opening) |
| B1 | NORM inputs depend only on the link and the clock time (the same on every day) | OK | most distinct values of any NORM input for one link and clock time over the 20 days: 1 |
| B2 | the normal level is the median of the train weekdays' bands only | OK | 166,272 link x slot cells (06:00-21:59) recomputed: 0 medians and 0 counts differ; with the validation days added, 5,866 cells (4%) would differ, so the check can tell the two apart |
| B3 | HOP '10 min ago' inputs equal the 'now' inputs at t - 10 | OK | 9,768,480 rows x 13 inputs: 0 differ from t - 10; 27,095,426 would differ if the lag pointed forward (t + 10) |
| B4 | truncation test: HOP rebuilt from the rows up to a cut time equals the stored inputs | OK | 3 days (4 Nov train; 11, 13 Nov validation) x cuts 07:30, 12:00, 17:45: 51,066,288 values compared, 0 differ. A deliberately leaky input (the value at t + 10) changes on 46,764 rows under the same test, so a leak would have been caught |
| B5 | the label looks 15 min ahead and the 1 km segment lags look back | OK | links (3 audit days): y(t) = U(t + 15) on 1,365,450 rows, 0 differ; segments: f_d5(t) = f_d0(t - 5) on 1,393,800 rows (0 differ), y(t) = U(t + 15) on 1,210,491 rows (0 differ) |
| A2 | the forest was fitted on train-day rows only (training roads) | OK | every one of the 400 trees drew 500,598 rows = the train fit rows after keeping 10% of the y = False rows (500,598); with the validation week added it would be about 630,939. Onset share in the draws 0.0928 vs 0.0927 in the fit rows. Inputs: 96, none of them a label, date or link id |
| A3 | the lasso was fitted on train-day rows only (training roads) | OK | stored fit rows 4,586,551 = 4,586,551; stored scaling means vs the train fit rows' means: largest difference 0.0e+00 SD; with the validation week added it would be 0.100 SD |
| B6 | no single input gives the answer (validation week, each input alone as a score) | OK | best single inputs: `x_dpers10` 0.171, `x_dpers15` 0.157, `f_d0` 0.128, `fe_dn_q0` 0.115, `x_lowpers15` 0.113; the forest 0.348; base rate 0.0118 |
| B7 | 'band persistence says low at t + 10 and t + 15' is a forecast, not the answer | NOTE | validation week, training roads: true on 1.2% of rows; the link really is unusually slow 15 min later on 32.7% of those (vs 0.81% otherwise); they hold 32.1% of the onsets |
| C1 | HIST on the fit rows leaves the own day out, so within a link x slot it is LOWER on days with onsets | NOTE | fit rows in cells with at least one onset (734,998 rows, base rate 0.063): the within-cell deviation of x_b1 ranks onsets with ROC-AUC 0.990 (PR-AUC 0.848); rows on a day with an onset in their cell have an onset rate of 0.641. This is information about the row's own label, but only usable by a model that can tell which link and slot a row is; validation and test rows never have it |
| C2 | does the own-day trace in HIST change the fold scores? (forests on train days only) | NOTE | as fitted (own day left out): folds 0.3465 / 0.3960, mean 0.3712; past days only (no own-day information): folds 0.3427 / 0.3946, mean 0.3686; no HIST: folds 0.3427 / 0.3880, mean 0.3653. 'As fitted' reproduces the tuning run in 06 (0.3465 / 0.3960) |
| D | accuracy rewards 'always no'; PR-AUC does not, and it does not depend on a threshold | NOTE | validation week, training roads (base rate 0.0118): 'always no' is 98.82% accurate with PR-AUC 0.0118; the forest's best possible accuracy is 98.91%; its PR-AUC is 0.3482 raw and 0.3482 after the frozen calibration map (a monotone map changes no ranking) |

## D. Accuracy vs PR-AUC (validation week, training roads)

| prediction | accuracy | rows called 'slowdown' | precision | onsets caught | PR-AUC | ROC-AUC |
|---|---|---|---|---|---|---|
| always 'no slowdown' | 98.82% | 0 | - | 0% | 0.0118 | 0.500 |
| forest, top 0.5% of links per update | 98.68% | 6,318 | 0.370 | 16.8% | 0.3482 | 0.942 |
| forest, top 1.0% of links per update | 98.41% | 12,152 | 0.299 | 26.2% | 0.3482 | 0.942 |
| forest, top 2.0% of links per update | 97.71% | 23,944 | 0.225 | 38.9% | 0.3482 | 0.942 |
| forest, top 5.0% of links per update | 95.16% | 59,277 | 0.136 | 58.0% | 0.3482 | 0.942 |
| forest, threshold with the best accuracy | 98.91% | 2,948 | 0.677 | 14.4% | 0.3482 | 0.942 |

## B6. PR-AUC of each input alone (validation week, training roads; the better of +x and -x)

| input | PR-AUC alone |
|---|---|
| x_dpers10 | 0.1715 |
| x_dpers15 | 0.1570 |
| f_d0 | 0.1284 |
| fe_dn_q0 | 0.1153 |
| x_lowpers15 | 0.1129 |
| f_dn_d0 | 0.1080 |
| fe_dn_r1_low0 | 0.0968 |
| fe_dn_r1_max0 | 0.0967 |
| fe_up_q0 | 0.0887 |
| f_up_d0 | 0.0853 |
| x_low0 | 0.0759 |
| x_b1 | 0.0688 |
| f_d_change15 | 0.0653 |
| fe_dn_qmove | 0.0580 |
| fe_up_r1_max0 | 0.0580 |
