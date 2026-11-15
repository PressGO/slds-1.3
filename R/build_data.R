# build_data.R - SLDS 42.510 project 1.3: raw LTA files -> model tables (data version 4), in R.
#
#   Rscript R/build_data.R [--now "YYYY-MM-DD HH:MM"] [--out data_processed/model_r] [--workers 8]
#
# The R version of analysis/build_data.py. The Python build makes the team's data (and uploads it to Drive);
# this script rebuilds the same tables from the same raw files in R, for the submission. It never uploads and
# never writes into data_processed/model/. R/compare_with_python.R then checks that every value is the same.
#
# Reads only the raw collector folders (data_raw/, data_raw_expressway/) and the rainfall and calendar tables
# that analysis/get_context_data.py downloads. Stops with "CHECK FAILED" if a check fails. Writes:
#   <out>/train.parquet, <out>/test.parquet and <out>/extra/ (full_table, test_full, train_lodo, links,
#   neighbours, connectors, norm, connector_norm, incidents, days.csv, build_info_r.json)
# Not made in R: extra/train_sample.parquet (its 300 links are drawn with Python's random numbers) and README.md.
#
# Packages: arrow, data.table, jsonlite (R/README.md). About 50 minutes and up to ~11 GB of memory. On the Linux PC
# run it under a memory cap (the collectors share the machine), with two settings that make R give freed memory
# back to the system (without them it passed 14 GB):
#   MALLOC_MMAP_THRESHOLD_=131072 MALLOC_ARENA_MAX=2 systemd-run --user --scope -p MemoryMax=14G Rscript R/build_data.R
#
# AI disclosure: translated from the Python version with Claude (Anthropic) on 15 Nov 2026; log in AI_USE.md.

Sys.setenv(ARROW_DEFAULT_MEMORY_POOL = "system")   # arrow gives memory back when tables are freed
suppressPackageStartupMessages({ library(arrow); library(data.table); library(jsonlite); library(parallel) })

args <- commandArgs(trailingOnly = TRUE)
opt <- function(name, default) { i <- match(name, args); if (is.na(i)) default else args[i + 1] }
script <- sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1])
PROJ <- normalizePath(file.path(dirname(script), ".."))
setwd(PROJ)
source("R/data_settings.R"); source("R/data_steps.R")

PROC <- "data_processed"
OUT <- opt("--out", file.path(PROC, "model_r"))
WORKERS <- as.integer(opt("--workers", "8"))
NOW <- if (is.null(opt("--now", NULL))) as.POSIXct(format(Sys.time(), tz = "Asia/Singapore"), tz = "UTC") else
  as.POSIXct(opt("--now", NULL), format = "%Y-%m-%d %H:%M", tz = "UTC")
if (normalizePath(OUT, mustWork = FALSE) == normalizePath(file.path(PROC, "model"), mustWork = FALSE))
  stop("--out must not be data_processed/model: that folder belongs to the Python build (the team's data)")
invisible(Sys.setlocale("LC_TIME", "C"))   # English day names in days.csv
T_START <- Sys.time()
CHECKS <- list()
check <- function(name, ok, detail = "") {
  ok <- isTRUE(ok)
  CHECKS[[length(CHECKS) + 1L]] <<- list(check = name, ok = ok, detail = as.character(detail))
  cat(sprintf("  %s  %s%s\n", if (ok) "ok  " else "FAIL", name, if (nzchar(detail)) sprintf("  [%s]", detail) else ""))
  if (!ok) stop(sprintf("CHECK FAILED: %s [%s]. Nothing in %s was changed.", name, detail, OUT), call. = FALSE)
}
mem_gb <- function() { st <- readLines("/proc/self/status"); g <- function(k) as.numeric(gsub("[^0-9]", "", grep(k, st, value = TRUE))) / 1048576
                        sprintf("memory %.1f GB, peak %.1f GB", g("^VmRSS"), g("^VmHWM")) }
log_msg <- function(...) cat(sprintf("[%s] %s  (%s)\n", format(Sys.time(), "%H:%M:%S", tz = "Asia/Singapore"), paste0(...), mem_gb()))
fmt <- function(x) format(x, big.mark = ",", scientific = FALSE, trim = TRUE)
pmap <- function(X, FUN) {                 # parallel lapply over files (forked workers; no arrow inside)
  r <- mclapply(X, FUN, mc.cores = WORKERS, mc.preschedule = TRUE)
  bad <- vapply(r, inherits, logical(1), "try-error")
  if (any(bad)) stop("reading failed: ", r[[which(bad)[1]]])
  r
}

# ---- typed parquet writing (the same column types as the Python files) ----
TS_COLS <- c("t", "info_retrieved", "first_seen", "last_seen", "last_seen_before", "reported")
F32 <- function(c) grepl("^f_(d|up_d|dn_d|conn_in_d|conn_out_d)[0-9]+$", c) || c %in% c("f_d_change15", "info_norm_band", "info_deficit")
I8 <- c("f_n_filled", "f_up_none", "f_dn_none", "f_rain15_missing", "f_rain30_missing", WEEKDAY_COLUMNS, "f_holiday",
        "f_conn_in_none", "f_conn_in_missing", "f_conn_out_none", "f_conn_out_missing", "info_band")
U32 <- c("n_snapshots", "n_attribute_versions", "n_categories", "n_downstream", "n_upstream", "n_roads_into",
         "n_roads_out_of", "n_obs", "n_days")
