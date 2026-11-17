"""Second-pass audit of kept originals that were never VLM-checked or look risky."""
from __future__ import annotations

import json
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import VLM_PROMPT, VLM_VIDEO_PROMPT
from .db import Ledger
from .frames import cleanup_frames, extract_frames
from .serve import LlamaServer
from .vlm import VLM

RISK_SQL = """max(
    COALESCE(json_extract(f.stage1_scores,'$.Pornography'),0),
    COALESCE(json_extract(f.stage1_scores,'$.Hentai'),0),
    COALESCE(json_extract(f.stage1_scores,'$.Enticing or Sensual'),0)
)"""

SELECT_SQL = f"""
SELECT f.*, {RISK_SQL} AS siglip_risk
FROM files f
LEFT JOIN reaudit r ON r.file_id=f.id
WHERE f.move_state='kept'
  AND f.final_json IS NOT NULL
  AND COALESCE(f.origin,'') <> 'thumb_only'
  AND r.file_id IS NULL
  AND (f.kind='video'
       OR f.needs_review=1
       OR f.category IN ('sexy','adult','review')
       OR (f.kind='image' AND f.category='anime' AND f.stage2_json IS NULL)
       OR {RISK_SQL} >= 0.1)
ORDER BY (f.kind='video') DESC,
         (f.stage2_json IS NULL AND f.stage1_label IN ('Anime Picture','Hentai')) DESC,
         siglip_risk DESC, f.size DESC
LIMIT ?
"""

AUDIT_PROMPT = VLM_PROMPT + """

Second-pass audit rules:
- Mark explicit for visible genitalia, bare buttocks, female nipples in a sexual context, sexual intercourse, oral sex, masturbation, or sexual fluids.
- Mark suggestive for sexual posing, lingerie, see-through clothing, or a clearly sexual focus on the body.
- Ordinary swimwear, beachwear, fitness photos, and fully covered bodies are safe unless they expose the parts listed above.
- When in doubt between safe and suggestive, use review; when visible sexual content is present, do not downgrade it to safe."""

VIDEO_AUDIT_PROMPT = """The following images are frames sampled uniformly and chronologically from ONE short video. Audit the video as a whole. If any frame shows the sexual content described below, classify the video accordingly.

""" + AUDIT_PROMPT


def _risk(row) -> float:
    try:
        s = json.loads(row["stage1_scores"] or "{}")
    except Exception:
        return 0.0
    return max(float(s.get("Pornography", 0) or 0), float(s.get("Hentai", 0) or 0),
               float(s.get("Enticing or Sensual", 0) or 0))


def select(limit: int = 0) -> dict:
    led = Ledger()
    rows = led.conn.execute(SELECT_SQL, (limit or -1,)).fetchall()
    now = time.time()
    for r in rows:
        led.conn.execute(
            "INSERT OR IGNORE INTO reaudit (file_id,state,model,updated_at) VALUES (?,?,?,?)",
            (r["id"], "pending", "", now),
        )
    led.commit()
    led.close()
    return {"selected": len(rows)}


def _flag_level(verdict: dict, risk: float) -> bool:
    level = verdict.get("nsfw_level", "safe")
    conf = float(verdict.get("confidence") or 0)
    if level == "explicit":
        return True
    if level == "suggestive":
        return conf >= 0.7 or risk >= 0.3
    return False


def _category(verdict: dict, level: str) -> str:
    cat = verdict.get("category", "review")
    ct = verdict.get("content_type", "other")
    if cat == "daily" and level != "safe":
        cat = "sexy" if level == "suggestive" else "adult"
    if ct == "real_photo" and cat in {"daily", "sexy", "adult"}:
        cat = {"safe": "daily", "suggestive": "sexy", "explicit": "adult"}[level]
    if cat not in {"daily", "sexy", "adult", "anime", "sticker", "screenshot", "review", "other"}:
        cat = "review"
    return cat


