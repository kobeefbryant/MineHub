"""Audit every QQ thumbnail: exact ledger match, SigLIP screening, VLM verdict, atomic move."""
from __future__ import annotations

import csv
import json
import os
import queue
import re
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .config import DATA, MEDIA_ROOT, QQ_ACCOUNTS, VLM_PROMPT
from .db import Ledger
from .stage3 import TMP_SUFFIX, _copy_hash, _same_volume, _unique, target_name

THUMB_ROOT = MEDIA_ROOT / "qq_thumbs"
STEM_RE = re.compile(r"_\d+$")

# Static thumbnails are cleanly separated by SigLIP; animations/video previews
# get a lower bar because a safe first frame can hide an explicit later frame.
STATIC_CAND = 0.10
VIDEO_FORCE_VLM = True

THUMB_PROMPT = (
    "This image is a QQ thumbnail/preview, possibly a keyframe of a video or "
    "animation. Classify only what is visible in the supplied image.\n\n" + VLM_PROMPT
)

STRONG_EXPLICIT = 0.85
STRONG_SUGGESTIVE = 0.85


def qq_stem(name: str) -> str:
    return STEM_RE.sub("", Path(name).stem).lower()


def _lower_priority() -> None:
    try:
        import psutil

        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass


def _ledger_index(led: Ledger) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    stem_map: dict[str, list[dict]] = {}
    md5_map: dict[str, list[dict]] = {}

    def add(mp: dict[str, list[dict]], key: str, row: dict) -> None:
        if key:
            mp.setdefault(key.lower(), []).append(row)

    rows = led.conn.execute(
        """SELECT id,src_path,md5,move_state,category,origin,kind,is_thumb,
                  json_extract(final_json,'$.nsfw_level') AS level
           FROM files"""
    ).fetchall()
    for r in rows:
        d = dict(r)
        stem = Path(d["src_path"]).stem
        add(stem_map, stem, d)
        # thumb-only rows store `..._0.jpg` / `..._720.gif`; the QQ thumb name
        # is the same hash, but qq_stem() strips the variant suffix.
        add(stem_map, STEM_RE.sub("", stem), d)
        add(md5_map, d["md5"] or "", d)
    return stem_map, md5_map


def _pick(cands: list[dict] | None) -> dict | None:
    if not cands:
        return None
    for state in ("moved", "kept"):
        for c in cands:
            if c["move_state"] == state:
                return c
    return cands[0]


def _match(stem: str, stem_map: dict, md5_map: dict) -> tuple[str, dict | None]:
    hit = _pick(stem_map.get(stem)) or _pick(md5_map.get(stem))
    if not hit:
        return "orphan", None
    if hit["move_state"] == "moved":
        return "moved", hit
    if hit["move_state"] == "kept":
        return "kept", hit
    return hit["move_state"], hit


