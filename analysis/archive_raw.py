"""archive_raw.py - SLDS 42.510 project 1.3: pack each finished day of raw collector data into one .tar.

Only reads data_raw*/ and writes to archive_raw/. Standard library only (Python 3.9+).

    python3 analysis/archive_raw.py              # pack every finished day not packed yet
    python3 analysis/archive_raw.py --dry-run    # list what would be packed; writes nothing

For each unit (data_raw, data_raw_expressway, data_raw_desktop if present) and each day D before today (SGT):
    archive_raw/<unit>/<unit>_<D>.tar  holding, with paths starting <unit>/ so they unpack into the project:
        speedbands/D/  speedbands_raw/D/  feeds/<feed>/D/  daily_feeds/daily_YYYYMMDD*  logs/collector.log.D
Plus once: archive_raw/data_raw/data_raw_source_check.tar (the 13-16 Oct source check).
Left out: the append-only log CSVs (upload_raw.sh copies them whole), state/status/lock files,
*.partial, nea_rainfall/ and calendar/ (uploaded as plain files).

A day already packed is never rebuilt. If its files on disk later differ from what was packed (count or
bytes), a WARN line is printed and the archive is left as it is.

Outputs in archive_raw/:
    MANIFEST.csv     unit, date, archive, n_files, bytes_raw, bytes_tar, n_speedbands, sha256
    SHA256SUMS.txt   for `sha256sum -c` (paths relative to archive_raw/)
AI disclosure: drafted with Claude (Anthropic) on 24 Oct 2026; log in AI_USE.md.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import sys
import tarfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SGT = timezone(timedelta(hours=8))
UNITS = ("data_raw", "data_raw_expressway", "data_raw_desktop")
FIELDS = ["unit", "date", "archive", "n_files", "bytes_raw", "bytes_tar", "n_speedbands", "sha256"]


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Pack finished days of raw data into archive_raw/")
    ap.add_argument("--dry-run", action="store_true", help="list what would be packed; write nothing")
    args = ap.parse_args(argv)
    proj = project_dir()
    arch = proj / "archive_raw"
    today = datetime.now(SGT).date().isoformat()
    man_path = arch / "MANIFEST.csv"
    manifest: dict[tuple[str, str], dict] = {}
    if man_path.exists():
        with open(man_path, newline="", encoding="utf-8") as f:
            manifest = {(r["unit"], r["date"]): r for r in csv.DictReader(f)}

    jobs = []   # (unit, date label, files, archive path)
    for unit in UNITS:
        unit_dir = proj / unit
        if not unit_dir.is_dir():
            continue
        days = sorted(d for d in days_seen(unit_dir) if d < today)
        if days:   # gaps between the first and last day are reported, not packed
            d0, d1 = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
            for i in range((d1 - d0).days + 1):
                d = (d0 + timedelta(days=i)).isoformat()
                if d not in days:
                    print(f"GAP  {unit} {d}: no files at all")
        for d in days:
            jobs.append((unit, d, day_files(unit_dir, d), arch / unit / f"{unit}_{d}.tar"))
    sc = proj / "data_raw" / "source_check"
    if sc.is_dir():
        jobs.append(("data_raw", "source_check", files_under(sc), arch / "data_raw" / "data_raw_source_check.tar"))

    n_new = n_warn = 0
    for unit, d, files, out in jobs:
        n_raw, b_raw = len(files), sum(p.stat().st_size for p in files)
        n_sb = sum(1 for p in files if p.parent.parent.name == "speedbands" and p.name.startswith("sb_"))
        row = manifest.get((unit, d))
        if row and out.exists():
            if int(row["n_files"]) != n_raw or int(row["bytes_raw"]) != b_raw:
                n_warn += 1
                print(f"WARN {unit} {d}: files changed after archiving (archive {row['n_files']} files / "
                      f"{row['bytes_raw']} B, disk now {n_raw} / {b_raw} B); archive left as it is")
            continue
        if args.dry_run:
            print(f"would pack {unit} {d}: {n_raw} files, {b_raw / 1e6:.1f} MB, {n_sb} speed-band snapshots")
            continue
        build_tar(proj, files, out)
        digest = sha256(out)
        out.with_name(out.name + ".sha256").write_text(f"{digest}  {out.name}\n", encoding="utf-8")
        manifest[(unit, d)] = {"unit": unit, "date": d, "archive": f"{unit}/{out.name}", "n_files": n_raw,
                               "bytes_raw": b_raw, "bytes_tar": out.stat().st_size, "n_speedbands": n_sb,
                               "sha256": digest}
        n_new += 1
        print(f"packed {unit} {d}: {n_raw} files, {out.stat().st_size / 1e6:.1f} MB, {n_sb} speed-band snapshots")

    if not args.dry_run:
        arch.mkdir(exist_ok=True)
        rows = sorted(manifest.values(), key=lambda r: (r["unit"], r["date"]))
        tmp = man_path.with_name("MANIFEST.csv.partial")
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, man_path)
        (arch / "SHA256SUMS.txt").write_text("".join(f"{r['sha256']}  {r['archive']}\n" for r in rows), encoding="utf-8")
    print(f"archive_raw: {n_new} new archive(s), {n_warn} warning(s), {len(manifest)} in manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
