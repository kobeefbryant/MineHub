"""Enumerate QQ media caches into the ledger."""
from __future__ import annotations

import os
import time
from pathlib import Path

from .config import IMAGE_EXTS, QQ_ACCOUNTS, VIDEO_EXTS
from .db import Ledger


def iter_media(include_thumb: bool = False):
    for acct_root in QQ_ACCOUNTS:
        if not acct_root.is_dir():
            continue
        account = acct_root.parent.parent.name
        for kind, exts in (("image", IMAGE_EXTS), ("video", VIDEO_EXTS)):
            base = acct_root / ("Pic" if kind == "image" else "Video")
            if not base.is_dir():
                continue
            for dirpath, _dirnames, filenames in os.walk(base):
                rel = Path(dirpath).relative_to(base)
                parts = rel.parts
                is_thumb = len(parts) > 1 and parts[1].lower() == "thumb"
                if is_thumb and not include_thumb:
                    continue
                for name in filenames:
                    if Path(name).suffix.lower() not in exts:
                        continue
                    p = Path(dirpath) / name
                    try:
                        st = p.stat()
                    except OSError:
                        continue
                    if st.st_size == 0:
                        continue
                    yield str(p), kind, account, is_thumb, st.st_size, st.st_mtime


def scan(include_thumb: bool = False, ledger: Ledger | None = None) -> int:
    led = ledger or Ledger()
    started = time.time()
    batch: list[tuple] = []
    total = 0
    for row in iter_media(include_thumb):
        batch.append(row)
        if len(batch) >= 2000:
            led.upsert_many(batch)
            total += len(batch)
            batch.clear()
            print(f"  scanned {total} ...", flush=True)
    if batch:
        led.upsert_many(batch)
        total += len(batch)
    led.commit()
    print(f"scan done: {total} new/updated rows in {time.time() - started:.1f}s")
    if ledger is None:
        led.close()
    return total


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--include-thumb", action="store_true")
    args = ap.parse_args()
    scan(include_thumb=args.include_thumb)