def scan(limit: int = 0) -> dict:
    """Enumerate QQ Thumb files and classify their relationship to the ledger."""
    _lower_priority()
    led = Ledger()
    stem_map, md5_map = _ledger_index(led)
    scanned = 0
    batch: list[tuple] = []
    t0 = time.time()

    def flush() -> None:
        nonlocal batch
        if not batch:
            return
        led.conn.executemany(
            """INSERT INTO thumb_audit
                 (path,account,kind,month,stem,size,mtime,match_state,ledger_id,
                  matched_src,matched_origin,matched_category,matched_level,state)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(path) DO UPDATE SET
                 account=excluded.account, kind=excluded.kind, month=excluded.month,
                 stem=excluded.stem, size=excluded.size, mtime=excluded.mtime,
                 match_state=excluded.match_state, ledger_id=excluded.ledger_id,
                 matched_src=excluded.matched_src, matched_origin=excluded.matched_origin,
                 matched_category=excluded.matched_category, matched_level=excluded.matched_level,
                 state=CASE WHEN thumb_audit.size=excluded.size
                                 AND thumb_audit.mtime=excluded.mtime
                                 AND NOT (excluded.match_state='moved'
                                          AND thumb_audit.match_state<>'moved')
                            THEN thumb_audit.state ELSE excluded.state END,
                 siglip_json=CASE WHEN thumb_audit.size=excluded.size
                                       AND thumb_audit.mtime=excluded.mtime
                                  THEN thumb_audit.siglip_json ELSE NULL END,
                 siglip_label=CASE WHEN thumb_audit.size=excluded.size
                                        AND thumb_audit.mtime=excluded.mtime
                                   THEN thumb_audit.siglip_label ELSE NULL END,
                 siglip_nsfw=CASE WHEN thumb_audit.size=excluded.size
                                       AND thumb_audit.mtime=excluded.mtime
                                  THEN thumb_audit.siglip_nsfw ELSE NULL END,
                 best_frame=CASE WHEN thumb_audit.size=excluded.size
                                      AND thumb_audit.mtime=excluded.mtime
                                 THEN thumb_audit.best_frame ELSE 0 END,
                 vlm_json=CASE WHEN thumb_audit.size=excluded.size
                                    AND thumb_audit.mtime=excluded.mtime
                               THEN thumb_audit.vlm_json ELSE NULL END,
                 final_level=CASE WHEN thumb_audit.size=excluded.size
                                       AND thumb_audit.mtime=excluded.mtime
                                  THEN thumb_audit.final_level ELSE NULL END,
                 final_category=CASE WHEN thumb_audit.size=excluded.size
                                          AND thumb_audit.mtime=excluded.mtime
                                     THEN thumb_audit.final_category ELSE NULL END,
                 target_path=CASE WHEN thumb_audit.size=excluded.size
                                       AND thumb_audit.mtime=excluded.mtime
                                  THEN thumb_audit.target_path ELSE NULL END,
                 error=NULL, moved_at=NULL""",
            batch,
        )
        led.commit()
        batch.clear()

    for nt_data in QQ_ACCOUNTS:
        if not nt_data.is_dir():
            continue
        account = nt_data.parent.parent.name
        for kind in ("Pic", "Video"):
            base = nt_data / kind
            if not base.is_dir():
                continue
            for month in base.iterdir():
                thumb_dir = month / "Thumb"
                if not month.is_dir() or not thumb_dir.is_dir():
                    continue
                for entry in thumb_dir.iterdir():
                    if not entry.is_file():
                        continue
                    if limit and scanned >= limit:
                        break
                    try:
                        st = entry.stat()
                    except OSError:
                        continue
                    stem = qq_stem(entry.name)
                    match_state, hit = _match(stem, stem_map, md5_map)
                    initial = "exact" if match_state == "moved" else "pending"
                    batch.append((
                        str(entry), account, kind, month.name, stem, st.st_size, st.st_mtime,
                        match_state,
                        hit["id"] if hit else None,
                        hit["src_path"] if hit else None,
                        hit["origin"] if hit else None,
                        hit["category"] if hit else None,
                        hit["level"] if hit else None,
                        initial,
                    ))
                    scanned += 1
                    if len(batch) >= 2000:
                        flush()
    flush()
    led.close()
    return {"scanned": scanned, "elapsed_s": round(time.time() - t0, 1), "db": str(DATA / "minehub.sqlite")}