arrow_type <- function(c, default) {
  if (c %in% TS_COLS) return(timestamp("us"))
  if (c == "date") return(date32())
  if (F32(c)) return(float32())
  if (c %in% c("f_slot15", "slot15")) return(int16())
  if (c %in% I8) return(int8())
  if (c %in% U32) return(uint32())
  if (c == "RoadCategory") return(int64())
  default
}
as_typed_table <- function(dt) {
  tb <- arrow_table(as.data.frame(dt))
  tb$cast(schema(lapply(names(dt), function(c) field(c, arrow_type(c, tb$schema[[c]]$type)))))
}
write_typed <- function(dt, path) write_parquet(as_typed_table(dt), path)
concat_parquet <- function(files, out) {   # parts -> one file, one part in memory at a time
  first <- read_parquet(files[1], as_data_frame = FALSE)
  sink <- FileOutputStream$create(out)
  w <- ParquetFileWriter$create(first$schema, sink, properties = ParquetWriterProperties$create(names(first$schema)))
  for (f in files) w$WriteTable(read_parquet(f, as_data_frame = FALSE), chunk_size = 1e6)
  w$Close(); sink$close()
  invisible(out)
}

TMP <- paste0(OUT, ".tmp")
unlink(TMP, recursive = TRUE)
dir.create(file.path(TMP, "extra", "parts"), recursive = TRUE)
log_msg("build_data.R, data version ", DATA_VERSION, ", as of ", format(NOW, "%Y-%m-%d %H:%M"), ", ", WORKERS, " workers")

# ---- 1. calendar, rainfall, finished days ----
log_msg("1. calendar and rainfall")
cal <- fread(file.path(PROC, "calendar_2026.csv"), colClasses = list(character = "school_period"))
cal[, date := as.IDate(date)][, is_public_holiday := as.logical(is_public_holiday)]
check("calendar: one row per date", !anyDuplicated(cal$date))
holidays <- cal[is_public_holiday == TRUE, date]
check("calendar: Deepavali (Sun 8 Nov) and its holiday (Mon 9 Nov) are public holidays",
      all(as.IDate(c("2026-11-08", "2026-11-09")) %in% holidays), paste(holidays[month(holidays) >= 10], collapse = ", "))
rain_raw <- fread(cmd = sprintf("zcat '%s'", file.path(PROC, "rainfall_5min.csv.gz")),
                  colClasses = c("character", "character", "numeric"))
rain <- rain_raw[, .(t = parse_sgt(timestamp), station_id, rain_mm)]
rm(rain_raw)
check("rainfall: every timestamp parses", !anyNA(rain$t), sum(is.na(rain$t)))
check("rainfall: one reading per station and time", !anyDuplicated(rain, by = c("station_id", "t")))
check("rainfall: readings are >= 0 mm and whole tenths of a mm",
      !any(rain$rain_mm < 0 | abs(rain$rain_mm * 10 - round(rain$rain_mm * 10)) > 1e-9, na.rm = TRUE))
check("rainfall: times on the 5-min grid", all(secs_of_day(rain$t) %% 300 == 0))
stations <- fread(file.path(PROC, "rain_stations.csv"), colClasses = list(character = "station_id"))

first_day <- SPLITS$train[1]
last_planned <- max(do.call(c, SPLITS))
rain_last <- as.IDate(max(rain[hour_of(t) == 23L & (secs_of_day(t) %% 3600) %/% 60 == 55, t]))
finished_by_clock <- as.IDate(NOW - FINISHED_AFTER_H * 3600) - 1L
cutoff <- min(finished_by_clock, rain_last, last_planned)
check("at least the first training day is finished", cutoff >= first_day, paste("cutoff", cutoff))
days <- day_table(first_day, cutoff, holidays)
log_msg("   finished days ", first_day, " to ", cutoff, " (clock allows ", finished_by_clock, ", rainfall to ", rain_last, ")")
check("calendar covers every day", all(days$date %in% cal$date))

# ---- 2. link registry from the hourly raw snapshots, one day at a time ----
log_msg("2. link registry (raw JSON snapshots of the whole network)")
reg_files <- sort(Sys.glob(file.path(REGISTRY_SOURCE, "speedbands_raw", "*", "sbraw_*.jsonl.gz")), method = "radix")
reg_files <- reg_files[!is.na(folder_date(reg_files)) & folder_date(reg_files) <= cutoff]
check("registry: raw snapshot files found", length(reg_files) > 0, length(reg_files))
reg_day <- folder_date(reg_files)
versions <- list(); pages <- integer(); no_id <- 0L
for (d in unique(reg_day)) {               # ~3.5 M records a day; only the attribute versions are kept
  idx <- which(reg_day == d)
  res <- pmap(idx, function(k) { r <- read_registry_file(reg_files[k], k - 1L)
                                 list(v = registry_versions(r$records), pages = r$pages, no_id = sum(is.na(r$records$LinkID))) })
  pages <- c(pages, vapply(res, `[[`, integer(1), "pages"))
  no_id <- no_id + sum(vapply(res, `[[`, integer(1), "no_id"))
  day_v <- rbindlist(lapply(res, `[[`, "v"))
  versions[[length(versions) + 1L]] <- parse_registry_numbers(day_v)
  rm(res, day_v)
}
check("registry: every snapshot file read", length(pages) == length(reg_files), length(pages))
check("registry: >= 95% of snapshot files have all 288 pages", sum(pages == 288L) >= 0.95 * length(reg_files),
      sprintf("%d of %d", sum(pages == 288L), length(reg_files)))
