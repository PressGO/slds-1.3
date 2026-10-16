# 00_check_sources.R
# SLDS 42.510 project 1.3 (recurring vs unusual congestion): one-off check of
# the planned data sources.
#
# For each source the script makes a few requests, saves every raw response
# byte for byte (gzipped) with retrieval metadata, and prints data-quality
# checks you can quote as "evidence that the data are accessible" (Brief §6.1).
# It is a check, not the collector. Run it once now, and again if an endpoint
# changes.
#
# Setup, once per machine
#   install.packages(c("httr2", "jsonlite"))
#   Put your keys in a file called .Renviron in the project root, and add
#   .Renviron to .gitignore so the key is never committed (LTA terms require
#   keeping it confidential):
#     LTA_ACCOUNT_KEY=<your LTA DataMall AccountKey>
#     DATAGOVSG_API_KEY=<optional data.gov.sg key; raises rate limits>
#   Restart R so the keys load.
#
# Run from the project root
#   Rscript analysis/00_check_sources.R      (or source() it in RStudio)
#
# Outputs in data_raw/source_check/ (new files each run, nothing overwritten)
#   raw/<source>/<run>_p<page>.json.gz   raw response bodies
#   request_log_<run>.csv                one row per HTTP request
#   summary_<run>.txt                    the checks printed at the end
#
# Assumptions to confirm against LTA's API User Guide (the script reports any
# mismatch instead of failing):
#   - speed-band endpoint "v4/TrafficSpeedBands" and 500-record pages
#     (from the ltasg 1.0.0 Python client, which cites guide v6.8);
#   - field names in EXPECTED_* below (from the lta_models 0.6.0 Rust client).
#
# AI disclosure: drafted with Claude (Anthropic) on 10 Oct 2026. Log it in
# AI_USE.md and read every line before relying on it (Brief §5).

for (pkg in c("httr2", "jsonlite")) {
  if (!requireNamespace(pkg, quietly = TRUE)) {
    stop(sprintf("Package '%s' is missing. Run install.packages(\"%s\") first.", pkg, pkg))
  }
}

sgt_today <- as.Date(format(Sys.time(), "%Y-%m-%d", tz = "Asia/Singapore"))

CONFIG <- list(
  out_dir             = file.path("data_raw", "source_check"),
  lta_base            = "https://datamall2.mytransport.sg/ltaodataservice/",
  lta_speed_path      = "v4/TrafficSpeedBands",
  lta_incidents_path  = "TrafficIncidents",
  rain_url            = "https://api-open.data.gov.sg/v2/real-time/api/rainfall",
  # Yesterday tests day-level retrieval. 30 days back tests whether rainfall
  # for the whole study window can be backfilled after collection ends.
  rain_past_dates     = format(sgt_today - c(1, 30)),
  holiday_url         = "https://data.gov.sg/api/action/datastore_search",
  holiday_resource_id = "d_149b61ad0a22f61c09dc80f2df5bbec8",  # MOM "Public Holidays for 2026"
  holiday_window      = as.Date(c("2026-10-01", "2026-12-31")),
  lta_page_limit      = 500,  # LTA returns at most this many records per call
  max_pages           = 400,  # safety stop for paging loops
  pause_seconds       = 2,    # data.gov.sg real-time API: 6 calls per 10 s without a key
  timeout_seconds     = 60
)

EXPECTED_SPEED_FIELDS <- c("LinkID", "RoadName", "RoadCategory", "SpeedBand",
                           "MinimumSpeed", "MaximumSpeed",
                           "StartLon", "StartLat", "EndLon", "EndLat")
EXPECTED_INCIDENT_FIELDS <- c("Type", "Latitude", "Longitude", "Message")

`%||%` <- function(a, b) if (is.null(a) || length(a) == 0) b else a

now_sgt   <- function() format(Sys.time(), "%Y-%m-%dT%H:%M:%OS3%z", tz = "Asia/Singapore")
run_stamp <- function() format(Sys.time(), "%Y%m%d_%H%M%OS3", tz = "Asia/Singapore")

