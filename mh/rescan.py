"""Manually triggered incremental QQ rescan for new originals and thumbnails."""
from __future__ import annotations

import json
import time
from typing import Any

from .db import Ledger


def _counts() -> dict[str, int]:
    led = Ledger()
    files = led.conn.execute(
        """SELECT
             COUNT(*) total,
             SUM(CASE WHEN stage1_label IS NULL AND kind='image' THEN 1 ELSE 0 END) stage1_pending,
             SUM(CASE WHEN stage2_json IS NULL AND final_json IS NULL AND is_thumb=0
                       AND (kind='video' OR stage1_label IN
                            ('Normal','Enticing or Sensual','Pornography','Anime Picture','Hentai'))
                      THEN 1 ELSE 0 END) stage2_pending,
             SUM(CASE WHEN stage2_b IS NULL AND final_json IS NULL AND stage2_json IS NOT NULL
                       AND is_thumb=0
                       AND (json_extract(stage2_json,'$.nsfw_level')='explicit'
                            OR json_extract(stage2_json,'$.confidence') < 0.85
                            OR json_extract(stage2_json,'$.category')='review')
                      THEN 1 ELSE 0 END) stage2b_pending,
             SUM(CASE WHEN final_json IS NULL AND stage2_json IS NOT NULL AND is_thumb=0
                      THEN 1 ELSE 0 END) finalize_pending,
             SUM(CASE WHEN final_json IS NOT NULL AND move_state='pending' AND is_thumb=0
                      THEN 1 ELSE 0 END) move_pending
           FROM files"""
    ).fetchone()
    out = {k: int(files[k] or 0) for k in files.keys()}
    for state in ("pending", "candidate", "exact", "ready_move", "error", "moved"):
        out[f"thumb_{state}"] = int(
            led.conn.execute(
                "SELECT COUNT(*) FROM thumb_audit WHERE state=?", (state,)
            ).fetchone()[0]
        )
    led.close()
    return out


def _emit(tag: str, value: Any) -> None:
    print(f"[rescan] {tag} {json.dumps(value, ensure_ascii=False)}", flush=True)


def run(limit: int = 0, dry_run: bool = False, slots: int = 4, workers: int = 4) -> dict:
    from . import thumb_audit
    from .scanner import scan
    from .stage1 import run_stage1
    from .stage2 import finalize, run_a, run_b
    from .stage3 import move_all

    t0 = time.time()
    before = _counts()
    _emit("before", before)

    scan(include_thumb=False)
    after_scan = _counts()
    _emit("scan", {
        "new_originals": after_scan["stage1_pending"] - before["stage1_pending"],
        "total_originals": after_scan["total"],
    })

    if after_scan["stage1_pending"]:
        _emit("stage1", run_stage1(64, limit, include_thumb=False))
    counts = _counts()
    if counts["stage2_pending"]:
        _emit("stage2_a", run_a(slots, 16384, workers, limit))
    counts = _counts()
    if counts["stage2b_pending"]:
        _emit("stage2_b", run_b(slots, 16384, workers, limit))
    counts = _counts()
    if counts["finalize_pending"]:
        _emit("finalize", {"rows": finalize()})
    counts = _counts()
    move_result = {"moved": 0}
    if counts["move_pending"]:
        move_result = move_all(limit, dry_run)
        _emit("move", move_result)

    thumbs = thumb_audit.incremental(slots=slots, workers=workers, limit=limit, dry_run=dry_run)
    after = _counts()
    result = {
        "elapsed_s": round(time.time() - t0, 1),
        "new_originals": after_scan["stage1_pending"] - before["stage1_pending"],
        "moved_originals": move_result.get("moved", 0),
        "thumb": thumbs,
        "after": after,
    }
    _emit("done", result)
    return result
