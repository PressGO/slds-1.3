# data_steps.R - the steps that turn the raw LTA files into the model tables (data version 4).
#
# The R version of analysis/data_steps.py: the same functions, in the same order, with the same rules.
# Each function takes tables and returns tables; only the read_* functions touch files. R/build_data.R runs
# them in order and checks the results. Times are Singapore time, kept as POSIXct with tz "UTC" (so no
# time-zone shifts happen; Singapore has no daylight saving).
#
# Rules that keep R and Python identical (R/compare_with_python.R checks the result):
#   - text is sorted by bytes (data.table sorts in the C locale), as Python/polars does;
#   - a value is unknown (NA) when any value it needs is unknown (R's NA & FALSE = FALSE is avoided);
#   - rounding to d decimals = round(x * 10^d) / 10^d (round half to even), as numpy does.
#
# AI disclosure: translated from the Python version with Claude (Anthropic) on 15 Nov 2026; log in AI_USE.md.

suppressPackageStartupMessages({ library(data.table); library(jsonlite) })

STEP <- STEP_MIN * 60                                   # seconds
DCOLS <- paste0("d", LAGS)                              # d0 = now, d5 = 5 min ago, ...
COORDS <- c("StartLon", "StartLat", "EndLon", "EndLat")

# ---------------------------------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------------------------------

parse_sgt <- function(x) {
  # '2026-11-10T00:01:50+0800', '...+08:00' or '2026-11-10 00:00:00' -> Singapore time; else NA.
  # Parses each distinct string once (a file holds a handful of distinct times).
  u <- unique(x)
  s <- sub("T", " ", sub("\\+08:?00$", "", u), fixed = FALSE)
  out <- rep(as.POSIXct(NA_real_, tz = "UTC"), length(u))
  full  <- grepl("^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]+)?$", s)
  short <- grepl("^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}$", s)
  out[full]  <- as.POSIXct(s[full], format = "%Y-%m-%d %H:%M:%OS", tz = "UTC")
  out[short] <- as.POSIXct(s[short], format = "%Y-%m-%d %H:%M", tz = "UTC")
  out[match(x, u)]
}

secs_of_day <- function(t) as.numeric(t) %% 86400
slot15 <- function(t) { s <- secs_of_day(t); as.integer((s %/% 3600) * 4 + (s %% 3600) %/% 900) }
hour_of <- function(t) as.integer(secs_of_day(t) %/% 3600)
in_hours <- function(t) { h <- hour_of(t); h >= HOUR_FROM & h <= HOUR_TO - 1L }
at_midnight <- function(d) as.POSIXct(as.numeric(as.IDate(d)) * 86400, origin = "1970-01-01", tz = "UTC")

file_time <- function(path) {
  # Retrieval time from a collector file name: sb_20261110_000150.csv.gz, sbraw_20261110_0000.jsonl.gz.
  b <- basename(path)
  m <- regmatches(b, regexec("_([0-9]{8})_([0-9]{4,6})\\.", b))
  s <- vapply(m, function(g) if (length(g) < 3) NA_character_ else paste0(g[2], substr(paste0(g[3], "000000"), 1, 6)),
              character(1))
  as.POSIXct(s, format = "%Y%m%d%H%M%S", tz = "UTC")
}

folder_date <- function(path) suppressWarnings(as.IDate(basename(dirname(path)), format = "%Y-%m-%d"))

# ---------------------------------------------------------------------------------------------------
# Days: day type and split
# ---------------------------------------------------------------------------------------------------

split_of <- function(d) {
  out <- rep(NA_character_, length(d))
  for (s in rev(names(SPLITS))) out[d >= SPLITS[[s]][1] & d <= SPLITS[[s]][2]] <- s
  out
}

