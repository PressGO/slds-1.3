# Feature engineering: build and checks

40 engineered columns for 9,976,320 weekday rows (20 days x 2,598 links x 192 updates).

## Links in each ring (path distance beyond the next link)

| direction | ring | median links | links with ring |
|---|---|---|---|
| dn | next link (0 m) | 1.0 | 2,571 |
| dn | (0, 500] m | 3.0 | 2,548 |
| dn | (500, 1500] m | 7.0 | 2,489 |
| dn | (1500, 3000] m | 11.0 | 2,398 |
| up | next link (0 m) | 1.0 | 2,578 |
| up | (0, 500] m | 3.0 | 2,561 |
| up | (500, 1500] m | 7.0 | 2,510 |
| up | (1500, 3000] m | 11.0 | 2,422 |

## Checks

| check | result | detail |
|---|---|---|
| band now = fe_norm_p0 - f_d0 is a whole band 1-8 on every usable row | OK | 8,048,388 rows |
| next-link maximum from our dfill series == the build's f_dn_d0 (usable rows) | OK | 0 differ |
| next-link maximum from our dfill series == the build's f_up_d0 (usable rows) | OK | 0 differ |
| HOP values recomputed independently for 400 random rows (Bellman-Ford paths, dict lookups) | OK | 0 values differ |
| fe_norm_p{k} == norm.parquet at the slot of t + k (300 random rows x 6) | OK | 0 differ |

## Columns

`fe_norm_p0`, `fe_norm_p5`, `fe_norm_p10`, `fe_norm_p15`, `fe_norm_p25`, `fe_norm_p30`, `fe_dn_r1_max0`, `fe_dn_r1_low0`, `fe_dn_r2_max0`, `fe_dn_r2_low0`, `fe_dn_r3_max0`, `fe_dn_r3_low0`, `fe_up_r1_max0`, `fe_up_r1_low0`, `fe_up_r2_max0`, `fe_up_r2_low0`, `fe_up_r3_max0`, `fe_up_r3_low0`, `fe_dn_q0`, `fe_up_q0`, `fe_dn_r1_max10`, `fe_dn_r1_low10`, `fe_dn_r2_max10`, `fe_dn_r2_low10`, `fe_dn_r3_max10`, `fe_dn_r3_low10`, `fe_up_r1_max10`, `fe_up_r1_low10`, `fe_up_r2_max10`, `fe_up_r2_low10`, `fe_up_r3_max10`, `fe_up_r3_low10`, `fe_dn_q10`, `fe_dn_qmove`, `fe_dn_r1_none`, `fe_dn_r2_none`, `fe_dn_r3_none`, `fe_up_r1_none`, `fe_up_r2_none`, `fe_up_r3_none`
