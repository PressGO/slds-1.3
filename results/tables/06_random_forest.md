# M2: random forest

Inputs: **BASE + NORM + HOP + HIST** (96 columns, raw scale). Fit rows: train days, training roads, normal now; 10% of the y = False rows kept with a fixed seed, every onset kept. 150 trees while tuning, 400 in the final forest.

## Tuning (forward-chaining inside the train days)

| max_features | min_samples_leaf | fold 1 | fold 2 | mean |
|---|---|---|---|---|
| 0.15 | 5 | 0.3439 | 0.3909 | 0.3674 |
| 0.15 | 20 | 0.3438 | 0.3924 | 0.3681 |
| 0.15 | 80 | 0.3262 | 0.3811 | 0.3537 |
| 0.15 | 320 | 0.3034 | 0.3615 | 0.3325 |
| 0.35 | 5 | 0.3423 | 0.3892 | 0.3658 |
| 0.35 | 20 | 0.3475 | 0.3948 | 0.3711 |
| 0.35 | 80 | 0.3370 | 0.3889 | 0.3629 |
| 0.35 | 320 | 0.3126 | 0.3708 | 0.3417 |
| 0.6 | 5 | 0.3386 | 0.3863 | 0.3624 |
| 0.6 | 20 | 0.3465 | 0.3960 | **0.3712** |
| 0.6 | 80 | 0.3382 | 0.3905 | 0.3643 |
| 0.6 | 320 | 0.3142 | 0.3739 | 0.3440 |

Chosen: **{'max_features': 0.6, 'min_samples_leaf': 20}**.

## Grouped permutation importance (validation week, training roads, 400,000-row sample, 2 repeats)

PR-AUC of the sample with nothing permuted: 0.3423. Each group's columns are shuffled together.

| input group | columns | PR-AUC drop |
|---|---|---|
| NORM: normal level ahead | 8 | 0.1265 |
| HOP: queue distance downstream | 3 | 0.0607 |
| HOP: upstream rings | 16 | 0.0409 |
| HIST: B1 rate | 1 | 0.0383 |
| HOP: downstream rings | 15 | 0.0297 |
| next links (f_up_*, f_dn_*) | 16 | 0.0084 |
| time of day | 1 | 0.0076 |
| own drops (f_d*) | 9 | 0.0051 |
| rain | 4 | 0.0029 |
| day of week | 5 | 0.0008 |
| joining roads (f_conn_*) | 18 | -0.0004 |
