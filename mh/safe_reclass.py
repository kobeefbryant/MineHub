"""Huihui review of the safe folder; move qualifying NSFW images back to the library."""
from __future__ import annotations

import argparse
import csv
import json
import os
import queue
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import DATA, IMAGE_EXTS, LIBRARY, MEDIA_ROOT
from .db import Ledger
from .direct_audit import AUDIT_PROMPT, AUDIT_SCHEMA
from .serve import LlamaServer
from .stage3 import _unique, target_name
from .stash import Stash
from .vlm import VLM

CATEGORIES = {"daily", "sexy", "adult", "anime", "sticker", "screenshot", "review", "other"}
SKIP = {".csv", ".json", ".txt", ".md"}


def _norm(path: str | Path) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(str(path))))


def list_images(root: Path, limit: int = 0) -> list[Path]:
    paths = sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS and p.suffix.lower() not in SKIP
    )
    return paths[:limit] if limit else paths


def ledger_map(root: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    prefix = str(root) + os.sep
    led = Ledger()
    try:
        rows = led.conn.execute(
            "SELECT id, category, target_path, src_path, move_state, final_json "
            "FROM files WHERE target_path LIKE ? OR src_path LIKE ?",
            (prefix + "%", prefix + "%"),
        ).fetchall()
        for row in rows:
            item = dict(row)
            for key in ("target_path", "src_path"):
                if item[key]:
                    out.setdefault(_norm(item[key]), item)
    finally:
        led.close()
    return out


def category_for(path: Path, row: dict | None, root: Path) -> str:
    if row and row.get("category") in CATEGORIES:
        return row["category"]
    try:
        rel = path.relative_to(root)
        first = rel.parts[0] if len(rel.parts) > 1 else ""
        if first in CATEGORIES:
            return first
    except ValueError:
        pass
    return "review"


def classify(vlm: VLM, path: Path) -> tuple[dict, bool]:
    verdict, _usage = vlm.complete_custom(
        [str(path)], AUDIT_PROMPT, AUDIT_SCHEMA,
        max_tokens=200, max_side=768, timeout=180,
    )
    keep = (
        verdict.get("content_class") == "sexual_person"
        and verdict.get("content_type") not in ("text", "meme")
    )
    return verdict, keep


def update_ledger(led: Ledger, row: dict | None, verdict: dict, model: str,
                  target: Path | None = None) -> None:
    if not row:
        return
    final = json.loads(row.get("final_json") or "{}")
    final.update({
        "corporeal_nsfw": target is not None,
        "content_audit": verdict,
        "content_model": model,
        "content_at": time.time(),
    })
    if target is not None:
        led.conn.execute(
            "UPDATE files SET target_path=?, move_state='moved', stash_state='pending', "
            "needs_review=1, final_json=?, updated_at=? WHERE id=?",
            (str(target), json.dumps(final, ensure_ascii=False), time.time(), row["id"]),
        )
    else:
        led.conn.execute(
            "UPDATE files SET final_json=?, updated_at=? WHERE id=?",
            (json.dumps(final, ensure_ascii=False), time.time(), row["id"]),
        )


def move_to_library(path: Path, category: str) -> Path:
    month = time.strftime("%Y-%m", time.localtime(path.stat().st_mtime))
    dest_dir = LIBRARY / category / month
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = _unique(dest_dir / target_name(path))
    shutil.move(str(path), str(dest))
    return dest


def run(root: Path, limit: int = 0, model: str = "huihui", slots: int = 4,
        workers: int = 4, apply: bool = False, scan_stash: bool = True) -> dict:
    paths = list_images(root, limit)
    rows = ledger_map(root)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    report = root / f"huihui_safe_reclass_{stamp}.csv"
    summary_path = DATA / "reports" / f"safe_reclass_{stamp}.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    q: queue.Queue[Path] = queue.Queue()
    for path in paths:
        q.put(path)
    lock = threading.Lock()
    local = threading.local()
    counts = {
        "candidates": len(paths), "checked": 0, "keep": 0, "moved": 0,
        "safe": 0, "errors": 0, "no_ledger": 0, "elapsed_s": 0.0,
    }
    written: list[dict] = []
    scan_dirs: set[str] = set()
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
                path = q.get_nowait()
            except queue.Empty:
                return
            row = rows.get(_norm(path))
            try:
                verdict, keep = classify(get_vlm(), path)
                target = None
                if keep and apply:
                    category = category_for(path, row, root)
                    target = move_to_library(path, category)
                    scan_dirs.add(str(target.parent))
                with lock:
                    if keep and apply:
                        update_ledger(led, row, verdict, model, target)
                        counts["moved"] += 1
                    elif keep:
                        counts["keep"] += 1
                    else:
                        if apply:
                            update_ledger(led, row, verdict, model)
                        counts["safe"] += 1
                    if row is None:
                        counts["no_ledger"] += 1
                    counts["checked"] += 1
                    written.append({
                        "path": str(path),
                        "category": category_for(path, row, root),
                        "keep": int(keep),
                        "content_class": verdict.get("content_class", ""),
                        "content_type": verdict.get("content_type", ""),
                        "confidence": verdict.get("confidence", ""),
                        "target": str(target) if target else "",
                        "status": "moved" if target else ("would_move" if keep else "left"),
                        "error": "",
                    })
                    if counts["checked"] % 20 == 0:
                        led.commit()
                        rate = counts["checked"] / max(1, time.time() - t0)
                        print(f"[safe] {counts['checked']}/{len(paths)} checked, "
                              f"{counts['moved']} moved, {counts['safe']} safe, "
                              f"{counts['errors']} err, {rate:.2f}/s", flush=True)
            except Exception as exc:  # noqa: BLE001
                with lock:
                    counts["errors"] += 1
                    counts["checked"] += 1
                    written.append({
                        "path": str(path), "category": category_for(path, row, root),
                        "keep": "", "content_class": "", "content_type": "",
                        "confidence": "", "target": "", "status": "error",
                        "error": str(exc)[:240],
                    })
                print(f"[safe] error {path.name}: {str(exc)[:160]}", flush=True)

    if paths:
        with LlamaServer(model, slots=slots, ctx=8192):
            with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                for _ in range(max(1, workers)):
                    pool.submit(worker)

    counts["elapsed_s"] = round(time.time() - t0, 1)
    led.commit()
    led.close()
    with open(report, "w", newline="", encoding="utf-8") as fh:
        fields = ["path", "category", "keep", "content_class", "content_type",
                  "confidence", "target", "status", "error"]
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(written)

    summary = {**counts, "report": str(report), "apply": apply, "model": model}
    if apply and scan_dirs and scan_stash:
        try:
            job = Stash().scan(sorted(scan_dirs))
            summary["stash_scan_job"] = job
        except Exception as exc:  # noqa: BLE001
            summary["stash_scan_error"] = str(exc)[:240]
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(MEDIA_ROOT / "safe"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--model", default="huihui")
    ap.add_argument("--slots", type=int, default=4)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-scan", action="store_true")
    args = ap.parse_args()
    print(json.dumps(run(
        Path(args.root), limit=args.limit, model=args.model,
        slots=args.slots, workers=args.workers,
        apply=args.apply, scan_stash=not args.no_scan,
    ), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
