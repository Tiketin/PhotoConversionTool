#!/usr/bin/env python3
"""
Scan a folder for JPEGs; set EXIF dates from either filesystem Modified time
(default behavior) or from the filename (--from-filename), without changing
the OS Modified timestamp. Also supports printing metadata with --show-meta.

Usage:
  python set_exif_from_mtime.py /path/to/folder
                                [--recursive]
                                [--dry-run]
                                [--show-meta]
                                [--from-filename]
                                [--time-default {zero,keep-mtime,noon}]
                                [--force]

Notes:
- By default, EXIF is written ONLY if DateTimeOriginal is missing.
- Use --force to overwrite existing EXIF date fields.
- Filesystem times (atime/mtime) are restored after writing EXIF.
"""

import argparse
import os
import re
import sys
from datetime import datetime, time
from pathlib import Path

try:
    import piexif
except ImportError:
    print("This script requires the 'piexif' package. Install with: pip install piexif")
    sys.exit(1)

JPEG_EXTS = {".jpg", ".jpeg"}

# --------- EXIF helpers ---------

def ensure_exif_dict(exif_dict=None):
    if not exif_dict or not isinstance(exif_dict, dict):
        return {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    exif_dict.setdefault("0th", {})
    exif_dict.setdefault("Exif", {})
    exif_dict.setdefault("GPS", {})
    exif_dict.setdefault("1st", {})
    exif_dict.setdefault("thumbnail", None)
    return exif_dict

def exif_get_field(exif_dict, ifd, tag):
    try:
        v = exif_dict[ifd].get(tag, b"")
        if isinstance(v, bytes):
            v = v.decode(errors="ignore")
        v = v.strip()
        return v or None
    except Exception:
        return None

def exif_has_datetime_original(exif_dict) -> bool:
    return exif_get_field(exif_dict, "Exif", piexif.ExifIFD.DateTimeOriginal) is not None

def dt_to_exif_string(dt: datetime) -> str:
    # EXIF uses local time, no timezone, YYYY:MM:DD HH:MM:SS
    return dt.strftime("%Y:%m:%d %H:%M:%S")

def set_exif_dates(exif_dict, dt: datetime):
    s = dt_to_exif_string(dt).encode()
    exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = s
    exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = s
    exif_dict["0th"][piexif.ImageIFD.DateTime] = s
    return exif_dict

# --------- Filename parsing ---------

# Try a handful of common patterns:
FILENAME_PATTERNS = [
    # WhatsApp classic: IMG-YYYYMMDD-WA####.jpg, VID-YYYYMMDD-WA####.mp4
    re.compile(r"^(?:IMG|VID)-(?P<date>\d{8})-WA\d+"),
    # Google Camera: PXL_YYYYMMDD_HHMMSS.*
    re.compile(r"^PXL_(?P<date>\d{8})_(?P<time>\d{6})"),
    # Samsung/LG style: YYYYMMDD_HHMMSS.*
    re.compile(r"^(?P<date>\d{8})[_-](?P<time>\d{6})"),
    # iOS export-ish: YYYY-MM-DD HH.MM.SS or YYYY-MM-DD HH-MM-SS
    re.compile(r"^(?P<date>\d{4}[-_]\d{2}[-_]\d{2})[ _T.-](?P<time>\d{2})[.\-_:](?P<min>\d{2})[.\-_:](?P<sec>\d{2})"),
    # Generic leading date: YYYYMMDD.*
    re.compile(r"^(?P<date>\d{8})"),
]

def parse_datetime_from_filename(name: str):
    """
    Try to parse datetime from a filename (without extension).
    Returns (date_str 'YYYYMMDD', time_str 'HHMMSS' or None) or (None, None).
    """
    stem = Path(name).stem
    for pat in FILENAME_PATTERNS:
        m = pat.match(stem)
        if not m:
            continue
        gd = m.groupdict()
        date_raw = gd.get("date")
        if not date_raw:
            continue

        # Normalize date to YYYYMMDD
        if "-" in date_raw or "_" in date_raw:
            parts = re.split(r"[-_]", date_raw)
            if len(parts) == 3:
                y, mo, d = parts
                date_raw = f"{y}{mo}{d}"

        time_raw = None
        if "time" in gd and gd.get("time"):
            time_raw = gd["time"]
        elif all(k in gd for k in ("time", "min", "sec")):
            # Already handled via 'time', 'min', 'sec'
            pass

        # iOS export-ish branch: HH.mm.SS captured into named groups
        if ("time" not in gd) and all(k in gd for k in ("min", "sec")) and gd.get("sec"):
            hh = gd.get("date")  # not correct; handled above only when matched
            # We only get here for the iOS-ish regex; reconstruct time from groups
        if pat.pattern.startswith("^(") is False and "min" in gd and "sec" in gd and gd.get("min") and gd.get("sec"):
            # Build HHMMSS from named groups if present
            hh = gd.get("time") if gd.get("time") else None
            if hh is None:
                hh = gd.get(0)  # fallback; shouldn't happen
            # For our iOS regex, 'time' is the hour group
            hh = gd.get("time") or gd.get(0)
            if gd.get("time"):
                time_raw = f"{gd['time']}{gd['min']}{gd['sec']}"

        # Validate lengths
        if len(date_raw) != 8:
            continue
        if time_raw is not None and len(time_raw) != 6:
            # ignore malformed time
            time_raw = None

        return date_raw, time_raw

    return None, None

def compose_datetime(date_raw: str, time_raw: str | None, time_default: str, mtime: float) -> datetime:
    y = int(date_raw[0:4]); mo = int(date_raw[4:6]); d = int(date_raw[6:8])

    if time_raw:
        hh = int(time_raw[0:2]); mi = int(time_raw[2:4]); ss = int(time_raw[4:6])
        return datetime(year=y, month=mo, day=d, hour=hh, minute=mi, second=ss)

    if time_default == "keep-mtime":
        t = datetime.fromtimestamp(mtime).time()
        return datetime(year=y, month=mo, day=d, hour=t.hour, minute=t.minute, second=t.second)
    elif time_default == "noon":
        return datetime(year=y, month=mo, day=d, hour=12, minute=0, second=0)
    else:  # "zero"
        return datetime(year=y, month=mo, day=d, hour=0, minute=0, second=0)

# --------- Core processing ---------

def process_file(path: Path, *, dry_run: bool, show_meta: bool, from_filename: bool, time_default: str, force: bool) -> str:
    stat = path.stat()
    orig_atime = stat.st_atime
    orig_mtime = stat.st_mtime
    fs_modified_str = datetime.fromtimestamp(orig_mtime).strftime("%Y-%m-%d %H:%M:%S")

    try:
        try:
            exif_dict = piexif.load(str(path))
        except Exception:
            exif_dict = {}
        exif_dict = ensure_exif_dict(exif_dict)

        if show_meta:
            dto = exif_get_field(exif_dict, "Exif", piexif.ExifIFD.DateTimeOriginal)
            dtd = exif_get_field(exif_dict, "Exif", piexif.ExifIFD.DateTimeDigitized)
            dt0 = exif_get_field(exif_dict, "0th", piexif.ImageIFD.DateTime)
            return (f"SHOW-META {path}\n"
                    f"  Filesystem Modified: {fs_modified_str}\n"
                    f"  DateTimeOriginal:   {dto}\n"
                    f"  DateTimeDigitized:  {dtd}\n"
                    f"  DateTime (0th):     {dt0}")

        already_has = exif_has_datetime_original(exif_dict)
        if already_has and not force:
            return f"SKIP (has DateTimeOriginal): {path}"

        # Decide source datetime
        dt_source = None
        if from_filename:
            date_raw, time_raw = parse_datetime_from_filename(path.name)
            if date_raw:
                dt_source = compose_datetime(date_raw, time_raw, time_default, orig_mtime)

        if dt_source is None:
            # fallback to mtime (original script behavior)
            dt_source = datetime.fromtimestamp(orig_mtime)

        if dry_run:
            src = "filename" if from_filename and dt_source else "mtime"
            return f"DRY-RUN would set EXIF from {src} -> {dt_to_exif_string(dt_source)}: {path}"

        # Write EXIF and restore file times
        exif_dict = set_exif_dates(exif_dict, dt_source)
        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, str(path))
        os.utime(path, (orig_atime, orig_mtime))

        src = "filename" if from_filename else "mtime"
        return f"UPDATED EXIF (from {src}: {dt_to_exif_string(dt_source)}) and restored file times: {path}"

    except Exception as e:
        return f"ERROR processing {path}: {e}"

