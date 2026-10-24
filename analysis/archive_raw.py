"""archive_raw.py - SLDS 42.510 project 1.3: stage the raw data for Google Drive in archive_raw/.

Only reads data_raw/ and data_raw_expressway/; writes archive_raw/, which mirrors the Drive folder
SLDS_1.3_raw exactly. Standard library only (Python 3.9+).

    python3 analysis/archive_raw.py              # stage every finished day not staged yet
    python3 analysis/archive_raw.py --dry-run    # list what would be staged; writes nothing

archive_raw/ (= Drive SLDS_1.3_raw/):
    README.txt  MANIFEST.csv  SHA256SUMS.txt
    lta_network/       lta_network_<D>.tar       from data_raw/ (lta-collector)
    lta_expressway/    lta_expressway_<D>.tar    from data_raw_expressway/ (lta-collector-expressway)
    lta_fetch_logs/    network_log_*.csv, expressway_log_*.csv   (copied whole each run)
    lta_source_check/  lta_source_check_2026-10-16.tar           (data_raw/source_check/, once)
    nea_rainfall/      rain_YYYYMMDD.jsonl.gz    (copied from data_raw/nea_rainfall/)
    calendar/          mom_public_holidays_2026.json             (copied each run)

A day's tar holds, for day D (SGT) and with paths starting data_raw/ or data_raw_expressway/ so it unpacks
into the project: speedbands/D/, speedbands_raw/D/, feeds/<feed>/D/, daily_feeds/daily_YYYYMMDD*,
logs/collector.log.D. Only days before today are packed. A tar or rainfall day already staged is never
rebuilt; if its source files change later, a WARN line is printed and the staged copy is left as it is.
AI disclosure: drafted with Claude (Anthropic) on 24 Oct 2026; log in AI_USE.md.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import shutil
import sys
import tarfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SGT = timezone(timedelta(hours=8))
UNITS = {"data_raw": ("lta_network", "network"), "data_raw_expressway": ("lta_expressway", "expressway")}
FIELDS = ["folder", "file", "date", "bytes", "sha256", "n_files", "bytes_raw", "n_speedbands"]
README = """SLDS 1.3 raw data (SUTD 42.510, project 1.3). Updated nightly at about 02:30 SGT with the previous day.
Uploaded by upload_raw.sh on the team's Linux PC; files are only added, never deleted or replaced.

MANIFEST.csv        one row per file: folder, file, date, bytes, sha256; for tars also n_files (raw files
                    inside), bytes_raw and n_speedbands (speed-band snapshots that day)
SHA256SUMS.txt      checksums of every file below
lta_network/        lta_network_<date>.tar: whole road network, from data_raw/ (collector 1, key 1).
                    Speed bands each LTA update (~5 min), incidents and VMS (2 min), travel times (5 min),
                    road works and road openings (daily), the collector's log for that day
lta_expressway/     lta_expressway_<date>.tar: the 58 speed-band pages with the expressway links, every
                    2 min, plus PUB flood alerts, from data_raw_expressway/ (collector 2, key 2)
lta_fetch_logs/     every fetch of both collectors (log_speedbands.csv, log_feeds.csv), whole, refreshed nightly
lta_source_check/   the 13-16 Oct check of every source
nea_rainfall/       NEA 5-minute rainfall per station from data.gov.sg, one file per day
calendar/           MOM public holidays 2026 from data.gov.sg

Collection: LTA from 16 Oct 2026 on this PC. 16 Oct is a part day (collection moved here that day).
Licence: LTA DataMall, NEA and MOM data under the Singapore Open Data Licence v1.0.

To use: download MANIFEST.csv, SHA256SUMS.txt and the files you need into one folder, keeping the
folders above. Then, from the repo:
    python analysis/verify_raw.py <folder>               must end RESULT: OK
    python analysis/verify_raw.py <folder> --extract .   unpacks into data_raw/ and data_raw_expressway/
