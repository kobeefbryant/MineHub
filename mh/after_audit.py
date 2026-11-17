"""Wait for the thumbnail VLM pass, then finish moves, reaudit, and Stash tagging."""
from __future__ import annotations

import json
import time

from .config import DATA
from .db import Ledger
from .reaudit import run as reaudit_run, select as reaudit_select
from .stage3 import move_all
from .thumb_audit import repair_vlm_errors, run_move

LOG = DATA / "logs" / "after_audit.log"
SUMMARY = DATA / "logs" / "after_audit_summary.json"
MAX_WAIT = 12 * 3600


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _candidates() -> int:
    led = Ledger()
    n = led.conn.execute("SELECT COUNT(*) FROM thumb_audit WHERE state='candidate'").fetchone()[0]
    led.close()
    return n


def wait_for_vlm() -> int:
    t0 = time.time()
    last = -1
    last_move = 0.0
    while time.time() - t0 < MAX_WAIT:
        n = _candidates()
        if n == 0:
            log("thumbnail VLM queue empty")
            return 0
        if n != last:
            log(f"waiting for thumbnail VLM: {n} candidates left")
            last = n
        # Do not leave already-confirmed NSFW thumbnails in QQ for the whole
        # multi-hour VLM pass; drain ready_move incrementally.
        if time.time() - last_move >= 600:
            log("incremental move: " + str(run_move(0, False, False)))
            log("incremental originals: " + str(move_all(0, False, True)))
            last_move = time.time()
        time.sleep(60)
    log("timeout waiting for thumbnail VLM; continuing with current results")
    return _candidates()


def stash_scan_tag() -> dict:
    from .stash import Stash, start_stash

    s = Stash()
    if not s.wait_ready(5):
        log("starting Stash")
        start_stash()
        if not s.wait_ready(180):
            return {"error": "stash not ready"}
    job = s.scan()
    status = s.wait_job(job)
    log(f"stash scan finished: {status}")
    out = {}
    for attempt in range(3):
        out = s.push_tags()
        log(f"stash tag pass {attempt + 1}: {out}")
        if out.get("unmatched", 0) == 0:
            break
        job = s.scan()
        s.wait_job(job)
    return out


def rebuild_index() -> dict:
    from .index import SimilarityIndex

    idx = SimilarityIndex()
    # Keep index and viewer on the same fp32 CPU encoder; CUDA fp16 embeddings
    # are close but not identical, which would skew re-ranking scores.
    out = idx.build(("image", "scene"), 0, "cpu", 32)
    log("similarity index: " + json.dumps(out, ensure_ascii=False))
    try:
        import requests

        r = requests.post("http://127.0.0.1:8765/reload", timeout=30)
        log(f"viewer reload: {r.status_code} {r.text[:200]}")
    except Exception as exc:
        log(f"viewer reload skipped: {exc}")
    return out


def main() -> int:
    log("=== after-audit watcher start ===")
    wait_for_vlm()
    time.sleep(10)

    log("=== recover truncated VLM verdicts ===")
    log(str(repair_vlm_errors()))

    log("=== move VLM-confirmed thumbnails ===")
    log(str(run_move(0, False, False)))
    log("=== move flagged originals ===")
    log(str(move_all(0, False, True)))

    log("=== select kept originals for second pass ===")
    log(str(reaudit_select()))
    log("=== reaudit (model B) ===")
    log(str(reaudit_run("huihui", 4, 4, 0)))
    log("=== move reaudit results ===")
    log(str(move_all(0, False, True)))

    log("=== Stash scan + tag ===")
    tag = stash_scan_tag()
    log(str(tag))

    log("=== rebuild similarity index ===")
    try:
        index = rebuild_index()
    except Exception as exc:
        index = {"error": str(exc)[:300]}
        log("similarity index failed: " + json.dumps(index, ensure_ascii=False))

    led = Ledger()
    stats = led.stats()
    tstat = {r["state"]: r["n"] for r in led.conn.execute(
        "SELECT state,COUNT(*) n FROM thumb_audit GROUP BY state")}
    rstat = {r["state"]: r["n"] for r in led.conn.execute(
        "SELECT state,COUNT(*) n FROM reaudit GROUP BY state")}
    led.close()
    summary = {"stats": stats, "thumb_audit": tstat, "reaudit": rstat, "tag": tag, "index": index}
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    log("=== after-audit complete ===")
    log(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
