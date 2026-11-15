# compare_with_python.R - are the R tables the same as the Python tables?
#
#   Rscript R/compare_with_python.R [python_folder] [r_folder]
#   (defaults: data_processed/model and data_processed/model_r)
#
# For every table both builds make: the same columns (and types), the same rows in the same order, and the
# same value in every cell (exactly; a missing value equals only a missing value). Reads one column at a time,
# so the 14-million-row full table fits in memory. Also compares days.csv and the counts in the build records.
# The last line says SAME or DIFFERENT. The R build does not make extra/train_sample.parquet or README.md.
#
# AI disclosure: written with Claude (Anthropic) on 15 Nov 2026; log in AI_USE.md.

suppressPackageStartupMessages({ library(arrow); library(data.table); library(jsonlite) })
a <- commandArgs(trailingOnly = TRUE)
PY <- if (length(a) >= 1) a[1] else "data_processed/model"
RR <- if (length(a) >= 2) a[2] else "data_processed/model_r"

KEYS <- list("train.parquet" = c("LinkID", "t"), "test.parquet" = c("LinkID", "t"),
             "extra/full_table.parquet" = c("LinkID", "t"), "extra/test_full.parquet" = c("LinkID", "t"),
             "extra/train_lodo.parquet" = c("LinkID", "t"), "extra/links.parquet" = "LinkID",
             "extra/neighbours.parquet" = c("LinkID", "downstream"), "extra/connectors.parquet" = c("LinkID", "joins", "kind"),
             "extra/norm.parquet" = c("LinkID", "daytype", "slot15"), "extra/connector_norm.parquet" = c("LinkID", "daytype", "slot15"),
             "extra/incidents.parquet" = c("first_seen", "type", "message", "lat", "lon"))
type_name <- function(t) sub("^large_", "", t$ToString())          # string = large_string
as_cmp <- function(x) if (inherits(x, "POSIXt")) as.numeric(x) else if (inherits(x, "integer64")) as.numeric(x) else
  if (is.factor(x)) as.character(x) else if (inherits(x, "Date")) as.numeric(x) else x
n_diff <- function(x, y) { x <- as_cmp(x); y <- as_cmp(y)
  if (is.numeric(x) && is.numeric(y)) { x <- as.numeric(x); y <- as.numeric(y) }
  sum(!((is.na(x) & is.na(y)) | (!is.na(x) & !is.na(y) & x == y))) }
col <- function(f, c) as_cmp(read_parquet(f, col_select = all_of(c))[[1]])

results <- list(); all_same <- TRUE
say <- function(file, ok, detail) {
  results[[length(results) + 1L]] <<- data.table(file = file, result = if (ok) "same" else "DIFFERENT", detail = detail)
  if (!ok) all_same <<- FALSE
  cat(sprintf("%-32s %-9s %s\n", file, if (ok) "same" else "DIFFERENT", detail))
}

for (f in names(KEYS)) {
  fp <- file.path(PY, f); fr <- file.path(RR, f)
  if (!file.exists(fp) && !file.exists(fr)) next
  if (!file.exists(fp) || !file.exists(fr)) { say(f, FALSE, paste("only in", if (file.exists(fp)) "Python" else "R")); next }
  sp <- open_dataset(fp)$schema; sr <- open_dataset(fr)$schema
  if (!identical(names(sp), names(sr))) {
    say(f, FALSE, sprintf("columns differ: only Python [%s], only R [%s], or a different order",
                          paste(setdiff(names(sp), names(sr)), collapse = " "), paste(setdiff(names(sr), names(sp)), collapse = " ")))
    next
  }
  ty <- names(sp)[vapply(names(sp), function(c) type_name(sp[[c]]$type) != type_name(sr[[c]]$type), logical(1))]
  np <- open_dataset(fp)$num_rows; nr <- open_dataset(fr)$num_rows
  if (np != nr) { say(f, FALSE, sprintf("rows: Python %s, R %s", np, nr)); next }
  # rows in the same order? (compare the key columns first)
  k <- KEYS[[f]]
  kp <- as.data.table(lapply(setNames(nm = k), function(c) col(fp, c)))
  kr <- as.data.table(lapply(setNames(nm = k), function(c) col(fr, c)))
  order_note <- "same order"
  op <- or <- NULL
  if (sum(vapply(k, function(c) n_diff(kp[[c]], kr[[c]]), numeric(1))) > 0) {
    op <- do.call(order, c(unname(as.list(kp)), method = "radix")); or <- do.call(order, c(unname(as.list(kr)), method = "radix"))
    if (sum(vapply(k, function(c) n_diff(kp[[c]][op], kr[[c]][or]), numeric(1))) > 0) {
      say(f, FALSE, "the rows are not the same (key columns differ)"); next
    }
    order_note <- "different order, compared after sorting"
  }
  rm(kp, kr)
  bad <- c()
  for (c in names(sp)) {
    x <- col(fp, c); y <- col(fr, c)
    if (!is.null(op)) { x <- x[op]; y <- y[or] }
    d <- n_diff(x, y)
    if (d > 0) bad[c] <- d
  }
  cells <- format(as.numeric(np) * length(names(sp)), big.mark = ",", scientific = FALSE)
  say(f, !length(bad), sprintf("%s rows x %d columns = %s values; %s%s%s", format(np, big.mark = ","), length(names(sp)), cells, order_note,
                               if (length(bad)) paste0("; values differ: ", paste(sprintf("%s (%d)", names(bad), bad), collapse = ", ")) else "",
                               if (length(ty)) paste0("; types differ: ", paste(sprintf("%s %s/%s", ty, sapply(ty, function(c) type_name(sp[[c]]$type)),
                                                                                         sapply(ty, function(c) type_name(sr[[c]]$type))), collapse = ", ")) else ""))
  if (length(ty)) all_same <- FALSE
}

# days.csv: the same values (read as numbers and text; "1.0" and "1" are the same number)
dp <- fread(file.path(PY, "extra", "days.csv"), colClasses = "character"); dr <- fread(file.path(RR, "extra", "days.csv"), colClasses = "character")
num <- function(x) suppressWarnings(as.numeric(x))
dd <- if (!identical(names(dp), names(dr)) || nrow(dp) != nrow(dr)) NA else
  sum(vapply(names(dp), function(c) { x <- dp[[c]]; y <- dr[[c]]
    if (all(is.na(num(x)) == (x == "")) && all(is.na(num(y)) == (y == ""))) n_diff(num(x), num(y)) else sum(x != y) }, numeric(1)))
say("extra/days.csv", isTRUE(dd == 0), if (is.na(dd)) "columns or rows differ" else sprintf("%d rows; %d values differ", nrow(dp), dd))

# build records: rows, links and label counts
bp <- fromJSON(file.path(PY, "extra", "build_info.json")); br <- fromJSON(file.path(RR, "extra", "build_info_r.json"))
same_part <- function(nm) { a <- bp[[nm]]; b <- br[[nm]]; if (nm == "rows") a[["extra/train_sample.parquet"]] <- NULL
  isTRUE(all.equal(a[order(names(a))], b[order(names(b))])) }
for (nm in c("days", "links", "rows", "label_summary", "speed_band_cleaning"))
  say(paste0("build record: ", nm), same_part(nm), if (same_part(nm)) "same numbers" else "numbers differ (see the two json files)")

cat(if (all_same) "\nRESULT: SAME (every table and value the R build makes equals the Python build)\n" else "\nRESULT: DIFFERENT\n")
quit(status = if (all_same) 0 else 1)
