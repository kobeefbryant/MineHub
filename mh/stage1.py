"""Stage 1: batched SigLIP2 prefilter over all originals."""
from __future__ import annotations

import sys
import time
from pathlib import Path

from .config import NSFW_MODEL
from .db import Ledger
from .prefilter import SiglipNSFW


def _lower_priority() -> None:
    if sys.platform == "win32":
        try:
            import psutil

            psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        except Exception:
            pass


def run_stage1(batch_size: int = 64, limit: int = 0, include_thumb: bool = False, quiet: bool = False) -> dict:
    from PIL import Image

    _lower_priority()
    led = Ledger()
    clf = SiglipNSFW(NSFW_MODEL)
    run_id = led.start_run("stage1", {"batch": batch_size, "limit": limit})
    processed = errors = 0
    t0 = time.perf_counter()
    last_report = 0.0
    while True:
        take = batch_size if not limit else min(batch_size, limit - processed)
        if take <= 0:
            break
        q = "SELECT * FROM files WHERE stage1_label IS NULL AND kind='image'"
        if not include_thumb:
            q += " AND is_thumb=0"
        q += " ORDER BY id LIMIT ?"
        rows = led.conn.execute(q, (take,)).fetchall()
        if not rows:
            break
        images, valid = [], []
        for row in rows:
            try:
                with Image.open(row["src_path"]) as im:
                    im.load()
                    images.append(im.convert("RGB"))
                valid.append(row)
            except Exception as exc:  # noqa: BLE001
                led.conn.execute(
                    "UPDATE files SET stage1_label='UNREADABLE', stage1_src='error', error=?, stage1_at=? WHERE id=?",
                    (str(exc)[:300], time.time(), row["id"]),
                )
                errors += 1
        if images:
            results = clf.classify_batch(images)
            for row, res in zip(valid, results):
                led.set_stage1(row["src_path"], res.label, res.scores, "siglip")
            processed += len(results)
        led.commit()
        if not quiet and time.perf_counter() - last_report > 10:
            elapsed = time.perf_counter() - t0
            rate = processed / elapsed if elapsed else 0
            print(f"[stage1] {processed} done, {errors} errors, {rate:.1f} img/s", flush=True)
            last_report = time.perf_counter()
    led.finish_run(run_id, processed, errors)
    elapsed = time.perf_counter() - t0
    stats = led.stats()
    led.close()
    return {"processed": processed, "errors": errors, "elapsed_s": round(elapsed, 1), "stats": stats}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--include-thumb", action="store_true")
    args = ap.parse_args()
    out = run_stage1(args.batch, args.limit, args.include_thumb)
    print(out["processed"], "processed in", out["elapsed_s"], "s; errors", out["errors"])