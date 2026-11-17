"""Stage 3: dedupe + safe move into the library tree, with rollback."""
from __future__ import annotations

import csv
import hashlib
import os
import re
import shutil
import sys
import time
from pathlib import Path

from .config import CATEGORY_DIRS, DATA, LIBRARY, ensure_dirs
from .db import Ledger


def _lower_priority() -> None:
    if sys.platform == "win32":
        try:
            import psutil

            psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        except Exception:
            pass


def md5_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        while True:
            buf = fh.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


TMP_SUFFIX = ".mhpart"


def target_name(src: str | Path) -> str:
    """QQ can store real images as .null; restore the image suffix on move."""
    p = Path(src)
    if p.suffix.lower() != ".null":
        return p.name
    try:
        from PIL import Image

        with Image.open(p) as im:
            fmt = (im.format or "").lower()
        ext = {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png", "gif": ".gif", "webp": ".webp"}.get(fmt)
        if ext:
            return p.with_suffix(ext).name
    except Exception:
        pass
    return p.name


def _same_volume(src: str, dst_dir: Path) -> bool:
    try:
        return os.stat(src).st_dev == os.stat(dst_dir).st_dev
    except OSError:
        return False


def _copy_hash(src: str, dst: Path, chunk: int = 1 << 20) -> str:
    """Copy src to dst while hashing; fsync before returning."""
    h = hashlib.md5()
    with open(src, "rb") as fh, open(dst, "wb") as out:
        while True:
            buf = fh.read(chunk)
            if not buf:
                break
            h.update(buf)
            out.write(buf)
        out.flush()
        os.fsync(out.fileno())
    try:
        shutil.copystat(src, dst)
    except OSError:
        pass
    return h.hexdigest()


def _unique(dst: Path) -> Path:
    if not dst.exists():
        return dst
    stem, suffix = dst.stem, dst.suffix
    i = 1
    while True:
        cand = dst.with_name(f"{stem}_{i}{suffix}")
        if not cand.exists():
            return cand
        i += 1


def reconcile_missing(led: Ledger | None = None) -> dict:
    """Repair rows whose file was moved by a killed run before the DB commit landed."""
    own = led is None
    led = led or Ledger()
    rows = led.conn.execute(
        "SELECT * FROM files WHERE move_state='error' AND error='source missing'"
    ).fetchall()
    if not rows:
        if own:
            led.close()
        return {"repaired": 0}
    index: dict[tuple[str, int], list[Path]] = {}
    for p in LIBRARY.rglob("*"):
        if p.is_file():
            stem = re.sub(r"_\d+$", "", p.stem.lower())
            try:
                index.setdefault((stem, p.stat().st_size), []).append(p)
            except OSError:
                pass
    repaired = 0
    for r in rows:
        stem = re.sub(r"_\d+$", "", Path(r["src_path"]).stem.lower())
        cands = index.get((stem, r["size"]), [])
        if len(cands) != 1:
            continue
        pick = cands[0]
        led.conn.execute(
            "UPDATE files SET target_path=?, move_state='moved', error=NULL, md5=COALESCE(md5,?), updated_at=? WHERE id=?",
            (str(pick), md5_file(str(pick)), time.time(), r["id"]),
        )
        repaired += 1
    led.commit()
    if own:
        led.close()
    return {"repaired": repaired, "checked": len(rows)}


NSFW_SQL = "json_extract(final_json,'$.nsfw_level') IN ('suggestive','explicit')"


def recover_moving(led: Ledger | None = None) -> dict:
    """Finish or undo moves interrupted between the intent commit and the result commit."""
    own = led is None
    led = led or Ledger()
    rows = led.conn.execute(
        "SELECT * FROM files WHERE move_state='moving' AND target_path IS NOT NULL"
    ).fetchall()
    done = undone = lost = 0
    for r in rows:
        src = r["src_path"]
        dst = Path(r["target_path"])
        tmp = dst.with_name(dst.name + TMP_SUFFIX)
        try:
            if not dst.exists() and tmp.exists() and tmp.stat().st_size == r["size"]:
                os.replace(tmp, dst)
            if dst.exists() and dst.stat().st_size == r["size"]:
                digest = r["md5"] or md5_file(str(dst))
                dup = led.conn.execute(
                    "SELECT id FROM files WHERE md5=? AND move_state IN ('moved','kept') AND id<>? LIMIT 1",
                    (digest, r["id"]),
                ).fetchone()
                led.conn.execute(
                    "UPDATE files SET md5=?, move_state='moved', dup_of=?, error=NULL, updated_at=? WHERE id=?",
                    (digest, dup["id"] if dup else None, time.time(), r["id"]),
                )
                done += 1
                if os.path.exists(src):
                    try:
                        if os.path.getsize(src) == r["size"] and md5_file(src) == digest:
                            os.remove(src)
                    except OSError:
                        pass
            elif os.path.exists(src):
                led.conn.execute(
                    "UPDATE files SET move_state='pending', target_path=NULL, error=NULL, updated_at=? WHERE id=?",
                    (time.time(), r["id"]),
                )
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
                undone += 1
            else:
                led.conn.execute(
                    "UPDATE files SET move_state='error', error=?, updated_at=? WHERE id=?",
                    ("interrupted move: source and target both missing", time.time(), r["id"]),
                )
                lost += 1
        except OSError as exc:
            led.conn.execute(
                "UPDATE files SET error=?, updated_at=? WHERE id=?",
                (f"recover: {exc}"[:300], time.time(), r["id"]),
            )
    led.commit()
    if own:
        led.close()
    return {"recovered": done, "reset": undone, "lost": lost, "checked": len(rows)}


def move_all(limit: int = 0, dry_run: bool = False, compute_md5: bool = True) -> dict:
    _lower_priority()
    ensure_dirs()
    led = Ledger()
    run_id = led.start_run("stage3_move", {"limit": limit, "dry_run": dry_run}) if not dry_run else 0
    if not dry_run:
        rec = recover_moving(led)
        if rec["checked"]:
            print(f"[stage3] recovered {rec['recovered']} interrupted moves, "
                  f"reset {rec['reset']}, lost {rec['lost']}", flush=True)
        fixed = reconcile_missing(led)
        if fixed.get("repaired"):
            print(f"[stage3] reconciled {fixed['repaired']} rows moved by a previous interrupted run", flush=True)
        kept = led.conn.execute(
            f"""UPDATE files SET move_state='kept', updated_at=? WHERE final_json IS NOT NULL
                AND move_state='pending' AND is_thumb=0 AND NOT ({NSFW_SQL})""",
            (time.time(),),
        ).rowcount
        led.commit()
        print(f"[stage3] kept in place (non-NSFW): {kept}", flush=True)
    q = ("SELECT * FROM files WHERE final_json IS NOT NULL AND move_state='pending' AND is_thumb=0 "
         f"AND category IS NOT NULL AND ({NSFW_SQL}) ORDER BY id")
    if limit:
        q += f" LIMIT {int(limit)}"
    rows = led.conn.execute(q).fetchall()
    moved = dup = errors = 0
    t0 = time.time()
    log_path = DATA / "moves.csv"
    log = None
    writer = None
    if not dry_run:
        new_log = not log_path.exists()
        log = open(log_path, "a", newline="", encoding="utf-8")
        writer = csv.writer(log)
        if new_log:
            writer.writerow(["ts", "src", "dst", "md5", "category", "size", "dup_of"])

    for r in rows:
        src = r["src_path"]
        if not os.path.exists(src):
            if not dry_run:
                led.set_move(src, None, "error", "source missing")
                led.commit()
            errors += 1
            continue
        cat = r["category"] if r["category"] in CATEGORY_DIRS else "other"
        month = time.strftime("%Y-%m", time.localtime(r["mtime"]))
        dst_dir = LIBRARY / cat / month
        if dry_run:
            digest = None
            if compute_md5:
                try:
                    digest = md5_file(src)
                except OSError as exc:
                    errors += 1
                    print(f"[stage3] dry-run md5 failed: {src}: {exc}", flush=True)
                    continue
            dup_row = None
            if digest:
                dup_row = led.conn.execute(
                    "SELECT id FROM files WHERE md5=? AND move_state IN ('moved','kept') AND id<>? LIMIT 1",
                    (digest, r["id"]),
                ).fetchone()
            moved += 1
            if dup_row:
                dup += 1
            continue
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = _unique(dst_dir / target_name(src))
        tmp = dst.with_name(dst.name + TMP_SUFFIX)
        # Intent journal: if the process dies anywhere below, recover_moving can
        # tell exactly where this file should be.
        led.conn.execute(
            "UPDATE files SET move_state='moving', target_path=?, updated_at=? WHERE id=?",
            (str(dst), time.time(), r["id"]),
        )
        led.commit()
        digest = None
        leftover = ""
        try:
            if _same_volume(src, dst_dir):
                if compute_md5:
                    digest = md5_file(src)
                os.replace(src, str(dst))
            else:
                digest = _copy_hash(src, tmp)
                if tmp.stat().st_size != r["size"]:
                    raise RuntimeError("temp size verify failed")
                os.replace(str(tmp), str(dst))
                if dst.stat().st_size != r["size"]:
                    raise RuntimeError("size verify failed")
                try:
                    os.remove(src)
                except OSError as exc:
                    leftover = f"source not removed: {exc}"[:300]
            if dst.stat().st_size != r["size"]:
                raise RuntimeError("size verify failed")
            dup_row = None
            if digest:
                dup_row = led.conn.execute(
                    "SELECT id FROM files WHERE md5=? AND move_state IN ('moved','kept') AND id<>? LIMIT 1",
                    (digest, r["id"]),
                ).fetchone()
            led.conn.execute(
                "UPDATE files SET md5=?, target_path=?, move_state='moved', dup_of=?, error=?, updated_at=? WHERE id=?",
                (digest, str(dst), dup_row["id"] if dup_row else None, leftover or None, time.time(), r["id"]),
            )
            writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), src, str(dst), digest, cat, r["size"],
                             dup_row["id"] if dup_row else ""])
            moved += 1
            if dup_row:
                dup += 1
        except Exception as exc:  # noqa: BLE001
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            if dst.exists() and dst.stat().st_size == r["size"]:
                digest = digest or md5_file(str(dst))
                led.conn.execute(
                    "UPDATE files SET md5=COALESCE(md5,?), target_path=?, move_state='moved', error=?, updated_at=? WHERE id=?",
                    (digest, str(dst), str(exc)[:300], time.time(), r["id"]),
                )
                writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), src, str(dst), digest, cat, r["size"], ""])
                moved += 1
            elif os.path.exists(src):
                led.conn.execute(
                    "UPDATE files SET move_state='pending', target_path=NULL, error=?, updated_at=? WHERE id=?",
                    (str(exc)[:300], time.time(), r["id"]),
                )
                errors += 1
            else:
                led.conn.execute(
                    "UPDATE files SET move_state='error', error=?, updated_at=? WHERE id=?",
                    (str(exc)[:300], time.time(), r["id"]),
                )
                errors += 1
        if (moved + dup + errors) % 10 == 0:
            log.flush()
            rate = (moved + dup + errors) / max(1, time.time() - t0)
            print(f"[stage3] {moved} moved, {dup} dup, {errors} err, {rate:.1f} files/s", flush=True)
        led.commit()
    led.commit()
    if log is not None:
        log.close()
    if run_id:
        led.finish_run(run_id, moved + dup, errors)
    led.close()
    return {"moved": moved, "duplicates": dup, "errors": errors, "elapsed_s": round(time.time() - t0, 1)}


