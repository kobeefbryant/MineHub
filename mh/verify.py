"""Re-check SigLIP-only explicit items with the VLM before/after moving."""
from __future__ import annotations

import json
import queue
import sys
import threading
import time
from pathlib import Path

from .config import VLM_PROMPT
from .db import Ledger
from .serve import LlamaServer
from .stage3 import _unique
from .vlm import VLM

SELECT = """
SELECT * FROM files
WHERE final_json IS NOT NULL
  AND json_extract(final_json,'$.source')='siglip'
  AND json_extract(final_json,'$.nsfw_level')='explicit'
  AND move_state IN ('moved','pending')
ORDER BY (move_state='moved') DESC, size DESC
LIMIT ?
"""


def _restore(led: Ledger, row, final: dict, target: Path) -> None:
    src = Path(row["src_path"])
    src.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        src = _unique(src)
    try:
        import shutil

        shutil.move(str(target), str(src))
        led.conn.execute(
            "UPDATE files SET final_json=?, category=?, needs_review=0, move_state='kept', "
            "target_path=NULL, src_path=?, updated_at=? WHERE id=?",
            (json.dumps(final, ensure_ascii=False), final["category"], str(src), time.time(), row["id"]),
        )
    except Exception as exc:  # noqa: BLE001
        led.conn.execute("UPDATE files SET error=?, updated_at=? WHERE id=?", (str(exc)[:300], time.time(), row["id"]))


def verify_siglip_explicit(limit: int = 0, slots: int = 4, ctx: int = 16384, workers: int = 4) -> dict:
    led = Ledger()
    rows = led.conn.execute(SELECT, (limit or 999999,)).fetchall()
    if not rows:
        led.close()
        return {"checked": 0, "restored": 0, "kept_explicit": 0}
    print(f"[verify] {len(rows)} siglip-only explicit rows", flush=True)
    work: queue.Queue = queue.Queue(maxsize=workers * 2)
    results: queue.Queue = queue.Queue()
    stats = {"checked": 0, "restored": 0, "kept_explicit": 0, "errors": 0}

    def worker(port: int) -> None:
        vlm = VLM("nsfw", port=port)
        while True:
            row = work.get()
            if row is None:
                return
            path = row["target_path"] if row["move_state"] == "moved" else row["src_path"]
            try:
                if not path or not Path(path).exists():
                    results.put((row, None, "file missing"))
                else:
                    v, _ = vlm.complete([path], prompt=VLM_PROMPT, max_tokens=320, max_side=1024)
                    results.put((row, v, None))
            except Exception as exc:  # noqa: BLE001
                results.put((row, None, str(exc)[:300]))

    with LlamaServer("nsfw", slots=slots, ctx=ctx) as srv:
        threads = [threading.Thread(target=worker, args=(srv.port,), daemon=True) for _ in range(workers)]
        for t in threads:
            t.start()
        for r in rows:
            work.put(r)
        for _ in threads:
            work.put(None)
        pending = len(rows)
        while pending:
            row, verdict, err = results.get()
            pending -= 1
            stats["checked"] += 1
            if err:
                stats["errors"] += 1
                led.conn.execute("UPDATE files SET error=?, updated_at=? WHERE id=?", (err, time.time(), row["id"]))
            else:
                lvl = verdict.get("nsfw_level", "explicit")
                ct = verdict.get("content_type", "anime")
                tags = list(dict.fromkeys([t.lower() for t in (verdict.get("tags") or [])] + ["verified"]))[:10]
                if lvl == "safe":
                    final = {
                        "category": "anime" if ct in ("anime", "illustration") else "daily",
                        "nsfw_level": "safe",
                        "content_type": ct,
                        "confidence": verdict.get("confidence", 0.9),
                        "tags": tags + ["verified_safe"],
                        "main_subject": verdict.get("main_subject", ""),
                        "scene": verdict.get("scene", ""),
                        "clothing": verdict.get("clothing", "unknown"),
                        "needs_review": False,
                        "source": "siglip+A",
                    }
                    if row["move_state"] == "moved" and row["target_path"]:
                        _restore(led, row, final, Path(row["target_path"]))
                        stats["restored"] += 1
                    else:
                        led.conn.execute(
                            "UPDATE files SET final_json=?, category=?, needs_review=0, move_state='kept', updated_at=? WHERE id=?",
                            (json.dumps(final, ensure_ascii=False), final["category"], time.time(), row["id"]),
                        )
                else:
                    cat = "adult" if lvl == "explicit" else "sexy"
                    if ct not in ("real_photo",):
                        cat = "anime" if ct in ("anime", "illustration") else cat
                    final = {
                        "category": cat,
                        "nsfw_level": lvl,
                        "content_type": ct,
                        "confidence": verdict.get("confidence", 0.9),
                        "tags": tags,
                        "main_subject": verdict.get("main_subject", ""),
                        "scene": verdict.get("scene", ""),
                        "clothing": verdict.get("clothing", "unknown"),
                        "needs_review": False,
                        "source": "siglip+A",
                    }
                    led.conn.execute(
                        "UPDATE files SET final_json=?, category=?, needs_review=0, updated_at=? WHERE id=?",
                        (json.dumps(final, ensure_ascii=False), cat, time.time(), row["id"]),
                    )
                    stats["kept_explicit"] += 1
            led.commit()
            if stats["checked"] % 50 == 0:
                print(f"[verify] {stats['checked']}/{len(rows)} {stats}", flush=True)
        for t in threads:
            t.join(timeout=10)
    led.close()
    print(f"[verify] done {stats}", flush=True)
    return stats


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    print(verify_siglip_explicit(args.limit))