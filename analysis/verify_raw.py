"""verify_raw.py - SLDS 42.510 project 1.3: check (and unpack) raw-data archives downloaded from Google Drive.

Works on Windows, macOS and Linux; standard library only (Python 3.9+).

    python analysis/verify_raw.py <download folder>                 # check every .tar against SHA256SUMS.txt
    python analysis/verify_raw.py <download folder> --extract .     # then unpack into the project folder

<download folder> is a copy of the Drive folder SLDS_1.3_raw (or part of it) with its layout kept:
SHA256SUMS.txt at the top, tars under data_raw/, data_raw_expressway/, ... Tars you did not download are
skipped. Unpacking recreates data_raw/speedbands/<date>/... etc. and never overwrites an existing file.
AI disclosure: drafted with Claude (Anthropic) on 24 Oct 2026; log in AI_USE.md.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tarfile
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check and unpack SLDS 1.3 raw-data archives")
    ap.add_argument("folder", type=Path, help="download folder (holds SHA256SUMS.txt)")
    ap.add_argument("--extract", type=Path, metavar="PROJECT", help="unpack checked tars into this folder")
    args = ap.parse_args(argv)
    sums = args.folder / "SHA256SUMS.txt"
    if not sums.exists():
        print(f"{sums} not found: download SHA256SUMS.txt from the top of the Drive folder too")
        return 2
    bad, ok = 0, []
    for line in sums.read_text(encoding="utf-8").splitlines():
        digest, rel = line.split(None, 1)
        p = args.folder / rel.strip()
        if not p.exists():
            continue
        if sha256(p) == digest:
            ok.append(p)
            print(f"OK   {rel}")
        else:
            bad += 1
            print(f"BAD  {rel}: checksum differs; download it again")
    if not ok and not bad:
        print("No archives listed in SHA256SUMS.txt were found in the folder")
        return 2
    if args.extract and not bad:
        dest = args.extract.resolve()
        for p in ok:
            with tarfile.open(p) as tar:
                for m in tar.getmembers():
                    target = (dest / m.name).resolve()
                    if not m.isfile() or dest not in target.parents:
                        raise SystemExit(f"unexpected member {m.name} in {p.name}")
                    if target.exists():
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(m) as src, open(target, "wb") as out:
                        out.write(src.read())
            print(f"unpacked {p.name} into {dest}")
    print(f"RESULT: {'OK' if not bad else 'FAILED'} ({len(ok)} archive(s) checked, {bad} bad)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
