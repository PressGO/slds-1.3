# AI use log

Required by the project brief (§5): tool, date, purpose, representative prompts, what was AI-generated and how we checked it.

Draft prepared with Claude on 15 Oct 2026 from the chat record. Dates come from file timestamps in that chat. **Team: check every row, fill the [brackets], and keep adding rows.**

## Tool

Claude (Anthropic), used through claude.ai in one chat attached to our course Project, 10–15 Oct 2026. [Add the model name shown in the app.]

- [ ] Confirm: the LTA key and the alert URL were never pasted into the chat.
- [ ] Confirm: no confidential, licensed or personal data was uploaded. Uploaded: the course brief and catalog PDFs, and the LTA DataMall API User Guide (public).

## Log

| Date | Purpose | Representative prompt (verbatim) | AI-generated material | How we checked it |
|---|---|---|---|---|
| 10 Oct | Requirements, rubric and plan from the course documents | "find sources and suggest sources if u have to. We will do project 1.3 on recurring congestion" | Summary of deliverables and rules with section citations; source-check script `00_check_sources.R` | Citations checked against the PDFs by [name]. Script run live by us on 13 Oct: 315 requests, 0 failed |
| 10–13 Oct | Data sources, access and licences | "list the datasets, and the quality and how i need to get it for exaple lta will require an api key?"; "double check please. including data.gov and update me after. what about geospace is that free to use or onemap?" | `data_sources_check.md`; licence notes (Singapore Open Data Licence, OneMap terms) | Licence pages opened by [name]; figures come from our own 13 Oct run |
| 13–14 Oct | Project plan | "basically take on the project lead role and then instruct me on what i need to do for the proposal" | `PROJECT_PLAN.md` v1 (13 Oct) and v2 (14 Oct) | Team review on [date] |
| 13 Oct | Source check as a notebook | "can we run as an ipynb. provide the code if possible here" | `00_check_sources.ipynb` | Run live by us on 13 Oct |
| 14 Oct | Data pipeline code | "sorry i require a full python code to run the data collection 24/7 for lta (it should be reliabel and address failures)."; "provide me a script to create a virtual env for all the things i require" | `analysis/lta_collector.py`, `analysis/get_context_data.py`, `01_collector_monitor.ipynb`, `04_process.ipynb`, `03_visuals.ipynb`, `setup_env.bat`, `requirements.txt` | Claude tested the code on simulated LTA and data.gov.sg responses (its sandbox cannot reach either site). Collector running on our desktop since 14 Oct. [Add: processing and visuals run on real data on (date) by (name).] |
| 15 Oct | Collector reliability and alerts | "Between 4am and 7plus my computer didnt run it. I had sleep turned off."; "How do i setup alert or what not as well" | Freeze guard and Healthchecks.io alerts in `lta_collector.py`; Windows power-setting commands | [Add: alert test received on (date); power settings applied on (date).] |
| 15 Oct | Proposal draft | "based on the information so far can we fill up the project proposal" | Proposal text | Every sentence reviewed by the team on [date]; all numbers come from our own runs |
| 15 Oct | Methods review | "Reread qn 1.3 and the project documents and the code and data. Then rethink our current methods." | Recommended changes: unit (~1 km segments), travel-time label, test split, leave-one-road-out transfer | Team decision on [date], recorded in `DECISIONS.md` |
| 15 Oct | Repository set-up | "Do we need to change the code in anyway currently else i want to push to github." | `.gitignore`, `README.md`, this log | Checked by [name] before the first commit |
| 16 Oct | Linux collector set-up and Python source check | "please fix the collector.py yes no actual key shjold be shown"; "for 00_chec_sources.ipynb it is using a R code. create one for python as well." | Key masking in `lta_collector.py` error messages; `analysis/00_check_sources.py` and `00_check_sources_python.ipynb` (port of the R check) | Claude Code ran both live on the Linux PC on 16 Oct: collector `--once` saved a full snapshot; Python check 315 requests, 0 failed, matching the R run. [Add: reviewed by (name).] |
| 16 Oct | Collection redesign after LTA rate limit | "what if i provided u the other key can u run both for me?"; "please make the changes we can shut down collector and redo the parts and push to github"; "can we clean up any old codes or markdowns we do not need anymore" | Expressway mode in `lta_collector.py` (`0a35c4c`), `04_process.ipynb` reading every `data_raw*/` folder, `check.sh`, `DECISIONS.md`, doc updates (README, TODO, PROJECT_PLAN, Linux setup). Rate-limit fix and collection review (`deda600`, `60c74a2`, `adf4f54`) were drafted with Claude by [colleague] | Offline tests against a fake LTA; live run with key 2 found 2,598 expressway links on 58 of 288 pages; `04_process.ipynb` run end to end on 16 Oct data. [Add: reviewed by (name).] |

## AI-generated material in the submission

- Code: every script and notebook listed above was drafted by Claude and then run, read and edited by us.
- Text: `PROJECT_PLAN.md`, the proposal draft, `README.md` and this log were drafted by Claude and edited by us.
- Graphics: none generated by AI. Figures are produced by our code.
