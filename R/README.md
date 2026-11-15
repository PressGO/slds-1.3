# R version of the data build

The same build as `analysis/build_data.py`, written in R for the submission. The Python build stays the one
that makes the team's data and uploads it to Drive. The R build reads the same raw files and writes the same
tables to a separate folder, `data_processed/model_r/`. It never uploads anything.

| File | What it does |
|---|---|
| `data_settings.R` | Every setting (dates, splits, label rule, look-backs). The same values as `analysis/data_settings.py`. |
| `data_steps.R` | The steps as small functions: cleaning, link registry, neighbours, joining roads, normal level, labels, inputs, incidents. |
| `build_data.R` | Runs the steps in order and checks each one (114 checks). Stops with `CHECK FAILED` if a check fails. |
| `compare_with_python.R` | Compares every table and every value with the Python build. Ends `RESULT: SAME` or `RESULT: DIFFERENT`. |

## How to run

From the project folder, on the Linux PC (after `analysis/get_context_data.py` has downloaded the rainfall):

```
MALLOC_MMAP_THRESHOLD_=131072 MALLOC_ARENA_MAX=2 systemd-run --user --scope -p MemoryMax=14G Rscript R/build_data.R
Rscript R/compare_with_python.R
```

To rebuild the same days as an earlier Python build, add `--now "YYYY-MM-DD HH:MM"` (the build's time, in
`extra/build_info.json` as `built_as_of`). Options: `--out <folder>` (default `data_processed/model_r`),
`--workers <n>` (default 8). The full build takes about 50 minutes and up to about 11 GB of memory. The two
`MALLOC_` settings make R give freed memory back to the system; without them the build went over 14 GB.

Last check (15 Nov 2026, the 30 days 16 Oct to 14 Nov): `RESULT: SAME`. That's 2.1 billion values in 11 tables plus
`days.csv`, all equal to the Python build of the same morning.

Packages: `arrow`, `data.table`, `jsonlite` (R 4.3; tested with arrow 26.0.1, data.table 1.18.6.1,
jsonlite 2.0.0). `install.packages(c("arrow", "data.table", "jsonlite"))`.

## What is the same, and what is not

- **The same:** `train.parquet`, `test.parquet`, and in `extra/`: `full_table`, `test_full`, `train_lodo`,
  `links`, `neighbours`, `connectors`, `norm`, `connector_norm`, `incidents` and `days.csv`. The same columns,
  rows, order and values, checked by `compare_with_python.R`.
- **Held-out roads:** drawn once on 11 Nov with Python's `random.Random(20261113)`. R's random numbers are
  different, so `data_settings.R` holds the result of that draw (AYE and CTE) instead of drawing again.
- **Not made in R:** `extra/train_sample.parquet` (its 300 links are drawn with Python's random numbers) and
  the team README.
- **Checks:** the same 114 as Python. Two work differently:
  - the held-out check confirms the recorded draw, instead of drawing again;
  - the re-check of 2,000 median cells uses R's `quantile()` instead of numpy.

To give the same numbers as Python down to the last digit, the R code:
- sorts text by bytes (data.table);
- treats a value as unknown when any value it needs is unknown;
- rounds like numpy;
- reads coordinates with arrow (R's `as.numeric` can be one unit off in the last digit);
- divides by a number the way polars does (`x * (1 / n)`).

AI disclosure: translated from the Python version with Claude (Anthropic) on 15 Nov 2026; see `AI_USE.md`.