day_table <- function(first, last, holidays) {
  # One row per date: weekday (1 = Monday), is_holiday, daytype, split, in_population.
  d <- data.table(date = seq(as.IDate(first), as.IDate(last), by = 1L))
  d[, weekday := as.integer((wday(date) + 5L) %% 7L + 1L)]
  d[, is_holiday := date %in% holidays]
  d[, daytype := fifelse(is_holiday | weekday == 7L, "sunday_or_holiday", fifelse(weekday == 6L, "saturday", "weekday"))]
  d[, split := split_of(date)]
  d[, in_population := daytype %in% POPULATION_DAYTYPES]
  d[]
}

# ---------------------------------------------------------------------------------------------------
# Speed bands: raw rows -> one row per link and LTA update
# ---------------------------------------------------------------------------------------------------

read_speedband_file <- function(path, keep_ids, file_no) {
  # One compact collector file (retrieved_at, last_updated, LinkID, SpeedBand), only the links in keep_ids.
  df <- fread(cmd = sprintf("zcat '%s'", path), colClasses = c("character", "character", "character", "integer"),
              na.strings = "", showProgress = FALSE)
  if (!nrow(df)) return(NULL)
  df[, row_no := .I - 1L]
  df <- df[LinkID %chin% keep_ids]
  data.table(retrieved = parse_sgt(df$retrieved_at), t = parse_sgt(df$last_updated), LinkID = df$LinkID,
             SpeedBand = df$SpeedBand, file_no = as.integer(file_no), row_no = df$row_no)
}

clean_speedbands <- function(raw) {
  # One row per (LinkID, t); band = SpeedBand if 1-8 (else NA); a link and update fetched more than once keeps
  # the earliest fetch (retrieved, then file, then row); 'conflicts' counts repeats whose bands disagree.
  stats <- list(rows_read = nrow(raw), no_update_time = sum(is.na(raw$t)),
                no_retrieval_time = sum(is.na(raw$retrieved)),
                band_outside_1_8 = sum(!(raw$SpeedBand >= 1L & raw$SpeedBand <= 8L), na.rm = TRUE))
  df <- raw[!is.na(t)]
  df[, band := fifelse(SpeedBand >= 1L & SpeedBand <= 8L, SpeedBand, NA_integer_)]
  g <- df[, .(n = .N, n_bands = uniqueN(band)), by = .(LinkID, t)]
  stats$link_updates_fetched_twice_or_more <- sum(g$n > 1L)
  stats$conflicts <- sum(g$n_bands > 1L)
  setorder(df, retrieved, file_no, row_no, na.last = TRUE)
  panel <- unique(df, by = c("LinkID", "t"))[, .(t, LinkID, band, retrieved)]
  setorder(panel, t, LinkID)
  stats$rows_kept <- nrow(panel)
  list(panel = panel, stats = stats)
}

# ---------------------------------------------------------------------------------------------------
# Link registry (from the hourly raw JSON snapshots of the whole network)
# ---------------------------------------------------------------------------------------------------

REC_COLS <- c("LinkID", "RoadName", "RoadCategory", COORDS)

read_registry_file <- function(path, file_no) {
  # One raw snapshot file (one JSON page per line) -> one row per link record (attributes as text).
  lines <- readLines(gzfile(path), warn = FALSE)
  parts <- lapply(lines, function(l) {
    o <- fromJSON(l)
    v <- fromJSON(o$body)$value
    if (is.null(v) || !length(v) || !nrow(v)) return(data.table(retrieved_at = character(), page = integer()))
    v <- as.data.table(v)
    for (c in setdiff(REC_COLS, names(v))) set(v, j = c, value = NA_character_)
    cbind(data.table(retrieved_at = o$retrieved_at, page = as.integer(o$page)), v[, ..REC_COLS])
  })
  d <- rbindlist(parts, fill = TRUE)
  if (nrow(d)) d[, retrieved := parse_sgt(retrieved_at)][, retrieved_at := NULL][, file_no := as.integer(file_no)]
  list(records = d, pages = uniqueN(d$page))           # pages that hold records (as the Python version counts)
}

as_int_strict <- function(x) { x <- trimws(x); out <- rep(NA_integer_, length(x)); ok <- grepl("^[+-]?[0-9]+$", x)
                               out[ok] <- as.integer(x[ok]); out }