check("registry: every record has a LinkID", no_id == 0L)
registry <- build_registry(rbindlist(versions), length(reg_files))
rm(versions)
check("registry: coordinates parse for every link", !anyNA(registry[, ..COORDS]))
xw <- registry[RoadCategory == EXPRESSWAY_CATEGORY]
xw_ids <- sort(xw$LinkID, method = "radix")
check("registry: expressway links = the 2,598 in DECISIONS.md", length(xw_ids) == EXPECTED_EXPRESSWAY_LINKS, length(xw_ids))
check("registry: no expressway link changed road category", !any(xw$n_categories > 1L))
check("registry: expressway links whose name or coordinates changed (latest used)", TRUE, sum(xw$n_attribute_versions > 1L))
log_msg("   ", fmt(nrow(registry)), " links in ", length(reg_files), " snapshots; ", fmt(length(xw_ids)), " expressway")

# ---- 3. roads that join the expressway links ----
log_msg("3. roads joining the expressway links")
conn <- connector_pairs(registry, xw_ids)
conn_ids <- sort(unique(conn$LinkID), method = "radix")
check("joining roads: none is an expressway link", !any(conn_ids %chin% xw_ids))
check("joining roads: every gap <= tolerance", all(conn$gap_m <= CONNECTOR_TOL_M))
log_msg("   ", length(conn_ids), " joining links, ", nrow(conn), " pairs, serving ", uniqueN(conn$joins), " expressway links")

# ---- 4. speed bands: both collectors -> one row per link and LTA update ----
log_msg("4. speed bands from both collectors")
late_limit <- at_midnight(cutoff + 1L) + LATE_ROWS_MIN * 60
sb <- rbindlist(lapply(SPEED_SOURCES, function(src) {
  f <- Sys.glob(file.path(src, "speedbands", "*", "sb_*.csv.gz"))
  data.table(ft = file_time(f), fd = folder_date(f), src = src, name = basename(f), path = f)
}))
sb <- sb[!is.na(ft) & !is.na(fd) & fd <= cutoff + 1L & ft <= late_limit]
setorder(sb, ft, src, name)
sb[, file_no := .I - 1L][, fetch_day := as.IDate(ft)]
check("speed bands: files found in both collector folders", all(SPEED_SOURCES %in% sb$src), nrow(sb))
keep_ids <- c(xw_ids, conn_ids)
parts <- list(); sb_stats <- list(); lag_max <- 0; over_midnight <- 0
for (d in unique(sb$fetch_day)) {          # one fetch day at a time keeps memory low ...
  items <- sb[fetch_day == d]
  raw <- rbindlist(pmap(seq_len(nrow(items)), function(k) read_speedband_file(items$path[k], keep_ids, items$file_no[k])))
  lag_max <- max(lag_max, floor(max(as.numeric(raw$retrieved - raw$t, units = "mins"), na.rm = TRUE)))
  late <- raw[as.IDate(retrieved) > as.IDate(t)]
  if (nrow(late)) over_midnight <- max(over_midnight, floor(max(secs_of_day(late$retrieved)) / 60))
  cs <- clean_speedbands(raw)
  rm(raw, late)
  for (k in names(cs$stats)) sb_stats[[k]] <- (if (is.null(sb_stats[[k]])) 0 else sb_stats[[k]]) + cs$stats[[k]]
  parts[[length(parts) + 1L]] <- cs$panel
}
stacked <- rbindlist(parts)                # ... then the same rule across fetch days (rows just after midnight)
rm(parts)
cs2 <- clean_speedbands(stacked[, .(retrieved, t, LinkID, SpeedBand = band, file_no = 0L, row_no = .I - 1L)])
rm(stacked)
panel <- cs2$panel
sb_stats$conflicts <- sb_stats$conflicts + cs2$stats$conflicts
sb_stats$link_updates_fetched_twice_or_more <- sb_stats$link_updates_fetched_twice_or_more + cs2$stats$link_updates_fetched_twice_or_more
sb_stats$rows_kept <- cs2$stats$rows_kept
sb_stats$longest_fetch_delay_min <- lag_max; sb_stats$latest_after_midnight_min <- over_midnight
panel <- panel[as.IDate(t) >= first_day & as.IDate(t) <= cutoff]
sb_stats$rows_in_finished_days <- nrow(panel)
bad_max <- floor(BAD_ROWS_MAX_SHARE * sb_stats$rows_read)
check("speed bands: rows without LTA's update time (dropped) at most 0.1%", sb_stats$no_update_time <= bad_max, sb_stats$no_update_time)
check("speed bands: every row has a retrieval time", sb_stats$no_retrieval_time == 0)
check("speed bands: SpeedBand outside 1-8 (band left empty) at most 0.1%", sb_stats$band_outside_1_8 <= bad_max, sb_stats$band_outside_1_8)
check("speed bands: a link and update fetched twice never disagree", sb_stats$conflicts == 0,
      sprintf("%d conflicts in %s repeats", sb_stats$conflicts, fmt(sb_stats$link_updates_fetched_twice_or_more)))
check("speed bands: rows of a day fetched after midnight all arrive within the late-file window",
      over_midnight <= LATE_ROWS_MIN, sprintf("latest %d min after midnight; longest delay %d min", over_midnight, lag_max))
check("panel: one row per link and update", !anyDuplicated(panel, by = c("LinkID", "t")))
check("panel: every update time on the 5-min grid", all(secs_of_day(panel$t) %% 300 == 0))
per_day <- panel[, .(updates = uniqueN(t)), by = .(date = as.IDate(t))]
check("panel: every finished day has data", nrow(per_day) == nrow(days), sprintf("%d of %d days", nrow(per_day), nrow(days)))
log_msg("   ", fmt(nrow(sb)), " files, ", fmt(sb_stats$rows_read), " rows read, ", fmt(nrow(panel)), " kept")