def restore_safe_moved(limit: int = 0, dry_run: bool = False) -> dict:
    """Return already-moved non-NSFW files to their original QQ paths."""
    led = Ledger()
    q = ("SELECT * FROM files WHERE move_state='moved' AND final_json IS NOT NULL "
         f"AND NOT ({NSFW_SQL}) ORDER BY updated_at DESC")
    if limit:
        q += f" LIMIT {int(limit)}"
    rows = led.conn.execute(q).fetchall()
    restored = errors = 0
    for r in rows:
        dst = Path(r["target_path"]) if r["target_path"] else None
        src = Path(r["src_path"])
        if dst is None or not dst.exists():
            state = "kept" if src.exists() else "lost"
            led.conn.execute("UPDATE files SET move_state=?, error=?, updated_at=? WHERE id=?",
                             (state, None if state == "kept" else "target missing and source missing",
                              time.time(), r["id"]))
            errors += 1
            continue
        src.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            src = _unique(src)
        if dry_run:
            restored += 1
            continue
        try:
            shutil.move(str(dst), str(src))
            led.conn.execute(
                "UPDATE files SET move_state='kept', target_path=NULL, src_path=?, updated_at=? WHERE id=?",
                (str(src), time.time(), r["id"]))
            with open(DATA / "moves.csv", "a", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow([time.strftime("%Y-%m-%d %H:%M:%S"), str(src), str(dst), r["md5"], "restore-safe", r["size"], ""])
            restored += 1
        except Exception as exc:  # noqa: BLE001
            led.conn.execute("UPDATE files SET error=?, updated_at=? WHERE id=?", (str(exc)[:300], time.time(), r["id"]))
            errors += 1
        if (restored + errors) % 20 == 0:
            led.commit()
        if (restored + errors) % 200 == 0:
            print(f"[restore] {restored} restored, {errors} err", flush=True)
    led.commit()
    led.close()
    return {"restored": restored, "errors": errors, "checked": len(rows)}


def rollback(limit: int = 0) -> dict:
    """Move files back to their original QQ paths."""
    led = Ledger()
    q = ("SELECT * FROM files WHERE move_state='moved' AND target_path IS NOT NULL "
         "ORDER BY updated_at DESC")
    if limit:
        q += f" LIMIT {int(limit)}"
    rows = led.conn.execute(q).fetchall()
    restored = errors = 0
    for r in rows:
        dst = Path(r["target_path"])
        src = Path(r["src_path"])
        if not dst.exists():
            errors += 1
            continue
        src.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            # never overwrite a file QQ may have re-created at the original path
            src = _unique(src)
        try:
            shutil.move(str(dst), str(src))
            led.conn.execute("UPDATE files SET move_state='rolled_back', target_path=NULL, src_path=?, updated_at=? WHERE id=?",
                             (str(src), time.time(), r["id"]))
            with open(DATA / "moves.csv", "a", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow([time.strftime("%Y-%m-%d %H:%M:%S"), str(src), str(dst), r["md5"], "rollback", r["size"], ""])
            restored += 1
        except Exception as exc:  # noqa: BLE001
            led.conn.execute("UPDATE files SET error=?, updated_at=? WHERE id=?", (str(exc)[:300], time.time(), r["id"]))
            errors += 1
    led.commit()
    led.close()
    return {"restored": restored, "errors": errors}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["move", "rollback", "stats"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-md5", action="store_true")
    args = ap.parse_args()
    if args.action == "move":
        print(move_all(args.limit, args.dry_run, not args.no_md5))
    elif args.action == "rollback":
        print(rollback(args.limit))
    else:
        led = Ledger()
        print(led.stats())
        led.close()