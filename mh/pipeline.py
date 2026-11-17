"""Unattended end-to-end pipeline: A -> B -> finalize -> move -> Stash scan/tag."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import traceback

from .config import DATA, LIBRARY, LOG_DIR, ensure_dirs
from .db import Ledger

LOG_PATH = LOG_DIR / "pipeline.log"
LOCK_PATH = DATA / "pipeline.lock"


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    try:
        import psutil

        return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
    except Exception:
        return False


def acquire_lock() -> bool:
    if LOCK_PATH.exists():
        try:
            pid = int(LOCK_PATH.read_text().strip())
        except ValueError:
            pid = 0
        if pid and _pid_alive(pid) and pid != os.getpid():
            log(f"pipeline already running (pid {pid}); exiting")
            return False
    LOCK_PATH.write_text(str(os.getpid()))
    return True


def release_lock() -> None:
    try:
        if LOCK_PATH.read_text().strip() == str(os.getpid()):
            LOCK_PATH.unlink()
    except OSError:
        pass


def ensure_stash(timeout: float = 180):
    from .stash import Stash, start_stash

    s = Stash()
    if s.wait_ready(5):
        return s
    log("starting stash ...")
    subprocess.run(["taskkill", "/IM", "stash-win.exe", "/F"], capture_output=True)
    time.sleep(2)
    p = start_stash()
    log(f"stash pid {p.pid}")
    if not s.wait_ready(timeout):
        raise RuntimeError("stash did not become ready")
    return s


def free_space_guard() -> None:
    from .stage3 import NSFW_SQL

    led = Ledger()
    need = led.conn.execute(
        f"SELECT COALESCE(SUM(size),0) FROM files WHERE final_json IS NOT NULL AND move_state='pending' "
        f"AND is_thumb=0 AND ({NSFW_SQL})"
    ).fetchone()[0]
    led.close()
    free = shutil.disk_usage(LIBRARY).free
    log(f"move needs {need / 1e9:.1f} GB, free {free / 1e9:.1f} GB")
    if free < need + 5 * 1024**3:
        raise RuntimeError("not enough free space on library drive")


def prevent_sleep() -> None:
    """Keep the machine awake while this process runs (process-scoped, reversible)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    except Exception:
        pass


def run(limit_a: int = 0) -> None:
    ensure_dirs()
    prevent_sleep()
    if not acquire_lock():
        return
    try:
        from .stage1 import run_stage1
        from .stage2 import finalize, run_a, run_b
        from .stage3 import move_all

        log("=== stage2 A (Qwen3-VL NSFW) start ===")
        log(str(run_a(4, 16384, 4, limit_a)))
        log("=== stage2 A done ===")

        log("=== stage1 for pending images (thumb-only imports) ===")
        log(str(run_stage1(96, 0, False, quiet=True)))
        # Do not fast-route thumb-only images: SigLIP alone misses explicit
        # previews whose first/representative frame looks safe. Let stage2 A
        # classify every thumb-only image.
        log("=== stage2 A for thumb-only images ===")
        log(str(run_a(4, 16384, 4, 0)))
        log("=== stage2 A done (thumbs) ===")

        log("=== stage2 B (Huihui arbitration) start ===")
        log(str(run_b(4, 16384, 4, 0)))
        log("=== stage2 B done ===")

        from .verify import verify_siglip_explicit

        log("=== verify SigLIP-only explicit with VLM ===")
        log(str(verify_siglip_explicit(0)))

        n = finalize()
        log(f"finalized rows: {n}")

        free_space_guard()
        log("=== stage3 move start ===")
        log(str(move_all(0, False, True)))
        log("=== stage3 move done ===")
        from .thumb_audit import promote_candidates, repair_states, run_move, run_siglip, run_vlm, scan

        log("=== qq thumb audit: scan ===")
        log(str(scan()))
        log("=== qq thumb audit: siglip ===")
        log(str(run_siglip()))
        log("=== qq thumb audit: repair ===")
        log(str(repair_states()))
        log("=== qq thumb audit: promote ===")
        log(str(promote_candidates()))
        log("=== qq thumb audit: vlm ===")
        log(str(run_vlm(slots=4, workers=4)))
        log("=== qq thumb audit: move ===")
        log(str(run_move(0, False, False)))

        from .reaudit import run as reaudit_run, select as reaudit_select

        log("=== kept-original second-pass audit ===")
        log(str(reaudit_select()))
        log(str(reaudit_run("huihui", 4, 4, 0)))

        free_space_guard()
        log(str(move_all(0, False, True)))
        log("=== qq thumb audit + reaudit done ===")

        s = ensure_stash()
        log("=== stash scan start ===")
        job = s.scan()
        log(f"scan job {job}")
        status = s.wait_job(job)
        log(f"scan finished: {status}")

        for attempt in range(3):
            res = s.push_tags()
            log(f"tag pass {attempt + 1}: {res}")
            if res.get("unmatched", 0) == 0:
                break
            job = s.scan()
            s.wait_job(job)
        log("=== pipeline complete ===")
    except Exception as exc:  # noqa: BLE001
        log(f"PIPELINE ERROR: {exc}")
        log(traceback.format_exc())
        raise
    finally:
        led = Ledger()
        log("stats: " + str(led.stats()))
        led.close()
        release_lock()


if __name__ == "__main__":
    sys.exit(run())