registry_versions <- function(snaps) {
  # One row per link and attribute version (attributes still as LTA's text), with when it was first and last
  # seen and in how many files. Runs in the file-reading workers; parse_registry_numbers() follows.
  snaps[, .(first_seen = min(retrieved), last_seen = max(retrieved), n_files = uniqueN(file_no)),
        by = c("LinkID", "RoadName", "RoadCategory", COORDS)]
}

text_to_double <- function(x) {
  # Text -> number, correctly rounded (arrow, like Python). R's own as.numeric() can be one unit off in the
  # last digit (e.g. "103.768459"). Text that is not a number -> NA. Main process only (arrow is not fork-safe).
  u <- unique(x); ok <- !is.na(u) & grepl("^[+-]?([0-9]+\\.?[0-9]*|\\.[0-9]+)([eE][+-]?[0-9]+)?$", trimws(u))
  v <- rep(NA_real_, length(u))
  if (any(ok)) v[ok] <- arrow::Array$create(trimws(u[ok]))$cast(arrow::float64())$as_vector()
  v[match(x, u)]
}

parse_registry_numbers <- function(v) {
  # Versions with text attributes -> RoadCategory as integer, coordinates as numbers, then grouped again
  # (two texts can give the same number).
  v[, RoadCategory := as_int_strict(RoadCategory)]
  for (c in COORDS) set(v, j = c, value = text_to_double(v[[c]]))
  v[, .(first_seen = min(first_seen), last_seen = max(last_seen), n_files = sum(n_files)),
    by = c("LinkID", "RoadName", "RoadCategory", COORDS)]
}

build_registry <- function(versions, n_files) {
  # One row per link: latest attributes, first/last seen, snapshots, attribute versions, categories.
  attrs <- c("RoadName", "RoadCategory", COORDS)
  v <- versions[, .(first_seen = min(first_seen), last_seen = max(last_seen), n_files = sum(n_files)),
                by = c("LinkID", attrs)]
  setorderv(v, c("LinkID", "last_seen", attrs), na.last = TRUE)
  latest <- v[v[, .I[.N], by = LinkID]$V1, c("LinkID", attrs), with = FALSE]
  per_link <- v[, .(first_seen = min(first_seen), last_seen = max(last_seen), n_snapshots = sum(n_files),
                    n_attribute_versions = .N, n_categories = uniqueN(RoadCategory)), by = LinkID]
  r <- merge(latest, per_link, by = "LinkID")
  r[, presence_snapshots := n_snapshots * (1 / n_files)]                   # as polars computes it
  setorder(r, LinkID)
  r[]
}

# ---------------------------------------------------------------------------------------------------
# Geometry: neighbours and joining roads
# ---------------------------------------------------------------------------------------------------

M_PER_DEG <- 111320.0
COS_LAT <- cos(1.35 * (pi / 180))                      # Singapore's latitude (numpy: x * (pi / 180))

xy_m <- function(lon, lat) cbind(lon * M_PER_DEG * COS_LAT, lat * M_PER_DEG)
round_dec <- function(x, d) round(x * 10^d) / 10^d     # numpy's np.round: half to even on x * 10^d

close_pairs <- function(a, b, tol, chunk = 4000L) {
  # All (i, j, distance) with |a_i - b_j| <= tol metres (1-based indices).
  out <- list()
  for (s in seq(1L, nrow(a), by = chunk)) {
    idx <- s:min(nrow(a), s + chunk - 1L)
    dx <- outer(a[idx, 1], b[, 1], "-"); dy <- outer(a[idx, 2], b[, 2], "-")
    d <- sqrt(dx^2 + dy^2)
    w <- which(d <= tol, arr.ind = TRUE)
    if (nrow(w)) out[[length(out) + 1L]] <- data.table(i = idx[w[, 1]], j = w[, 2], d = d[w])
  }
  if (length(out)) rbindlist(out) else data.table(i = integer(), j = integer(), d = numeric())
}