LOG <- new.env()
LOG$rows <- list()

# ---- HTTP -------------------------------------------------------------------

# The only function that touches the network. HTTP error statuses are
# returned rather than thrown, so every request can be logged.
http_get <- function(url, headers = list(), query = list()) {
  req <- httr2::request(url)
  if (length(query) > 0) req <- do.call(httr2::req_url_query, c(list(req), query))
  if (length(headers) > 0) req <- do.call(httr2::req_headers, c(list(req), headers))
  req <- httr2::req_timeout(req, CONFIG$timeout_seconds)
  req <- httr2::req_error(req, is_error = function(resp) FALSE)
  t0 <- Sys.time()
  resp <- httr2::req_perform(req)
  list(
    status        = httr2::resp_status(resp),
    body_raw      = tryCatch(httr2::resp_body_raw(resp), error = function(e) raw(0)),
    elapsed       = as.numeric(difftime(Sys.time(), t0, units = "secs")),
    server_date   = httr2::resp_header(resp, "date") %||% NA_character_,
    last_modified = httr2::resp_header(resp, "last-modified") %||% NA_character_
  )
}

query_string <- function(query) {
  if (length(query) == 0) return("")
  paste(names(query), vapply(query, as.character, character(1)), sep = "=", collapse = "&")
}

# Performs one request, saves the raw body and appends a row to the log.
# Headers (which carry the keys) are never written anywhere.
logged_get <- function(source, url, headers = list(), query = list(),
                       page = 1L, run = run_stamp()) {
  retrieved_at <- now_sgt()
  res <- tryCatch(
    http_get(url, headers, query),
    error = function(e) list(status = NA_integer_, body_raw = raw(0), elapsed = NA_real_,
                             server_date = NA_character_, last_modified = NA_character_,
                             error = conditionMessage(e))
  )
  res$body <- NA_character_
  raw_file <- NA_character_
  if (length(res$body_raw) > 0) {
    res$body <- rawToChar(res$body_raw)
    Encoding(res$body) <- "UTF-8"
    dir <- file.path(CONFIG$out_dir, "raw", source)
    dir.create(dir, recursive = TRUE, showWarnings = FALSE)
    raw_file <- file.path(dir, sprintf("%s_p%03d.json.gz", run, page))
    con <- gzfile(raw_file, "wb")
    writeBin(res$body_raw, con)
    close(con)
  }
  LOG$rows[[length(LOG$rows) + 1L]] <- data.frame(
    source = source, run = run, page = page, retrieved_at_sgt = retrieved_at,
    url = url, query = query_string(query),
    http_status = res$status, elapsed_s = round(res$elapsed, 3),
    bytes = length(res$body_raw), server_date = res$server_date,
    last_modified = res$last_modified, raw_file = raw_file,
    error = gsub("\\s+", " ", res$error %||% NA_character_),
    stringsAsFactors = FALSE
  )
  res
}

parse_json <- function(res) {
  tryCatch(jsonlite::fromJSON(res$body, simplifyVector = TRUE), error = function(e) NULL)
}

is_ok <- function(res) !is.na(res$status) && res$status == 200L

describe_failure <- function(res, what) {
  hint <- if (is.na(res$status)) {
    "no response: check the connection; a restricted network may block the host"
  } else {
    switch(as.character(res$status),
           "400" = "bad request: check the query parameters",
           "401" = "unauthorised: key missing, wrong, or not yet active",
           "403" = "forbidden: key not accepted for this endpoint",
           "404" = "not found: check the endpoint path against the current API guide",
           "429" = "rate limited: wait a minute and rerun, or add an API key",
           "unexpected status")
  }
  detail <- if (!is.na(res$body)) res$body else res$error %||% ""
  detail <- substr(gsub("\\s+", " ", detail), 1, 200)
  sprintf("FAILED %s: HTTP %s (%s). %s", what,
          if (is.na(res$status)) "none" else res$status, hint, detail)
}

# ---- Helpers for data frames ------------------------------------------------