def main():
    ap = argparse.ArgumentParser(description="Set or show EXIF dates for JPEGs from mtime or filename (WhatsApp/camera styles).")
    ap.add_argument("folder", type=Path, help="Folder to scan")
    ap.add_argument("--recursive", "-r", action="store_true", help="Recurse into subfolders")
    ap.add_argument("--dry-run", action="store_true", help="Show actions without modifying files")
    ap.add_argument("--show-meta", action="store_true", help="Show EXIF dates and filesystem Modified time")
    ap.add_argument("--from-filename", action="store_true", help="Prefer parsing date/time from filename (e.g., IMG-YYYYMMDD-WA####, PXL_YYYYMMDD_HHMMSS)")
    ap.add_argument("--time-default", choices=["zero", "keep-mtime", "noon"], default="zero",
                    help="If only a date is found in the filename, what time to set (default: zero=00:00:00)")
    ap.add_argument("--force", action="store_true", help="Overwrite EXIF dates even if already present")
    args = ap.parse_args()

    if not args.folder.exists() or not args.folder.is_dir():
        print(f"Not a directory: {args.folder}")
        sys.exit(2)

    if args.recursive:
        paths = [p for p in args.folder.rglob("*") if p.is_file() and p.suffix.lower() in JPEG_EXTS]
    else:
        paths = [p for p in args.folder.iterdir() if p.is_file() and p.suffix.lower() in JPEG_EXTS]

    if not paths:
        print("No JPEGs found.")
        return

    for p in sorted(paths):
        msg = process_file(
            p,
            dry_run=args.dry_run,
            show_meta=args.show_meta,
            from_filename=args.from_filename,
            time_default=args.time_default,
            force=args.force,
        )
        print(msg)

if __name__ == "__main__":
    main()