# ---- 5. population, held-out roads, neighbours, rain stations ----
log_msg("5. population, neighbours, rain stations")
pres <- presence_week1(panel, xw_ids)
links <- merge(xw, pres$table, by = "LinkID", all.x = TRUE)
links[, in_population := presence_week1 >= PRESENCE_MIN]
links[, road := fifelse(RoadName %chin% names(ROAD_GROUPS), ROAD_GROUPS[RoadName], RoadName)]
pop <- links[in_population == TRUE][order(LinkID, method = "radix")]
pop_ids <- pop$LinkID
check("population: every expressway link kept (presence >= 90%)", length(pop_ids) == EXPECTED_EXPRESSWAY_LINKS,
      sprintf("%d; presence %.3f-%.3f of %d updates", length(pop_ids), min(links$presence_week1), max(links$presence_week1), pres$n_updates))
road_pool <- setdiff(sort(unique(pop$road), method = "radix"), NEVER_HELD_OUT)
held <- EXPECTED_HELDOUT
check("held-out roads: AYE and CTE (the seeded draw, see data_settings.R) are among the 10 roads of the draw",
      length(road_pool) == 10L && all(held %chin% road_pool), paste(length(road_pool), "roads"))
links[, heldout_road := in_population & road %chin% held]
n_held <- sum(links$heldout_road)
pairs <- neighbour_pairs(pop)
check("neighbours: every gap <= tolerance", all(pairs$gap_m <= NEIGHBOUR_TOL_M))
check("neighbours: no link is its own neighbour", !any(pairs$LinkID == pairs$downstream))
train_days <- days[split == "train", date]
per_station <- rain[as.IDate(t) %in% train_days, .N, by = .(station_id, d = as.IDate(t))][N >= RAIN_STATION_MIN_SHARE * 288, .N, by = station_id]
good <- sort(per_station[N == length(train_days), station_id], method = "radix")
check("rain: stations with readings in >= 80% of slots on every training day", length(good) >= 30,
      sprintf("%d of %d", length(good), nrow(stations)))
near <- nearest_station(pop, stations[station_id %chin% good])
used <- sort(unique(near$station_id), method = "radix")
check("rain: every link has a station within 10 km", max(near$station_km) <= 10, sprintf("max %s km", max(near$station_km)))
cov <- rain[station_id %chin% used, .N, by = .(date = as.IDate(t))][, share := N * (1 / (length(used) * 288))]
cov <- merge(days[, .(date)], cov, by = "date", all.x = TRUE)[, share := fcoalesce(share, 0)]
check("rain: every finished day has readings in >= 80% of the used stations' slots", all(cov$share >= RAIN_DAY_MIN_SHARE),
      sprintf("lowest %.3f", min(cov$share)))
links[near, `:=`(station_id = i.station_id, station_km = i.station_km), on = "LinkID"]
cnt <- function(dt, by, name) setnames(dt[, .N, by = by], c("LinkID", name))
links[cnt(pairs, "LinkID", "n"), n_downstream := i.n, on = "LinkID"]
links[cnt(pairs, "downstream", "n"), n_upstream := i.n, on = "LinkID"]
links[cnt(conn[kind == "into"], "joins", "n"), n_roads_into := i.n, on = "LinkID"]
links[cnt(conn[kind == "out_of"], "joins", "n"), n_roads_out_of := i.n, on = "LinkID"]
for (c in c("n_downstream", "n_upstream", "n_roads_into", "n_roads_out_of")) set(links, which(is.na(links[[c]])), c, 0L)
setorder(links, LinkID)
updates_06_22 <- panel[LinkID %chin% pop_ids & in_hours(t), .(updates_06_22 = uniqueN(t)), by = .(date = as.IDate(t))]

# ---- 6. normal level, frozen from the training days ----
log_msg("6. normal level per link x day type x 15-min slot (training days only)")
pxw <- panel[LinkID %chin% pop_ids]; pcn <- panel[LinkID %chin% conn_ids]
rm(panel); invisible(gc())
norm <- normal_level(pxw, days); cnorm <- normal_level(pcn, days)
n_train_by_type <- days[split == NORM_SPLIT, .N, by = daytype]
check("norm: built from training days only (n_days <= training days of that type)",
      nrow(norm[n_train_by_type, on = "daytype", nomatch = NULL][n_days > N]) == 0,
      paste(n_train_by_type$daytype, n_train_by_type$N, collapse = ", "))
check("norm: every value between 1 and 8", all(norm$norm_band >= 1 & norm$norm_band <= 8))
need <- CJ(LinkID = pop_ids, daytype = DAYTYPES, slot15 = 22:90)
gaps <- nrow(need[!norm, on = c("LinkID", "daytype", "slot15")])
check("norm: link x day type x slot cells missing for 05:30-22:44", gaps <= 0.001 * nrow(need), sprintf("%d of %s", gaps, fmt(nrow(need))))
set.seed(7)
cells <- norm[sample(.N, 2000)]
re <- pxw[LinkID %chin% cells$LinkID & !is.na(band), .(LinkID, band, date = as.IDate(t), slot15 = slot15(t))][
  days[split == NORM_SPLIT, .(date, daytype)], on = "date", nomatch = NULL][
  cells, on = c("LinkID", "daytype", "slot15"), nomatch = NULL][
  , .(q = quantile(band, 0.5, type = 7, names = FALSE)), by = .(LinkID, daytype, slot15, norm_band)]
check("norm: 2,000 cells recomputed another way (quantile) give the same median", nrow(re) == 2000L && all(re$q == re$norm_band))
rm(cells, re)