def _frames(path: Path, max_frames: int = 4) -> list[tuple[int, Any]]:
    from PIL import Image

    out: list[tuple[int, Any]] = []
    with Image.open(path) as im:
        n = int(getattr(im, "n_frames", 1) or 1)
        if n <= 1:
            idxs = [0]
        else:
            idxs = sorted({0, max(0, n // 3), max(0, (2 * n) // 3), max(0, n - 1)})
        for idx in idxs[:max_frames]:
            try:
                im.seek(idx)
                out.append((idx, im.convert("RGB").copy()))
            except Exception:
                continue
    return out


def _candidate_threshold(row: dict) -> float:
    if row["kind"] == "Video":
        return -1.0  # all video previews go to VLM
    suffix = Path(row["path"]).suffix.lower()
    # A safe first frame can hide explicit later frames; extensionless files are
    # often real images that SigLIP cannot route reliably.
    if suffix in (".gif", ".null"):
        return -1.0
    # These were fast-routed by SigLIP alone in the first run. Use a much lower
    # bar than ordinary thumbnails, but do not spend VLM time on near-zero scores.
    if row["match_state"] == "kept" and (row.get("matched_origin") or "") == "thumb_only":
        return 0.03
    return STATIC_CAND


def run_siglip(limit: int = 0, batch_size: int = 96) -> dict:
    """Score pending thumbs; force all video previews and borderline images to VLM."""
    from .prefilter import SiglipNSFW

    _lower_priority()
    led = Ledger()
    rows = led.conn.execute(
        "SELECT * FROM thumb_audit WHERE state='pending' ORDER BY (kind='Video') DESC, id"
    ).fetchall()
    rows = [dict(r) for r in rows if Path(r["path"]).exists()]
    if limit:
        rows = rows[:limit]
    if not rows:
        led.close()
        return {"scored": 0, "candidates": 0}
    clf = SiglipNSFW()
    scored = candidates = errors = 0
    t0 = time.time()
    for start in range(0, len(rows), batch_size):
        chunk = rows[start:start + batch_size]
        flat: list[Any] = []
        meta: list[tuple[dict, int, int]] = []
        for r in chunk:
            try:
                frames = _frames(Path(r["path"]))
            except Exception:
                frames = []
            if not frames:
                led.conn.execute(
                    "UPDATE thumb_audit SET state='error', error='unreadable image', audited_at=? WHERE id=?",
                    (time.time(), r["id"]),
                )
                errors += 1
                continue
            for idx, im in frames:
                meta.append((r, idx, len(flat)))
                flat.append(im)
        results = clf.classify_batch(flat) if flat else []
        by_row: dict[int, list[tuple[int, dict[str, float]]]] = {}
        for (r, idx, _), res in zip(meta, results):
            by_row.setdefault(r["id"], []).append((idx, res.scores))
        for r in chunk:
            got = by_row.get(r["id"])
            if not got:
                continue
            agg = {k: max(s.get(k, 0.0) for _, s in got) for k in got[0][1]}
            best_idx, _ = max(
                got,
                key=lambda t: max(
                    t[1].get("Pornography", 0.0),
                    t[1].get("Hentai", 0.0),
                    t[1].get("Enticing or Sensual", 0.0),
                ),
            )
            label = max(agg, key=agg.get)
            nsfw = max(agg.get("Pornography", 0.0), agg.get("Hentai", 0.0),
                       agg.get("Enticing or Sensual", 0.0))
            threshold = _candidate_threshold(r)
            state = "candidate" if (threshold < 0 or nsfw >= threshold) else "safe_siglip"
            led.conn.execute(
                """UPDATE thumb_audit SET siglip_json=?, siglip_label=?, siglip_nsfw=?,
                       best_frame=?, state=?, audited_at=? WHERE id=?""",
                (json.dumps(agg, ensure_ascii=False), label, nsfw, best_idx, state, time.time(), r["id"]),
            )
            scored += 1
            if state == "candidate":
                candidates += 1
        led.commit()
        print(f"[thumb-audit] siglip {scored}/{len(rows)} scored, {candidates} candidates, "
              f"{errors} err, {scored / max(1, time.time() - t0):.1f}/s", flush=True)
    led.close()
    return {"scored": scored, "candidates": candidates, "errors": errors,
            "elapsed_s": round(time.time() - t0, 1)}


def _best_frame_file(row: dict) -> tuple[str, str | None]:
    """Return (path_for_vlm, temp_path). Animated images use the highest-NSFW frame."""
    path = Path(row["path"])
    if path.suffix.lower() != ".gif":
        return str(path), None
    best = 0
    try:
        best = int(json.loads(row["siglip_json"] or "{}").get("best_frame", 0))
    except Exception:
        pass
    frames = _frames(path, max_frames=4)
    pick = next((im for idx, im in frames if idx == best), frames[0][1] if frames else None)
    if pick is None:
        return str(path), None
    tmpdir = DATA / "tmp_thumbs"
    tmpdir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(suffix=".jpg", dir=str(tmpdir))
    os.close(fd)
    pick.save(name, format="JPEG", quality=90)
    return name, name


def _siglip_level(row: dict) -> str:
    try:
        scores = json.loads(row["siglip_json"] or "{}")
    except (TypeError, ValueError):
        scores = {}
    porn = scores.get("Pornography", 0.0)
    hentai = scores.get("Hentai", 0.0)
    enticing = scores.get("Enticing or Sensual", 0.0)
    if porn >= STRONG_EXPLICIT or hentai >= STRONG_EXPLICIT:
        return "explicit"
    if max(porn, hentai, enticing) >= STRONG_SUGGESTIVE:
        return "suggestive"
    return "safe"


def _recover_truncated_verdict(message: str) -> tuple[str, str] | None:
    """Salvage nsfw_level/content_type from a JSON response cut off by max_tokens."""
    level = re.search(r'"nsfw_level"\s*:\s*"(safe|suggestive|explicit)"', message)
    if not level:
        return None
    ctype = re.search(r'"content_type"\s*:\s*"([a-z_]+)"', message)
    return level.group(1), (ctype.group(1) if ctype else "other")


def repair_vlm_errors() -> dict:
    """Recover candidates whose VLM JSON was truncated after the verdict fields."""
    led = Ledger()
    rows = led.conn.execute(
        "SELECT * FROM thumb_audit WHERE state='error' AND error LIKE 'non-JSON VLM output:%'"
    ).fetchall()
    repaired = skipped = 0
    for raw in rows:
        r = dict(raw)
        parsed = _recover_truncated_verdict(r.get("error") or "")
        if not parsed:
            skipped += 1
            continue
        level, ctype = parsed
        strong = _siglip_level(r)
        if level == "safe" and strong != "safe":
            level = strong
        if level == "safe":
            state = "safe_vlm"
            category = "anime" if ctype in ("anime", "illustration") else "daily"
        else:
            state = "ready_move"
            category = "anime" if ctype in ("anime", "illustration") else (
                "adult" if level == "explicit" else "sexy")
        verdict = {"recovered_from_error": True, "nsfw_level": level,
                   "content_type": ctype, "category": category,
                   "tags": [], "confidence": 0.0}
        led.conn.execute(
            """UPDATE thumb_audit SET vlm_json=?, final_level=?, final_category=?,
                   state=?, error='recovered from truncated JSON', audited_at=? WHERE id=?""",
            (json.dumps(verdict, ensure_ascii=False), level, category, state, time.time(), r["id"]),
        )
        repaired += 1
    led.commit()
    led.close()
    return {"repaired": repaired, "skipped": skipped, "checked": len(rows)}


def repair_states() -> dict:
    """Reassert exact/moved states after a concurrent SigLIP run touched them."""
    led = Ledger()
    rows = led.conn.execute("SELECT * FROM thumb_audit WHERE match_state='moved'").fetchall()
    exact = moved = lost = 0
    for r in rows:
        r = dict(r)
        src = Path(r["path"])
        dst = Path(r["target_path"]) if r["target_path"] else (
            THUMB_ROOT / r["account"] / r["kind"] / r["month"] / "Thumb" / src.name
        )
        if src.exists():
            if r["state"] != "exact":
                led.conn.execute(
                    "UPDATE thumb_audit SET state='exact', error=NULL WHERE id=?", (r["id"],)
                )
                exact += 1
        elif dst.exists():
            if r["state"] != "moved":
                led.conn.execute(
                    "UPDATE thumb_audit SET state='moved', target_path=?, error=NULL WHERE id=?",
                    (str(dst), r["id"]),
                )
                moved += 1
        else:
            led.conn.execute(
                "UPDATE thumb_audit SET state='error', error='source and destination missing' WHERE id=?",
                (r["id"],),
            )
            lost += 1
    led.commit()
    led.close()
    return {"re_exact": exact, "mark_moved": moved, "lost": lost, "checked": len(rows)}


def promote_candidates() -> dict:
    """Apply current recall thresholds to thumbnails already scored by SigLIP."""
    led = Ledger()
    rows = led.conn.execute("SELECT * FROM thumb_audit WHERE state='safe_siglip'").fetchall()
    promoted = 0
    for r in rows:
        r = dict(r)
        th = _candidate_threshold(r)
        if th < 0 or float(r["siglip_nsfw"] or 0) >= th:
            led.conn.execute("UPDATE thumb_audit SET state='candidate' WHERE id=?", (r["id"],))
            promoted += 1
    led.commit()
    led.close()
    return {"promoted": promoted, "checked": len(rows)}


def incremental(slots: int = 4, workers: int = 4, limit: int = 0, dry_run: bool = False) -> dict:
    """Scan all QQ thumbs, then classify/move only rows whose content changed or is new."""
    before = status()
    scanned = scan()
    after_scan = status()
    out: dict[str, Any] = {
        "scanned": scanned,
        "new_pending": max(0, after_scan.get("pending", 0) - before.get("pending", 0)),
    }
    # QQ can recreate a previously moved thumb at the same path with an old
    # mtime; reassert exact so it is not skipped just because state says moved.
    out["repair"] = repair_states()
    if after_scan.get("pending", 0):
        out["siglip"] = run_siglip(limit)
        out["promote"] = promote_candidates()
    if status().get("candidate", 0):
        out["vlm"] = run_vlm(slots, workers, limit)
        out["repair_vlm"] = repair_vlm_errors()
    out["move"] = run_move(limit, dry_run)
    out["status"] = status()
    return out


def run_vlm(slots: int = 4, workers: int = 4, limit: int = 0) -> dict:
    """VLM-classify candidates (and every orphan/kept video preview)."""
    from .serve import LlamaServer
    from .vlm import VLM

    _lower_priority()
    led = Ledger()
    rows = led.conn.execute(
        "SELECT * FROM thumb_audit WHERE state='candidate' ORDER BY (kind='Video') DESC, id"
    ).fetchall()
    rows = [dict(r) for r in rows if Path(r["path"]).exists()]
    if limit:
        rows = rows[:limit]
    if not rows:
        led.close()
        return {"classified": 0}
    # QQ stores several variants of the same image (_0, _720, ...). Classify
    # one representative per stem, then copy the verdict to all variants.
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["stem"] or r["path"], []).append(r)
    jobs: list[dict] = []
    for members in groups.values():
        rep = max(members, key=lambda x: (
            1 if Path(x["path"]).suffix.lower() == ".gif" else 0,
            int(x["size"] or 0),
        ))
        jobs.append({"rep": rep, "members": members})
    total = sum(len(j["members"]) for j in jobs)
    lock = threading.Lock()
    local = threading.local()
    q: queue.Queue[dict] = queue.Queue()
    for job in jobs:
        q.put(job)
    done = errors = moved_ready = 0
    t0 = time.time()

    def get_vlm() -> VLM:
        v = getattr(local, "vlm", None)
        if v is None:
            v = VLM("nsfw")
            local.vlm = v
        return v

    def worker() -> None:
        nonlocal done, errors, moved_ready
        while True:
            try:
                job = q.get_nowait()
            except queue.Empty:
                return
            rep = job["rep"]
            img, tmp = _best_frame_file(rep)
            try:
                try:
                    verdict, _meta = get_vlm().complete([img], prompt=THUMB_PROMPT,
                                                       max_tokens=360, max_side=768)
                except ValueError:
                    verdict, _meta = get_vlm().complete([img], prompt=THUMB_PROMPT,
                                                       max_tokens=640, max_side=768)
                base_level = verdict.get("nsfw_level", "safe")
                base_category = verdict.get("category", "review")
                if base_level not in ("safe", "suggestive", "explicit"):
                    raise ValueError(f"bad nsfw_level: {base_level!r}")
                with lock:
                    for r in job["members"]:
                        level = base_level
                        category = base_category
                        # Never let a weak safe verdict erase strong SigLIP evidence.
                        if level == "safe" and _siglip_level(r) != "safe":
                            level = _siglip_level(r)
                            category = "review"
                        state = "ready_move" if level in ("suggestive", "explicit") else "safe_vlm"
                        led.conn.execute(
                            """UPDATE thumb_audit SET vlm_json=?, final_level=?, final_category=?,
                                   state=?, audited_at=? WHERE id=?""",
                            (json.dumps(verdict, ensure_ascii=False), level, category, state,
                             time.time(), r["id"]),
                        )
                        done += 1
                        if state == "ready_move":
                            moved_ready += 1
                    if done % 20 == 0 or done == total:
                        led.commit()
                        print(f"[thumb-audit] vlm {done}/{total}, {moved_ready} NSFW, "
                              f"{errors} err, {done / max(1, time.time() - t0):.2f}/s", flush=True)
            except Exception as exc:
                with lock:
                    for r in job["members"]:
                        led.conn.execute(
                            "UPDATE thumb_audit SET state='error', error=?, audited_at=? WHERE id=?",
                            (str(exc)[:300], time.time(), r["id"]),
                        )
                        errors += 1
                        done += 1
            finally:
                if tmp:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass

    with LlamaServer("nsfw", slots=slots, ctx=16384):
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for _ in range(workers):
                ex.submit(worker)
    led.commit()
    led.close()
    return {"classified": done, "groups": len(jobs), "nsfw": moved_ready, "errors": errors,
            "elapsed_s": round(time.time() - t0, 1)}


def run_move(limit: int = 0, dry_run: bool = False, move_originals: bool = False) -> dict:
    """Atomically move NSFW thumbs; optionally flag their kept Ori rows for move_all."""
    _lower_priority()
    led = Ledger()
    rows = led.conn.execute(
        "SELECT * FROM thumb_audit WHERE state IN ('exact','ready_move') ORDER BY id"
    ).fetchall()
    rows = [dict(r) for r in rows if Path(r["path"]).exists()]
    if limit:
        rows = rows[:limit]
    moved = dup = errors = flagged = 0
    t0 = time.time()
    log_path = DATA / "thumb_audit_moves.csv"
    log = None
    writer = None
    if not dry_run:
        new = not log_path.exists()
        log = open(log_path, "a", newline="", encoding="utf-8")
        writer = csv.writer(log)
        if new:
            writer.writerow(["ts", "src", "dst", "match_state", "level", "category",
                             "siglip_nsfw", "account", "kind", "size", "ledger_id"])
    for r in rows:
        src = Path(r["path"])
        level = r["final_level"] or r["matched_level"]
        category = r["final_category"] or r["matched_category"] or "review"
        if level not in ("suggestive", "explicit"):
            continue
        if category == "daily":
            category = "sexy" if level == "suggestive" else "adult"
        dst = THUMB_ROOT / r["account"] / r["kind"] / r["month"] / "Thumb" / target_name(src)
        if dry_run:
            moved += 1
            if r["match_state"] == "kept":
                flagged += 1
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.name + TMP_SUFFIX)
            if dst.exists() and dst.stat().st_size == r["size"]:
                os.remove(src)
                dup += 1
            else:
                if dst.exists():
                    dst = _unique(dst)
                if _same_volume(str(src), dst.parent):
                    os.replace(src, dst)
                else:
                    _copy_hash(str(src), tmp)
                    if tmp.stat().st_size != r["size"]:
                        raise RuntimeError("temp size verify failed")
                    os.replace(tmp, dst)
                    os.remove(src)
                if dst.stat().st_size != r["size"]:
                    raise RuntimeError("destination size mismatch")
                moved += 1
            led.conn.execute(
                """UPDATE thumb_audit SET state='moved', target_path=?, moved_at=?,
                       error=NULL WHERE id=?""",
                (str(dst), time.time(), r["id"]),
            )
            writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), str(src), str(dst),
                             r["match_state"], level, category, r["siglip_nsfw"],
                             r["account"], r["kind"], r["size"], r["ledger_id"]])
            if r["match_state"] == "kept" and r["ledger_id"]:
                hit = led.conn.execute("SELECT * FROM files WHERE id=?", (r["ledger_id"],)).fetchone()
                if hit:
                    try:
                        final = json.loads(hit["final_json"] or "{}")
                    except Exception:
                        final = {}
                    final.update({
                        "category": category,
                        "nsfw_level": level,
                        "needs_review": False,
                        "source": "thumb-audit",
                        "thumb_path": str(dst),
                    })
                    if Path(hit["src_path"]) == src:
                        # The ledger row points at this exact thumbnail: it has now moved.
                        led.conn.execute(
                            """UPDATE files SET final_json=?, category=?, needs_review=0,
                                   move_state='moved', target_path=?, error=NULL,
                                   stash_state='skipped', updated_at=?
                               WHERE id=?""",
                            (json.dumps(final, ensure_ascii=False), category, str(dst),
                             time.time(), r["ledger_id"]),
                        )
                    else:
                        # A different QQ copy/variant of the same media remains; let
                        # move_all take it through the normal atomic path.
                        led.conn.execute(
                            """UPDATE files SET final_json=?, category=?, needs_review=0,
                                   move_state=CASE WHEN move_state='kept' THEN 'pending' ELSE move_state END,
                                   updated_at=? WHERE id=?""",
                            (json.dumps(final, ensure_ascii=False), category, time.time(), r["ledger_id"]),
                        )
                        if hit["move_state"] == "kept":
                            flagged += 1
            if (moved + dup + errors) % 10 == 0:
                log.flush()
                led.commit()
                print(f"[thumb-audit] move {moved} moved, {dup} already, {errors} err, "
                      f"{flagged} Ori flagged", flush=True)
        except Exception as exc:
            errors += 1
            led.conn.execute(
                "UPDATE thumb_audit SET error=?, state='ready_move' WHERE id=?",
                (str(exc)[:300], r["id"]),
            )
    led.commit()
    if log is not None:
        log.flush()
        log.close()
    if move_originals and flagged:
        from .stage3 import move_all

        move_all(0, False, True)
    led.close()
    return {"moved": moved, "already": dup, "errors": errors, "originals_flagged": flagged,
            "elapsed_s": round(time.time() - t0, 1), "dry_run": dry_run}