"""


def project_dir() -> Path:
    env = os.environ.get("SLDS_PROJECT_DIR")
    return Path(env).resolve() if env else Path(__file__).resolve().parent.parent


def files_under(d: Path) -> list[Path]:
    return sorted(p for p in d.rglob("*") if p.is_file() and not p.name.endswith(".partial")) if d.is_dir() else []


def day_files(unit_dir: Path, d: str) -> list[Path]:
    """Every raw file of one SGT day, in a fixed order."""
    out = files_under(unit_dir / "speedbands" / d) + files_under(unit_dir / "speedbands_raw" / d)
    feeds = unit_dir / "feeds"
    if feeds.is_dir():
        for feed in sorted(feeds.iterdir()):
            out += files_under(feed / d)
    compact = d.replace("-", "")
    out += sorted(p for p in (unit_dir / "daily_feeds").glob(f"daily_{compact}*") if not p.name.endswith(".partial"))
    log = unit_dir / "logs" / f"collector.log.{d}"
    if log.is_file():
        out.append(log)
    return out


def days_seen(unit_dir: Path) -> set[str]:
    days = set()
    iso = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    for sub in ("speedbands", "speedbands_raw"):
        if (unit_dir / sub).is_dir():
            days |= {p.name for p in (unit_dir / sub).iterdir() if p.is_dir() and iso.match(p.name)}
    if (unit_dir / "feeds").is_dir():
        for feed in (unit_dir / "feeds").iterdir():
            if feed.is_dir():
                days |= {p.name for p in feed.iterdir() if p.is_dir() and iso.match(p.name)}
    for p in (unit_dir / "daily_feeds").glob("daily_*"):
        m = re.match(r"daily_(\d{4})(\d{2})(\d{2})", p.name)
        if m:
            days.add("-".join(m.groups()))
    for p in (unit_dir / "logs").glob("collector.log.*"):
        if iso.match(p.name.rsplit(".", 1)[-1]):
            days.add(p.name.rsplit(".", 1)[-1])
    return days


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_tar(proj: Path, files: list[Path], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".partial")
    with tarfile.open(tmp, "w", format=tarfile.PAX_FORMAT) as tar:
        for p in files:
            tar.add(p, arcname=p.relative_to(proj).as_posix(), recursive=False)
    os.replace(tmp, out)


def copy_file(src: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".partial")
    shutil.copyfile(src, tmp)
    os.replace(tmp, out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stage the raw data for Google Drive in archive_raw/")
    ap.add_argument("--dry-run", action="store_true", help="list what would be staged; write nothing")
    args = ap.parse_args(argv)
    proj = project_dir()
    arch = proj / "archive_raw"
    today = datetime.now(SGT).date().isoformat()
    man_path = arch / "MANIFEST.csv"
    manifest: dict[str, dict] = {}
    if man_path.exists():
        with open(man_path, newline="", encoding="utf-8") as f:
            manifest = {f"{r['folder']}/{r['file']}": r for r in csv.DictReader(f)}
    n_new = n_warn = 0

    def record(out: Path, d: str, files: list[Path] | None = None) -> None:
        row = {"folder": out.parent.name, "file": out.name, "date": d, "bytes": out.stat().st_size,
               "sha256": sha256(out), "n_files": "", "bytes_raw": "", "n_speedbands": ""}
        if files is not None:
            row.update(n_files=len(files), bytes_raw=sum(p.stat().st_size for p in files),
                       n_speedbands=sum(1 for p in files if p.parent.parent.name == "speedbands"))
        manifest[f"{row['folder']}/{row['file']}"] = row

    # 1. Daily tars per collector, plus the source check once.
    jobs = []   # (date label, files, tar path)
    for unit, (folder, _) in UNITS.items():
        unit_dir = proj / unit
        if not unit_dir.is_dir():
            continue
        days = sorted(d for d in days_seen(unit_dir) if d < today)
        if days:   # gaps between the first and last day are reported, not packed
            d0, d1 = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
            for i in range((d1 - d0).days + 1):
                d = (d0 + timedelta(days=i)).isoformat()
                if d not in days:
                    print(f"GAP  {folder} {d}: no files at all")
        for d in days:
            jobs.append((d, day_files(unit_dir, d), arch / folder / f"{folder}_{d}.tar"))
    sc = proj / "data_raw" / "source_check"
    if sc.is_dir():
        jobs.append(("2026-10-16", files_under(sc), arch / "lta_source_check" / "lta_source_check_2026-10-16.tar"))
    for d, files, out in jobs:
        n_raw, b_raw = len(files), sum(p.stat().st_size for p in files)
        row = manifest.get(f"{out.parent.name}/{out.name}")
        if row and out.exists():
            if int(row["n_files"]) != n_raw or int(row["bytes_raw"]) != b_raw:
                n_warn += 1
                print(f"WARN {out.name}: source files changed after packing (packed {row['n_files']} files / "
                      f"{row['bytes_raw']} B, disk now {n_raw} / {b_raw} B); tar left as it is")
            continue
        if args.dry_run:
            print(f"would pack {out.parent.name}/{out.name}: {n_raw} files, {b_raw / 1e6:.1f} MB")
            continue
        build_tar(proj, files, out)
        record(out, d, files)
        n_new += 1
        print(f"packed {out.parent.name}/{out.name}: {n_raw} files, {out.stat().st_size / 1e6:.1f} MB")

    # 2. Finished rainfall days: copied once, never replaced.
    for src in sorted((proj / "data_raw" / "nea_rainfall").glob("rain_*.jsonl.gz")):
        out = arch / "nea_rainfall" / src.name
        m = re.match(r"rain_(\d{4})(\d{2})(\d{2})", src.name)
        if out.exists():
            if out.stat().st_size != src.stat().st_size:
                n_warn += 1
                print(f"WARN nea_rainfall/{src.name}: source changed after staging; staged copy left as it is")
            continue
        if args.dry_run:
            print(f"would copy nea_rainfall/{src.name}")
            continue
        copy_file(src, out)
        record(out, "-".join(m.groups()) if m else "")
        n_new += 1

    # 3. Files that change: refreshed every run.
    if not args.dry_run:
        for unit, (_, prefix) in UNITS.items():
            for name in ("log_speedbands.csv", "log_feeds.csv"):
                src = proj / unit / name
                if src.is_file():
                    out = arch / "lta_fetch_logs" / f"{prefix}_{name}"
                    copy_file(src, out)
                    record(out, today)
        for src in sorted((proj / "data_raw" / "calendar").glob("*.json")):
            out = arch / "calendar" / src.name
            copy_file(src, out)
            record(out, "")

        rows = sorted(manifest.values(), key=lambda r: (r["folder"], r["file"]))
        tmp = man_path.with_name("MANIFEST.csv.partial")
        arch.mkdir(exist_ok=True)
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, man_path)
        (arch / "SHA256SUMS.txt").write_text(
            "".join(f"{r['sha256']}  {r['folder']}/{r['file']}\n" for r in rows), encoding="utf-8")
        (arch / "README.txt").write_text(README, encoding="utf-8")
    print(f"archive_raw: {n_new} new file(s), {n_warn} warning(s), {len(manifest)} in manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