# ---- 7. labels and inputs on the regular 5-min grid, a chunk of links at a time ----
log_msg("7. labels and inputs on the 5-min grid")
t_from <- at_midnight(first_day); t_to <- at_midnight(cutoff) + 23 * 3600 + 55 * 60
wdates <- days[!is.na(split), date]
chunks <- split(pop_ids, ceiling(seq_along(pop_ids) / LINK_CHUNK))
base <- rbindlist(lapply(chunks, function(ids) base_rows(pxw[LinkID %chin% ids], norm, days, ids, t_from, t_to, wdates)))
check("rows: one per link and 5-min time, 06:00-22:00, finished days",
      nrow(base) == length(pop_ids) * length(wdates) * (HOUR_TO - HOUR_FROM) * 12, fmt(nrow(base)))
cg <- add_lags(deficit_grid(pcn, cnorm, days, conn_ids, t_from, t_to), prefix = "c_")
clagged <- lag_table(cg[in_hours(t) & date %in% wdates], prefix = "c_")
rm(cg); invisible(gc())
lagged <- lag_table(base)
rin <- rain_inputs(rain, used, t_from, t_to)
rain_now <- rain[station_id %chin% used, .(station_id, t, rain_now = rain_mm)]
wd <- days[!is.na(split), .(date, weekday, is_holiday, daytype, split, in_population)]
road <- links[, .(LinkID, road, heldout_road)]
school <- cal[, .(date, school_period = fifelse(school_period == "", NA_character_, school_period))]

core <- core_input_columns(); extra_in <- connector_input_columns(); model_in <- model_input_columns()
main_cols <- c("LinkID", "road", "heldout_road", "t", "date", "daytype", "split", "y", "U", model_in, extra_in)
info <- c(band = "info_band", norm_band = "info_norm_band", deficit = "info_deficit", low = "info_low",
          rain_now = "info_rain_mm", station_id = "info_station_id", station_km = "info_station_km",
          school_period = "info_school_period", retrieved = "info_retrieved")
full_cols <- c("LinkID", "road", "heldout_road", "t", "date", "daytype", "split", "in_population", "use", "y",
               paste0("y_h", EXTRA_HORIZONS), "U", core, extra_in, names(info))

row_problems <- function(r, lag_d0, cl_d0) {
  # The checks every finished table of rows must pass: name -> number of bad rows. Time joins test that every
  # look-back and the label sit at the right time.
  out <- list()
  out[["one row per link and time"]] <- sum(duplicated(r, by = c("LinkID", "t")))
  out[["every row has its split, day type, road and both flags"]] <-
    sum(is.na(r$split) | is.na(r$daytype) | is.na(r$road) | is.na(r$in_population) | is.na(r$heldout_road))
  miss <- Reduce(`|`, lapply(c(core, extra_in, "y", "U"), function(c) is.na(r[[c]])))
  out[["use rows: no input, y or U missing"]] <- sum(r$use & miss)
  out[["use rows: band captured now, and f_d0 is the real drop now (never reused)"]] <-
    sum(r$use & (is.na(r$band) | r$f_d0 != r$deficit), na.rm = TRUE)
  k <- r[, .(LinkID, t, U, deficit)]
  j <- k[k[, .(LinkID, t = t + STEP, prev = deficit)], on = c("LinkID", "t"), nomatch = NULL]
  out[["U is NA exactly when the drop now or 5 min ago is missing"]] <- sum(is.na(j$U) != (is.na(j$deficit) | is.na(j$prev)))
  j <- r[, .(LinkID, t, y)][k[, .(LinkID, t = t - HORIZON * 60, ahead = U)], on = c("LinkID", "t"), nomatch = NULL]
  out[["y equals U 15 min later (time join)"]] <- sum(!((is.na(j$y) & is.na(j$ahead)) | (!is.na(j$y) & !is.na(j$ahead) & j$y == j$ahead)))
  for (cm in list(c("f_d", 5), c("f_d", 15), c("f_d", 30), c("f_up_d", 5), c("f_up_d", 30), c("f_dn_d", 5), c("f_dn_d", 30),
                  c("f_conn_in_d", 5), c("f_conn_in_d", 30), c("f_conn_out_d", 5), c("f_conn_out_d", 30))) {
    col <- cm[1]; m <- as.integer(cm[2])
    bk <- r[, .(LinkID, t = t + m * 60, back = get(paste0(col, 0)))]
    j <- r[, c("LinkID", "t", paste0(col, m)), with = FALSE][bk, on = c("LinkID", "t"), nomatch = NULL]
    a <- j[[paste0(col, m)]]; b <- j$back
    out[[sprintf("%s%d equals %s0 %d min earlier (time join)", col, m, col, m)]] <- sum(!((is.na(a) & is.na(b)) | (!is.na(a) & !is.na(b) & a == b)))
  }
  for (side in c("dn", "up")) {
    a <- if (side == "dn") "LinkID" else "downstream"; b <- if (side == "dn") "downstream" else "LinkID"
    one <- pairs[, .(n = .N, nbr = get(b)[1]), by = c(a)][n == 1L]; setnames(one, a, "LinkID")
    j <- r[, c("LinkID", "t", paste0("f_", side, "_d0")), with = FALSE][one, on = "LinkID", nomatch = NULL]
    j[lag_d0, theirs := i.d0, on = c(nbr = "nbr", t = "t")]
    x <- j[[paste0("f_", side, "_d0")]]
    out[[sprintf("f_%s_d0 = the f_d0 of the only %s link at the same t", side, if (side == "dn") "downstream" else "upstream")]] <-
      sum(!((is.na(x) & is.na(j$theirs)) | (!is.na(x) & !is.na(j$theirs) & x == j$theirs)))
  }
  for (k2 in c("into", "out_of")) {
    side <- if (k2 == "into") "in" else "out"
    one <- conn[kind == k2, .(n = .N, nbr = LinkID[1]), by = joins][n == 1L, .(LinkID = joins, nbr)]
    j <- r[, c("LinkID", "t", paste0("f_conn_", side, "_d0")), with = FALSE][one, on = "LinkID", nomatch = NULL]
    j[cl_d0, theirs := i.d0, on = c(nbr = "nbr", t = "t")]
    out[[sprintf("f_conn_%s_d0 = the drop of the only joining road at the same t (0 if missing)", side)]] <-
      sum(j[[paste0("f_conn_", side, "_d0")]] != fcoalesce(j$theirs, 0))
  }
  expect_day <- fifelse(r$is_holiday | r$weekday == 7L, "sunday_or_holiday", fifelse(r$weekday == 6L, "saturday", "weekday"))
  in_split <- rep(FALSE, nrow(r))
  for (s in names(SPLITS)) in_split <- in_split | (r$split == s & r$date >= SPLITS[[s]][1] & r$date <= SPLITS[[s]][2])
  rainbad <- Reduce(`|`, lapply(names(RAIN_WINDOWS), function(c) { x <- r[[c]]
    x < 0 | (x > 0 & x < 0.1 - 1e-9) | abs(x * 10 - round(x * 10)) > 1e-9 }))
  out[["low = drop >= 2"]] <- sum(!((is.na(r$low) & is.na(r$deficit)) | (!is.na(r$low) & !is.na(r$deficit) & r$low == (r$deficit >= THRESHOLD))))
  out[["f_n_filled is 0-7, and 0-5 on use rows"]] <- sum(r$f_n_filled < 0 | r$f_n_filled > 7 | (r$use & r$f_n_filled > 5))
  out[["exactly one of f_mon ... f_sun is 1"]] <- sum(Reduce(`+`, lapply(WEEKDAY_COLUMNS, function(c) r[[c]])) != 1L)
  out[["f_holiday matches the public-holiday list"]] <- sum(r$f_holiday != as.integer(r$date %in% holidays))
  out[["day type matches weekday and holiday"]] <- sum(r$daytype != expect_day)
  out[["in_population = Monday to Friday and not a public holiday"]] <- sum(r$in_population != (r$weekday <= 5L & !r$is_holiday))
  out[["heldout_road = the road is one of the held-out roads (AYE, CTE)"]] <- sum(r$heldout_road != (r$road %chin% EXPECTED_HELDOUT))
  out[["f_slot15 is 24-87 (06:00-22:00)"]] <- sum(r$f_slot15 < 24L | r$f_slot15 > 87L)
  out[["rain totals are 0 or whole tenths of a mm"]] <- sum(rainbad)
  out[["rain over 15 min <= rain over 30 min"]] <- sum(r$f_rain15 > r$f_rain30)
  out[["rain missing flag = 1 only with a total of 0"]] <- sum((r$f_rain15_missing == 1L & r$f_rain15 != 0) | (r$f_rain30_missing == 1L & r$f_rain30 != 0))
  out[["split matches the date"]] <- sum(!in_split)
  out
}
add_counts <- function(acc, new) { for (k in names(new)) acc[[k]] <- (if (is.null(acc[[k]])) 0 else acc[[k]]) + new[[k]]; acc }

