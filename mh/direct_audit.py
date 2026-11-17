"""Corporeal-content audit for moved files.

Library policy: keep every image that itself shows a sexual/suggestive person,
including underwear, lingerie, swimwear, suggestive posing, and covered,
censored or pixelated bodies in a sexual context. Exclude text cards, chat/UI
screenshots, memes and stickers whose sexual element is only words or a joke.

The audit re-checks error-prone categories, moves keepers into the library and
restores the rest to their original QQ paths.
"""
from __future__ import annotations

import argparse
import csv
import json
import queue
import shutil
import threading
import time
from pathlib import Path

from .config import DATA, LIBRARY, NSFW_POLICY
from .db import Ledger
from .frames import cleanup_frames, extract_frames
from .serve import LlamaServer
from .stage3 import _unique, target_name
from .vlm import VLM

AUDIT_PROMPT = """You are auditing one image for a library of sexual/suggestive person imagery.

Choose "sexual_person" when the image itself depicts a person (real photo, anime or illustration) that qualifies under the user's library policy. This includes:
- a clearly attractive feminine adult prominently visible, even when fully clothed
- a group photo with a clearly qualifying attractive female present, even when the whole group is the main subject
- nudity, visible genitalia or nipples, sexual acts involving a female subject
- underwear, lingerie, swimwear, bikini
- suggestive posing or a sexual focus on breasts, buttocks, thighs or the body
- a body covered by sheets or clothing, or censored/mosaic/pixelated, in a sexual context
- sexual or suggestive anime/illustration of a qualifying female person

Choose "text_or_meme" (the non-keep bucket) when any exclusion applies:
- gore, blood, injury or death
- only male subjects, or only an exposed male
- a female who looks male/masculine, or a female judged unattractive/not appealing
- pure text, chat/UI screenshots, captions, jokes, emoji, memes or stickers without a qualifying female
- non-human subjects only (animals, objects, scenery)
- a head-and-shoulders or face-only portrait, even with makeup/styled hair, unless body, fashion, lingerie, swimwear, a suggestive pose or sexual context is visible

A sexual joke or sexual words alone never count as sexual_person.
If gender or attractiveness is genuinely ambiguous, do not force a keep; use content_type "other" and explain.
Judge only visible pixels, never filenames or tags. Reply with ONE JSON object only.

Schema:
{
  "content_class": "sexual_person" or "text_or_meme",
  "content_type": one of ["real_photo","anime","illustration","screenshot","meme","text","other"],
  "evidence": string,        // <=60 chars, what is visible or why it is text/meme
  "confidence": number       // 0-1
}

""" + NSFW_POLICY

AUDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "content_class": {"type": "string", "enum": ["sexual_person", "text_or_meme"]},
        "content_type": {"type": "string", "enum": ["real_photo", "anime", "illustration", "screenshot", "meme", "text", "other"]},
        "evidence": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["content_class", "content_type", "evidence", "confidence"],
}

AUDIT_CATEGORIES = ("screenshot", "review", "other", "daily")

# Rows already touched by the move/restore machinery in the error-prone categories.
AUDIT_SQL = f"""
SELECT * FROM files
WHERE final_json IS NOT NULL
  AND category IN ({','.join('?' * len(AUDIT_CATEGORIES))})
  AND (
    move_state='moved'
    OR (move_state='kept' AND (
          json_extract(final_json,'$.corporeal_nsfw') IS NOT NULL
          OR json_extract(final_json,'$.direct_exposure') IS NOT NULL
       ))
  )
ORDER BY CASE category WHEN 'screenshot' THEN 0 WHEN 'review' THEN 1 WHEN 'other' THEN 2 ELSE 3 END, id
"""

# Stickers/memes are never corporeal content; restore all that are still in the library.
RESTORE_SQL = """
SELECT * FROM files
WHERE move_state='moved' AND final_json IS NOT NULL
  AND (category='sticker'
       OR json_extract(final_json,'$.corporeal_nsfw')=0
       OR (json_extract(final_json,'$.corporeal_nsfw')=1
           AND json_extract(final_json,'$.content_audit.content_type') IN ('text','meme')))
ORDER BY id
"""


