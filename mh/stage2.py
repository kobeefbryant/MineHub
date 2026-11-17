"""Stage 2: Qwen3-VL tagging with A-primary / B-arbitration."""
from __future__ import annotations

import json
import queue
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed  # noqa: F401

from .config import VLM_PROMPT, VLM_VIDEO_PROMPT
from .db import Ledger
from .frames import cleanup_frames, extract_frames
from .serve import LlamaServer
from .vlm import VLM

SELECT_A = """
SELECT * FROM files
WHERE stage2_json IS NULL
  AND final_json IS NULL
  AND is_thumb=0
  AND (kind='video'
       OR (kind='image' AND lower(src_path) LIKE '%.gif')
       OR stage1_label IN ('Enticing or Sensual','Pornography','Anime Picture','Hentai')
       OR (stage1_label='Normal' AND max(
             COALESCE(json_extract(stage1_scores,'$.Pornography'),0),
             COALESCE(json_extract(stage1_scores,'$.Hentai'),0),
             COALESCE(json_extract(stage1_scores,'$.Enticing or Sensual'),0)) >= 0.3))
ORDER BY (kind='video') DESC,
         CASE stage1_label WHEN 'Pornography' THEN 0 WHEN 'Enticing or Sensual' THEN 1 ELSE 2 END,
         size DESC
LIMIT ?
"""

SELECT_B = """
SELECT * FROM files
WHERE stage2_json IS NOT NULL AND stage2_b IS NULL AND final_json IS NULL
  AND is_thumb=0
  AND (json_extract(stage2_json,'$.nsfw_level')='explicit'
       OR json_extract(stage2_json,'$.confidence') < 0.85
       OR json_extract(stage2_json,'$.category')='review')
ORDER BY (kind='video') DESC, size DESC
LIMIT ?
"""

CLOTHING_CATS = {"none", "lingerie", "swimwear", "casual", "formal", "uniform", "other", "unknown"}


def _lower_priority() -> None:
    if sys.platform == "win32":
        try:
            import psutil

            psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        except Exception:
            pass


def _ask(vlm: VLM, row, max_tokens: int = 320, max_side: int = 1024) -> tuple[dict, dict]:
    if row["kind"] == "video":
        # 6 frames @640px stay under a 4096-token slot and give better temporal coverage
        frames = extract_frames(row["src_path"], count=6, max_side=640)
        if not frames:
            raise RuntimeError("no frames extracted")
        try:
            return vlm.complete([str(f) for f in frames], prompt=VLM_VIDEO_PROMPT,
                                max_tokens=max_tokens, max_side=640)
        finally:
            cleanup_frames(frames)
    return vlm.complete([row["src_path"]], prompt=VLM_PROMPT, max_tokens=max_tokens, max_side=max_side)


def _merge(verdict_a: dict, verdict_b: dict | None, siglip_scores: dict | None, kind: str) -> dict:
    lvl_rank = {"safe": 0, "suggestive": 1, "explicit": 2}
    a_lvl = verdict_a.get("nsfw_level", "safe")
    a_cat = verdict_a.get("category", "review")
    conf = float(verdict_a.get("confidence") or 0)
    review = a_cat == "review" or conf < 0.85
    b = verdict_b or {}
    tags = list(dict.fromkeys([t.lower() for t in (verdict_a.get("tags") or []) + (b.get("tags") or [])]))[:10]
    ct = verdict_a.get("content_type", "other")
    lvl = a_lvl
    cat = a_cat
    source = "A"

    if verdict_b:
        source = "A+B"
        b_lvl = b.get("nsfw_level", a_lvl)
        b_ct = b.get("content_type", "other")
        b_cat = b.get("category", a_cat)
        if lvl_rank.get(b_lvl, 0) > lvl_rank.get(a_lvl, 0):
            lvl = b_lvl
        if (a_lvl == "explicit") != (b_lvl == "explicit"):
            review = True
        if (ct == "real_photo") != (b_ct == "real_photo"):
            review = True
        if not (ct == "real_photo") and b_ct == "real_photo":
            ct = "real_photo"
        if b_cat != a_cat:
            real = {"daily", "sexy", "adult"}
            if a_cat in real and b_cat in real:
                cat = {"safe": "daily", "suggestive": "sexy", "explicit": "adult"}[lvl]
            elif {a_cat, b_cat} <= {"screenshot", "sticker"}:
                cat = "screenshot" if "screenshot" in (a_cat, b_cat) else "sticker"
            else:
                review = True
                cat = a_cat
    else:
        # un-arbitrated: independent confidence threshold
        if lvl == "explicit" and conf < 0.9:
            review = True

    if kind == "video" and a_cat == "daily" and lvl != "safe":
        cat = "sexy" if lvl == "suggestive" else "adult"

    if ct == "real_photo" and cat in {"daily", "sexy", "adult"}:
        cat = {"safe": "daily", "suggestive": "sexy", "explicit": "adult"}[lvl]
    if cat in {"daily", "sexy", "adult"} and ct != "real_photo" and not review:
        cat = "review"
        review = True
    if siglip_scores:
        porn = siglip_scores.get("Pornography", 0)
        if lvl == "explicit" and porn < 0.2 and not review:
            cat, review = "review", True
    if cat == "adult" and lvl != "explicit":
        cat = "sexy"
    if cat == "sexy" and lvl == "safe":
        cat = "daily"
    return {
        "category": cat,
        "nsfw_level": lvl,
        "content_type": ct,
        "confidence": conf if not verdict_b else round((conf + float(b.get("confidence") or conf)) / 2, 2),
        "tags": tags,
        "main_subject": verdict_a.get("main_subject", ""),
        "scene": verdict_a.get("scene", ""),
        "clothing": verdict_a.get("clothing", "unknown") if verdict_a.get("clothing") in CLOTHING_CATS else "unknown",
        "needs_review": bool(review),
        "source": source,
        "corporeal_nsfw": bool(verdict_a.get("corporeal_nsfw")) or bool((verdict_b or {}).get("corporeal_nsfw")),
        "b_category": (verdict_b or {}).get("category"),
        "b_nsfw_level": (verdict_b or {}).get("nsfw_level"),
    }


