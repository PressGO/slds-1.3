# Project 1.3 plan: recurring vs unusual congestion

42.510 Statistical Learning for Data Science · Team: [team name] · Version 2, Wed 14 Oct 2026 (v1: 13 Oct)
Prepared by the project lead (drafted with Claude; logged in `AI_USE.md`)

**How to read this file**

- `[Brief §x p.y]` and `[Catalog §x p.y]` mark requirements from the two course documents, which are the authority. Brief = *Project_Rules_and_Rubric1.pdf*. Catalog = *Project_Catalog1.pdf*.
- **Decision** marks a team choice made by the lead. We can change any decision, but only by adding a dated entry with a reason to `DECISIONS.md`.
- `- [ ]` is a task. When you finish one, tick it and add your initials and the date.

---

## Contents

0. [This week: the proposal (due Sat 17 Oct, 23:59)](#0-this-week-the-proposal-due-sat-17-oct-2359)
1. [Course rules at a glance](#1-course-rules-at-a-glance)
2. [Rubrics and how we secure each point](#2-rubrics-and-how-we-secure-each-point)
3. [What the catalog says about topic 1.3](#3-what-the-catalog-says-about-topic-13)
4. [Our design](#4-our-design)
5. [The proposal](#5-the-proposal)
6. [Future-proofing](#6-future-proofing)
7. [Data sources](#7-data-sources)
8. [Timeline to the presentation](#8-timeline-to-the-presentation)
9. [Roles](#9-roles)
10. [Defence question bank](#10-defence-question-bank)
11. [Questions for the instructor](#11-questions-for-the-instructor)
12. [Repository layout and team files](#12-repository-layout-and-team-files)
13. [Final pre-submission checklist](#13-final-pre-submission-checklist)

---

## 0. This week: the proposal (due Sat 17 Oct, 23:59)

The proposal is worth 5 of the 30 points, and "full score is given if all the checkpoints above are addressed, and the project is approved by the instructor" [Brief §6.1 p.3]. That means three things: cover all 8 checkpoints, fit on one A4 page at 12 pt [Brief §10 p.6], and include numbers from our own pulls that show we can get the data.

### Done so far

- [x] LTA DataMall API key received (13 Oct). The SDK key is not needed (it is for ERP 2.0 in-car units).
- [x] Source check run with the key (13 Oct, 21:39): 315 requests, 0 failed. 143,787 links per snapshot, 2,598 of them expressway links; rainfall backfill works; holidays verified (§7).
- [x] LTA API User Guide v6.10 (1 Oct 2026) saved to the project. It confirms the endpoint, the RoadCategory codes (1 = expressway) and the band → km/h mapping.
- [x] Scope narrowed to expressways (category 1), because category 1 + 2 would be about 147 M rows (§4.3).
- [x] Data pipeline written in Python and tested on simulated data (§12, `claude/PIPELINE.md`).
- [x] Decision: no cloud syncing for now. The data stays on the collecting desktop (risk noted in §6.3).

### Still to do this week

- [ ] **Start the 24/7 collector on the desktop:** `01_collector_monitor.ipynb`, cells 1–4 (cell 3 deletes the old 5-minute task if one was created). Keep the desktop awake (never sleep when plugged in).
- [ ] Check it the next morning: monitor notebook cell 5 (heartbeat under 2 min, about 12 snapshots per hour, no gap over 10 min).
- [ ] Fill in team names in §9 and the proposal draft (§5.2). Everyone reads this file.
- [ ] Send the instructor email in §11 (collection before approval, Python for collection, package due date, AI tools).
- [ ] Create a private GitHub repo for the code (§12). Put `.Renviron` in `.gitignore` in the very first commit. Data stays out of GitHub.
- [ ] Start `AI_USE.md` and log the Claude sessions so far: tool, date, purpose, representative prompts [Brief §5 p.3].
- [ ] **Thu 15 Oct, after ~24 h of collection:** run `get_context_data.py`, then `04_process.ipynb` and `03_visuals.ipynb`. Check that the expressway bands actually move during the day (time–space diagram) and count drops of 2+ bands. Fill the evidence line in the proposal: collector start date, snapshots so far, % complete.
- [ ] **Thu 15 Oct:** finish the one-page draft (§5.2) and run the self-check (§5.3).
- [ ] **Fri 16 Oct:** 30-minute team review; each member must be able to explain every line [Brief §2 p.1]. Export to PDF (A4, 12 pt) and check it is one page. Log AI-drafted text in `AI_USE.md`. Submit Friday night.
- [ ] **Sat 17 Oct:** deadline 23:59. Confirm the submission went through and that the collector is still running.

---

## 1. Course rules at a glance

| Item | Requirement | Source |
|---|---|---|
| Team | At most 4 members, assigned. Every member contributes to question formulation, data work, analysis and communication. Every member speaks and may be asked any question | Brief §2 p.1 |
| Proposal | 5 pts. Due 17 Oct (Sat), 23:59. Max one A4 page, 12-pt font. 8 checkpoints. "The project must be approved before substantial work begins" | Brief §6.1 p.3, §7.1 p.5, §10 p.6 |
| Analysis package | `README.md`, `data_raw/` or `get_data.R`, `data_processed/` (if redistribution is allowed), `R/`, `analysis/`, `figures/`, `report/`, `slides/`, `AI_USE.md`. Must run from raw data to final outputs "without undocumented manual steps" | Brief §6.2 p.4 |
| Final report | 10 pts. Due 6 Dec (Sun), 23:59. Main text ≤ 6 A4 pages at 11 or 12 pt, not counting references and a concise technical appendix. The appendix "is not a way to move essential reasoning out of the graded report". 8 required sections | Brief §6.3 p.4, §10 p.6 |
| Presentation and defence | 15 pts. In class, 7–13 Dec. 20–25 min per team: a 12–15 min talk, then Q&A | Brief §6.4 p.4, §10 p.6 |
| Scoring | Members normally get the same report score. Presentation and defence scores can differ "when individual understanding or contribution is demonstrably uneven" | Brief §2 p.1 |

The documents give no due date for the analysis package or the slides, so §11 asks.

### 1.1 What the project must contain [Brief §3 p.2]

- **Question.** One primary question in one sentence. Template: "For [decision maker or scientific audience], can [information available at the decision time] help [predict, compare, segment, recommend, or prioritise] [well-defined outcome] for [population, place, and period]?" Start from the question, not the method. Use "effect", "impact" or "causes" only if the design supports causal claims.
- **Curated dataset.** "Teams must construct an analysis-ready dataset rather than merely download a file and fit a model." Nine documentation items are required:
  1. source, access date, licence and a persistent link;
  2. unit of observation and target population;
  3. inclusion and exclusion criteria;
  4. a data dictionary;
  5. every join, filter, recode, aggregation and derived variable;
  6. missing-data, duplicate, outlier and measurement-error checks;
  7. a frozen raw snapshot, or a script that recreates it;
  8. limitations in coverage, sampling, proxies and label quality;
  9. confirmation that no confidential or personal information is exposed.

  For an API, also save the retrieval date, query, parameters, response metadata and an immutable analysis snapshot.
- **Tools.** The analysis needs all five of these:
  1. exploratory analysis;
  2. a transparent baseline;
  3. at least two defensible statistical-learning approaches, "preferably from different course families";
  4. out-of-sample evaluation that matches how the model would be used;
  5. interpretation and diagnosis: uncertainty, errors, sensitivity checks, failure cases and limitations.

  "Each method must have a role." Extra algorithms without a purpose earn no credit.

### 1.2 Validation rules that apply to us [Brief §4 p.3]

- Define the outcome and the evaluation metric before comparing models.
- Keep the final test set untouched until the analysis plan is stable.
- Split by time for future prediction. Split by location when the model would be deployed to new places.
- Do preprocessing, feature selection, imputation and tuning on training data only.
- Compare against a simple baseline and report the uncertainty of performance.
- The outcome is imbalanced, so don't rely on accuracy alone. Options: precision, recall, PR-AUC, ROC-AUC, calibration, decision costs.
- Report meaningful negative results. Don't pick only the most favourable metric, subgroup or split.

### 1.3 AI use [Brief §5 p.3]

- Keep `AI_USE.md` with the tool, date, purpose and representative prompts.
- Identify AI-generated code, text and graphics, and say how each was checked.
- Test all code and verify every claim and citation.
- Don't upload confidential, licensed or personal data to an unauthorised service.
- Don't fabricate anything.
- Every member must be able to explain and modify every submitted line.

### 1.4 Ethics [Brief §8 p.6]

- Use public, documented, reusable data, and never try to re-identify anyone.
- Discuss whose behaviour is missing or mismeasured.
- Audit performance across decision-relevant groups.
- Keep prediction separate from fairness, causation and policy.
- Don't make automated high-stakes recommendations from a course project.
- Cite data, software, articles and borrowed ideas.

---

## 2. Rubrics and how we secure each point

### 2.1 Proposal: 5 pts [Brief §7.1 p.5]

Full marks need all 8 checkpoints covered plus instructor approval. See §5.

### 2.2 Final report: 10 pts [Brief §7.2 p.5]

| Criterion | Pts | Full-credit evidence (Brief) | What we will show |
|---|---|---|---|
| Question, relevance and scope | 2.0 | Precise, important, answerable question; audience and decision explicit; claims match the study design | One-sentence question (§4.1); operations-centre decision with an alert budget; "predicts" and "is associated with", never "causes" |
| Data curation and provenance | 1.5 | Reproducible acquisition and construction; correct unit; thoughtful quality checks; dictionary, licence and limitations documented | Raw API archive with request logs; link registry; link × 5-min unit; gap and LinkID-change reports; data dictionary; licence notice |
| Methods and validation | 2.5 | Suitable baseline and competing course tools; choices justified; leakage avoided; tuning and evaluation match intended use | Two catalog baselines, elastic-net logistic regression and a random forest; norms frozen on training weeks; forward-in-time tuning; untouched test week; held-out roads |
| Results, interpretation and limitations | 2.5 | Honest out-of-sample evidence; uncertainty and diagnostics; substantive interpretation; failure cases and limitations discussed | Test-week PR-AUC with day-bootstrap intervals against both baselines; calibration; errors by road type, hour and rain; one failure case; sensitivity table |
| Writing, visuals and reproducibility | 1.5 | Concise structure; legible figures and tables; sources cited; code reproduces outputs; contributions and AI use disclosed | 8-section Quarto report; every figure made by code; a non-author reruns everything from a clean clone; `CONTRIBUTIONS.md`; `AI_USE.md` |

### 2.3 Presentation and defence: 15 pts [Brief §7.3 p.5]

| Criterion | Pts | Full-credit evidence (Brief) | What we will show |
|---|---|---|---|
| Motivation and narrative | 2.0 | Audience, decision, question and stakes immediately clear; coherent argument | First minute: the operator, "rush hour is not news", the question |
| Data story and curation | 2.0 | Provenance, unit, construction, missingness, representativeness, leakage risks | One raw → analysis flow diagram; collection-gap heatmap; one slide on leakage risks |
| Method choice and technical reasoning | 3.0 | Baseline and alternatives justified; assumptions, validation, metrics and tuning "understood rather than recited" | Table of each method's role; why we split by time and by road; why PR-AUC on onsets |
| Results and visual evidence | 3.0 | Readable, decision-relevant graphics; fair comparisons; uncertainty and meaningful errors shown | 2–3 decisive results with intervals; precision at the alert budget; one failure |
| Defence of the approach | 3.0 | Direct, sound answers; defend choices, diagnose weaknesses, separate association from causation, propose revisions | Question bank (§10); two mock defences |
| Team delivery, timing and shared command | 2.0 | All contribute; controlled timing; shared ownership | Every member presents a part and can answer anything; timed rehearsals |

"Scores reflect the quality of reasoning and evidence, not merely whether a named algorithm appears. A simpler, well-validated analysis can outperform an unnecessarily complex one." [Brief §7 p.5]. So we finish the core first and add extras only when they have a role.

### 2.4 Ways we could lose points without noticing

- [ ] Computing norms or thresholds with validation or test weeks. That is label leakage.
- [ ] Splitting rows at random, or tuning on the test week.
- [ ] Filling gaps by interpolation, which uses the future value. Carry the last observation forward and add a data-age flag instead.
- [ ] Reporting only overall metrics. Persistence looks strong there, and the onset results get hidden.
- [ ] Using accuracy as the headline metric.
- [ ] Giving no uncertainty for performance.
- [ ] Writing "rain causes congestion" instead of "rain is associated with…".
- [ ] Going over 6 pages, or moving essential reasoning into the appendix.
- [ ] Having a member who can't explain the label definition or the split.
- [ ] Undisclosed AI use, a key committed to GitHub, or a missing licence notice.
- [ ] Doing substantial analysis before approval.

---

## 3. What the catalog says about topic 1.3

[Catalog §1.3 p.2]

> **Primary question:** For selected Singapore road segments, can a model distinguish predictable peak-hour congestion from unusual low-speed events early enough to support route or operations decisions?
>
> - **Why it matters:** A useful warning system should not merely rediscover weekday rush hour; it should identify deviations that matter to travellers or network operators.
> - **Data curation:** Use the LTA Traffic Speed Bands API to collect snapshots at a fixed interval over several weeks; archive the API responses; resolve road-segment identifiers; join rainfall and calendar features; define "unusual" relative to each segment's normal time-of-week distribution.
> - **Possible tools:** Segment-level regression; logistic classification of unusual congestion; CART/random forest; clustering of roads by daily profile; regularised models for many lagged features.
> - **Validation:** Use later days as the test set and keep entire road segments out for a transferability analysis. Compare with time-of-week and last-observation baselines.
> - **Defence focus:** API collection failures, changing LinkIDs, ordinal speed bands, spatial dependence, incidents not observed in the data, and deployment latency.
>
> Authoritative source: LTA DataMall API guide, including Traffic Speed Bands updated at five-minute frequency.

- **Difficulty:** Advanced, meaning the topic "requires API collection, large/high-dimensional data, careful temporal design, or specialised interpretation". The catalog's natural course tools for 1.3 are regression, classification, trees and clustering [Catalog §7 p.9].
- **Team must specify:** "the data, time period, decision to be supported, and outcome of interest" [Catalog p.1].
- **Methods from class:** linear and logistic regression, LDA, discrete-choice models, regularisation and model selection, clustering and recommendation systems, SVD/PCA, CART and random forests, survival analysis, and multiple testing [Catalog p.1].

---

## 4. Our design

Everything in this section is a **Decision**. It is fixed now so that the outcome and metric are defined before any model comparison [Brief §4 p.3].

### 4.1 Question

> For traffic-operations staff, can speed bands observed up to time *t* on a road segment and its neighbours, together with recent rainfall and calendar information, predict whether that segment will be in an unusual low-speed state 15 minutes later, for Singapore expressway segments on weekdays between 13 Oct and 20 Nov 2026?

Why this framing:

- **"Distinguish recurring from unusual" becomes a definition.** Unusual means well below the segment's own time-of-week norm. The norm absorbs recurring peak congestion, so a model can't score well just by rediscovering rush hour.
- **The learning problem is "early enough".** Spotting an unusual state *now* is just a comparison with the norm, not something to learn. What a model has to learn is the state 15 minutes ahead, and above all the **onsets**: segments that are normal now and unusual 15 minutes later.
- **The decision maker is an operations centre.** Staff can check cameras, dispatch recovery vehicles or update road signs, but can only follow up a few alerts at once. So **precision at a fixed alert budget** is the decision-relevant metric. Travellers making route choices are a secondary audience, since navigation apps already show live speeds.
- **Why 15 minutes:** it leaves time to verify and act. We also run 5, 10 and 30 minutes as a sensitivity check.

### 4.2 Unit, outcome and labels

- **Unit:** link (LinkID) × LTA update (about every 5 minutes). Time *t* is LTA's `lastUpdatedTime`, which every speed-band response carries (found in the 13 Oct check); our retrieval time is the fallback, flagged in the panel as `t_from_retrieval`.
- **Norm:** `norm(l, daytype, slot)` is the median band for link *l*, day type (Mon–Thu or Fri) and 15-minute slot. It is computed from **training weeks only** and then frozen.
- **Band deficit:** `d(l,t) = norm(l, daytype, slot) − band(l,t)`.
- **Unusual state:** `U(l,t) = 1` if `d ≥ 2` at both *t* and *t − 5 min*, i.e. two consecutive snapshots.
- **Outcome:** `Y(l,t) = U(l, t + 15 min)`. **Onset rows** are rows with `U(l,t) = 0`.
- **Why 2 bands for 2 snapshots:** a 1-band change happens whenever speed crosses a band edge, so it's mostly noise, and one-snapshot dips flicker. Sensitivity checks: 1 band for 3 snapshots, and a rolling 21-day norm instead of the frozen one.
- **Known limitation, the floor effect:** where the norm is already band 1–2 at peak, a 2-band drop is impossible. Unusual events inside heavy recurring congestion are therefore invisible to this label. We say so in the report.

### 4.3 Population and selection rule (coded, never hand-picked)

- **What we collect:** the whole network. We analyse a pre-specified subset.
- **Links:** RoadCategory 1 = Expressways (LTA API guide v6.10 §2.19: 1 Expressways, 2 Major Arterial, 3 Arterial, 4 Minor Arterial, 5 Small Roads, 6 Slip Roads, 8 Short Tunnels). 2,598 links on 13 Oct. Keep links present in ≥ 95% of valid snapshots in the first collection week; record the final count `[L]` in `DECISIONS.md`.
- **Why not major arterials too:** categories 1 + 2 = 27,345 links ≈ 147 M rows, too many for laptop modelling. Expressways also fit the operations-centre audience and give about 10 roads for the held-out-road test. Major arterials stay in the archive as a fallback or secondary analysis.
- **Time:** weekdays excluding public holidays, 06:00–22:00, which is 192 snapshots per day. Mon 9 Nov is the Deepavali public holiday and is excluded.
- **Weekends and nights:** descriptive only. Weekend norms would rest on 3 days each, which is too noisy. Nights have little traffic and sit at the band ceiling.
- **F1 closures:** the closures ran to 05:30 Tue 13 Oct, so they end before collection starts and need no exclusion rule.

### 4.4 Split (dates fixed now)

| Set | Dates | Weekdays used | Purpose |
|---|---|---|---|
| Train | Tue 13 Oct – Fri 6 Nov | 19 (15 Mon–Thu, 4 Fri) | Norms, model fitting, cross-validated tuning |
| Validation | Sat 7 – Fri 13 Nov | 4 (Mon 9 Nov is a public holiday) | Model selection, calibration, alert threshold |
| Test | Sat 14 – Fri 20 Nov | 5 | Used once, after the plan freeze |
| Transfer | 2–3 whole roads (by RoadName), drawn at random with a fixed seed before modelling | Same weeks | Never used in training or tuning; evaluated on the test week |

- **School calendar:** Term 4 ends Fri 20 Nov and the school holidays start Sat 21 Nov, so the window stays in term time. Schools used as O-Level venues end term on Fri 23 Oct. In EDA, compare weekday peak profiles before and after 23 Oct. If they shift, the rolling-norm sensitivity check becomes important.
- **Sample size:** `[L]` links × 28 weekdays × 192 snapshots = `[L] × 5,376` rows. With 2,598 expressway links that is about **14.0 M rows**.
- **Effective sample size:** much smaller than the row count. Rows are strongly autocorrelated, so what limits precision is the number of distinct unusual episodes and of test days. Report episode counts alongside row counts.

### 4.5 Features (all available at time *t*)

- **Own history:** deficit at *t*, *t − 5*, …, *t − 30*, and the change over the last 15 minutes.
- **Neighbours:** upstream and downstream neighbour deficits at the same lags. We find neighbours by matching one link's end coordinates to another link's start coordinates, within about 20 m. Congestion spreads upstream, so a slowdown downstream is a plausible early signal. EDA will test this rather than assume it.
- **Rainfall:** from the station nearest the link midpoint, total over the last 15 and 30 minutes. Only use readings timestamped ≤ *t* − 5 min, as a conservative allowance for publication lag.
- **Calendar and road:** time of day (15-minute slot), a Friday flag, and road category.
- **Data age:** a flag when the previous snapshot is missing. Never interpolate.
- **Planned road works:** LTA's Approved Road Works list (collected daily) is known in advance, so an "active road works on this road today" flag is legitimate information at time *t*. Five of the seven incidents in the 13 Oct check were road works.
- **Incidents:** used to audit labels. Use them as a predictor only in a sensitivity run, only incidents reported before *t*, and never the "Heavy Traffic" type, which is itself a congestion report and would be circular.

### 4.6 Methods and their roles [Brief §3.3 p.2]

| Model | Course family | Role | Notes |
|---|---|---|---|
| B1: time-of-week rate | Baseline | What "knowing rush hour" alone achieves: the training-week rate of `U` for each link × slot | Required by the catalog |
| B2: persistence | Baseline | Last observation: score = current deficit `d(l,t)` | Required by the catalog. Expect it to be strong overall and weak on onsets |
| Norm (stage 1) | Segment-level profile model | Defines what "recurring" means | Median by slot. A smooth regression of expected band is the alternative; be ready to discuss the bias–variance trade-off between them |
| M1: elastic-net logistic regression | Logistic regression + regularisation | Interpretation; handles many correlated lags | `glmnet`. Standardise using training statistics. Tune λ and α by forward-chaining CV within the training weeks. Check coefficient stability with a bootstrap |
| M2: random forest | CART / random forests | Nonlinear benchmark, e.g. rain × peak × road type | `ranger`. Tune `mtry` and `min.node.size` with the same CV. Use permutation importance on the validation week. Calibrate on the validation week |
| M3 (stretch): clustering of daily profiles, with PCA first if needed | Clustering, PCA | Segmentation for error analysis and transfer | Only once Tiers 1–2 (§6.2) are done |

If the training set is too big for `ranger`, subsample the negatives with a fixed seed and recalibrate probabilities on the validation week afterwards, because subsampling distorts the probabilities.

### 4.7 Metrics (fixed before modelling) [Brief §4 p.3]

- **Primary:** PR-AUC on onset rows (`U(l,t) = 0`) in the test week, comparing M1 and M2 against B1 and B2.
- **Secondary:**
  - PR-AUC on all rows;
  - precision and recall at a fixed alert budget (the top *k* links in each 5-minute snapshot, with *k* set on the validation week; report 2–3 values of *k*);
  - calibration (Brier score and a reliability plot);
  - event level: the share of test episodes warned at least 10 minutes before onset, and false alarms per hour.
- **Prevalence:** report it next to every PR-AUC, because it's the PR-AUC a random scorer would get.
- **Uncertainty:** 95% intervals from a block bootstrap over test days. Use a paired bootstrap for the model − baseline differences. Five test days is thin, and we'll say so.
- **Subgroups:** expressway vs arterial, peak vs off-peak, rain vs dry, and the held-out roads.

### 4.8 EDA plan [Brief §3.3 p.2]

- **Collection completeness:** a heatmap of gaps (day × time of day) and LinkID churn.
- **Band distributions:** by road category and hour, plus norm curves for example links.
- **Motivating figure:** the share of low-speed snapshots (band ≤ 3) that are recurring vs unusual, by hour. It shows that a naive congestion detector mostly rediscovers rush hour.
- **Class balance:** prevalence of `U` by hour and road type, and the distribution of episode durations.
- **Dependence:** autocorrelation of deficits, and the lagged cross-correlation between a link and its downstream neighbour. The second one justifies the neighbour features, or shows they aren't needed.
- **Rain:** deficit distributions in rain vs dry, presented as association only.

### 4.9 Diagnosis and sensitivity [Brief §3.3 p.2]

- **Errors:** break down errors by subgroup. Check the largest false alarms and misses against the incidents feed.
- **Sensitivity checks:**
  - threshold (1 band for 3 snapshots);
  - horizon (5, 10 and 30 minutes);
  - norm (frozen vs rolling 21-day, and a leave-own-day-out norm for training rows);
  - with and without neighbour features;
  - with and without incident features.
- **Failure case for the talk:** for example, incident-driven onsets with no precursor, or the floor effect at peak.
- **Limitations:**
  - we don't know how LTA derives the bands, and each band is 10 km/h wide, so small slowdowns are invisible;
  - band 8 is open-ended (≥ 70 km/h per client docs);
  - the data cover one season and term time only;
  - incidents are reported incompletely.

---

## 5. The proposal

### 5.1 Format

- One A4 page, 12-pt font [Brief §10 p.6]. Suggested: 2 cm margins, single spacing, about 450–520 words.
- Use the 8 checkpoints as headings, in the brief's order, so the marker can tick them off.
- Skip the literature review. Our own numbers carry more weight than adjectives.
- Page check: the draft below fits one A4 page at 12 pt with 2 cm margins, even in a wide font (DejaVu Serif), with a few lines to spare. Filling in the brackets won't change that much, but check the exported PDF anyway.

### 5.2 Draft to adapt (fill in the [brackets])

<!-- proposal-start -->

**Recurring or unusual? Early warning of abnormal slowdowns on Singapore roads**
Team: [A], [B], [C], [D]. Catalog topic 1.3.

**Question and why it matters.** For traffic-operations staff, can speed bands observed up to time *t* on a road segment and its neighbours, together with recent rainfall and calendar information, predict whether that segment will be in an unusual low-speed state 15 minutes later, for Singapore expressway segments on weekdays between 13 Oct and 20 Nov 2026? Weekday rush hour is predictable from the clock alone. A useful warning must flag departures from each segment's normal pattern early enough to act, so we judge models by what they add over time-of-week and last-observation baselines, especially for new events.

**Audience.** A road network operations centre that can follow up only a limited number of alerts. Precision at a fixed alert budget is therefore our decision metric.

**Data and access.** LTA DataMall Traffic Speed Bands for the whole network, saved at every LTA update (about every 5 minutes) with raw responses archived; also LTA incidents and planned road works, NEA 5-minute rainfall (89 stations) and MOM public holidays, all under the Singapore Open Data Licence. Evidence: a test pull on 13 Oct returned 143,787 links (2,598 on expressways) in 288 requests with no failures; rainfall downloads work for past dates; collector running since [date] with [n] snapshots ([x]% of expected).

**Unit, outcome, size.** Unit: segment × 5-minute snapshot. A segment is unusual when it is at least 2 speed bands below its median for that 15-minute slot and day type for 2 consecutive snapshots, with medians estimated from training weeks only. About 2,600 expressway segments × 28 weekdays × 192 snapshots (06:00–22:00) ≈ 14 M rows. Positives will be rare and onsets rarer, so we will report episode counts.

**Methods.** Baselines: the historical unusual rate for each segment and slot, and persistence (current band deficit). (1) Elastic-net logistic regression on lagged own and neighbour deficits, rainfall and time of day: interpretable, and handles many correlated lags. (2) Random forest: a nonlinear benchmark for interactions such as rain × peak × road type. (3) If time allows, clustering segments by daily profile, for error analysis.

**Validation.** Train 13 Oct–6 Nov, validate 7–13 Nov, test 14–20 Nov, with the test week untouched until the plan is frozen. Tuning by forward-chaining cross-validation within the training weeks. Transfer: whole roads held out. Primary metric: PR-AUC for segments that are normal at *t* (onsets). Also precision and recall at a fixed alert budget and calibration, with 95% intervals from a day-level bootstrap.

**Largest risk and fallback.** Collection gaps or changing LinkIDs could leave too little clean data, or there may be too few unusual events. Fallbacks: a second collector on another key, adding major arterials, 15-minute resolution, and a 1-band threshold.

**Responsibilities.** [A] collection and data quality; [B] labels, EDA and data documentation; [C] logistic model and validation code; [D] random forest, figures and report assembly. Every member reviews another member's code and presents.

<!-- proposal-end -->

### 5.3 Self-check before submitting

Brief §6.1 p.3 checkpoints:

- [ ] Team members and provisional title
- [ ] Primary question and why it matters
- [ ] Intended decision maker or audience
- [ ] Proposed sources, with evidence the data are accessible (numbers from our own pulls)
- [ ] Unit of observation, expected outcome, approximate sample size
- [ ] Two or three candidate methods and the validation design
- [ ] Largest anticipated risk and a fallback plan
- [ ] Short division of responsibilities

Catalog §6 p.8 (every answer must be "yes"):

- [ ] One primary question, one primary unit, one principal evaluation target?
- [ ] Can the raw data be legally accessed and curated in the time available?
- [ ] Is there enough for a nontrivial baseline and two justified approaches?
- [ ] Does the validation resemble the intended use, not a convenient random split?
- [ ] Can we explain why an accurate answer would matter?
- [ ] Is there a smaller fallback if collection or the advanced method fails?

Format:

- [ ] One page in the exported PDF.
- [ ] 12-pt font.
- [ ] All names included.
- [ ] No causal words.
- [ ] AI use logged.

---

## 6. Future-proofing

The aim is that late surprises (API changes, collector crashes, instructor feedback, a member falling ill) cost us hours rather than points.

### 6.1 Practices, starting now

1. **Raw data is never edited.** The collector saves responses exactly as received (gzipped), writing each file under a temporary name and renaming it, so no file is ever half-written. Processing reads raw files and writes processed ones, and processed files can always be rebuilt (`04_process.ipynb`).
2. **Self-healing collector.** Retries with back-off, consistency checks on every snapshot, one feed failing never stops the others, and a Windows watchdog task restarts it within 10 minutes after a crash or reboot (`claude/PIPELINE.md`).
3. **Daily health check (2 minutes, data lead).** Monitor notebook cell 5: heartbeat, snapshots in the last 24 h, gaps, failures and projected disk use. Post one line in the team chat.
4. **Backups (deferred).** For now the data lives only on the collecting desktop. Before the end of the training weeks (6 Nov), copy `data_raw/` to an external drive or a cloud folder at least weekly, and consider a second collector on a teammate's key (§6.3).
5. **Pre-registration in `DECISIONS.md`.** Every frozen choice gets a date, a reason and an author. Changes are appended, never edited in place. This is our evidence that the outcome and metric were defined before models were compared [Brief §4 p.3].
6. **One `config.yml`** (for the R modelling stage) holding dates, thresholds, horizon, *k*, seeds, paths and the API endpoint. Sensitivity runs and any changes the instructor asks for then become config edits, not code rewrites.
7. **Test lock.** Test-week rows go to a separate file that only `90_final_test.R` reads. EDA and tuning scripts stop with an error if they ever see a date after 13 Nov.
8. **Reproducibility.**
   - An `renv` lockfile for R; a `requirements.txt` (polars, numpy, matplotlib) for the Python notebooks. The collector and context script use only the Python standard library.
   - `run_all.R` runs every script in order, and seeds are set.
   - Figures are saved by code only.
   - Before submission, a member who didn't write the pipeline reruns everything from a clean clone [Brief §6.2 p.4].
9. **Write as we go.** Start the 8-section `report.qmd` skeleton now. Each workstream drafts its section as soon as its work is done. Update the data dictionary whenever a variable is added.
10. **Grading records.** Update `CONTRIBUTIONS.md` weekly and `AI_USE.md` after every AI session [Brief §5 p.3, §6.3 p.4].
11. **Schema and endpoint changes.** Endpoints are set at the top of `lta_collector.py`. The processing notebook's quality report (updates per day, coverage, missing bands, time-format fallback) shows quickly if LTA changes the feed.
12. **Key hygiene.** Keys live only in `.Renviron` (or a Windows user variable). Never commit them, and never paste them into chats or AI tools; LTA's terms require keeping credentials confidential.

### 6.2 Scope ladder: what to cut if time runs out

| Tier | Contents | Status |
|---|---|---|
| 1. Must (most of the points) | Collection and documentation; labels; B1, B2, M1, M2; temporal split; test-week metrics with intervals; EDA figures; limitations | [ ] |
| 2. Should | Held-out-road transfer; calibration and alert-budget analysis; event-level metrics; sensitivity table | [ ] |
| 3. Could | Clustering of profiles (M3); incident features; school-holiday stress test (23–27 Nov); survival analysis of episode duration (or keep it as the "next step" in the Discussion) | [ ] |

### 6.3 Risk register

| Risk | Early signal | Response |
|---|---|---|
| Collector downtime (desktop asleep, off, offline) | Monitor cell 5: heartbeat old, fewer than ~280 snapshots a day | Fix power settings; the watchdog restarts the collector. Document gaps, exclude affected rows, report % excluded by time of day |
| Data lost with the desktop (disk failure, accident) | — | No sync for now (team decision, 14 Oct). Weekly copy of `data_raw/` to an external drive or cloud folder from 21 Oct at the latest; optional second collector |
| Paging overlaps a 5-minute update | `log_speedbands.csv`: status `ok_flagged`, mixed `lastUpdatedTime` | Already handled: the collector probes every minute, fetches pages with 6 threads (~10 s) and refetches once if LTA updated mid-fetch |
| LinkIDs change | Registry shows new or vanished IDs | Match by coordinates; keep links present in ≥ 95% of snapshots |
| Too few unusual events | Only a few hundred onset episodes in the training weeks | Add major-arterial (category 2) links, use the 1-band rule or a 10-minute horizon, and document the change in `DECISIONS.md` |
| Endpoint or schema change | Schema warning in the log | Update the path in config; parse fields by name |
| Traffic drifts within the window | Peak profiles differ before and after 23 Oct | Rolling-norm sensitivity check; a post-23-Oct flag |
| Random forest too slow | Fits take hours | Subsample negatives and recalibrate; use fewer trees while tuning |
| Instructor asks for changes | Approval feedback | Change config and `DECISIONS.md`, not the pipeline |
| A member becomes unavailable | — | Every workstream has a second (§9) |

---

## 7. Data sources

Full details: `claude/data_sources_check.md` (checked live 13 Oct) and `claude/PIPELINE.md`.

| Dataset | Role | How we get it | Key? | Status |
|---|---|---|---|---|
| LTA Traffic Speed Bands (API guide §2.19) | Outcome and main features | `lta_collector.py`: probe every minute, full fetch at each LTA update (~5 min) | **Yes**, our LTA key | ✅ Tested 13 Oct: 143,787 links, 288 pages, 0 failures |
| LTA Traffic Incidents (§2.18) | Label audit, failure cases | `lta_collector.py`: every 2 min, saved on change | Same key | ✅ Tested; messages carry a report time, e.g. "(13/10)21:34" |
| LTA VMS/EMAS (§2.20), Estimated Travel Times (§2.13) | Extra signals, fallback | `lta_collector.py`: every 2 / 5 min, saved on change | Same key | ✅ In collector |
| LTA Approved Road Works (§2.16), Planned Road Openings (§2.15) | Planned disruptions (known in advance) | `lta_collector.py`: once a day | Same key | ✅ In collector |
| NEA rainfall (data.gov.sg) | Weather feature | `get_context_data.py`, downloaded after the fact by date | No (optional key raises the limit) | ✅ Tested 13 Oct, incl. 30 days back |
| MOM public holidays 2026 | Calendar | `get_context_data.py` (data.gov.sg dataset `d_149b61ad0a22f61c09dc80f2df5bbec8`) | No | ✅ Verified |
| MOE school calendar 2026, F1 closures | Analysis window, drift check | Dates typed into `get_context_data.py` from the MOE press release and LTA OneMotoring, with sources | No | ✅ Verified |

- **Not used:** OneMap (its own restrictive terms), LTA geospatial layers (link coordinates are enough), Traffic Flow, loop-detector counts (NDA). No public archive of past speed bands exists, so our collection is the only source, as the catalog intends.
- **Licence:** all of these fall under the Singapore Open Data Licence v1.0. The README and report must show the attribution notice with a link to the licence, and must not imply any agency endorses our work.
- **Personal data:** none, since speed bands are per road link. Check that incident messages contain nothing personal before publishing any examples.

---

## 8. Timeline to the presentation

| Date | Milestone | Owner |
|---|---|---|
| Tue 13 Oct | ✅ Key received; source check passed | Lead |
| Wed 14 Oct | Pipeline written; collector live on the desktop | Data lead |
| Thu 15 Oct | Evidence numbers; proposal draft | All |
| Fri 16 Oct | Review; submit | Lead |
| **Sat 17 Oct, 23:59** | **Proposal deadline** | — |
| 18 Oct until approval | Collection and documentation only (link registry, gap reports). No modelling | Data lead, labels lead |
| By Wed 21 Oct, then weekly | Copy `data_raw/` to an external drive or cloud folder (backup) | Data lead |
| After approval | Build the pipeline on data so far (first two weeks as a development set); EDA; feature code | All |
| Fri 30 Oct | `DECISIONS.md` v1 frozen: label rule, features, metrics, transfer roads (seeded draw) | Lead |
| Sat 7 Nov | Norms frozen from the training weeks; training panel built | Labels lead |
| 7–13 Nov | Fit and tune with forward-chaining CV inside the training weeks | Models leads |
| Sat 14 – Sun 15 Nov | Validation-week evaluation; final model choice; *k* and calibration set | Models leads |
| Fri 20 Nov | **Plan freeze**: git tag `plan-freeze` before any test-week analysis | Lead |
| Sat 21 – Sun 22 Nov | Run `90_final_test.R` once and record every result, including negative ones | Models lead |
| 23–29 Nov | Diagnostics, sensitivity, transfer, figures. Optional school-holiday stress test (needs collection to 27 Nov) | All |
| Mon 30 Nov | Full report draft | Report lead |
| Tue 1 – Sat 5 Dec | Cut to 6 pages; clean-clone rerun by a non-author; slides; two timed rehearsals and a mock defence | All |
| **Sun 6 Dec, 23:59** | **Report deadline** | Lead |
| **7–13 Dec** | **Presentation and defence** | All |

Keep the collector running until at least Fri 20 Nov, 23:59, or until Fri 27 Nov if we do the stress test.

---

## 9. Roles

Each member leads one workstream and is the second on another. Everyone also contributes to question formulation, data work, analysis and communication [Brief §2 p.1]. With three members, merge workstreams 3 and 4.

| Workstream | Lead | Second | Outputs |
|---|---|---|---|
| 1. Collection and pipeline | [A] | [C] | Collector (Python), daily health checks, backups, processing notebook |
| 2. Labels, EDA, data documentation | [B] | [D] | Norms, labels, EDA figures, data dictionary, limitations |
| 3. Models and validation | [C] | [A] | B1, B2, M1, CV and split code, bootstrap |
| 4. Benchmark, figures, report | [D] | [B] | M2 (and M3), final figures, report assembly |
| Coordination | [lead] | — | `DECISIONS.md`, submissions, instructor contact, timeline |

Presentation outline, 12–15 min in total [Brief §6.4 p.4]:

1. Problem and audience: [A], 2 min
2. Data story: [B], 3 min
3. Methods and validation: [C], 3.5 min
4. Results: [D], 3.5 min
5. One failure, limitations and the direct answer: [A]/[B], 2 min

Every member also prepares to answer any question in §10.

---

## 10. Defence question bank

Start drafting answers now and keep them in `docs/defence.md`. They cover the catalog's defence focus [Catalog §1.3 p.2] and the topics in Brief §6.4 p.4: sampling, leakage, variable availability, assumptions, model choices, tuning, uncertainty, ethics and alternative decisions.

1. Why not just flag low speeds? *(Point to the recurring vs unusual figure.)*
2. How exactly is "unusual" defined, and why 2 bands for 2 snapshots? What changes under 1 band?
3. Could the label leak into the features? *(Norms are frozen from training weeks; a leave-own-day-out check covers training rows.)*
4. Why split by time and by road instead of using random CV?
5. Why PR-AUC on onsets? What's the prevalence, and what would a random model score?
6. Persistence is strong overall. What does your model add?
7. How did you tune, and on what data?
8. Speed bands are ordinal. What does subtracting bands assume? How do you handle band 8 being open-ended?
9. What happens when the API fails, or when LinkIDs change?
10. Neighbouring links are correlated. Are your intervals too narrow?
11. Rain has a positive coefficient. Does rain cause congestion? *(No: it's an association, conditional on the other features.)*
12. How do incidents you can't see affect the labels and the errors?
13. Deployment latency: when would an operator actually receive the alert?
14. Would your conclusion change with a 1-band threshold, a 30-minute horizon or a rolling norm?
15. Do arterial roads get worse warnings than expressways? Who is under-served?
16. Why a median-by-slot norm rather than a regression for expected speed? *(The bias–variance trade-off.)*
17. Are the random forest's probabilities calibrated? Which variable-importance method did you use, and why?
18. Why 15 minutes?

---

## 11. Questions for the instructor

The documents leave these open:

1. Collection before approval. "The project must be approved before substantial work begins" [Brief §6.1 p.3], but the speed-band feed only shows the current state, so any day we don't record is lost for good. The proposal also needs "evidence that the data are accessible". May we run the collector before approval?
2. The proposal gets "full score … if all the checkpoints above are addressed, and the project is approved by the instructor" [Brief §6.1 p.3; also §7.1 p.5]. Is there partial credit, or a chance to resubmit if changes are requested?
3. Brief §10 gives no due date for the analysis package or slides [Brief §6.2 p.4]. Are they due with the report on 6 Dec?
4. The brief requires "a frozen raw-data snapshot or a script that recreates it" [Brief §3.2 p.2], and says "Large raw files need not be submitted if the retrieval instructions are reliable" [Brief §6.2 p.4]. No script can re-download past snapshots. Would a shared-drive link with checksums be acceptable?
5. AI use is "subject to course and university policy" [Brief §5 p.3]. Which tools are authorised?
6. How and where should the proposal be submitted, and in what format?
7. The package layout assumes R [Brief §6.2 p.4]. Is it acceptable to collect and process the data with Python scripts, with all statistical analysis in R?

Email template (send tonight):

> **Subject:** 42.510 project 1.3: data collection before proposal approval
>
> Dear Prof. Das,
>
> We are [team name] ([names]), working on catalog topic 1.3 (Singapore congestion warning). The LTA Traffic Speed Bands API only returns the current snapshot, so any day we don't record can't be recovered later. May we start an automated 5-minute collection now, before the proposal is approved? We would only archive raw responses and run access checks, and would do no modelling until approval.
>
> We also have four short questions:
> 1. Are the analysis package and slides due with the report on 6 Dec?
> 2. Our raw archive may run to several GB, and past snapshots can't be re-downloaded. Would a shared-drive link with checksums satisfy the frozen raw-data snapshot requirement?
> 3. Is it acceptable to collect and process the data with Python scripts, with all statistical analysis in R?
> 4. Which generative-AI tools are authorised under the course policy?
>
> Best regards,
> [names]

---

## 12. Repository layout and team files

This follows Brief §6.2 p.4, plus planning files of our own.

```
slds-1.3-congestion/
├── README.md                  how to reproduce; licence notice
├── PROJECT_PLAN.md            this file
├── DECISIONS.md               dated, frozen definitions and any changes
├── CONTRIBUTIONS.md           who did what, updated weekly
├── AI_USE.md                  tool, date, purpose, prompts, how checked
├── .Renviron                  API keys: never committed
├── 01_collector_monitor.ipynb set up, start and health-check the collector
├── 03_visuals.ipynb           maps, time–space diagrams, band shares
├── 04_process.ipynb           raw → link registry, panel, incidents, analysis panel
├── analysis/
│   ├── lta_collector.py       24/7 LTA collector (Python standard library)
│   ├── get_context_data.py    NEA rainfall + calendar (MOM, MOE, F1)
│   ├── 00_check_sources.R     one-off source check (done 13 Oct)
│   └── (R modelling scripts: 05_labels.R, 06_models.R, 07_validate.R, 90_final_test.R, run_all.R)
├── data_raw/                  collector output; large, not in GitHub
├── data_processed/            Parquet tables for R (arrow::open_dataset)
├── R/                         R functions: norms, features, metrics
├── figures/                   produced by code only
├── report/                    report.qmd → PDF
├── slides/                    slides source → PDF
└── docs/                      LTA API guide, course PDFs, defence.md
```

Superseded and not to be used: `collect.py`, `01_collect.R`, `collector_setup_py.ipynb`, `01_collector_setup.ipynb`, `02_map_speedbands.R`.

Python packages for the notebooks: `polars`, `numpy`, `matplotlib`. R packages for modelling: `arrow`, `dplyr` or `data.table`, `glmnet`, `ranger`, `PRROC` or `yardstick`, `ggplot2`, `renv`, `quarto`.

First entries for `DECISIONS.md`:

```
2026-10-13  Outcome: U(l,t+15); unusual = deficit >= 2 bands for 2 consecutive snapshots   (lead)
2026-10-13  Norm: median band by link x daytype (Mon-Thu, Fri) x 15-min slot, training weeks only, frozen
2026-10-14  Population: RoadCategory 1 (expressways, 2,598 links on 13 Oct), presence >= 95%; weekdays excl. PH; 06:00-22:00
2026-10-14  Time t = LTA lastUpdatedTime (fallback: retrieval time)
2026-10-14  Collection: lta_collector.py (Python) on the desktop; no cloud sync for now, weekly backup from 21 Oct
2026-10-13  Split: train 13 Oct-6 Nov; validate 7-13 Nov; test 14-20 Nov (locked)
2026-10-13  Primary metric: PR-AUC on onset rows, test week; 95% day-block bootstrap
```

README licence notice (adapt the dates):

> Contains information from LTA DataMall (Traffic Speed Bands, Traffic Incidents, VMS/EMAS, Estimated Travel Times, Approved Road Works, Planned Road Openings), accessed [dates] from LTA DataMall, and from NEA rainfall and MOM public holiday data accessed from data.gov.sg, which are made available under the terms of the Singapore Open Data Licence version 1.0 (<https://data.gov.sg/open-data-licence>).

---

## 13. Final pre-submission checklist

[Brief §9 p.6], ticked before 6 Dec.

- [ ] Team contains no more than four members.
- [ ] The primary question fits in one sentence and identifies an audience.
- [ ] Dataset provenance, licence, retrieval date, unit and inclusion rules are documented.
- [ ] Raw-to-final processing is scripted and reproducible.
- [ ] A transparent baseline and at least two justified approaches are compared.
- [ ] The validation split matches the intended future use and avoids leakage.
- [ ] Metrics, uncertainty, important errors and limitations are reported.
- [ ] Causal language is avoided unless supported by the design.
- [ ] The report is within the page limit and figures are legible.
- [ ] Every member can defend the entire analysis.
- [ ] Contributions, references and AI use are disclosed.