neighbour_pairs <- function(links) {
  # B is downstream of A when B starts within NEIGHBOUR_TOL_M of where A ends (never itself).
  p <- close_pairs(xy_m(links$EndLon, links$EndLat), xy_m(links$StartLon, links$StartLat), NEIGHBOUR_TOL_M)[i != j]
  r <- data.table(LinkID = links$LinkID[p$i], downstream = links$LinkID[p$j], gap_m = round_dec(p$d, 2))
  setorder(r, LinkID, downstream)
  r[]
}

connector_pairs <- function(registry, xw_ids) {
  # A non-expressway link whose end is within CONNECTOR_TOL_M of an expressway link's start leads 'into' it;
  # one whose start is within CONNECTOR_TOL_M of its end leads 'out_of' it.
  xw <- registry[LinkID %chin% xw_ids]
  other <- na.omit(registry[!LinkID %chin% xw_ids], cols = COORDS)
  parts <- list(
    into   = close_pairs(xy_m(other$EndLon, other$EndLat), xy_m(xw$StartLon, xw$StartLat), CONNECTOR_TOL_M),
    out_of = close_pairs(xy_m(other$StartLon, other$StartLat), xy_m(xw$EndLon, xw$EndLat), CONNECTOR_TOL_M))
  r <- rbindlist(lapply(names(parts), function(k) {
    p <- parts[[k]]
    data.table(LinkID = other$LinkID[p$i], joins = xw$LinkID[p$j], kind = rep(k, nrow(p)), gap_m = round_dec(p$d, 2))
  }))
  r <- merge(r, other[, .(LinkID, RoadName, RoadCategory)], by = "LinkID", all.x = TRUE, sort = FALSE)
  r <- r[, .(LinkID, joins, kind, RoadName, RoadCategory, gap_m)]
  setorder(r, joins, kind, LinkID)
  r[]
}

haversine_km <- function(lat1, lon1, lat2, lon2) {
  r <- pi / 180
  lat1 <- lat1 * r; lon1 <- lon1 * r; lat2 <- lat2 * r; lon2 <- lon2 * r
  a <- sin((lat2 - lat1) / 2)^2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2)^2
  6371.0 * 2 * asin(sqrt(a))
}

nearest_station <- function(links, stations) {
  # Nearest rain station to each link's midpoint (ties: the first station_id in byte order).
  st <- stations[order(station_id, method = "radix")]
  mid_lat <- (links$StartLat + links$EndLat) / 2
  mid_lon <- (links$StartLon + links$EndLon) / 2
  d <- outer(seq_along(mid_lat), seq_len(nrow(st)), function(i, j) haversine_km(mid_lat[i], mid_lon[i], st$lat[j], st$lon[j]))
  k <- max.col(-d, ties.method = "first")
  data.table(LinkID = links$LinkID, station_id = st$station_id[k], station_km = round_dec(d[cbind(seq_along(k), k)], 3))
}

# ---------------------------------------------------------------------------------------------------
# Population and normal level
# ---------------------------------------------------------------------------------------------------

presence_week1 <- function(panel, ids) {
  # Share of the update times captured in PRESENCE_DAYS (06:00-22:00) at which each link has a band.
  week <- panel[LinkID %chin% ids & as.IDate(t) >= PRESENCE_DAYS[1] & as.IDate(t) <= PRESENCE_DAYS[2] & in_hours(t)]
  n_updates <- uniqueN(week$t)
  got <- week[!is.na(band), .(n = uniqueN(t)), by = LinkID]
  r <- data.table(LinkID = ids)[got, n := i.n, on = "LinkID"]
  r[, presence_week1 := fcoalesce(n, 0L) * (1 / n_updates)][, n := NULL]   # polars divides by a number this way
  setorder(r, LinkID)
  list(table = r, n_updates = n_updates)
}

