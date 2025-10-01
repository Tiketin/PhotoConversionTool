import os
import re
import sys
import datetime
import mimetypes
import piexif
import subprocess

# Folder to scan
ROOT_DIR = r"C:\siirto"

# Dry run flag
DRY_RUN = "--dry-run" in sys.argv
# For converted .avi files. Normally originals are left untouched, but can be deleted with this flag
DELETE_ORIGINALS = "--delete-originals" in sys.argv

# Stats counters
stats = {
    "scanned": 0,
    "photos_changed": 0,
    "videos_changed": 0,
    "skipped": 0,
    "errors": 0
}

def get_best_file_time(path):
    created = datetime.datetime.fromtimestamp(os.path.getctime(path))
    modified = datetime.datetime.fromtimestamp(os.path.getmtime(path))
    best_time = min(created, modified)

    # Regex: look for \YYYY\ in the full path
    match = re.search(r"[\\/](\d{4})(?=[\\/])", path)
    if match:
        folder_year = int(match.group(1))
        # If both times are newer than folder year → fallback
        if best_time.year > folder_year:
            best_time = datetime.datetime(folder_year, 12, 31, 23, 59, 59)

    return best_time

def has_exif_datetime(path):
    try:
        exif_dict = piexif.load(path)
        if piexif.ExifIFD.DateTimeOriginal in exif_dict["Exif"]:
            return True
    except Exception:
        return False
    return False

def set_exif_datetime(path, dt):
    formatted = dt.strftime("%Y:%m:%d %H:%M:%S")
    if DRY_RUN:
        print(f"[DRY-RUN][PHOTO] Would set DateTimeOriginal for {path} -> {formatted}")
        stats["photos_changed"] += 1
        return
    exif_dict = piexif.load(path)
    exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = formatted.encode()
    exif_bytes = piexif.dump(exif_dict)
    piexif.insert(exif_bytes, path)
    print(f"[PHOTO] Set DateTimeOriginal for {path} -> {formatted}")
    stats["photos_changed"] += 1

def create_xmp_sidecar(path, dt):
    """Write XMP sidecar with CreateDate for formats without EXIF."""
    sidecar_path = path + ".xmp"
    formatted = dt.strftime("%Y-%m-%dT%H:%M:%S")

    xmp_template = f"""<?xpacket begin='' id='W5M0MpCehiHzreSzNTczkc9d'?>
<x:xmpmeta xmlns:x='adobe:ns:meta/' x:xmptk='Python-Sidecar-Generator'>
 <rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
  <rdf:Description rdf:about=''
    xmlns:xmp='http://ns.adobe.com/xap/1.0/'>
   <xmp:CreateDate>{formatted}</xmp:CreateDate>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end='w'?>"""

    if DRY_RUN:
        print(f"[DRY-RUN][SIDECAR] Would create {sidecar_path} -> {formatted}")
        stats["photos_changed"] += 1
        return

    try:
        with open(sidecar_path, "w", encoding="utf-8") as f:
            f.write(xmp_template)
        print(f"[SIDECAR] Created {sidecar_path} -> {formatted}")
        stats["photos_changed"] += 1
    except Exception as e:
        print(f"[ERROR] Failed to write sidecar for {path}: {e}")
        stats["errors"] += 1

def process_photo(path):
    ext = os.path.splitext(path)[1].lower()
    if ext not in [".jpg", ".jpeg", ".tif", ".tiff"]:
        print(f"[UNSUPPORTED][PHOTO] {path}")
        stats["skipped"] += 1
        return

    if not has_exif_datetime(path):
        chosen_dt = get_best_file_time(path)
        if DRY_RUN:
            print(f"[DRY-RUN][PHOTO] Would set DateTimeOriginal for {path} -> {chosen_dt}")
            stats["photos_changed"] += 1
        else:
            try:
                set_exif_datetime(path, chosen_dt)
            except Exception as e:
                print(f"[ERROR] Failed to set EXIF for {path}: {e}")
                stats["errors"] += 1
    else:
        stats["skipped"] += 1