def _run_pass(model: str, select_sql: str, slots: int, ctx: int, workers: int, limit: int = 0,
              mode: str = "a", quiet: bool = False) -> dict:
    _lower_priority()
    led = Ledger()
    run_id = led.start_run(f"stage2_{mode}_{model}", {"slots": slots, "workers": workers, "limit": limit})
    processed = errors = 0
    t0 = time.perf_counter()
    last = 0.0
    total = None
    if mode == "a":
        total = led.conn.execute(
            "SELECT COUNT(*) FROM files WHERE stage2_json IS NULL AND final_json IS NULL AND is_thumb=0 "
            "AND (kind='video' OR (kind='image' AND lower(src_path) LIKE '%.gif') "
            "OR stage1_label IN "
            "('Normal','Enticing or Sensual','Pornography','Anime Picture','Hentai'))"
        ).fetchone()[0]

    work: queue.Queue = queue.Queue(maxsize=workers * 2)
    results: queue.Queue = queue.Queue()
    inflight: set[int] = set()

    def worker(port: int) -> None:
        vlm = VLM(model, port=port)
        while True:
            row = work.get()
            if row is None:
                work.task_done()
                return
            try:
                try:
                    verdict, meta = _ask(vlm, row, max_side=768 if mode == "b" else 1024)
                except ValueError:
                    verdict, meta = _ask(vlm, row, max_tokens=640, max_side=768 if mode == "b" else 1024)
                results.put((row, verdict, meta, None))
            except Exception as exc:  # noqa: BLE001
                results.put((row, None, None, str(exc)[:300]))
            finally:
                work.task_done()

    with LlamaServer(model, slots=slots, ctx=ctx) as srv:
        threads = [threading.Thread(target=worker, args=(srv.port,), daemon=True) for _ in range(workers)]
        for t in threads:
            t.start()
        feeding = True
        pending = 0
        while feeding or pending:
            while feeding and work.qsize() < work.maxsize:
                take = work.maxsize - work.qsize()
                if limit:
                    take = min(take, max(0, limit - processed - pending))
                if take <= 0:
                    feeding = False
                    break
                rows = led.conn.execute(select_sql, (take + len(inflight) + 16,)).fetchall()
                rows = [r for r in rows if r["id"] not in inflight][:take]
                if not rows:
                    feeding = False
                    for _ in threads:
                        work.put(None)
                    break
                for r in rows:
                    work.put(r)
                    inflight.add(r["id"])
                    pending += 1
            if not pending:
                continue
            try:
                row, verdict, _meta, err = results.get(timeout=600)
            except queue.Empty:
                print("[stage2] no result for 10 min; aborting pass", flush=True)
                break
            pending -= 1
            inflight.discard(row["id"])
            if err:
                errors += 1
                if mode == "a":
                    fallback = {"category": "review", "nsfw_level": "suggestive", "content_type": "other",
                                "confidence": 0.0, "tags": [], "main_subject": "", "scene": "",
                                "clothing": "unknown", "_error": err}
                    led.set_stage2(row["src_path"], fallback, model)
                    led.conn.execute("UPDATE files SET needs_review=1, updated_at=? WHERE id=?",
                                     (time.time(), row["id"]))
                else:
                    try:
                        a = json.loads(row["stage2_json"])
                        scores = json.loads(row["stage1_scores"]) if row["stage1_scores"] else None
                        final = _merge(a, None, scores, row["kind"])
                        led.conn.execute(
                            "UPDATE files SET final_json=?, category=?, needs_review=?, error=?, updated_at=? WHERE id=?",
                            (json.dumps(final, ensure_ascii=False), final["category"], int(final["needs_review"]),
                             err, time.time(), row["id"]),
                        )
                    except Exception:
                        led.conn.execute("UPDATE files SET error=?, updated_at=? WHERE id=?",
                                         (err, time.time(), row["id"]))
            else:
                if mode == "a":
                    led.set_stage2(row["src_path"], verdict, model)
                    needs = (float(verdict.get("confidence") or 0) < 0.85
                             or verdict.get("category") in ("review", "other")
                             or verdict.get("nsfw_level") == "explicit")
                    led.conn.execute("UPDATE files SET needs_review=? WHERE id=?", (int(needs), row["id"]))
                else:
                    led.conn.execute(
                        "UPDATE files SET stage2_b=?, updated_at=? WHERE id=?",
                        (json.dumps(verdict, ensure_ascii=False), time.time(), row["id"]),
                    )
                processed += 1
            led.commit()
            if not quiet and time.perf_counter() - last > 15:
                elapsed = time.perf_counter() - t0
                rate = processed / elapsed if elapsed else 0
                remain = f"{int((total - processed) / rate / 60)} min" if total and rate else "?"
                print(f"[stage2-{mode}:{model}] {processed}/{total or '?'} done, {errors} err, "
                      f"{rate:.2f} it/s, ETA {remain}", flush=True)
                last = time.perf_counter()
        for _ in threads:
            work.put(None)
        for t in threads:
            t.join(timeout=30)
    led.finish_run(run_id, processed, errors)
    led.commit()
    led.close()
    return {"processed": processed, "errors": errors, "elapsed_s": round(time.perf_counter() - t0, 1)}