normal_level <- function(panel, days) {
  # Median band per link x day type x 15-min slot over the NORM_SPLIT days, all hours; n_obs, n_days.
  p <- panel[!is.na(band), .(LinkID, t, band, date = as.IDate(t))]
  p <- p[days[, .(date, daytype, split)], on = "date", nomatch = NULL][split == NORM_SPLIT]
  p[, slot15 := slot15(t)]
  r <- p[, .(norm_band = as.numeric(median(band)), n_obs = .N, n_days = uniqueN(date)), by = .(LinkID, daytype, slot15)]
  setorder(r, LinkID, daytype, slot15)
  r[]
}

# ---------------------------------------------------------------------------------------------------
# Regular 5-minute grid: deficit, label, look-backs
# ---------------------------------------------------------------------------------------------------
# The grid has every link x every 5-min time, sorted by link and time, so 'k rows back within a link' is
# exactly k x 5 min. back(x, k) / ahead(x, k) shift within a link and give NA across a link's edge.

back <- function(x, k, pos) { if (k == 0L) return(x); y <- shift(x, k); y[pos <= k] <- NA; y }
ahead <- function(x, k, pos, n_t) { y <- shift(x, k, type = "lead"); y[pos > n_t - k] <- NA; y }

deficit_grid <- function(panel, norm, days, ids, t_from, t_to) {
  # deficit = normal level - band (NA if either is missing); dfill = deficit, or if missing the value up to
  # CARRY_MAX min earlier (never the future); filled = dfill came from an earlier update.
  times <- seq(t_from, t_to, by = STEP)
  g <- CJ(LinkID = sort(unique(ids), method = "radix"), t = times)
  cols <- intersect(c("band", "retrieved"), names(panel))
  g[panel, (cols) := mget(paste0("i.", cols)), on = c("LinkID", "t")]
  g[, date := as.IDate(t)][, slot15 := slot15(t)]
  g[days, daytype := i.daytype, on = "date"]
  g[norm, norm_band := i.norm_band, on = c("LinkID", "daytype", "slot15")]
  g[, deficit := norm_band - band]
  g[, pos := rowid(LinkID)]
  dfill <- g$deficit
  for (k in seq_len(CARRY_MAX %/% STEP_MIN)) dfill <- fcoalesce(dfill, back(g$deficit, k, g$pos))
  g[, dfill := dfill]
  g[, filled := is.na(deficit) & !is.na(dfill)]
  attr(g, "n_t") <- length(times)
  g
}

add_labels <- function(g) {
  # low = deficit >= THRESHOLD. U = low at t and the CONSECUTIVE - 1 updates before; NA when any is missing.
  # y = U at t + HORIZON; y_h* = other horizons. Uses the deficit as captured, never the reused value.
  n_t <- attr(g, "n_t")
  g[, low := deficit >= THRESHOLD]
  parts <- lapply(seq_len(CONSECUTIVE) - 1L, function(k) back(g$low, k, g$pos))
  any_na <- Reduce(`|`, lapply(parts, is.na))
  all_low <- Reduce(`&`, lapply(parts, function(p) fcoalesce(p, FALSE)))
  g[, U := fifelse(any_na, NA, all_low)]
  shifts <- c(y = HORIZON, setNames(EXTRA_HORIZONS, paste0("y_h", EXTRA_HORIZONS)))
  for (nm in names(shifts)) set(g, j = nm, value = ahead(g$U, shifts[[nm]] %/% STEP_MIN, g$pos, n_t))
  g
}

add_lags <- function(g, prefix = "") {
  # {prefix}d0 ... d30: dfill at t, t - 5, ..., t - 30; {prefix}n_filled: how many of them were reused.
  nf <- integer(nrow(g))
  for (m in LAGS) {
    k <- m %/% STEP_MIN
    set(g, j = paste0(prefix, "d", m), value = back(g$dfill, k, g$pos))
    nf <- nf + as.integer(fcoalesce(back(g$filled, k, g$pos), FALSE))
  }
  g[, (paste0(prefix, "n_filled")) := nf]
  g
}