lag_d0 <- lagged[, .(nbr, t, d0)]; cl_d0 <- clagged[, .(nbr, t, d0)]
bad_total <- list(); written <- list(); rday_parts <- list(); lab_parts <- list(); rows_seen <- 0; rows_tv <- 0
achunks <- split(pop_ids, ceiling(seq_along(pop_ids) / 260L))    # smaller chunks: a finished row is ~100 columns
for (ci in seq_along(achunks)) {
  r <- assemble(base[LinkID %chin% achunks[[ci]]], pairs, lagged, conn, clagged, near, rin, rain_now, wd, road, school)
  bad_total <- add_counts(bad_total, row_problems(r, lag_d0, cl_d0))
  rows_seen <- rows_seen + nrow(r); rows_tv <- rows_tv + sum(r$split %chin% c("train", "validate"))
  rday_parts[[ci]] <- r[, .(rows = .N, captured = sum(!is.na(band)), use_rows = sum(use), rain_missing = sum(f_rain15_missing)), by = date]
  lab_parts[[ci]] <- r[use & in_population, .(rows = .N, U = sum(U), y = sum(y), onset = sum(!U), onset_y = sum(y & !U)), by = .(split, date)]
  for (sp in names(SPLITS)) {
    p <- r[split == sp]
    if (!nrow(p)) next
    f_full <- file.path(TMP, "extra", "parts", sprintf("full_%s_%03d.parquet", sp, ci))
    f_main <- file.path(TMP, "extra", "parts", sprintf("main_%s_%03d.parquet", sp, ci))
    full <- p[, c(setdiff(full_cols, names(info)), names(info)), with = FALSE]
    setnames(full, names(info), unname(info))
    write_typed(full, f_full)
    write_typed(p[use & in_population, ..main_cols], f_main)
    written[[sp]] <- c(written[[sp]], ci)
  }
  rm(r, p, full); invisible(gc())
  log_msg("   links chunk ", ci, " of ", length(achunks), " done")
}
check("rows: the input steps kept every row (no join added or lost one)", rows_seen == nrow(base), fmt(rows_seen))
rm(base, lagged, lag_d0, cl_d0, clagged); invisible(gc())   # not needed any more (memory)
for (nm in names(bad_total)) check(paste("rows:", nm), bad_total[[nm]] == 0,
                                   if (bad_total[[nm]] == 0) paste(length(wdates), "days") else paste(fmt(bad_total[[nm]]), "bad"))
