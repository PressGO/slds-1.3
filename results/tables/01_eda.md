# Exploratory analysis (train and validation days; data version 4)

## 1. Collection completeness

Share of the 2,598 expressway links' updates captured, 06:00-22:00, 16 Oct-13 Nov: median hour 0.959, lowest hour 0.083 (Fri 16 Oct). Thu 12 Nov is low because the second collector was down (`DATA.md`, section 6).

## 2. Recurring vs unusual slow traffic (train weekdays)

Of all captured link-updates with band <= 3 (< 30 km/h), 38.3% are unusual (>= 2 bands below that link's normal level) and 61.7% are recurring. A plain 'slow traffic' detector would mostly rediscover rush hour.

## 2b. The floor effect

0.6% of the weekday link x 15-min cells (06:00-22:00) have a normal level of band 1 or 2, where a drop of 2 bands is impossible, and 7 links sit at band <= 2 all day. Unusual events inside heavy recurring congestion are invisible to this label (`DATA.md`, section 8).

## 3. Class balance and the effective sample size

| split | roads | onset episodes (normal just before) | median length (min) |
|---|---|---|---|
| train | training roads | 22,661 | 10 |
| train | AYE + CTE | 8,648 | 10 |
| validate | training roads | 7,481 | 10 |
| validate | AYE + CTE | 3,279 | 10 |

Rows are strongly autocorrelated, so what limits precision is the number of episodes and of days, not the 8 M rows.

| road | held out | split | onset rows | onsets | onset rate |
|---|---|---|---|---|---|
| Aljunied West Flyover |  | train | 14,541 | 113 | 0.0078 |
| Aljunied West Flyover |  | validate | 3,617 | 37 | 0.0102 |
| Ayer Rajah Expressway | yes | train | 1,001,120 | 10,253 | 0.0102 |
| Ayer Rajah Expressway | yes | validate | 257,144 | 3,916 | 0.0152 |
| Bukit Timah Expressway |  | train | 404,081 | 5,786 | 0.0143 |
| Bukit Timah Expressway |  | validate | 103,812 | 1,594 | 0.0154 |
| Central Expressway | yes | train | 668,679 | 7,698 | 0.0115 |
| Central Expressway | yes | validate | 171,523 | 2,514 | 0.0147 |
| East Coast Parkway |  | train | 572,760 | 3,842 | 0.0067 |
| East Coast Parkway |  | validate | 147,649 | 1,408 | 0.0095 |
| Kallang Bahru Flyover |  | train | 11,934 | 169 | 0.0142 |
| Kallang Bahru Flyover |  | validate | 2,889 | 68 | 0.0235 |
| Kallang Paya Lebar Expressway |  | train | 491,752 | 2,611 | 0.0053 |
| Kallang Paya Lebar Expressway |  | validate | 122,662 | 759 | 0.0062 |
| Kranji Expressway |  | train | 319,434 | 1,304 | 0.0041 |
| Kranji Expressway |  | validate | 81,412 | 496 | 0.0061 |
| Marina Coastal Expressway |  | train | 186,795 | 482 | 0.0026 |
| Marina Coastal Expressway |  | validate | 46,657 | 170 | 0.0036 |
| Pan Island Expressway |  | train | 1,578,348 | 21,076 | 0.0134 |
| Pan Island Expressway |  | validate | 403,364 | 6,631 | 0.0164 |
| Seletar Expressway |  | train | 444,283 | 5,891 | 0.0133 |
| Seletar Expressway |  | validate | 118,269 | 1,676 | 0.0142 |
| Tampines Expressway |  | train | 562,623 | 5,148 | 0.0091 |
| Tampines Expressway |  | validate | 148,135 | 1,044 | 0.0070 |

## 4. Dependence

Autocorrelation of the drop (pooled over links): 5 min 0.77, 15 min 0.57, 30 min 0.40, 60 min 0.24.
Correlation of a link's drop now with its downstream link's drop k minutes earlier: k = -15: 0.511, k = -5: 0.654, k = 0: 0.732, k = 5: 0.652, k = 15: 0.507. No clear lead of the downstream link.

## 5. Rain (association, not cause)

| rain in last 30 min | onset rows | onsets | onset rate |
|---|---|---|---|
| dry | 5,825,052 | 47,929 | 0.0082 |
| 0.1-1 mm | 213,577 | 6,261 | 0.0293 |
| 1-5 mm | 93,958 | 4,262 | 0.0454 |
| > 5 mm | 56,750 | 5,242 | 0.0924 |
| no reading | 67,013 | 679 | 0.0101 |

## 6. Drift across the weeks

| split | mean drop (bands) | share low (drop >= 2) |
|---|---|---|
| train | 0.099 | 0.0295 |
| validate | 0.126 | 0.0351 |

The validation week runs a little below the training norm; part of that is the norm being built from the train days themselves (see the leave-own-day-out check).

## 7. What comes before an onset (train weekdays, training roads, normal now)

35.1% of onsets start from a link at or above its normal level (f_d0 <= 0): last observation alone cannot rank those.

| drop now | rows | onsets | onset rate |
|---|---|---|---|
| <= -2 | 36,741 | 221 | 0.0060 |
| -1.5 | 1,683 | 18 | 0.0107 |
| -1 | 280,937 | 1,462 | 0.0052 |
| -0.5 | 14,131 | 111 | 0.0079 |
| 0 | 3,770,317 | 14,484 | 0.0038 |
| 0.5 | 12,266 | 306 | 0.0249 |
| 1 | 435,098 | 17,654 | 0.0406 |
| 1.5 | 2,404 | 531 | 0.2209 |
| >= 2 | 32,974 | 11,635 | 0.3529 |

| band persistence predicts unusual at t+15 | rows | onsets | onset rate |
|---|---|---|---|
| no | 4,542,843 | 30,266 | 0.0067 |
| yes | 43,708 | 16,156 | 0.3696 |

| nearest low link downstream | rows | onsets | onset rate |
|---|---|---|---|
| next link | 52,833 | 14,101 | 0.2669 |
| <= 500 m | 90,689 | 9,293 | 0.1025 |
| 500-1,500 m | 159,517 | 5,360 | 0.0336 |
| 1.5-3 km | 199,494 | 2,661 | 0.0133 |
| none within 3 km | 4,084,018 | 15,007 | 0.0037 |