BASE_COLS <- c("LinkID", "t", "date", "band", "norm_band", "deficit", "low", "U", "y",
               paste0("y_h", EXTRA_HORIZONS), paste0("f_", DCOLS), "f_n_filled")

base_rows <- function(panel, norm, days, ids, t_from, t_to, window_dates) {
  # Labels and the link's own look-backs on the grid, kept for 06:00-22:00 of window_dates.
  g <- add_lags(add_labels(deficit_grid(panel, norm, days, ids, t_from, t_to)), prefix = "f_")
  cols <- c(BASE_COLS, intersect("retrieved", names(g)))
  g[in_hours(t) & date %in% window_dates, ..cols]
}

lag_table <- function(rows, prefix = "f_") {
  # nbr, t, d0 ... d30: the look-up table for neighbours or joining roads.
  r <- rows[, c("LinkID", "t", paste0(prefix, DCOLS)), with = FALSE]
  setnames(r, c("nbr", "t", DCOLS))
  setkey(r, nbr, t)
  r
}

worst_of <- function(keys, pairs, lagged, names_out) {
  # For each (LinkID, t) in keys: the largest of the related links' look-back values at the same t
  # (NA if the link has related links but none had a value). pairs: LinkID -> nbr.
  p <- pairs[LinkID %chin% unique(keys$LinkID)]
  j <- keys[p, on = "LinkID", allow.cartesian = TRUE, nomatch = NULL]
  j <- lagged[j, on = c("nbr", "t")]
  for (c in DCOLS) set(j, which(is.na(j[[c]])), c, -Inf)
  r <- j[, lapply(.SD, max), by = .(LinkID, t), .SDcols = DCOLS]
  for (c in DCOLS) set(r, which(is.infinite(r[[c]])), c, NA_real_)
  setnames(r, DCOLS, names_out)
  r
}

neighbour_inputs <- function(rows, pairs, lagged) {
  # f_up_d* / f_dn_d*: the worst deficit among the links just upstream / downstream. No link on a side:
  # f_*_none = 1 and 0 for the values; a link with some but no value stays NA.
  keys <- rows[, .(LinkID, t)]
  for (side in c("dn", "up")) {
    p <- if (side == "dn") pairs[, .(LinkID, nbr = downstream)] else pairs[, .(LinkID = downstream, nbr = LinkID)]
    nm <- paste0("f_", side, "_", DCOLS)
    agg <- worst_of(keys, p, lagged, nm)
    rows[agg, (nm) := mget(paste0("i.", nm)), on = c("LinkID", "t")]
    for (c in setdiff(nm, names(rows))) set(rows, j = c, value = NA_real_)
    none <- paste0("f_", side, "_none")
    rows[, (none) := fifelse(LinkID %chin% unique(p$LinkID), 0L, 1L)]
    for (c in nm) set(rows, which(rows[[none]] == 1L), c, 0)
  }
  rows
}

connector_inputs <- function(rows, conn, clagged) {
  # f_conn_in_d* / f_conn_out_d*: the worst deficit among the roads leading into / out of the link. No such
  # road: *_none = 1; a road but a missing value: *_missing = 1. Values are then 0.
  keys <- rows[, .(LinkID, t)]
  for (k in c("into", "out_of")) {
    side <- if (k == "into") "in" else "out"
    p <- unique(conn[kind == k, .(LinkID = joins, nbr = LinkID)])
    nm <- paste0("f_conn_", side, "_", DCOLS)
    agg <- worst_of(keys, p, clagged, nm)
    rows[agg, (nm) := mget(paste0("i.", nm)), on = c("LinkID", "t")]
    for (c in setdiff(nm, names(rows))) set(rows, j = c, value = NA_real_)
    none <- paste0("f_conn_", side, "_none"); miss <- paste0("f_conn_", side, "_missing")
    rows[, (none) := fifelse(LinkID %chin% unique(p$LinkID), 0L, 1L)]
    any_na <- Reduce(`|`, lapply(nm, function(c) is.na(rows[[c]])))
    rows[, (miss) := as.integer(get(none) == 0L & any_na)]
    for (c in nm) set(rows, which(is.na(rows[[c]])), c, 0)
  }
  rows
}

