"""Perceptual duplicate detection for images and videos with adjustable thresholds."""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

import numpy as np
from PIL import Image, ImageOps

from .config import DATA, IMAGE_EXTS, LIBRARY, QQ_ACCOUNTS, VIDEO_EXTS
from .manager import _find_thumb

DUPES_DB = DATA / "dupes.sqlite"
HASH_SIZE = 16
HASH_BITS = HASH_SIZE * HASH_SIZE
MAX_THRESHOLD = 40
ALGOS = ("ahash", "dhash", "phash")
SCOPES = ("library", "qq", "folder")
VIDEO_FRAMES = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    scope     TEXT NOT NULL,
    path      TEXT NOT NULL,
    name      TEXT,
    size      INTEGER,
    mtime     REAL,
    kind      TEXT,
    width     INTEGER,
    height    INTEGER,
    ahash     TEXT,
    dhash     TEXT,
    phash     TEXT,
    frames    TEXT,
    error     TEXT,
    hashed_at REAL,
    PRIMARY KEY(scope, path)
);
CREATE INDEX IF NOT EXISTS idx_dupes_scope ON items(scope);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""

_DCT = None


def _dct_matrix(n: int = 32) -> np.ndarray:
    global _DCT
    if _DCT is None:
        k = np.arange(n, dtype=np.float64)[:, None]
        x = np.arange(n, dtype=np.float64)[None, :]
        mat = np.cos(np.pi * (2 * x + 1) * k / (2 * n)) * np.sqrt(2.0 / n)
        mat[0, :] *= np.sqrt(0.5)
        _DCT = mat
    return _DCT


def _pack(bits: np.ndarray) -> str:
    return np.packbits(bits.reshape(-1).astype(np.uint8)).tobytes().hex()


def _hash_arrays(gray: Image.Image) -> dict[str, str]:
    small = np.asarray(gray.resize((HASH_SIZE, HASH_SIZE), Image.Resampling.LANCZOS), dtype=np.float32)
    ahash = _pack(small > small.mean())

    wide = np.asarray(gray.resize((HASH_SIZE + 1, HASH_SIZE), Image.Resampling.LANCZOS), dtype=np.float32)
    dhash = _pack(wide[:, 1:] > wide[:, :-1])

    dct_size = 32
    dct_img = np.asarray(gray.resize((dct_size, dct_size), Image.Resampling.LANCZOS), dtype=np.float32)
    d = _dct_matrix(dct_size)
    low = (d @ dct_img @ d.T)[:HASH_SIZE, :HASH_SIZE]
    phash = _pack(low > np.median(low))

    out = {"ahash": ahash, "dhash": dhash, "phash": phash}
    for name, value in list(out.items()):
        if value in ("", "00" * (HASH_BITS // 8), "ff" * (HASH_BITS // 8)):
            out[name] = ""
    return out


def hash_file(path: str | Path) -> dict:
    started = time.time()
    path = Path(path)
    try:
        with Image.open(path) as im:
            if im.format == "JPEG":
                im.draft("L", (128, 128))
            if im.getexif().get(0x0112):
                im = ImageOps.exif_transpose(im)
            im.seek(0)
            width, height = im.size
            gray = im.convert("L")
            hashes = _hash_arrays(gray)
        return {"width": width, "height": height, **hashes, "frames": "",
                "error": "", "seconds": time.time() - started}
    except Exception as exc:  # noqa: BLE001
        return {"width": 0, "height": 0, "ahash": "", "dhash": "", "phash": "",
                "frames": "", "error": str(exc)[:200], "seconds": time.time() - started}


def hash_video(path: str | Path, count: int = VIDEO_FRAMES) -> dict:
    started = time.time()
    from .frames import cleanup_frames, extract_frames

    frames = extract_frames(path, count=count, max_side=512)
    try:
        hashes: list[str] = []
        width = 0
        height = 0
        for frame in frames:
            result = hash_file(frame)
            signature = result.get("phash") or result.get("dhash") or result.get("ahash")
            if signature:
                hashes.append(signature)
                width = width or int(result.get("width") or 0)
                height = height or int(result.get("height") or 0)
        if not hashes:
            return {"width": 0, "height": 0, "ahash": "", "dhash": "", "phash": "",
                    "frames": "", "error": "无法从视频提取关键帧", "seconds": time.time() - started}
        return {"width": width, "height": height, "ahash": "", "dhash": "", "phash": "",
                "frames": ",".join(hashes), "error": "", "seconds": time.time() - started}
    finally:
        cleanup_frames(frames)


class BKTree:
    __slots__ = ("root",)

    class Node:
        __slots__ = ("key", "children")

        def __init__(self, key: int) -> None:
            self.key = key
            self.children: dict[int, "BKTree.Node"] = {}

    def __init__(self) -> None:
        self.root: BKTree.Node | None = None

    def add(self, key: int) -> None:
        if self.root is None:
            self.root = self.Node(key)
            return
        node = self.root
        while True:
            distance = (key ^ node.key).bit_count()
            child = node.children.get(distance)
            if child is None:
                node.children[distance] = self.Node(key)
                return
            node = child

    def search(self, key: int, max_distance: int) -> list[tuple[int, int]]:
        if self.root is None:
            return []
        out: list[tuple[int, int]] = []
        stack = [self.root]
        while stack:
            node = stack.pop()
            distance = (key ^ node.key).bit_count()
            if distance <= max_distance:
                out.append((distance, node.key))
            for edge, child in node.children.items():
                if abs(edge - distance) <= max_distance:
                    stack.append(child)
        return out


def _norm(path: str | Path) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(str(path))))