def run_a(slots: int = 4, ctx: int = 16384, workers: int = 4, limit: int = 0, quiet: bool = False) -> dict:
    # Anime/Hentai must go through the VLM too: "Anime Picture" is not a
    # reliable safe verdict and can contain explicit or suggestive content.
    return _run_pass("nsfw", SELECT_A, slots, ctx, workers, limit, "a", quiet)


def run_b(slots: int = 4, ctx: int = 16384, workers: int = 4, limit: int = 0, quiet: bool = False) -> dict:
    return _run_pass("huihui", SELECT_B, slots, ctx, workers, limit, "b", quiet)


def finalize(led: Ledger | None = None) -> int:
    """Merge A (+B) verdicts into final_json/category/needs_review."""
    own = led is None
    led = led or Ledger()
    led.conn.execute(
        "UPDATE files SET move_state='skipped', needs_review=1, updated_at=? "
        "WHERE stage1_label='UNREADABLE' AND move_state='pending'",
        (time.time(),),
    )
    rows = led.conn.execute(
        "SELECT * FROM files WHERE stage2_json IS NOT NULL AND final_json IS NULL AND is_thumb=0"
    ).fetchall()
    for r in rows:
        try:
            a = json.loads(r["stage2_json"])
        except json.JSONDecodeError:
            continue
        b = json.loads(r["stage2_b"]) if r["stage2_b"] else None
        scores = json.loads(r["stage1_scores"] or "{}") if r["stage1_scores"] else None
        final = _merge(a, b, scores, r["kind"])
        led.conn.execute(
            "UPDATE files SET final_json=?, category=?, needs_review=?, updated_at=? WHERE id=?",
            (json.dumps(final, ensure_ascii=False), final["category"], int(final["needs_review"]), time.time(), r["id"]),
        )
    led.commit()
    if own:
        led.close()
    return len(rows)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("pass_", choices=["a", "b", "finalize"], help="pipeline pass")
    ap.add_argument("--slots", type=int, default=4)
    ap.add_argument("--ctx", type=int, default=16384)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    if args.pass_ == "a":
        print(run_a(args.slots, args.ctx, args.workers, args.limit, args.quiet))
    elif args.pass_ == "b":
        print(run_b(args.slots, args.ctx, args.workers, args.limit, args.quiet))
    else:
        print(finalize(), "rows finalized")