window_sum <- function(x, w) {
  # Sum of the last w values (this one included), skipping NA; NA when all of them are NA.
  v <- fcoalesce(x, 0L); cs <- cumsum(as.numeric(v)); cn <- cumsum(!is.na(x))
  lag_cs <- c(rep(0, w), cs)[seq_along(cs)]; lag_cn <- c(rep(0L, w), cn)[seq_along(cn)]
  s <- cs - lag_cs; n <- cn - lag_cn
  fifelse(n > 0L, s, NA_real_)
}

rain_inputs <- function(rain, station_ids, t_from, t_to) {
  # Per station and 5-min time t: total rain of the readings timestamped t - RAIN_LAG back to t - window. A
  # missing reading is skipped; all missing -> 0 and *_missing = 1. Summed in whole tenths of a mm.
  times <- seq(t_from - 3600, t_to, by = STEP)
  g <- CJ(station_id = sort(unique(station_ids), method = "radix"), t = times)
  g[rain, rain_mm := i.rain_mm, on = c("station_id", "t")]
  g[, pos := rowid(station_id)]
  g[, r10 := back(as.integer(round(rain_mm * 10)), RAIN_LAG %/% STEP_MIN, pos)]
  for (n in names(RAIN_WINDOWS)) {
    g[, (n) := window_sum(r10, RAIN_WINDOWS[[n]] %/% STEP_MIN), by = station_id]
    g[, (paste0(n, "_missing")) := as.integer(is.na(get(n)))]
    g[, (n) := fcoalesce(get(n), 0) / 10]
  }
  g[, c("station_id", "t", names(RAIN_WINDOWS), paste0(names(RAIN_WINDOWS), "_missing")), with = FALSE]
}

calendar_inputs <- function(rows) {
  # f_slot15 (time of day), f_mon ... f_sun (one-hot), f_holiday.
  rows[, f_slot15 := slot15(t)]
  for (k in seq_along(WEEKDAY_COLUMNS)) set(rows, j = WEEKDAY_COLUMNS[k], value = as.integer(rows$weekday == k))
  rows[, f_holiday := as.integer(is_holiday)]
  rows
}

core_input_columns <- function() c(paste0("f_", DCOLS), "f_d_change15", "f_n_filled",
                                   as.vector(outer(DCOLS, c("up", "dn"), function(c, s) paste0("f_", s, "_", c))),
                                   "f_up_none", "f_dn_none", names(RAIN_WINDOWS), paste0(names(RAIN_WINDOWS), "_missing"),
                                   "f_slot15", WEEKDAY_COLUMNS, "f_holiday")
model_input_columns <- function() setdiff(core_input_columns(), NOT_IN_MAIN_FILES)
connector_input_columns <- function() c(as.vector(outer(DCOLS, c("in", "out"), function(c, s) paste0("f_conn_", s, "_", c))),
                                        as.vector(outer(c("none", "missing"), c("in", "out"), function(x, s) paste0("f_conn_", s, "_", x))))

assemble <- function(base, pairs, lagged, conn, clagged, near, rin, rain_now, days, road, school) {
  # All inputs and `use` for base rows: day columns, neighbours, joining roads, rain, calendar.
  r <- copy(base)
  r[days, (setdiff(names(days), "date")) := mget(paste0("i.", setdiff(names(days), "date"))), on = "date"]
  r[, f_d_change15 := f_d0 - f_d15]
  r <- neighbour_inputs(r, pairs, lagged)
  r <- connector_inputs(r, conn, clagged)
  r[near, `:=`(station_id = i.station_id, station_km = i.station_km), on = "LinkID"]
  r[rin, (setdiff(names(rin), c("station_id", "t"))) := mget(paste0("i.", setdiff(names(rin), c("station_id", "t")))),
    on = c("station_id", "t")]
  r[rain_now, rain_now := i.rain_now, on = c("station_id", "t")]
  r <- calendar_inputs(r)
  ok <- !is.na(r$y) & !is.na(r$U)
  for (c in core_input_columns()) ok <- ok & !is.na(r[[c]])
  r[, use := ok]
  r[road, `:=`(road = i.road, heldout_road = i.heldout_road), on = "LinkID"]
  r[school, school_period := i.school_period, on = "date"]
  setorder(r, LinkID, t)
  r
}