# rbind that tolerates pages with different columns.
bind_pages <- function(pages) {
  pages <- Filter(function(d) NROW(d) > 0, pages)
  if (length(pages) == 0) return(data.frame())
  cols <- unique(unlist(lapply(pages, names)))
  pages <- lapply(pages, function(d) {
    for (col in setdiff(cols, names(d))) d[[col]] <- NA
    d[cols]
  })
  out <- do.call(rbind, pages)
  rownames(out) <- NULL
  out
}

count_string <- function(x) {
  tab <- table(x, useNA = "ifany")
  paste(sprintf("%s=%d", names(tab), as.integer(tab)), collapse = "  ")
}

field_check <- function(found, expected) {
  missing <- setdiff(expected, found)
  extra <- setdiff(found, expected)
  c(sprintf("Expected fields missing: %s",
            if (length(missing)) paste(missing, collapse = ", ") else "none"),
    sprintf("Fields not in the expected list: %s",
            if (length(extra)) paste(extra, collapse = ", ") else "none"))
}

missing_check <- function(df) {
  n_bad <- vapply(df, function(x) {
    blank <- if (is.character(x)) !is.na(x) & trimws(x) == "" else FALSE
    sum(is.na(x) | blank)
  }, numeric(1))
  bad <- n_bad[n_bad > 0]
  if (length(bad) == 0) return("Missing or blank values: none")
  paste("Missing or blank values:", paste(sprintf("%s=%d", names(bad), as.integer(bad)), collapse = "  "))
}

# "2026-10-09T23:55:00+08:00" -> POSIXct in Singapore time
parse_ts <- function(x) {
  x <- sub("([+-][0-9]{2}):([0-9]{2})$", "\\1\\2", x)
  as.POSIXct(x, format = "%Y-%m-%dT%H:%M:%S%z", tz = "Asia/Singapore")
}

# ---- LTA DataMall -----------------------------------------------------------

# Identifies a page by its first record, to catch an endpoint that ignores $skip.
first_record_id <- function(value) {
  if (is.data.frame(value) && "LinkID" %in% names(value)) return(as.character(value$LinkID[1]))
  first <- if (is.data.frame(value)) value[1, , drop = FALSE] else value[[1]]
  as.character(jsonlite::toJSON(first, auto_unbox = TRUE))
}

# Pages through an endpoint with $skip. A page shorter than the page limit,
# an empty page, or a page that repeats the previous one ends the loop.
fetch_lta_all <- function(source, path, key) {
  base <- paste0(CONFIG$lta_base, path)
  headers <- list(AccountKey = key, accept = "application/json")
  run <- run_stamp()
  pages <- list()
  page <- 1L
  skip <- 0L
  first_page_size <- NA_integer_
  prev_id <- NULL
  top_keys <- NULL
  hit_cap <- FALSE
  repeated <- FALSE
  t0 <- Sys.time()
  repeat {
    url <- if (skip == 0L) base else paste0(base, "?$skip=", skip)
    res <- logged_get(source, url, headers, page = page, run = run)
    if (!is_ok(res)) {
      return(list(ok = FALSE, message = describe_failure(res, paste(source, "request", page))))
    }
    js <- parse_json(res)
    if (is.null(js)) {
      return(list(ok = FALSE,
                  message = sprintf("FAILED %s request %d: response is not valid JSON", source, page)))
    }
    top_keys <- top_keys %||% names(js)
    value <- js$value
    n <- NROW(value)
    if (n == 0L) break
    if (is.data.frame(value)) value <- jsonlite::flatten(value)
    id <- first_record_id(value)
    if (identical(id, prev_id)) {
      repeated <- TRUE
      break
    }
    prev_id <- id
    pages[[length(pages) + 1L]] <- value
    if (is.na(first_page_size)) first_page_size <- n
    if (n < CONFIG$lta_page_limit) break
    if (page >= CONFIG$max_pages) {
      hit_cap <- TRUE
      break
    }
    skip <- skip + n
    page <- page + 1L
  }
  list(ok = TRUE, data = bind_pages(pages), requests = page, first_page_size = first_page_size,
       elapsed = as.numeric(difftime(Sys.time(), t0, units = "secs")),
       top_keys = top_keys, hit_cap = hit_cap, repeated = repeated)
}