def _thumb_url(path: str) -> str:
    return f"/mh/api/pm/thumb?path={quote(path)}&size=320"


class DuplicateStore:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.job: dict = {"status": "idle"}
        self.version = 0
        self._group_cache: dict[tuple, dict] = {}
        self._stash_map: dict[str, dict] | None = None
        self._stash_at = 0.0
        DATA.mkdir(parents=True, exist_ok=True)
        with self._conn() as con:
            con.executescript(SCHEMA)
            columns = {row[1] for row in con.execute("PRAGMA table_info(items)")}
            if "frames" not in columns:
                con.execute("ALTER TABLE items ADD COLUMN frames TEXT")

    def _conn(self) -> sqlite3.Connection:
        con = sqlite3.connect(DUPES_DB, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def _setting(self, key: str, default: str = "") -> str:
        con = self._conn()
        try:
            row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return str(row["value"]) if row else default
        finally:
            con.close()

    def _save_setting(self, key: str, value: str) -> None:
        con = self._conn()
        try:
            con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value))
            con.commit()
        finally:
            con.close()

    # ---------- scans ----------
    def status(self, scope: str = "library") -> dict:
        with self.lock:
            job = dict(self.job)
        con = self._conn()
        try:
            total = con.execute("SELECT COUNT(*) FROM items WHERE scope=?", (scope,)).fetchone()[0]
            hashed = con.execute(
                "SELECT COUNT(*) FROM items WHERE scope=? AND "
                "(ahash!='' OR dhash!='' OR phash!='' OR frames!='')",
                (scope,),
            ).fetchone()[0]
            errors = con.execute(
                "SELECT COUNT(*) FROM items WHERE scope=? AND error!=''", (scope,)
            ).fetchone()[0]
            latest = con.execute(
                "SELECT MAX(hashed_at) FROM items WHERE scope=?", (scope,)
            ).fetchone()[0] or 0
            counts = {row["kind"]: row["n"] for row in con.execute(
                "SELECT kind, COUNT(*) AS n FROM items WHERE scope=? GROUP BY kind", (scope,)
            )}
        finally:
            con.close()
        root = self._setting("folder_root") if scope == "folder" else ""
        recursive = self._setting("folder_recursive", "1") == "1"
        return {"scope": scope, "items": total, "hashed": hashed, "errors": errors,
                "hashed_at": latest, "job": job, "algorithms": list(ALGOS),
                "max_threshold": MAX_THRESHOLD, "hash_bits": HASH_BITS,
                "root": root, "recursive": recursive,
                "images": int(counts.get("image", 0)), "videos": int(counts.get("video", 0))}

    def start(self, scope: str = "library", limit: int = 0, force: bool = False,
              root: str = "", recursive: bool = True) -> dict:
        if scope not in SCOPES:
            raise ValueError(f"unknown scope: {scope}")
        root_path: Path | None = None
        if scope == "folder":
            raw = str(root or "").strip() or self._setting("folder_root")
            if not raw:
                raise ValueError("需要指定要扫描的文件夹")
            root_path = Path(raw).expanduser().resolve()
            if not root_path.is_dir():
                raise ValueError(f"文件夹不存在：{root_path}")
            if root_path.parent == root_path:
                raise ValueError("请不要扫描磁盘根目录")
            self._save_setting("folder_root", str(root_path))
            self._save_setting("folder_recursive", "1" if recursive else "0")
        with self.lock:
            if self.job.get("status") == "running":
                return dict(self.job)
            self.job = {"status": "running", "scope": scope, "done": 0, "total": 0,
                        "errors": 0, "started_at": time.time(),
                        "root": str(root_path or ""), "recursive": bool(recursive)}
        threading.Thread(target=self._scan, args=(scope, max(0, limit), bool(force),
                                                  root_path, bool(recursive)), daemon=True).start()
        return dict(self.job)

    def _paths(self, scope: str, root: Path | None = None, recursive: bool = True) -> list[Path]:
        if scope == "library":
            return [p for p in LIBRARY.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
        if scope == "folder":
            if root is None or not root.is_dir():
                return []
            out: list[Path] = []
            if recursive:
                for dirpath, dirnames, filenames in os.walk(root):
                    dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                    for name in filenames:
                        ext = Path(name).suffix.lower()
                        if ext in IMAGE_EXTS or ext in VIDEO_EXTS:
                            out.append(Path(dirpath) / name)
            else:
                for entry in os.scandir(root):
                    if entry.is_file(follow_symlinks=False):
                        ext = Path(entry.name).suffix.lower()
                        if ext in IMAGE_EXTS or ext in VIDEO_EXTS:
                            out.append(Path(entry.path))
            return out
        out: list[Path] = []
        for nt_data in QQ_ACCOUNTS:
            root = nt_data / "Pic"
            if not root.is_dir():
                continue
            for p in root.rglob("*"):
                if p.is_file() and p.suffix.lower() in IMAGE_EXTS and p.parent.name.lower() != "thumb":
                    out.append(p)
        return out

    def _scan(self, scope: str, limit: int, force: bool,
              root: Path | None = None, recursive: bool = True) -> None:
        try:
            paths = self._paths(scope, root, recursive)
            if limit:
                paths = paths[:limit]
            con = self._conn()
            existing = {
                r["path"]: r
                for r in con.execute(
                    "SELECT path,size,mtime,kind,ahash,dhash,phash,frames,error "
                    "FROM items WHERE scope=?", (scope,)
                )
            }
            with self.lock:
                self.job.update({"total": len(paths), "done": 0, "errors": 0})
            stale = set(existing) - {str(p) for p in paths}
            if stale and not limit:
                con.executemany("DELETE FROM items WHERE scope=? AND path=?", [(scope, p) for p in stale])
                con.commit()

            errors = 0
            done = 0
            pending: list[tuple] = []
            hashed_this_round = 0

            def hash_one(path: Path) -> tuple[Path, str, dict, bool]:
                kind = "video" if path.suffix.lower() in VIDEO_EXTS else "image"
                row = existing.get(str(path))
                cached_hash = bool(row and (row["frames"] if kind == "video"
                                           else (row["ahash"] or row["dhash"] or row["phash"])))
                if (not force and row is not None and row["size"] == path.stat().st_size
                        and abs(float(row["mtime"]) - path.stat().st_mtime) < 1e-6
                        and cached_hash):
                    return path, kind, {}, True
                source = path
                if scope == "qq" and kind == "image":
                    thumb = _find_thumb(str(path))
                    if thumb is not None:
                        source = thumb
                result = hash_video(source) if kind == "video" else hash_file(source)
                if kind == "image" and path.suffix.lower() == ".null" and result.get("error"):
                    video_result = hash_video(source)
                    if not video_result.get("error"):
                        kind = "video"
                        result = video_result
                return path, kind, result, False

            workers = 2 if scope == "folder" else 4
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(hash_one, p): p for p in paths}
                for future in as_completed(futures):
                    path = futures[future]
                    kind = "video" if path.suffix.lower() in VIDEO_EXTS else "image"
                    try:
                        path, kind, result, cached = future.result()
                        if cached:
                            done += 1
                            with self.lock:
                                self.job.update({"done": done, "errors": errors})
                            continue
                        st = path.stat()
                        pending.append((
                            scope, str(path), path.name, st.st_size, st.st_mtime,
                            kind, result.get("width", 0), result.get("height", 0),
                            result.get("ahash", ""), result.get("dhash", ""), result.get("phash", ""),
                            result.get("frames", ""), result.get("error", ""), time.time(),
                        ))
                        hashed_this_round += 1
                        if result.get("error"):
                            errors += 1
                    except Exception as exc:  # noqa: BLE001
                        errors += 1
                        pending.append((
                            scope, str(path), path.name, 0, 0, kind, 0, 0,
                            "", "", "", "", str(exc)[:200], time.time(),
                        ))
                    done += 1
                    if len(pending) >= 200:
                        con.executemany(
                            """INSERT INTO items(scope,path,name,size,mtime,kind,width,height,
                               ahash,dhash,phash,frames,error,hashed_at)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                               ON CONFLICT(scope,path) DO UPDATE SET
                               size=excluded.size,mtime=excluded.mtime,width=excluded.width,
                               height=excluded.height,ahash=excluded.ahash,dhash=excluded.dhash,
                               phash=excluded.phash,frames=excluded.frames,
                               error=excluded.error,hashed_at=excluded.hashed_at""",
                            pending,
                        )
                        con.commit()
                        pending.clear()
                    with self.lock:
                        self.job.update({"done": done, "errors": errors})
            if pending:
                con.executemany(
                    """INSERT INTO items(scope,path,name,size,mtime,kind,width,height,
                       ahash,dhash,phash,frames,error,hashed_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(scope,path) DO UPDATE SET
                       size=excluded.size,mtime=excluded.mtime,width=excluded.width,
                       height=excluded.height,ahash=excluded.ahash,dhash=excluded.dhash,
                       phash=excluded.phash,frames=excluded.frames,
                       error=excluded.error,hashed_at=excluded.hashed_at""",
                    pending,
                )
                con.commit()
            con.close()
            with self.lock:
                self.version += 1
                self._group_cache.clear()
                self.job.update({"status": "done", "done": done, "total": len(paths),
                                 "errors": errors, "hashed_this_round": hashed_this_round,
                                 "ended_at": time.time()})
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                self.job.update({"status": "error", "error": str(exc)[:300], "ended_at": time.time()})

    # ---------- grouping ----------
    def _stash_paths(self) -> dict[str, dict]:
        if self._stash_map is not None and time.time() - self._stash_at < 600:
            return self._stash_map
        mapping: dict[str, dict] = {}
        try:
            from .stash import Stash

            stash = Stash()
            for kind in ("image", "scene"):
                for obj in stash._all_objects(kind):
                    if not obj.get("path"):
                        continue
                    mapping.setdefault(_norm(obj["path"]), {"kind": kind, "stash_id": obj["id"]})
        except Exception:  # noqa: BLE001
            mapping = {}
        self._stash_map = mapping
        self._stash_at = time.time()
        return mapping

    @staticmethod
    def _video_signature(raw: str) -> list[int]:
        out: list[int] = []
        for value in str(raw or "").split(","):
            value = value.strip()
            if not value:
                continue
            try:
                out.append(int(value, 16))
            except ValueError:
                continue
        return out

    @staticmethod
    def _video_distance(left: list[int], right: list[int]) -> int:
        size = min(len(left), len(right))
        if size == 0:
            return MAX_THRESHOLD + 1
        return max((left[i] ^ right[i]).bit_count() for i in range(size))

    def _member(self, row: dict, distance: int | None, stash: dict[str, dict]) -> dict:
        mapped = stash.get(_norm(row["path"]), {})
        kind = row.get("kind") or "image"
        return {
            "path": row["path"], "name": row["name"], "size": row["size"],
            "width": row["width"], "height": row["height"], "kind": kind,
            "distance": distance, "thumb_url": _thumb_url(row["path"]),
            "stash_id": mapped.get("stash_id", ""),
            "page_url": (f"/{ 'images' if mapped.get('kind') == 'image' else 'scenes' }/{mapped['stash_id']}"
                         if mapped.get("stash_id") else ""),
        }

    def _group_images(self, rows: list[dict], threshold: int,
                      stash: dict[str, dict]) -> list[dict]:
        by_hash: dict[int, list[dict]] = {}
        valid: list[dict] = []
        for row in rows:
            try:
                value = int(row["hash"], 16)
            except (TypeError, ValueError):
                continue
            row["h"] = value
            by_hash.setdefault(value, []).append(row)
            valid.append(row)
        if not valid:
            return []
        tree = BKTree()
        for value in by_hash:
            tree.add(value)
        assigned: set[str] = set()
        groups_out: list[dict] = []
        for row in sorted(valid, key=lambda r: (-int(r["size"] or 0), r["path"])):
            if row["path"] in assigned:
                continue
            matches = tree.search(row["h"], threshold)
            matches.sort(key=lambda x: x[0])
            cluster = [row]
            cluster_paths = {row["path"]}
            for _distance, value in matches:
                for other in by_hash.get(value, []):
                    if other["path"] in assigned or other["path"] in cluster_paths:
                        continue
                    if all(((other["h"] ^ member["h"]).bit_count() <= threshold)
                           for member in cluster):
                        cluster.append(other)
                        cluster_paths.add(other["path"])
            if len(cluster) < 2:
                continue
            for item in cluster:
                assigned.add(item["path"])
            ordered = [row] + [item for item in cluster if item["path"] != row["path"]]
            ordered.sort(key=lambda item: ((item["h"] ^ row["h"]).bit_count(),
                                            -int(item["size"] or 0)))
            ordered = [row] + [item for item in ordered if item["path"] != row["path"]]
            members = [self._member(item, (item["h"] ^ row["h"]).bit_count(), stash)
                       for item in ordered]
            groups_out.append({
                "representative": members[0],
                "members": members[1:],
                "count": len(members),
                "total_size": sum(int(item["size"] or 0) for item in members),
                "max_distance": max(item["distance"] for item in members),
                "kind": "image",
            })
        return groups_out

    def _group_videos(self, rows: list[dict], threshold: int,
                      stash: dict[str, dict]) -> list[dict]:
        videos: list[dict] = []
        for row in rows:
            signature = self._video_signature(row.get("frames", ""))
            if not signature:
                continue
            row["sig"] = signature
            videos.append(row)
        assigned: set[str] = set()
        groups_out: list[dict] = []
        for row in sorted(videos, key=lambda item: (-int(item["size"] or 0), item["path"])):
            if row["path"] in assigned:
                continue
            candidates: list[tuple[int, dict]] = []
            for other in videos:
                if other is row or other["path"] in assigned:
                    continue
                distance = self._video_distance(row["sig"], other["sig"])
                if distance <= threshold:
                    candidates.append((distance, other))
            candidates.sort(key=lambda item: (item[0], item[1]["path"]))
            cluster = [row]
            cluster_paths = {row["path"]}
            for distance, other in candidates:
                if any(self._video_distance(other["sig"], item["sig"]) > threshold
                       for item in cluster):
                    continue
                cluster.append(other)
                cluster_paths.add(other["path"])
            if len(cluster) < 2:
                continue
            for item in cluster:
                assigned.add(item["path"])
            ordered = [row] + [item for item in cluster if item["path"] != row["path"]]
            ordered.sort(key=lambda item: (self._video_distance(item["sig"], row["sig"]),
                                            -int(item["size"] or 0)))
            ordered = [row] + [item for item in ordered if item["path"] != row["path"]]
            members = [self._member(item, self._video_distance(item["sig"], row["sig"]), stash)
                       for item in ordered]
            groups_out.append({
                "representative": members[0],
                "members": members[1:],
                "count": len(members),
                "total_size": sum(int(item["size"] or 0) for item in members),
                "max_distance": max(item["distance"] for item in members),
                "kind": "video",
            })
        return groups_out

    def groups(self, scope: str = "library", algo: str = "phash",
               threshold: int = 10, limit: int = 60) -> dict:
        if scope not in SCOPES:
            raise ValueError(f"unknown scope: {scope}")
        if algo not in ALGOS:
            raise ValueError(f"unknown algorithm: {algo}")
        threshold = max(0, min(MAX_THRESHOLD, int(threshold)))
        key = (scope, algo, threshold, self.version, self._setting("folder_root"))
        with self.lock:
            cached = self._group_cache.get(key)
        if cached is not None:
            return self._slice_groups(cached, limit)

        con = self._conn()
        try:
            rows = [dict(r) for r in con.execute(
                f"SELECT path,name,kind,size,mtime,width,height,{algo} AS hash,frames "
                "FROM items WHERE scope=? AND error=''",
                (scope,),
            )]
        finally:
            con.close()
        image_rows = [row for row in rows if row.get("kind") != "video" and row.get("hash")]
        video_rows = [row for row in rows if row.get("kind") == "video" and row.get("frames")]
        stash = self._stash_paths()
        groups_out = self._group_images(image_rows, threshold, stash)
        groups_out += self._group_videos(video_rows, threshold, stash)
        groups_out.sort(key=lambda group: (-group["total_size"], -group["count"]))
        root = self._setting("folder_root") if scope == "folder" else ""
        result = {"scope": scope, "algo": algo, "threshold": threshold, "root": root,
                  "groups": groups_out, "total_groups": len(groups_out),
                  "total_files": sum(group["count"] for group in groups_out),
                  "hashed": len(rows), "images": len(image_rows), "videos": len(video_rows)}
        with self.lock:
            if len(self._group_cache) > 8:
                self._group_cache.clear()
            self._group_cache[key] = result
        return self._slice_groups(result, limit)

    @staticmethod
    def _slice_groups(result: dict, limit: int) -> dict:
        limit = max(1, min(200, int(limit)))
        out = dict(result)
        out["groups"] = result["groups"][:limit]
        out["returned"] = len(out["groups"])
        return out

    # ---------- Stash scene pHash ----------
    def scenes(self, distance: int = 10, limit: int = 60) -> dict:
        from .stash import Stash

        distance = max(0, min(MAX_THRESHOLD, int(distance)))
        query = """query($d:Int!){ findDuplicateScenes(distance:$d){
            id title paths { screenshot } files { path size }
        } }"""
        rows = Stash().graphql(query, {"d": distance})["findDuplicateScenes"]
        groups_out: list[dict] = []
        for group in rows:
            members: list[dict] = []
            for scene in group:
                files = scene.get("files") or []
                path = files[0].get("path", "") if files else ""
                size = sum(int(f.get("size") or 0) for f in files)
                shot = (scene.get("paths") or {}).get("screenshot") or ""
                shot = shot.replace("http://127.0.0.1:9998", "http://127.0.0.1:9999")
                members.append({
                    "path": path, "name": f"场景 #{scene['id']}", "size": size,
                    "width": 0, "height": 0, "distance": None,
                    "thumb_url": shot or _thumb_url(path),
                    "stash_id": scene["id"], "page_url": f"/scenes/{scene['id']}",
                })
            if len(members) < 2:
                continue
            members.sort(key=lambda x: -int(x["size"] or 0))
            groups_out.append({
                "representative": members[0], "members": members[1:],
                "count": len(members), "total_size": sum(int(m["size"] or 0) for m in members),
                "max_distance": None,
            })
        groups_out.sort(key=lambda g: (-g["total_size"], -g["count"]))
        limit = max(1, min(200, int(limit)))
        return {"scope": "scene", "algo": "stash-phash", "threshold": distance,
                "scene_mode": True, "groups": groups_out[:limit],
                "total_groups": len(groups_out),
                "total_files": sum(g["count"] for g in groups_out),
                "hashed": sum(g["count"] for g in groups_out), "returned": min(limit, len(groups_out))}

    # ---------- exact duplicates ----------
    def exact(self, limit: int = 60) -> dict:
        from .config import DB_PATH

        con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True, timeout=10)
        try:
            rows = con.execute(
                """SELECT md5, size, src_path, target_path, move_state
                   FROM files WHERE md5 IS NOT NULL AND md5!=''"""
            ).fetchall()
        finally:
            con.close()
        by_md5: dict[str, list[tuple]] = {}
        for row in rows:
            by_md5.setdefault(row[0], []).append(row)
        groups = []
        for md5, items in by_md5.items():
            if len(items) < 2:
                continue
            members = []
            for _, size, src, target, state in items:
                path = target or src
                members.append({"path": path, "name": Path(path).name if path else "",
                                "size": int(size or 0), "state": state or ""})
            members.sort(key=lambda x: (-x["size"], x["path"]))
            groups.append({"md5": md5, "count": len(members), "total_size": sum(m["size"] for m in members),
                           "members": members})
        groups.sort(key=lambda g: (-g["total_size"], -g["count"]))
        limit = max(1, min(200, int(limit)))
        return {"total_groups": len(groups), "total_files": sum(g["count"] for g in groups),
                "groups": groups[:limit], "returned": min(limit, len(groups)),
                "note": "完全相同文件来自 MineHub 账本 MD5，不重新读盘"}