# ---------------------------------------------------------------------------------------------------
# Incidents (for checking labels and explaining errors; not a model input)
# ---------------------------------------------------------------------------------------------------

read_incident_file <- function(path, snap_no) {
  # One saved incidents snapshot -> snap_no, retrieved, one row per incident; a snapshot (or page) without
  # incidents gives one row with Type NA.
  lines <- readLines(gzfile(path), warn = FALSE)
  empty <- function(ret) data.table(retrieved = ret, Type = NA_character_, Latitude = NA_real_,
                                    Longitude = NA_real_, Message = NA_character_)
  if (!length(lines)) return(cbind(empty(file_time(path)), snap_no = as.integer(snap_no)))
  d <- rbindlist(lapply(lines, function(l) {
    o <- fromJSON(l)
    ret <- parse_sgt(o$retrieved_at)
    v <- tryCatch(fromJSON(o$body)$value, error = function(e) NULL)
    if (is.null(v) || !length(v) || !NROW(v)) return(empty(ret))
    v <- as.data.table(v)
    data.table(retrieved = ret,
               Type = if ("Type" %in% names(v)) as.character(v$Type) else NA_character_,
               Latitude = if ("Latitude" %in% names(v)) as.numeric(v$Latitude) else NA_real_,
               Longitude = if ("Longitude" %in% names(v)) as.numeric(v$Longitude) else NA_real_,
               Message = if ("Message" %in% names(v)) as.character(v$Message) else NA_character_)
  }))
  d[, snap_no := as.integer(snap_no)]
  d
}

incident_episodes <- function(snaps) {
  # An incident is listed from the snapshot where it appears (first_seen) to the first later snapshot without
  # it (last_seen_before; NA if still listed at the end). 'reported' = the time at the start of the message.
  times <- snaps[, .(retrieved = retrieved[1]), by = snap_no][order(snap_no)]
  last_snap <- max(times$snap_no)
  key <- c("Type", "Message", "Latitude", "Longitude")
  inc <- unique(snaps[!is.na(Type)], by = c("snap_no", key))
  setorderv(inc, c(key, "snap_no"), na.last = TRUE)
  inc[, run := snap_no - (rowidv(inc, cols = key) - 1L)]
  ep <- inc[, .(a = min(snap_no), b = max(snap_no)), by = c(key, "run")]
  ep[, gone := fifelse(b < last_snap, b + 1L, NA_integer_)]
  ep[times, first_seen := i.retrieved, on = c(a = "snap_no")]
  ep[times, last_seen_before := i.retrieved, on = c(gone = "snap_no")]
  m <- regmatches(ep$Message, regexec("^\\(([0-9]{1,2})/([0-9]{1,2})\\)([0-9]{1,2}):([0-9]{2})", ep$Message))
  txt <- vapply(seq_along(m), function(i) {
    g <- m[[i]]
    if (length(g) < 5) return(NA_character_)
    sprintf("%s-%02d-%02d-%02d-%s", format(ep$first_seen[i], "%Y"), as.integer(g[3]), as.integer(g[2]), as.integer(g[4]), g[5])
  }, character(1))
  ep[, reported := as.POSIXct(txt, format = "%Y-%m-%d-%H-%M", tz = "UTC")]
  r <- ep[, .(type = Type, message = Message, lat = Latitude, lon = Longitude, first_seen, last_seen_before, reported)]
  setorder(r, first_seen, type, message, lat, lon)
  r[]
}