paging_lines <- function(r) {
  out <- c(sprintf("Response keys: %s", paste(r$top_keys, collapse = ", ")),
           sprintf("Records: %d from %d request(s); first page %s records; paging took %.1f s",
                   nrow(r$data), r$requests, r$first_page_size, r$elapsed))
  if (r$repeated) {
    out <- c(out, "WARNING: a page repeated the previous one, so the endpoint seems to ignore $skip; check paging in the API guide.")
  }
  if (r$hit_cap) out <- c(out, "WARNING: stopped at max_pages; the snapshot may be incomplete.")
  if (r$elapsed > 60) {
    out <- c(out, "WARNING: paging took over a minute, so pages may straddle a 5-minute update.")
  }
  out
}

check_speed_bands <- function(sb) {
  df <- sb$data
  out <- paging_lines(sb)
  if (nrow(df) == 0) return(c(out, "WARNING: no records returned."))
  out <- c(out, field_check(names(df), EXPECTED_SPEED_FIELDS))
  if ("LinkID" %in% names(df)) {
    out <- c(out, sprintf("Unique LinkIDs: %d; duplicated LinkIDs: %d",
                          length(unique(df$LinkID)), sum(duplicated(df$LinkID))))
  }
  out <- c(out, missing_check(df))
  if ("SpeedBand" %in% names(df)) out <- c(out, paste("SpeedBand counts:", count_string(df$SpeedBand)))
  if ("RoadCategory" %in% names(df)) {
    out <- c(out, paste("RoadCategory counts:", count_string(df$RoadCategory)))
  }
  if (all(c("SpeedBand", "MinimumSpeed", "MaximumSpeed") %in% names(df))) {
    combos <- unique(data.frame(
      band = suppressWarnings(as.integer(df$SpeedBand)),
      min  = suppressWarnings(as.numeric(df$MinimumSpeed)),
      max  = suppressWarnings(as.numeric(df$MaximumSpeed))
    ))
    combos <- combos[order(combos$band, combos$min, combos$max), ]
    shown <- head(combos, 20)
    out <- c(out, paste0(
      "Band -> km/h range in this pull: ",
      paste(sprintf("%s:[%s,%s]", shown$band, shown$min, shown$max), collapse = "  "),
      if (nrow(combos) > 20) sprintf("  (+%d more combinations)", nrow(combos) - 20) else ""
    ))
  }
  coord_cols <- c("StartLat", "StartLon", "EndLat", "EndLon")
  if (all(coord_cols %in% names(df))) {
    lat <- suppressWarnings(as.numeric(c(df$StartLat, df$EndLat)))
    lon <- suppressWarnings(as.numeric(c(df$StartLon, df$EndLon)))
    bad <- sum(is.na(lat) | is.na(lon) | lat < 1.1 | lat > 1.5 | lon < 103.5 | lon > 104.1)
    out <- c(out, sprintf("Link endpoints unparseable or outside a Singapore bounding box: %d of %d",
                          bad, length(lat)))
  }
  out
}

check_incidents <- function(inc) {
  df <- inc$data
  out <- c(paging_lines(inc), sprintf("Incidents listed right now: %d", nrow(df)))
  if (nrow(df) == 0) return(c(out, "No incidents at the moment, so field checks are skipped; rerun later."))
  out <- c(out, field_check(names(df), EXPECTED_INCIDENT_FIELDS), missing_check(df))
  if ("Type" %in% names(df)) out <- c(out, paste("Type counts:", count_string(df$Type)))
  if ("Message" %in% names(df)) {
    out <- c(out, "Example messages (the schema has no time field; check whether the text carries one):",
             paste0("  ", substr(head(df$Message, 3), 1, 140)))
  }
  out
}

# ---- NEA rainfall (data.gov.sg) ---------------------------------------------

