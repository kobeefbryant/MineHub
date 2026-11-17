"""Nine independent images judged concurrently by the local Qwen3-VL Huihui model."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .config import VLM_PROMPT
from .folder_ops import IMAGE_EXTS, resolve_folder
from .serve import LlamaServer
from .vlm import VLM

NINE_PORT = 8091
NINE_SLOTS = 4


def list_images(folder: str | Path, limit: int = 9) -> list[Path]:
    root = resolve_folder(folder)
    paths = sorted(
        (p for p in root.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS),
        key=lambda p: p.name.lower(),
    )
    return paths[:max(1, min(9, int(limit or 9)))]


def _classify_one(index: int, path: Path, model: str, port: int) -> tuple[dict[str, Any], dict[str, Any]]:
    row, col = divmod(index, 3)
    vlm = VLM(model, port=port)
    try:
        verdict, meta = vlm.complete(
            [path], prompt=VLM_PROMPT, max_tokens=700, timeout=180, max_side=768,
        )
        level = str(verdict.get("nsfw_level") or "safe").lower()
        if level not in ("safe", "suggestive", "explicit"):
            level = "safe"
        keep = level in ("suggestive", "explicit") and bool(verdict.get("corporeal_nsfw"))
        reason = str(
            verdict.get("nsfw_evidence")
            or ", ".join(str(t) for t in (verdict.get("tags") or [])[:4])
            or verdict.get("main_subject")
            or ""
        )[:160]
        return {
            "index": index + 1,
            "row": row + 1,
            "col": col + 1,
            "keep": keep,
            "level": level,
            "reason": reason,
            "confidence": round(float(verdict.get("confidence") or 0), 3),
            "path": str(path),
        }, meta
    except Exception as exc:  # noqa: BLE001
        return {
            "index": index + 1,
            "row": row + 1,
            "col": col + 1,
            "keep": False,
            "level": "safe",
            "reason": f"单图判定失败: {exc}"[:160],
            "confidence": 0,
            "path": str(path),
            "error": str(exc)[:300],
        }, {}


def scan_folder(folder: str | Path, model: str = "huihui", port: int = NINE_PORT) -> dict[str, Any]:
    """Judge nine files independently; concurrency is across images, not in one prompt."""
    paths = list_images(folder)
    if not paths:
        raise ValueError("文件夹里没有图片")
    started = time.perf_counter()
    server: LlamaServer | None = None
    vlm = VLM(model, port=port)
    if not vlm.healthy():
        server = LlamaServer(model, slots=NINE_SLOTS, ctx=16384, port=port)
        server.__enter__()
    results: list[dict[str, Any]] = []
    usages: list[dict[str, Any]] = []
    try:
        with ThreadPoolExecutor(max_workers=min(NINE_SLOTS, len(paths))) as pool:
            futures = {
                pool.submit(_classify_one, index, path, model, port): index
                for index, path in enumerate(paths)
            }
            for future in as_completed(futures):
                cell, meta = future.result()
                results.append(cell)
                if meta:
                    usages.append(meta)
    finally:
        if server is not None:
            server.__exit__(None, None, None)
    results.sort(key=lambda cell: cell["index"])
    return {
        "folder": str(resolve_folder(folder)),
        "model": model,
        "mode": "concurrent_single",
        "slots": NINE_SLOTS,
        "count": len(paths),
        "cells": results,
        "verified": sum(1 for cell in results if not cell.get("error")),
        "elapsed_s": round(time.perf_counter() - started, 1),
        "usage": {
            "latency_s": round(sum(float(u.get("latency_s") or 0) for u in usages), 2),
            "prompt_tokens": sum(int(u.get("prompt_tokens") or 0) for u in usages),
            "completion_tokens": sum(int(u.get("completion_tokens") or 0) for u in usages),
        },
    }