rdays <- rbindlist(rday_parts)[, lapply(.SD, sum), by = date]
labs <- rbindlist(lab_parts)
summ <- function(l) list(days = uniqueN(l$date), use_rows = sum(l$rows), share_U = round(sum(l$U) / sum(l$rows), 4),
                         share_y = round(sum(l$y) / sum(l$rows), 4), onset_rows = sum(l$onset),
                         onset_rows_y_true = sum(l$onset_y), share_y_onset = round(sum(l$onset_y) / sum(l$onset), 4))
summary_lab <- lapply(setNames(nm = intersect(c("train", "validate"), unique(labs$split))), function(s) summ(labs[split == s]))
check("labels: share of unusual rows (U) in train is 0.5%-10%", summary_lab$train$share_U >= 0.005 && summary_lab$train$share_U <= 0.10,
      summary_lab$train$share_U)

# ---- 8. incidents ----
log_msg("8. incidents")
inc_files <- sort(Sys.glob(file.path(INCIDENT_SOURCE, "feeds", "incidents", "*", "incidents_*.jsonl.gz")), method = "radix")
inc_files <- inc_files[!is.na(folder_date(inc_files)) & folder_date(inc_files) <= cutoff]
isnaps <- rbindlist(pmap(seq_along(inc_files), function(k) read_incident_file(inc_files[k], k - 1L)))
check("incidents: read every saved snapshot", uniqueN(isnaps$snap_no) == length(inc_files), length(inc_files))
incidents <- incident_episodes(isnaps)
rm(isnaps)

# ---- 9. write the main tables (rows in order: split, link, time) ----
log_msg("9. writing the main tables")
n_rows <- function(f) open_dataset(f)$num_rows
pf <- function(kind, sp) file.path(TMP, "extra", "parts", sprintf("%s_%s_%03d.parquet", kind, sp, written[[sp]]))
tv <- intersect(c("train", "validate"), names(written))
concat_parquet(unlist(lapply(tv, function(s) pf("full", s))), file.path(TMP, "extra", "full_table.parquet"))
# each part holds other links and was checked for repeated (LinkID, t), so the row count shows every row is in once
check("written: extra/full_table.parquet holds every row once", n_rows(file.path(TMP, "extra", "full_table.parquet")) == rows_tv, fmt(rows_tv))
concat_parquet(unlist(lapply(tv, function(s) pf("main", s))), file.path(TMP, "train.parquet"))
if ("test" %in% names(written)) {
  concat_parquet(pf("main", "test"), file.path(TMP, "test.parquet"))
  concat_parquet(pf("full", "test"), file.path(TMP, "extra", "test_full.parquet"))
}
n <- list("extra/full_table.parquet" = n_rows(file.path(TMP, "extra", "full_table.parquet")),
          "train.parquet" = lapply(summary_lab, `[[`, "use_rows"))
if ("test" %in% names(written)) {
  n[["test.parquet"]] <- n_rows(file.path(TMP, "test.parquet")); n[["extra/test_full.parquet"]] <- n_rows(file.path(TMP, "extra", "test_full.parquet"))
}
tr_keys <- as.data.table(read_parquet(file.path(TMP, "train.parquet"), col_select = c("LinkID", "t", "date")))
check("written: train.parquet holds every row once", nrow(tr_keys) == sum(unlist(n[["train.parquet"]])) && !anyDuplicated(tr_keys, by = c("LinkID", "t")),
      fmt(nrow(tr_keys)))
want <- days[in_population == TRUE & split %in% c("train", "validate"), date]
check("written: train.parquet holds exactly the proposal's days (Mon-Fri, no public holiday) of train and validate",
      setequal(unique(tr_keys$date), want), paste(uniqueN(tr_keys$date), "days"))
check("written: train.parquet has none of f_sat, f_sun, f_holiday",
      !any(NOT_IN_MAIN_FILES %in% names(read_parquet(file.path(TMP, "train.parquet"), as_data_frame = FALSE))))
rm(tr_keys)
link_cols <- c("LinkID", "RoadName", "RoadCategory", COORDS, "first_seen", "last_seen", "n_snapshots", "n_attribute_versions",
               "n_categories", "presence_snapshots", "presence_week1", "in_population", "road", "heldout_road", "station_id",
               "station_km", "n_downstream", "n_upstream", "n_roads_into", "n_roads_out_of")
write_typed(links[, ..link_cols], file.path(TMP, "extra", "links.parquet"))
write_typed(pairs, file.path(TMP, "extra", "neighbours.parquet"))
write_typed(conn, file.path(TMP, "extra", "connectors.parquet"))
write_typed(norm, file.path(TMP, "extra", "norm.parquet"))
write_typed(cnorm, file.path(TMP, "extra", "connector_norm.parquet"))
write_typed(incidents, file.path(TMP, "extra", "incidents.parquet"))
n[["extra/incidents.parquet"]] <- nrow(incidents)
unlink(file.path(TMP, "extra", "parts"), recursive = TRUE)

