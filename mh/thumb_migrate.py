"""Move QQ thumbnails belonging to already-moved NSFW files out of the QQ cache."""
from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import time
from pathlib import Path

from .config import DATA, MEDIA_ROOT, QQ_ACCOUNTS
from .db import Ledger
from .stage3 import _copy_hash, _lower_priority, _same_volume, TMP_SUFFIX, _unique

THUMB_ROOT = MEDIA_ROOT / "qq_thumbs"
MD5_RE = re.compile(r"^([0-9a-fA-F]{32})(?:_\d+)?$")


def _account_name(nt_data: Path) -> str:
    return nt_data.parts[-3] if len(nt_data.parts) >= 3 else nt_data.name


def nsfw_maps() -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str]]]:
    """Return both content-MD5 and QQ filename-stem indexes for moved NSFW rows.

    QQ names media with its own hash, which is not always the file's byte MD5
    (GIFs and some JPEG/video files differ), so matching only `files.md5` leaves
    thumbnails behind.
    """
    led = Ledger()
    rows = led.conn.execute(
        """SELECT src_path, md5, category, json_extract(final_json,'$.nsfw_level')
           FROM files WHERE move_state='moved'"""
    ).fetchall()
    led.close()
    by_md5: dict[str, tuple[str, str]] = {}
    by_stem: dict[str, tuple[str, str]] = {}
    for src, md5, cat, lvl in rows:
        val = (cat or "", lvl or "")
        if md5:
            by_md5.setdefault(md5.lower(), val)
        by_stem.setdefault(Path(src).stem.lower(), val)
    return by_md5, by_stem


def move_nsfw_thumbs(dry_run: bool = False, limit: int = 0) -> dict:
    _lower_priority()
    by_md5, by_stem = nsfw_maps()
    moved = skipped = errors = 0
    moved_bytes = 0
    t0 = time.time()
    log_path = DATA / "thumb_moves.csv"
    log = None
    writer = None
    if not dry_run:
        THUMB_ROOT.mkdir(parents=True, exist_ok=True)
        new_log = not log_path.exists()
        log = open(log_path, "a", newline="", encoding="utf-8")
        writer = csv.writer(log)
        if new_log:
            writer.writerow(["ts", "src", "dst", "md5", "category", "level", "account", "kind", "size"])

    for nt_data in QQ_ACCOUNTS:
        if not nt_data.is_dir():
            continue
        account = _account_name(nt_data)
        for kind in ("Pic", "Video"):
            base = nt_data / kind
            if not base.is_dir():
                continue
            for month in base.iterdir():
                thumb_dir = month / "Thumb"
                if not month.is_dir() or not thumb_dir.is_dir():
                    continue
                for entry in thumb_dir.iterdir():
                    if limit and (moved + skipped + errors) >= limit:
                        break
                    if not entry.is_file():
                        continue
                    m = MD5_RE.match(entry.stem)
                    key = m.group(1).lower() if m else re.sub(r"_\d+$", "", entry.stem).lower()
                    hit = by_md5.get(key) or by_stem.get(key)
                    if not hit:
                        continue
                    try:
                        size = entry.stat().st_size
                    except OSError:
                        errors += 1
                        continue
                    dst = THUMB_ROOT / account / kind / month.name / "Thumb" / entry.name
                    if dry_run:
                        moved += 1
                        moved_bytes += size
                        continue
                    try:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        if dst.exists():
                            if dst.stat().st_size == size:
                                os.remove(entry)
                                skipped += 1
                                continue
                            dst = _unique(dst)
                        tmp = dst.with_name(dst.name + TMP_SUFFIX)
                        if _same_volume(str(entry), dst.parent):
                            os.replace(entry, dst)
                        else:
                            _copy_hash(str(entry), tmp)
                            if tmp.stat().st_size != size:
                                raise RuntimeError("size verify failed")
                            os.replace(tmp, dst)
                            os.remove(entry)
                        if dst.stat().st_size != size:
                            raise RuntimeError("destination size mismatch")
                        cat, lvl = hit
                        writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), str(entry), str(dst),
                                         key, cat, lvl, account, kind, size])
                        moved += 1
                        moved_bytes += size
                    except OSError as exc:
                        errors += 1
                        print(f"[thumbs] failed {entry}: {exc}", flush=True)
                        try:
                            tmp = dst.with_name(dst.name + TMP_SUFFIX)
                            if tmp.exists():
                                tmp.unlink()
                        except OSError:
                            pass
                    if (moved + skipped + errors) % 200 == 0:
                        if log is not None:
                            log.flush()
                        print(f"[thumbs] {moved} moved, {skipped} already, {errors} err, "
                              f"{moved_bytes / 1024**2:.0f} MB", flush=True)

    if log is not None:
        log.flush()
        log.close()
    return {
        "moved": moved,
        "already": skipped,
        "errors": errors,
        "bytes": moved_bytes,
        "elapsed_s": round(time.time() - t0, 1),
        "dry_run": dry_run,
        "destination": str(THUMB_ROOT),
    }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    print(json.dumps(move_nsfw_thumbs(args.dry_run, args.limit), ensure_ascii=False, indent=1))
