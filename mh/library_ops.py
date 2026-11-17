"""User-initiated deletion of MineHub library media."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from send2trash import send2trash

from .config import DATA, LIBRARY, QUARANTINE
from .db import Ledger
from .stash import Stash

ALLOWED_ROOTS = tuple(p.resolve() for p in (LIBRARY, QUARANTINE))
LOG_PATH = DATA / "logs" / "library_deletions.jsonl"


def _allowed(path: str) -> bool:
    p = Path(path).resolve()
    return any(p.is_relative_to(root) for root in ALLOWED_ROOTS)


def _paths_for(stash: Stash, kind: str, media_id: str) -> list[str]:
    if kind == "image":
        return stash.image_paths(media_id)
    if kind == "scene":
        return stash.scene_paths(media_id)
    raise ValueError(f"unknown kind: {kind}")


def _destroy(stash: Stash, kind: str, media_id: str, delete_file: bool) -> None:
    if kind == "image":
        stash.destroy_image(media_id, delete_file=delete_file)
    else:
        stash.destroy_scene(media_id, delete_file=delete_file)


def _mark_ledger(paths: list[str], state: str) -> None:
    if not paths:
        return
    led = Ledger()
    try:
        now = time.time()
        for path in paths:
            led.conn.execute(
                """UPDATE files SET move_state=?, target_path=?, stash_state='skipped', updated_at=?
                   WHERE target_path=? OR src_path=?""",
                (state, path, now, path, path),
            )
        led.commit()
    finally:
        led.close()


def delete_items(items: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    if mode not in ("trash", "delete"):
        raise ValueError("mode must be trash or delete")
    if not items:
        raise ValueError("没有选择文件")
    stash = Stash()
    results: list[dict[str, Any]] = []
    ok_count = 0
    for item in items:
        kind = str(item.get("kind") or "").strip()
        media_id = str(item.get("id") or "").strip()
        result: dict[str, Any] = {"kind": kind, "id": media_id, "ok": False, "paths": []}
        try:
            if not media_id:
                raise ValueError("缺少图片/场景 ID")
            paths = _paths_for(stash, kind, media_id)
            if any(not _allowed(path) for path in paths):
                raise PermissionError("只能删除 MineHub 库或 review 目录中的文件")
            result["paths"] = paths
            if mode == "trash":
                for path in paths:
                    if Path(path).exists():
                        send2trash(str(path))
                _destroy(stash, kind, media_id, delete_file=False)
            else:
                _destroy(stash, kind, media_id, delete_file=True)
                for path in paths:
                    if Path(path).exists():
                        Path(path).unlink()
            _mark_ledger(paths, "trashed" if mode == "trash" else "deleted")
            result["ok"] = True
            ok_count += 1
        except Exception as exc:  # noqa: BLE001
            result["error"] = str(exc)[:300]
        results.append(result)
    data = {
        "mode": mode,
        "deleted": ok_count,
        "failed": len(results) - ok_count,
        "items": results,
        "at": time.time(),
    }
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")
    return data