def process_video(path):
    chosen_dt = get_best_file_time(path)
    formatted = chosen_dt.strftime("%Y-%m-%dT%H:%M:%S")

    root, ext = os.path.splitext(path)
    tmpfile = f"{root}.tmp{ext}"

    # Probe streams before doing anything
    probe = subprocess.run(
        ["ffmpeg", "-i", path],
        capture_output=True, text=True
    )

    if "Stream #" not in probe.stderr:
        print(f"[BROKEN][VIDEO] {path} (no valid streams)")
        stats["skipped"] += 1
        return

    if DRY_RUN:
        print(f"[DRY-RUN][VIDEO] Would set creation_time for {path} -> {formatted}")
        stats["videos_changed"] += 1
        return

    try:
        result = subprocess.run([
            "ffmpeg", "-i", path, "-metadata", f"creation_time={formatted}",
            "-codec", "copy", tmpfile, "-y"
        ], capture_output=True, text=True)

        if result.returncode == 0:
            os.replace(tmpfile, path)
            print(f"[VIDEO] Set creation_time for {path} -> {formatted}")
            stats["videos_changed"] += 1
        else:
            print(f"[ERROR] Failed for {path}: {result.stderr.splitlines()[-5:]}")
            stats["errors"] += 1
            if os.path.exists(tmpfile):
                os.remove(tmpfile)

    except Exception as e:
        print(f"[EXCEPTION] {path}: {e}")
        stats["errors"] += 1
        if os.path.exists(tmpfile):
            os.remove(tmpfile)

def process_avi(path):
    """
    Convert AVI to standards-compliant MP4 (yuv420p, H.264, AAC).
    Keeps the function signature the same as before (only path).
    """

    chosen_dt = get_best_file_time(path)
    formatted = chosen_dt.strftime("%Y-%m-%dT%H:%M:%S")

    output_file = os.path.splitext(path)[0] + ".mp4"

    cmd = [
        "ffmpeg", "-i", path,
        "-c:v", "libx264", "-crf", "20", "-preset", "slow",
        "-vf", "format=yuv420p",  # ensure compatible chroma format
        "-c:a", "aac", "-b:a", "192k", "-ac", "2",
        "-movflags", "+faststart",
        "-metadata", f"creation_time={formatted}",
        output_file, "-y"
    ]

    if DRY_RUN:
        print(f"[DRY RUN] Would convert AVI: {path} -> {output_file} (date={formatted})")
        return True

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[ERROR] Failed to convert {path}: {result.stderr.strip()}")
            return False
        else:
            print(f"[OK] Converted {path} -> {output_file} (date={formatted})")
            if DELETE_ORIGINALS:
                try:
                    os.remove(path)
                    print(f"[CLEANUP] Deleted original AVI: {path}")
                except Exception as e:
                    print(f"[WARN] Could not delete {path}: {e}")
            return True
    except Exception as e:
        print(f"[ERROR] Exception while converting {path}: {e}")
        return False

def main():
    for root, dirs, files in os.walk(ROOT_DIR):
        for file in files:
            path = os.path.join(root, file)
            ext = os.path.splitext(path)[1].lower()
            stats["scanned"] += 1

            if ext in [".jpg", ".jpeg", ".tif", ".tiff"]:
                process_photo(path)
            elif ext in [".png", ".bmp", ".gif", ".webp"]:
                chosen_dt = get_best_file_time(path)
                create_xmp_sidecar(path, chosen_dt)
            elif ext == ".avi":
                process_avi(path)
            elif ext in [".mp4", ".mov", ".m4v", ".3gp", ".3g2"]:
                process_video(path)
            else:
                print(f"[SKIP] {path} (unsupported format)")
                stats["skipped"] += 1

    # Summary
    print("\n=== SUMMARY ===")
    print(f"Files scanned:     {stats['scanned']}")
    print(f"Photos updated:    {stats['photos_changed']}")
    print(f"Videos updated:    {stats['videos_changed']}")
    print(f"Skipped (had date or not supported): {stats['skipped']}")
    print(f"Errors:            {stats['errors']}")
    print(f"Mode:              {'DRY-RUN (no changes made)' if DRY_RUN else 'APPLY (files modified)'}")

if __name__ == "__main__":
    main()
