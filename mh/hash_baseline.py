"""Complete the MD5 baseline for kept files so future moves can dedupe against them."""
from __future__ import annotations

import os
import time

from .db import Ledger
from .stage3 import _lower_priority, md5_file

BATCH = 50


def hash_kept(limit: int = 0) -> dict:
    _lower_priority()
    led = Ledger()
    q = ("SELECT id, src_path, size FROM files "
         "WHERE move_state='kept' AND (md5 IS NULL OR md5='') ORDER BY size")
    if limit:
        q += f" LIMIT {int(limit)}"
    rows = led.conn.execute(q).fetchall()
    done = missing = changed = errors = 0
    t0 = time.time()
    for r in rows:
        path = r["src_path"]
        try:
            if not os.path.isfile(path):
                missing += 1
                continue
            if os.path.getsize(path) != r["size"]:
                changed += 1
                continue
            digest = md5_file(path)
            led.conn.execute(
                "UPDATE files SET md5=?, updated_at=? WHERE id=?", (digest, time.time(), r["id"])
            )
            done += 1
        except OSError as exc:
            led.conn.execute(
                "UPDATE files SET error=?, updated_at=? WHERE id=?",
                (f"baseline: {exc}"[:300], time.time(), r["id"]),
            )
            errors += 1
        if (done + errors) % BATCH == 0:
            led.commit()
            rate = (done + errors) / max(1, time.time() - t0)
            print(f"[baseline] {done} hashed, {changed} changed, {missing} missing, "
                  f"{errors} err, {rate:.1f} files/s", flush=True)
    led.commit()
    led.close()
    return {
        "hashed": done,
        "changed": changed,
        "missing": missing,
        "errors": errors,
        "checked": len(rows),
        "elapsed_s": round(time.time() - t0, 1),
    }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    print(hash_kept(args.limit))
