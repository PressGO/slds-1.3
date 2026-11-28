# Recurring or unusual? Early warning of abnormal slowdowns on Singapore expressways

42.510 Statistical Learning for Data Science (SUTD, 2026), catalog topic 1.3.
Team: Aveline, Liam, Juan Peng, Ronnie

**Question.** For traffic-operations staff: can recent speeds on an expressway link and its neighbouring links,
together with rainfall and time of day, predict whether that link will have an unusual slowdown 15 minutes later?

**Answer.** Yes, partly. On the test week (16-20 Nov 2026, settings frozen before it was opened):

| Score | PR-AUC, roads used for training | PR-AUC, two expressways never trained on |
|---|---|---|
| Time-of-week rate (baseline) | 0.081 | 0.025 |
| Last observation (baseline) | 0.164 | 0.162 |
| Lasso logistic regression | 0.370 | 0.326 |
| **Random forest** | **0.390** (95% interval 0.378-0.409) | **0.367** |

The models say well where a slowdown that has started will spread. They rarely foresee one that starts on a clear
road. A score that only guesses would reach 0.0125.

## Start here

| To see | Open |
|---|---|
| The results in one place | `notebooks/part4_summary.ipynb` |
| 1. How the data were collected and built | `notebooks/part1_data_collection_and_transformation.ipynb` |
| 2. Exploration and the inputs we built | `notebooks/part2_eda_and_feature_engineering.ipynb` |
| 3. The models, from tuning to the test week | `notebooks/part3_models.ipynb` |

The notebooks are saved with their outputs, so they can be read here without running anything.

## Folders

| Folder | What is in it |
|---|---|
| `notebooks/` | the four walk-through notebooks, in order |
| `analysis/` | the collector and the code that turns the raw files into the model tables |
| `modelling/` | the models as numbered scripts, `01_eda.py` to `16_classifiers_and_roc.py` |
| `results/` | the result tables, the record of the frozen settings, the test-week log |
| `figures/` | every figure, made by code |
| `docs/` | how to reproduce, the data rules, the build record, the project plan |

## Run it

The whole project is in Python (3.10 or newer).

1. `./setup_env.sh` (Linux, macOS) or `setup_env.bat` (Windows) makes `.venv` from `requirements.txt`.
2. Get the data (see "Data" below).
3. Run the model scripts once: `modelling/run_all.sh` (about 2 hours, 14 GB of memory; Linux). The notebooks
   compare themselves with what these scripts save. On another system, run the same scripts in the same order.
4. Open the notebooks in `notebooks/` in order and run all cells. Parts 1, 2 and 4 take a few minutes each; Part 3
   takes about an hour. Part 1 also needs the raw files.

The same steps as scripts, the test-week rules and every file are described in **`docs/REPRODUCE.md`**.

## Data

- **Model tables (about 200 MB):** on the Releases page of this repository, with checksums. Unzip them into the
  project folder.
- **Raw files (about 9 GB):** archived on Google Drive. LTA serves only the current state, so they cannot be
  downloaded again from LTA. [TEAM: say here how the instructor gets access to the Drive folder.]
- **What the data are and how they were built:** `DATA.md`.

Contains information from LTA DataMall (Traffic Speed Bands, Traffic Incidents, VMS/EMAS, Estimated Travel Times,
Approved Road Works, Planned Road Openings), accessed from 13 Oct 2026, and from NEA rainfall and MOM public holiday
data accessed from data.gov.sg, which are made available under the terms of the Singapore Open Data Licence version
1.0 (https://data.gov.sg/open-data-licence).

## More

- `DATA.md`: the data sheet (sources, licence, unit, rules, checks, limitations)
- `DECISIONS.md`: the dated decisions
- `AI_USE.md`: how AI tools were used and how the output was checked
- `CONTRIBUTIONS.md`: who did what [TEAM: to fill in]

The report is submitted separately and is not in this repository.