# One row per station and reading time.
flatten_readings <- function(readings) {
  rows <- Map(function(ts, d) {
    if (NROW(d) == 0) return(NULL)
    data.frame(timestamp = ts, stationId = d$stationId, value = d$value, stringsAsFactors = FALSE)
  }, readings$timestamp, readings$data)
  bind_pages(Filter(Negate(is.null), rows))
}

# date = NULL gives the latest reading; "YYYY-MM-DD" gives that whole day,
# following paginationToken until the API stops returning one.
fetch_rain <- function(date = NULL, key = "") {
  headers <- if (nzchar(key)) list(`x-api-key` = key) else list()
  source <- if (is.null(date)) "rainfall_latest" else paste0("rainfall_", date)
  run <- run_stamp()
  page <- 1L
  token <- NULL
  stations <- NULL
  readings <- list()
  reading_type <- NA_character_
  unit <- NA_character_
  repeat {
    query <- list()
    if (!is.null(date)) query$date <- date
    if (!is.null(token)) query$paginationToken <- token
    res <- logged_get(source, CONFIG$rain_url, headers, query, page, run)
    if (!is_ok(res)) {
      return(list(ok = FALSE, message = describe_failure(res, paste(source, "request", page))))
    }
    js <- parse_json(res)
    if (is.null(js) || is.null(js$data)) {
      return(list(ok = FALSE, message = sprintf("FAILED %s request %d: unexpected response (code %s)",
                                                source, page, js$code %||% "?")))
    }
    d <- js$data
    if (is.null(stations) && NROW(d$stations) > 0) stations <- jsonlite::flatten(d$stations)
    if (NROW(d$readings) > 0) readings[[length(readings) + 1L]] <- flatten_readings(d$readings)
    reading_type <- d$readingType %||% reading_type
    unit <- d$readingUnit %||% unit
    token <- d$paginationToken
    if (is.null(token) || !nzchar(token) || page >= CONFIG$max_pages) break
    page <- page + 1L
    Sys.sleep(CONFIG$pause_seconds)
  }
  list(ok = TRUE, stations = stations, readings = bind_pages(readings), requests = page,
       reading_type = reading_type, unit = unit)
}

check_rain <- function(r, date = NULL) {
  label <- if (is.null(date)) "latest" else date
  st <- r$stations
  rd <- r$readings
  out <- sprintf("[%s] %d request(s); reading type: %s; unit: %s; stations listed: %d",
                 label, r$requests, r$reading_type, r$unit, NROW(st))
  if (NROW(rd) == 0) return(c(out, sprintf("[%s] WARNING: no readings returned", label)))
  ts <- parse_ts(unique(rd$timestamp))
  out <- c(out, sprintf("[%s] Distinct reading times: %d, from %s to %s", label, length(ts),
                        format(min(ts, na.rm = TRUE), "%Y-%m-%d %H:%M"),
                        format(max(ts, na.rm = TRUE), "%Y-%m-%d %H:%M")))
  if (!is.null(date)) {
    day_slots <- seq(as.POSIXct(paste(date, "00:00:00"), tz = "Asia/Singapore"),
                     by = "5 min", length.out = 288)
    off_day <- sum(format(ts, "%Y-%m-%d") != date, na.rm = TRUE)
    out <- c(out, sprintf("[%s] 5-minute slots missing from the day: %d of 288; readings dated another day: %d",
                          label, sum(!(as.numeric(day_slots) %in% as.numeric(ts))), off_day))
  }
  per_time <- as.integer(table(rd$timestamp))
  out <- c(out, sprintf("[%s] Stations reporting per reading time: min %d, median %g, max %d",
                        label, min(per_time), stats::median(per_time), max(per_time)))
  if (!is.null(st) && "id" %in% names(st)) {
    out <- c(out, sprintf("[%s] Station IDs in readings but not listed: %d; listed but never reporting: %d",
                          label, length(setdiff(unique(rd$stationId), st$id)),
                          length(setdiff(st$id, unique(rd$stationId)))))
  }
  v <- suppressWarnings(as.numeric(rd$value))
  if (all(is.na(v))) return(c(out, sprintf("[%s] WARNING: all values missing", label)))
  c(out, sprintf("[%s] Values: %d missing; range %g to %g; %.1f%% zero", label, sum(is.na(v)),
                 min(v, na.rm = TRUE), max(v, na.rm = TRUE), 100 * mean(v == 0, na.rm = TRUE)))
}

