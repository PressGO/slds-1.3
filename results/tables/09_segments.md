# 1 km segments (docs/data_rules.md rules 26-32): build, checks and validation scores

374 segments on 87 paths; rows: every segment x 5-min update, 06:00-22:00, weekdays of the train and validation days (1,436,160 rows, 1,075,775 usable).

## Checks

| check | result | detail |
|---|---|---|
| every link on exactly one segment | OK | 2,598 links |
| paths = 87 and segments = 374 (the 18 Nov dry run) | OK | 87 paths, 374 segments |
| every segment lies on one road | OK |  |
| segment length: median / 90th percentile / under 500 m | OK | 996 m / 1101 m / 37 |
| rain: eligible stations = 82 (build_info.json of data version 4) | OK | 82 |
| segment band = length-weighted mean of captured link bands (300 random use rows) | OK | 0 differ |
| f_d5 equals f_d0 of the same segment 5 min earlier (use rows with a row 5 min earlier) | OK | 0 differ |
| y equals U of the same segment 15 min later | OK | 0 differ |
| segment normal level = numpy median of its train-weekday bands (500 cells) | OK | 0 differ |

B1 m chosen by forward-chaining on the segment rows: **48** (fold means: 0: 0.0210, 12: 0.0287, 48: 0.0296, 192: 0.0290, 768: 0.0230, inf: 0.0141).

## Validation week (onset rows; models fitted on the train days with the frozen link settings)

| rows | model | scored rows | onsets | base rate | PR-AUC | precision at 1% |
|---|---|---|---|---|---|---|
| training roads (main) | B1 | 160,228 | 879 | 0.0055 | 0.0470 | 0.043 |
| training roads (main) | B2 | 160,228 | 879 | 0.0055 | 0.2635 | 0.162 |
| training roads (main) | Lasso | 160,228 | 879 | 0.0055 | 0.3624 | 0.197 |
| training roads (main) | RF | 160,228 | 879 | 0.0055 | 0.3842 | 0.197 |
| AYE + CTE (transfer) | B1 | 57,863 | 514 | 0.0089 | 0.0121 | 0.012 |
| AYE + CTE (transfer) | B2 | 57,863 | 514 | 0.0089 | 0.3263 | 0.212 |
| AYE + CTE (transfer) | Lasso | 57,863 | 514 | 0.0089 | 0.3907 | 0.242 |
| AYE + CTE (transfer) | RF | 57,863 | 514 | 0.0089 | 0.4289 | 0.256 |
