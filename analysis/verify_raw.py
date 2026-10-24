"""verify_raw.py - SLDS 42.510 project 1.3: check (and unpack) raw data downloaded from Google Drive.

Works on Windows, macOS and Linux; standard library only (Python 3.9+).

    python analysis/verify_raw.py <download folder>                 # check every file against SHA256SUMS.txt
    python analysis/verify_raw.py <download folder> --extract .     # then put it into the project folder

<download folder> is a copy of the Drive folder SLDS_1.3_raw (or part of it) with its layout kept:
SHA256SUMS.txt at the top, then lta_network/, lta_expressway/, nea_rainfall/, ... Files you did not
download are skipped. --extract never overwrites an existing file. It puts:
    lta_*/ *.tar                -> unpacked: data_raw/... and data_raw_expressway/...
    nea_rainfall/, calendar/    -> data_raw/nea_rainfall/, data_raw/calendar/
    lta_fetch_logs/network_*    -> data_raw/log_*.csv;  expressway_* -> data_raw_expressway/log_*.csv
AI disclosure: drafted with Claude (Anthropic) on 24 Oct 2026; log in AI_USE.md.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tarfile
from pathlib import Path

LOG_PREFIX = {"network_": "data_raw", "expressway_": "data_raw_expressway"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def place(rel: str, src: Path, dest: Path) -> int:
    """Put one checked file into the project. Returns the number of files written."""
    folder, name = rel.split("/", 1)
    if name.endswith(".tar"):
        n = 0
        with tarfile.open(src) as tar:
            for m in tar.getmembers():
                target = (dest / m.name).resolve()
                if not m.isfile() or dest not in target.parents:
                    raise SystemExit(f"unexpected member {m.name} in {src.name}")
                if target.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(m) as f, open(target, "wb") as out:
                    shutil.copyfileobj(f, out)
                n += 1
        return n
    if folder in ("nea_rainfall", "calendar"):
        target = dest / "data_raw" / folder / name
    elif folder == "lta_fetch_logs":
        prefix = next((p for p in LOG_PREFIX if name.startswith(p)), None)
        if prefix is None:
            return 0
        target = dest / LOG_PREFIX[prefix] / name[len(prefix):]
    else:
        return 0
    if target.exists():
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, target)
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check and unpack SLDS 1.3 raw data downloaded from Drive")
    ap.add_argument("folder", type=Path, help="download folder (holds SHA256SUMS.txt)")
    ap.add_argument("--extract", type=Path, metavar="PROJECT", help="put checked files into this project folder")
    args = ap.parse_args(argv)
    sums = args.folder / "SHA256SUMS.txt"
    if not sums.exists():
        print(f"{sums} not found: download SHA256SUMS.txt from the top of the Drive folder too")
        return 2
    bad, ok = 0, []
    for line in sums.read_text(encoding="utf-8").splitlines():
        digest, rel = line.split(None, 1)
        rel = rel.strip()
        p = args.folder / rel
        if not p.exists():
            continue
        if sha256(p) == digest:
            ok.append((rel, p))
            print(f"OK   {rel}")
        else:
            bad += 1
            print(f"BAD  {rel}: checksum differs; download it again (with the current SHA256SUMS.txt)")
    if not ok and not bad:
        print("No file listed in SHA256SUMS.txt was found in the folder")
        return 2
    if args.extract and not bad:
        dest = args.extract.resolve()
        n = sum(place(rel, p, dest) for rel, p in ok)
        print(f"extract: {n} file(s) written into {dest} (existing files kept)")
    print(f"RESULT: {'OK' if not bad else 'FAILED'} ({len(ok)} file(s) checked, {bad} bad)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