def status() -> dict:
    led = Ledger()
    out: dict[str, Any] = {}
    for r in led.conn.execute("SELECT state, COUNT(*) n FROM thumb_audit GROUP BY state"):
        out[r["state"]] = r["n"]
    out["total"] = led.conn.execute("SELECT COUNT(*) FROM thumb_audit").fetchone()[0]
    out["by_match"] = {r["match_state"]: r["n"] for r in led.conn.execute(
        "SELECT match_state, COUNT(*) n FROM thumb_audit GROUP BY match_state")}
    out["by_level"] = {r["final_level"] or "<none>": r["n"] for r in led.conn.execute(
        "SELECT final_level, COUNT(*) n FROM thumb_audit GROUP BY final_level")}
    led.close()
    return out


def run_all(slots: int = 4, workers: int = 4, limit: int = 0, dry_run: bool = False) -> dict:
    print("[thumb-audit] scan", json.dumps(scan(limit), ensure_ascii=False), flush=True)
    print("[thumb-audit] siglip", json.dumps(run_siglip(limit), ensure_ascii=False), flush=True)
    print("[thumb-audit] repair", json.dumps(repair_states(), ensure_ascii=False), flush=True)
    print("[thumb-audit] promote", json.dumps(promote_candidates(), ensure_ascii=False), flush=True)
    print("[thumb-audit] vlm", json.dumps(run_vlm(slots, workers, limit), ensure_ascii=False), flush=True)
    print("[thumb-audit] repair-vlm", json.dumps(repair_vlm_errors(), ensure_ascii=False), flush=True)
    print("[thumb-audit] move", json.dumps(run_move(limit, dry_run), ensure_ascii=False), flush=True)
    return status()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["scan", "siglip", "promote", "repair", "repair-vlm",
                                      "vlm", "move", "all", "status"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--slots", type=int, default=4)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--move-originals", action="store_true")
    a = ap.parse_args()
    if a.stage == "scan":
        print(scan(a.limit))
    elif a.stage == "siglip":
        print(run_siglip(a.limit))
    elif a.stage == "promote":
        print(promote_candidates())
    elif a.stage == "repair":
        print(repair_states())
    elif a.stage == "repair-vlm":
        print(repair_vlm_errors())
    elif a.stage == "vlm":
        print(run_vlm(a.slots, a.workers, a.limit))
    elif a.stage == "move":
        print(run_move(a.limit, a.dry_run, a.move_originals))
    elif a.stage == "all":
        print(run_all(a.slots, a.workers, a.limit, a.dry_run))
    else:
        print(json.dumps(status(), ensure_ascii=False, indent=1))