def run(model: str = "huihui", slots: int = 4, workers: int = 4, limit: int = 0) -> dict:
    led = Ledger()
    rows = led.conn.execute(
        """SELECT f.*, r.state AS reaudit_state, r.file_id AS reaudit_id
           FROM reaudit r JOIN files f ON f.id=r.file_id
           WHERE r.state='pending' ORDER BY (f.kind='video') DESC, f.id"""
    ).fetchall()
    rows = [dict(r) for r in rows if Path(r["src_path"]).exists()]
    if limit:
        rows = rows[:limit]
    if not rows:
        led.close()
        return {"checked": 0}
    q: queue.Queue[dict] = queue.Queue()
    for r in rows:
        q.put(r)
    lock = threading.Lock()
    local = threading.local()
    checked = flagged = errors = 0
    t0 = time.time()

    def get_vlm() -> VLM:
        v = getattr(local, "vlm", None)
        if v is None:
            v = VLM(model)
            local.vlm = v
        return v

    def worker() -> None:
        nonlocal checked, flagged, errors
        while True:
            try:
                r = q.get_nowait()
            except queue.Empty:
                return
            frames = []
            try:
                if r["kind"] == "video":
                    frames = extract_frames(r["src_path"], count=8, max_side=512)
                    if not frames:
                        raise RuntimeError("no frames extracted")
                    verdict, _ = get_vlm().complete(
                        [str(f) for f in frames], prompt=VIDEO_AUDIT_PROMPT,
                        max_tokens=360, max_side=512,
                    )
                else:
                    verdict, _ = get_vlm().complete(
                        [r["src_path"]], prompt=AUDIT_PROMPT, max_tokens=360, max_side=768,
                    )
                level = verdict.get("nsfw_level", "safe")
                if level not in ("safe", "suggestive", "explicit"):
                    raise ValueError(f"bad nsfw_level: {level!r}")
                risk = float(r.get("siglip_risk") or 0)
                should_move = _flag_level(verdict, risk)
                cat = _category(verdict, level) if should_move else (verdict.get("category") or "review")
                conf = float(verdict.get("confidence") or 0)
                with lock:
                    if should_move:
                        try:
                            final = json.loads(r["final_json"] or "{}")
                        except Exception:
                            final = {}
                        final.update({
                            "category": cat,
                            "nsfw_level": level,
                            "needs_review": bool(conf < 0.8 or cat == "review"),
                            "source": "reaudit-" + model,
                            "audit_verdict": verdict,
                        })
                        led.conn.execute(
                            """UPDATE files SET final_json=?, category=?, needs_review=?,
                                   move_state=CASE WHEN move_state='kept' THEN 'pending' ELSE move_state END,
                                   updated_at=? WHERE id=?""",
                            (json.dumps(final, ensure_ascii=False), cat, int(conf < 0.8 or cat == "review"),
                             time.time(), r["id"]),
                        )
                        led.conn.execute(
                            "UPDATE reaudit SET state='nsfw', model=?, verdict_json=?, final_level=?, final_category=?, updated_at=? WHERE file_id=?",
                            (model, json.dumps(verdict, ensure_ascii=False), level, cat, time.time(), r["id"]),
                        )
                        flagged += 1
                    else:
                        led.conn.execute(
                            "UPDATE reaudit SET state='safe', model=?, verdict_json=?, final_level=?, final_category=?, updated_at=? WHERE file_id=?",
                            (model, json.dumps(verdict, ensure_ascii=False), level,
                             verdict.get("category", "review"), time.time(), r["id"]),
                        )
                    checked += 1
                    if checked % 20 == 0:
                        led.commit()
                        print(f"[reaudit] {checked}/{len(rows)} checked, {flagged} flagged, "
                              f"{errors} err, {checked / max(1, time.time() - t0):.2f}/s", flush=True)
            except Exception as exc:
                with lock:
                    led.conn.execute(
                        "UPDATE reaudit SET state='error', model=?, error=?, updated_at=? WHERE file_id=?",
                        (model, str(exc)[:300], time.time(), r["id"]),
                    )
                    errors += 1
                    checked += 1
            finally:
                if frames:
                    cleanup_frames(frames)

    with LlamaServer(model, slots=slots, ctx=16384):
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for _ in range(workers):
                ex.submit(worker)
    led.commit()
    led.close()
    return {"checked": checked, "flagged": flagged, "errors": errors,
            "elapsed_s": round(time.time() - t0, 1), "model": model}


def status() -> dict:
    led = Ledger()
    out = {r["state"]: r["n"] for r in led.conn.execute(
        "SELECT state, COUNT(*) n FROM reaudit GROUP BY state")}
    out["total"] = led.conn.execute("SELECT COUNT(*) FROM reaudit").fetchone()[0]
    out["by_level"] = {r["final_level"] or "<none>": r["n"] for r in led.conn.execute(
        "SELECT final_level, COUNT(*) n FROM reaudit GROUP BY final_level")}
    led.close()
    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["select", "run", "status"])
    ap.add_argument("--model", default="huihui", choices=["huihui", "nsfw"])
    ap.add_argument("--slots", type=int, default=4)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if a.stage == "select":
        print(select(a.limit))
    elif a.stage == "run":
        print(run(a.model, a.slots, a.workers, a.limit))
    else:
        print(json.dumps(status(), ensure_ascii=False, indent=1))
