"""Import images that exist only as QQ thumbnails (no Ori counterpart)."""
from __future__ import annotations

import os
import re
import time
from collections import defaultdict
from pathlib import Path

from .config import IMAGE_EXTS, QQ_ACCOUNTS
from .db import Ledger

STEM_RE = re.compile(r"_\d+$")


def collect_thumbs() -> dict[str, list[tuple[str, str, int, float]]]:
    """stem -> [(path, account, size, mtime)] across all accounts."""
    groups: dict[str, list[tuple[str, str, int, float]]] = defaultdict(list)
    for acct_root in QQ_ACCOUNTS:
        base = acct_root / "Pic"
        if not base.is_dir():
            continue
        account = acct_root.parent.parent.name
        for dirpath, _dn, filenames in os.walk(base):
            rel = Path(dirpath).relative_to(base).parts
            if len(rel) < 2 or rel[1].lower() != "thumb":
                continue
            for name in filenames:
                if Path(name).suffix.lower() not in IMAGE_EXTS:
                    continue
                p = Path(dirpath) / name
                try:
                    st = p.stat()
                except OSError:
                    continue
                if st.st_size == 0:
                    continue
                stem = STEM_RE.sub("", p.stem.lower())
                groups[stem].append((str(p), account, st.st_size, st.st_mtime))
    return groups


def import_thumbs(apply: bool = True) -> dict:
    led = Ledger()
    ori_stems = set()
    existing = set()
    for r in led.conn.execute("SELECT src_path FROM files WHERE kind='image'"):
        p = r["src_path"]
        existing.add(p)
        if "\\ori\\" in p.lower() or "/ori/" in p.lower():
            ori_stems.add(Path(p).stem.lower())
    groups = collect_thumbs()
    picked = []
    for stem, files in groups.items():
        if stem in ori_stems:
            continue
        files.sort(key=lambda t: t[2], reverse=True)
        path, account, size, mtime = files[0]
        if path in existing:
            continue
        picked.append((path, account, size, mtime))
    picked.sort()
    total = sum(r[2] for r in picked)
    print(f"thumb stems={len(groups)}, ori stems={len(ori_stems)}, to import={len(picked)}, "
          f"size={total / 1e9:.2f} GB")
    if apply and picked:
        now = time.time()
        led.conn.executemany(
            """INSERT OR IGNORE INTO files (src_path, kind, account, is_thumb, origin, size, mtime, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [(p, "image", acct, 0, "thumb_only", size, mtime, now, now) for p, acct, size, mtime in picked],
        )
        led.commit()
    print("imported:", led.conn.execute("SELECT COUNT(*) FROM files WHERE origin='thumb_only'").fetchone()[0])
    led.close()
    return {"picked": len(picked), "bytes": total, "apply": apply}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    print(import_thumbs(not args.dry_run))