# ---- 10. the train days again, each with a normal level built without that day ----
log_msg("10. leave-own-day-out version of the train days")
lodo_days <- days[split == "train" & in_population == TRUE, date]
dir.create(file.path(TMP, "lodo_parts"))
pxw[, date := as.IDate(t)]; pcn[, date := as.IDate(t)]
bad_total <- list(); excl_bad <- 0L; lodo_lab <- list()
for (i in seq_along(lodo_days)) {
  d <- lodo_days[i]
  days_d <- copy(days)[date == d, split := NA_character_]
  norm_d <- normal_level(pxw, days_d); cnorm_d <- normal_level(pcn, days_d)
  dt_d <- days[date == d, daytype]
  had <- pxw[date == d & !is.na(band), .(had = 1L), by = .(LinkID, slot15 = slot15(t))]
  cmp <- norm[daytype == dt_d][had, had := i.had, on = c("LinkID", "slot15")]
  cmp[, expect := n_days - fcoalesce(had, 0L)]
  cmp[norm_d[daytype == dt_d], got := i.n_days, on = c("LinkID", "slot15")]
  excl_bad <- excl_bad + sum(fcoalesce(cmp$got, 0L) != cmp$expect)
  t0 <- at_midnight(d); t1 <- t0 + 23 * 3600 + 55 * 60
  b <- base_rows(pxw[date == d], norm_d, days, pop_ids, t0, t1, d)
  cg <- add_lags(deficit_grid(pcn[date == d], cnorm_d, days, conn_ids, t0, t1), prefix = "c_")
  cl <- lag_table(cg[in_hours(t)], prefix = "c_")
  lb <- lag_table(b)
  r <- assemble(b, pairs, lb, conn, cl, near, rin, rain_now, wd, road, school)
  bad_total <- add_counts(bad_total, row_problems(r, lb[, .(nbr, t, d0)], cl[, .(nbr, t, d0)]))
  lodo_lab[[i]] <- r[use & in_population, .(rows = .N, U = sum(U), y = sum(y), onset = sum(!U), onset_y = sum(y & !U), date = d)]
  write_typed(r[use & in_population, ..main_cols], file.path(TMP, "lodo_parts", sprintf("%s.parquet", d)))
  rm(b, cg, cl, lb, r); invisible(gc())
}
check("lodo: each day's normal level leaves out exactly that day", excl_bad == 0, paste(excl_bad, "cells differ"))
for (nm in names(bad_total)) check(paste("lodo rows:", nm), bad_total[[nm]] == 0,
                                   if (bad_total[[nm]] == 0) paste(length(lodo_days), "days") else paste(fmt(bad_total[[nm]]), "bad"))
concat_parquet(sort(list.files(file.path(TMP, "lodo_parts"), full.names = TRUE), method = "radix"),
               file.path(TMP, "extra", "train_lodo.parquet"))
unlink(file.path(TMP, "lodo_parts"), recursive = TRUE)
summary_lab$train_lodo <- summ(rbindlist(lodo_lab))
n[["extra/train_lodo.parquet"]] <- summary_lab$train_lodo$use_rows
check("written: train_lodo.parquet holds every usable row once",
      n_rows(file.path(TMP, "extra", "train_lodo.parquet")) == summary_lab$train_lodo$use_rows, fmt(summary_lab$train_lodo$use_rows))

# ---- 11. days.csv, build_info_r.json; then swap the new tables in ----
log_msg("11. build record")
dtab <- copy(days)
dtab[per_day, updates := i.updates, on = "date"]
dtab[updates_06_22, updates_06_22 := i.updates_06_22, on = "date"]
dtab[rdays, `:=`(rows = i.rows, share_captured = round(i.captured / i.rows, 4), use_rows = i.use_rows,
                 share_use = round(i.use_rows / i.rows, 4), share_rain_missing = round(i.rain_missing / i.rows, 4)), on = "date"]
dtab[cov, share_rain_readings := round(i.share, 4), on = "date"]
dtab[, day := format(date, "%a")]
dtab <- dtab[order(date), .(date, day, daytype, is_holiday, split, in_population, updates, updates_06_22, rows,
                            share_captured, use_rows, share_use, share_rain_missing, share_rain_readings)]
for (c in c("is_holiday", "in_population")) set(dtab, j = c, value = tolower(as.character(dtab[[c]])))
fwrite(dtab, file.path(TMP, "extra", "days.csv"))
info_json <- list(
  data_version = DATA_VERSION, language = "R", built_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%S%z", tz = "Asia/Singapore"),
  built_as_of = format(NOW, "%Y-%m-%d %H:%M"),
  software = list(R = paste(R.version$major, R.version$minor, sep = "."), arrow = as.character(packageVersion("arrow")),
                  data.table = as.character(packageVersion("data.table")), jsonlite = as.character(packageVersion("jsonlite"))),
  days = list(first = as.character(first_day), last_finished = as.character(cutoff),
              by_split = lapply(setNames(nm = names(SPLITS)), function(s) sum(dtab$split == s, na.rm = TRUE)),
              population_by_split = lapply(setNames(nm = names(SPLITS)), function(s) sum(dtab$split == s & dtab$in_population == "true", na.rm = TRUE))),
  links = list(registry = nrow(registry), expressway = length(xw_ids), in_population = length(pop_ids), roads = uniqueN(links$road),
               presence_week1_updates = pres$n_updates, heldout_roads = held, heldout_links = n_held, neighbour_pairs = nrow(pairs),
               joining_roads = length(conn_ids), joining_pairs = nrow(conn), expressway_links_with_joining_road = uniqueN(conn$joins),
               rain_stations_eligible = length(good), rain_stations_used = length(used)),
  speed_band_cleaning = sb_stats, rows = n, label_summary = summary_lab,
  checks = CHECKS, seconds = round(as.numeric(Sys.time() - T_START, units = "secs")))
write_json(info_json, file.path(TMP, "extra", "build_info_r.json"), auto_unbox = TRUE, pretty = TRUE, digits = NA)
old <- paste0(OUT, ".old")
unlink(old, recursive = TRUE)
if (dir.exists(OUT)) invisible(file.rename(OUT, old))
invisible(file.rename(TMP, OUT))
unlink(old, recursive = TRUE)
log_msg(sprintf("done in %.0f s: %d checks passed; output in %s", as.numeric(Sys.time() - T_START, units = "secs"), length(CHECKS), OUT))