# ---- Public holidays (MOM via data.gov.sg) -----------------------------------

check_holidays <- function(key = "") {
  headers <- if (nzchar(key)) list(`x-api-key` = key) else list()
  res <- logged_get("public_holidays", CONFIG$holiday_url, headers,
                    list(resource_id = CONFIG$holiday_resource_id, limit = 100))
  if (!is_ok(res)) return(describe_failure(res, "public holidays"))
  recs <- parse_json(res)$result$records
  if (NROW(recs) == 0 || !all(c("date", "day", "holiday") %in% names(recs))) {
    return("FAILED public holidays: no records, or fields other than date/day/holiday")
  }
  d <- as.Date(recs$date)
  keep <- !is.na(d) & d >= CONFIG$holiday_window[1] & d <= CONFIG$holiday_window[2]
  c(sprintf("Records: %d", nrow(recs)),
    sprintf("Holidays from %s to %s:", CONFIG$holiday_window[1], CONFIG$holiday_window[2]),
    if (any(keep)) sprintf("  %s %s  %s", recs$date[keep], recs$day[keep], recs$holiday[keep]) else "  none")
}

# ---- Main -------------------------------------------------------------------

main <- function() {
  dir.create(CONFIG$out_dir, recursive = TRUE, showWarnings = FALSE)
  LOG$rows <- list()
  run <- run_stamp()
  lta_key <- trimws(Sys.getenv("LTA_ACCOUNT_KEY"))
  dgs_key <- trimws(Sys.getenv("DATAGOVSG_API_KEY"))
  out <- c(sprintf("Source check started %s (Singapore time)", now_sgt()), "")

  lta_sections <- list(
    list(title = "LTA Traffic Speed Bands", source = "speed_bands",
         path = CONFIG$lta_speed_path, check = check_speed_bands),
    list(title = "LTA Traffic Incidents", source = "incidents",
         path = CONFIG$lta_incidents_path, check = check_incidents)
  )
  for (s in lta_sections) {
    out <- c(out, sprintf("== %s ==", s$title))
    if (!nzchar(lta_key)) {
      out <- c(out, "SKIPPED: LTA_ACCOUNT_KEY is not set (see the setup notes at the top).", "")
      next
    }
    r <- fetch_lta_all(s$source, s$path, lta_key)
    out <- c(out, if (r$ok) s$check(r) else r$message, "")
  }

  out <- c(out, "== NEA rainfall via data.gov.sg ==")
  for (date in c(list(NULL), as.list(CONFIG$rain_past_dates))) {
    r <- fetch_rain(date, dgs_key)
    out <- c(out, if (r$ok) check_rain(r, date) else r$message)
    Sys.sleep(CONFIG$pause_seconds)
  }
  out <- c(out, "", "== Public holidays (MOM via data.gov.sg) ==", check_holidays(dgs_key), "")

  log <- bind_pages(LOG$rows)
  log_file <- file.path(CONFIG$out_dir, sprintf("request_log_%s.csv", run))
  summary_file <- file.path(CONFIG$out_dir, sprintf("summary_%s.txt", run))
  utils::write.csv(log, log_file, row.names = FALSE)
  n_failed <- sum(is.na(log$http_status) | log$http_status != 200L)
  out <- c(out, sprintf("Requests: %d, failed: %d. Log: %s", nrow(log), n_failed, log_file))
  writeLines(out, summary_file)
  cat(out, sep = "\n")
  invisible(list(summary = out, log = log))
}

# Set options(check_sources.skip_main = TRUE) before source() to load the
# functions without running the checks (used for testing).
if (!isTRUE(getOption("check_sources.skip_main"))) main()
