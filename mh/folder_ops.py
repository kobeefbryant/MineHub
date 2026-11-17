"""Folder browsing and selected-media moves for the MineHub UI."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from .config import DATA, LIBRARY, MEDIA_ROOT
from .db import Ledger
from .stash import STASH_DB, Stash

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".avif", ".heic"}
VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v", ".wmv", ".flv", ".ts", ".mpg", ".mpeg"}
SAFE = MEDIA_ROOT / "safe"
EMBEDDING_SAFE = MEDIA_ROOT / "embeddingsafedata"
THUMB_CACHE = DATA / "cache" / "folder_thumbs"
ROOT = MEDIA_ROOT.resolve()


def media_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    return ""


def resolve_media(path: str | Path) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.is_relative_to(ROOT):
        raise PermissionError("只能访问资料库根目录内的媒体")
    if not p.is_file():
        raise FileNotFoundError(str(p))
    return p


def resolve_folder(path: str | Path) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.is_relative_to(ROOT):
        raise PermissionError("只能浏览资料库根目录内的文件夹")
    if not p.is_dir():
        raise FileNotFoundError(str(p))
    return p


def _relative_source(path: Path) -> Path:
    for root in (LIBRARY, SAFE, EMBEDDING_SAFE):
        try:
            return path.relative_to(root)
        except ValueError:
            pass
    return path.relative_to(ROOT)


def list_folder(path: str | Path, recursive: bool = True, kind: str = "all",
                page: int = 1, per_page: int = 120) -> dict[str, Any]:
    root = resolve_folder(path)
    page = max(1, int(page or 1))
    per_page = max(1, min(200, int(per_page or 120)))
    rows: list[dict[str, Any]] = []
    it = root.rglob("*") if recursive else root.iterdir()
    for p in it:
        if not p.is_file():
            continue
        k = media_kind(p)
        if not k or (kind in ("image", "video") and k != kind):
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        rows.append({"path": str(p), "name": p.name, "kind": k, "size": st.st_size,
                     "mtime": st.st_mtime, "rel": str(p.relative_to(root))})
    rows.sort(key=lambda x: (-x["mtime"], x["path"].lower()))
    total = len(rows)
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    start = (page - 1) * per_page
    return {"path": str(root), "recursive": recursive, "kind": kind, "page": page,
            "per_page": per_page, "pages": pages, "total": total,
            "files": rows[start:start + per_page]}


def thumbnail(path: str | Path, size: int = 320) -> Path:
    p = resolve_media(path)
    if media_kind(p) != "image":
        raise ValueError("不是图片")
    size = max(64, min(1600, int(size or 320)))
    st = p.stat()
    key = hashlib.sha1(
        f"{os.path.normcase(str(p))}|{st.st_size}|{st.st_mtime_ns}|{size}".encode("utf-8")
    ).hexdigest()
    out = THUMB_CACHE / key[:2] / f"{key}.jpg"
    if out.is_file():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(p) as im:
        try:
            im.seek(0)
        except Exception:
            pass
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((size, size), Image.LANCZOS)
        im.save(out, "JPEG", quality=84, optimize=True)
    return out


def _path_key(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _stash_image_ids_many(paths: list[Path]) -> dict[str, list[str]]:
    if not paths or not STASH_DB.is_file():
        return {}
    wanted: dict[str, set[str]] = defaultdict(set)
    for path in paths:
        wanted[str(path.parent)].add(path.name)
    out: dict[str, list[str]] = defaultdict(list)
    con = sqlite3.connect(f"file:{STASH_DB.as_posix()}?mode=ro", uri=True)
    try:
        parents = sorted(wanted)
        for start in range(0, len(parents), 400):
            chunk = parents[start:start + 400]
            placeholders = ",".join("?" for _ in chunk)
            rows = con.execute(
                f"""SELECT d.path, f.basename, im.image_id FROM files f
                    JOIN folders d ON d.id=f.parent_folder_id
                    JOIN images_files im ON im.file_id=f.id
                    WHERE d.path IN ({placeholders})""",
                chunk,
            ).fetchall()
            for parent, basename, image_id in rows:
                if basename in wanted.get(parent, ()) and image_id is not None:
                    out[_path_key(os.path.join(parent, basename))].append(str(image_id))
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    return {key: sorted(set(values)) for key, values in out.items()}


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    i = 2
    while True:
        candidate = path.with_name(f"{path.stem}__{i}{path.suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def _update_ledger_many(entries: list[tuple[Path, Path, str]], to_library: bool) -> list[str]:
    if not entries:
        return []
    errors: list[str] = []
    led = Ledger()
    try:
        # target_path/src_path have no useful composite index for one-row probes;
        # fetch the candidate rows once so a 100-file move does not scan the
        # 90k-row ledger 100 times.
        paths: list[str] = []
        for src, dst, _category in entries:
            paths.extend((str(src), str(dst)))
        paths = list(dict.fromkeys(paths))
        by_target: dict[str, sqlite3.Row] = {}
        by_src: dict[str, sqlite3.Row] = {}
        for start in range(0, len(paths), 300):
            chunk = paths[start:start + 300]
            placeholders = ",".join("?" for _ in chunk)
            rows = led.conn.execute(
                f"""SELECT id, src_path, target_path, final_json, category FROM files
                    WHERE target_path IN ({placeholders}) OR src_path IN ({placeholders})
                    ORDER BY id""",
                chunk + chunk,
            ).fetchall()
            for row in rows:
                if row["target_path"]:
                    by_target.setdefault(str(row["target_path"]), row)
                if row["src_path"]:
                    by_src.setdefault(str(row["src_path"]), row)
        now = time.time()
        for src, dst, category in entries:
            try:
                row = by_target.get(str(src)) or by_src.get(str(src))
                if row is None:
                    row = by_target.get(str(dst)) or by_src.get(str(dst))
                if row is None:
                    continue
                try:
                    final = json.loads(row["final_json"] or "{}")
                except Exception:
                    final = {}
                if category and category not in ("", "other"):
                    final["category"] = category
                state = "pending" if to_library else "training"
                led.conn.execute(
                    "UPDATE files SET target_path=?, category=?, move_state='moved', stash_state=?, "
                    "needs_review=?, final_json=?, updated_at=? WHERE id=?",
                    (str(dst), category or row["category"], state, 1 if to_library else 0,
                     json.dumps(final, ensure_ascii=False), now, row["id"]),
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{src}: 账本更新失败: {exc}")
        led.commit()
    finally:
        led.close()
    return errors


def move_files(paths: list[str], dest: str) -> dict[str, Any]:
    if dest not in ("library", "embeddingsafedata"):
        raise ValueError("dest 只能是 library 或 embeddingsafedata")
    if not paths:
        raise ValueError("没有选择文件")
    started = time.perf_counter()
    dest_root = LIBRARY if dest == "library" else EMBEDDING_SAFE
    dest_resolved = dest_root.resolve()
    to_library = dest == "library"
    moved: list[dict[str, Any]] = []
    errors: list[str] = []
    scan_dirs: set[str] = set()
    prepared: list[tuple[Path, Path, str]] = []
    seen: set[str] = set()
    for raw in paths:
        try:
            src = resolve_media(raw)
            if not any(src.is_relative_to(root) for root in (LIBRARY, SAFE, EMBEDDING_SAFE)):
                raise PermissionError("只能移动 library、safe 或 embeddingsafedata 中的文件")
            key = _path_key(src)
            if key in seen:
                continue
            seen.add(key)
            rel = _relative_source(src)
            if dest_resolved in src.parents:
                raise ValueError("文件已经在目标目录")
            category = rel.parts[0] if rel.parts and rel.parts[0] in {
                "daily", "sexy", "adult", "anime", "sticker", "screenshot", "review", "other"
            } else ""
            prepared.append((src, rel, category))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{raw}: {exc}")

    # Resolve all Stash records in one read-only query instead of opening
    # SQLite for every file while moving a large selection.
    stash_map = _stash_image_ids_many(
        [src for src, _rel, _cat in prepared if src.is_relative_to(LIBRARY) and not to_library]
    )
    image_ids: set[str] = set()
    ledger_entries: list[tuple[Path, Path, str]] = []
    pending_scan: set[str] = set()
    for src, rel, category in prepared:
        try:
            dst = _unique(dest_root / rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved.append({"src": str(src), "dst": str(dst)})
            ledger_entries.append((src, dst, category))
            if src.is_relative_to(LIBRARY) and not to_library:
                image_ids.update(stash_map.get(_path_key(src), []))
            if to_library:
                pending_scan.add(str(dst.parent))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{src}: {exc}")

    errors.extend(_update_ledger_many(ledger_entries, to_library))
    stash = Stash()
    destroy_errors: list[str] = []
    if image_ids:
        try:
            destroy_errors = stash.destroy_images(sorted(image_ids), delete_file=False)
        except Exception as exc:  # noqa: BLE001
            destroy_errors = [f"Stash 批量删除失败: {exc}"]
    errors.extend(destroy_errors)
    scan_job = ""
    if pending_scan:
        try:
            scan_job = stash.scan(sorted(pending_scan))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Stash 扫描失败: {exc}")
        scan_dirs.update(pending_scan)
    return {
        "moved": moved,
        "errors": errors,
        "dest": str(dest_root),
        "scan_job": scan_job,
        "stash_destroyed": len(image_ids) - len(destroy_errors),
        "scan_dirs": sorted(scan_dirs),
        "elapsed_s": round(time.perf_counter() - started, 3),
    }


def move_stash_items(items: list[dict[str, Any]], dest: str = "embeddingsafedata") -> dict[str, Any]:
    stash = Stash()
    paths: list[str] = []
    errors: list[str] = []
    for item in items:
        media_id = str(item.get("id") or "").strip()
        kind = str(item.get("kind") or "image").strip()
        if not media_id or kind != "image":
            errors.append(f"不支持的条目: {item}")
            continue
        try:
            paths.extend(stash.image_paths(media_id))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{media_id}: {exc}")
    result = move_files(paths, dest)
    result["errors"] = errors + result.get("errors", [])
    return result