def _restore(led: Ledger, row, note: str, verdict: dict | None = None, model: str = "") -> str:
    dst = Path(row["target_path"]) if row["target_path"] else None
    src = Path(row["src_path"])
    if dst is None or not dst.exists():
        state = "kept" if src.exists() else "lost"
        led.conn.execute(
            "UPDATE files SET move_state=?, error=?, updated_at=? WHERE id=?",
            (state, None if state == "kept" else "target missing and source missing", time.time(), row["id"]),
        )
        return state
    src.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        src = _unique(src)
    shutil.move(str(dst), str(src))
    final = json.loads(row["final_json"] or "{}")
    final["corporeal_nsfw"] = False
    if verdict is not None:
        final["content_audit"] = verdict
        final["content_model"] = model
        final["content_at"] = time.time()
    led.conn.execute(
        "UPDATE files SET move_state='kept', target_path=NULL, src_path=?, final_json=?, stash_state='pending', updated_at=? WHERE id=?",
        (str(src), json.dumps(final, ensure_ascii=False), time.time(), row["id"]),
    )
    with open(DATA / "moves.csv", "a", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow([time.strftime("%Y-%m-%d %H:%M:%S"), str(src), str(dst), row["md5"], note, row["size"], ""])
    return "restored"


def _move_in(led: Ledger, row, verdict: dict, model: str) -> str:
    src = Path(row["src_path"])
    if not src.exists():
        led.conn.execute(
            "UPDATE files SET move_state='lost', error='source missing after audit', updated_at=? WHERE id=?",
            (time.time(), row["id"]),
        )
        return "lost"
    cat = row["category"] if row["category"] else "other"
    month = time.strftime("%Y-%m", time.localtime(row["mtime"]))
    dst_dir = LIBRARY / cat / month
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = _unique(dst_dir / target_name(src))
    final = json.loads(row["final_json"] or "{}")
    final["corporeal_nsfw"] = True
    final["content_audit"] = verdict
    final["content_model"] = model
    final["content_at"] = time.time()
    shutil.move(str(src), str(dst))
    led.conn.execute(
        "UPDATE files SET move_state='moved', target_path=?, final_json=?, stash_state='pending', error=NULL, updated_at=? WHERE id=?",
        (str(dst), json.dumps(final, ensure_ascii=False), time.time(), row["id"]),
    )
    with open(DATA / "moves.csv", "a", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow([time.strftime("%Y-%m-%d %H:%M:%S"), str(src), str(dst), row["md5"], "content-audit-keep", row["size"], ""])
    return "moved"


def select(limit: int = 0) -> list:
    led = Ledger()
    rows = led.conn.execute(AUDIT_SQL, AUDIT_CATEGORIES).fetchall()
    led.close()
    rows = [dict(r) for r in rows]
    rows = [r for r in rows if (r["target_path"] and Path(r["target_path"]).exists())
            or Path(r["src_path"]).exists()]
    return rows[:limit] if limit else rows


def run_audit(model: str = "huihui", slots: int = 4, workers: int = 4, limit: int = 0,
              dry_run: bool = False) -> dict:
    rows = select(limit)
    if dry_run or not rows:
        return {"candidates": len(rows), "checked": 0, "keep": 0, "restored": 0, "errors": 0}

    q: queue.Queue[dict] = queue.Queue()
    for r in rows:
        q.put(r)
    lock = threading.Lock()
    local = threading.local()
    counts = {"checked": 0, "keep": 0, "restored": 0, "kept": 0, "errors": 0}
    t0 = time.time()
    led = Ledger()

    def get_vlm() -> VLM:
        v = getattr(local, "vlm", None)
        if v is None:
            v = VLM(model)
            local.vlm = v
        return v

    def worker() -> None:
        while True:
            try:
                r = q.get_nowait()
            except queue.Empty:
                return
            path = r["target_path"] if r["target_path"] and Path(r["target_path"]).exists() else r["src_path"]
            frames: list[Path] = []
            try:
                if r["kind"] == "video":
                    frames = extract_frames(path, count=6, max_side=512)
                    if not frames:
                        raise RuntimeError("no frames extracted")
                    verdict, _ = get_vlm().complete_custom(
                        [str(f) for f in frames], AUDIT_PROMPT, AUDIT_SCHEMA,
                        max_tokens=200, max_side=512,
                    )
                else:
                    verdict, _ = get_vlm().complete_custom(
                        [path], AUDIT_PROMPT, AUDIT_SCHEMA, max_tokens=200, max_side=768,
                    )
                keep = (verdict.get("content_class") == "sexual_person"
                        and verdict.get("content_type") not in ("text", "meme"))
                with lock:
                    if keep:
                        if r["move_state"] == "moved" and r["target_path"] and Path(r["target_path"]).exists():
                            counts["keep"] += 1
                            final = json.loads(r["final_json"] or "{}")
                            final["corporeal_nsfw"] = True
                            final["content_audit"] = verdict
                            final["content_model"] = model
                            final["content_at"] = time.time()
                            led.conn.execute(
                                "UPDATE files SET final_json=?, updated_at=? WHERE id=?",
                                (json.dumps(final, ensure_ascii=False), time.time(), r["id"]),
                            )
                        else:
                            state = _move_in(led, r, verdict, model)
                            counts["keep" if state == "moved" else "errors"] += 1
                    else:
                        if r["move_state"] == "moved":
                            state = _restore(led, r, "content-audit-false", verdict, model)
                            if state == "restored":
                                counts["restored"] += 1
                            elif state == "lost":
                                counts["errors"] += 1
                            else:
                                counts["kept"] += 1
                        else:
                            final = json.loads(r["final_json"] or "{}")
                            final["corporeal_nsfw"] = False
                            final["content_audit"] = verdict
                            final["content_model"] = model
                            final["content_at"] = time.time()
                            led.conn.execute(
                                "UPDATE files SET final_json=?, updated_at=? WHERE id=?",
                                (json.dumps(final, ensure_ascii=False), time.time(), r["id"]),
                            )
                            counts["restored"] += 1
                    counts["checked"] += 1
                    if counts["checked"] % 20 == 0:
                        led.conn.commit()
                        rate = counts["checked"] / max(1, time.time() - t0)
                        print(f"[content] {counts['checked']}/{len(rows)} checked, "
                              f"{counts['keep']} keep, {counts['restored']} restore, "
                              f"{counts['errors']} err, {rate:.2f}/s", flush=True)
            except Exception as exc:  # noqa: BLE001
                with lock:
                    counts["errors"] += 1
                    counts["checked"] += 1
                    print(f"[content] error {r['id']}: {str(exc)[:160]}", flush=True)
            finally:
                if frames:
                    cleanup_frames(frames)

    with LlamaServer(model, slots=slots, ctx=8192):
        with __import__("concurrent.futures").futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for _ in range(workers):
                pool.submit(worker)
    led.conn.commit()
    led.close()
    counts["candidates"] = len(rows)
    counts["elapsed_s"] = round(time.time() - t0, 1)
    return counts


def run_restore(limit: int = 0, dry_run: bool = False) -> dict:
    led = Ledger()
    rows = led.conn.execute(RESTORE_SQL).fetchall()
    if limit:
        rows = rows[:limit]
    restored = errors = skipped = 0
    for r in rows:
        if dry_run:
            restored += 1
            continue
        state = _restore(led, r, "corporeal-policy-restore")
        if state == "restored":
            restored += 1
        elif state == "lost":
            errors += 1
        else:
            skipped += 1
        if (restored + errors + skipped) % 200 == 0:
            led.conn.commit()
            print(f"[restore] {restored} restored, {skipped} skipped, {errors} err", flush=True)
    led.conn.commit()
    led.close()
    return {"checked": len(rows), "restored": restored, "skipped": skipped, "errors": errors}


def stats() -> dict:
    led = Ledger()
    moved = {}
    for r in led.conn.execute(
        "SELECT category, json_extract(final_json,'$.nsfw_level') lvl, COUNT(*) n "
        "FROM files WHERE move_state='moved' GROUP BY category, lvl ORDER BY n DESC"
    ):
        moved[f"{r[0]}/{r[1]}"] = r[2]
    confirmed = led.conn.execute(
        "SELECT COUNT(*) FROM files WHERE json_extract(final_json,'$.corporeal_nsfw')=1"
    ).fetchone()[0]
    rejected = led.conn.execute(
        "SELECT COUNT(*) FROM files WHERE json_extract(final_json,'$.corporeal_nsfw')=0"
    ).fetchone()[0]
    led.close()
    return {"moved": moved, "corporeal_confirmed": confirmed, "corporeal_rejected": rejected}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="action", required=True)
    a = sub.add_parser("audit")
    a.add_argument("--limit", type=int, default=0)
    a.add_argument("--workers", type=int, default=4)
    a.add_argument("--slots", type=int, default=4)
    a.add_argument("--model", default="huihui")
    a.add_argument("--dry-run", action="store_true")
    r = sub.add_parser("restore-stickers")
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--dry-run", action="store_true")
    sub.add_parser("stats")
    args = ap.parse_args()
    if args.action == "audit":
        print(run_audit(workers=args.workers, slots=args.slots, limit=args.limit,
                        model=args.model, dry_run=args.dry_run))
    elif args.action == "restore-stickers":
        print(run_restore(limit=args.limit, dry_run=args.dry_run))
    else:
        print(json.dumps(stats(), ensure_ascii=False, indent=1))
