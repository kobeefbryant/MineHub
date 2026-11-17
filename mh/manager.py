"""QQ cache manager backing the in-Stash MineHub panel."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .config import DATA, IMAGE_EXTS, LIBRARY, MEDIA_ROOT, QUARANTINE, QQ_ACCOUNTS, VIDEO_EXTS
from .qq import keys as qq_keys
from .qq.indexer import build_index

CACHE_DIR = MEDIA_ROOT / "cache" / "pm_thumbs"
QQ_INDEX_DIR = DATA / "qq"
LEGACY_INDEX = Path(os.environ.get("LOCALAPPDATA", "")) / "PicManager" / "qq_index.sqlite"
LEGACY_ACCOUNT = next((p.parent.parent.name for p in QQ_ACCOUNTS), "")
FFMPEG = Path("D:/ffmpeg/bin/ffmpeg.exe")
MD5_RE = re.compile(r"^([0-9a-fA-F]{32})(?:_\d+)?$")
MAX_THUMB = 2048


@dataclass(slots=True)
class FileRec:
    path: str
    name: str
    rel_dir: str
    size: int
    mtime: float
    kind: str
    md5: str
    variant: str


def _norm(path: str | Path) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(str(path))))


def _under(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([_norm(path), _norm(root)]) == _norm(root)
    except ValueError:
        return False


def _parse_md5(name: str) -> str:
    stem = os.path.splitext(name)[0]
    m = MD5_RE.match(stem)
    return m.group(1).lower() if m else ""


def _account_of(path: str) -> str:
    parts = Path(path).parts
    for i, part in enumerate(parts):
        if part.lower() == "tencent files" and i + 1 < len(parts):
            return parts[i + 1]
    return ""


def _find_thumb(path: str) -> Path | None:
    p = Path(path)
    if p.parent.name.lower() == "thumb":
        return p if p.is_file() else None
    md5 = _parse_md5(p.name)
    if not md5 or p.parent.name.lower() != "ori":
        return None
    thumb_dir = p.parent.parent / "Thumb"
    for suffix in ("_0.png", "_720.png", "_0.jpg", "_720.jpg", "_0.webp"):
        cand = thumb_dir / (md5 + suffix)
        if cand.is_file():
            return cand
    return None


class Manager:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.records: list[FileRec] = []
        self.record_roots: tuple[str, ...] = ()
        self.scanned_at = 0.0
        self.labels: dict[str, dict] = {}
        self.label_tags: dict[str, int] = {}
        self.chats: list[dict] = []
        self.chat_map: dict[str, list[dict]] = {}
        self.indexes: dict[str, dict] = {}
        self.index_job: dict = {"status": "idle"}
        self.thumb_sem = threading.Semaphore(6)
        self.allowed_roots: list[str] = [str(a) for a in QQ_ACCOUNTS] + [str(LIBRARY), str(QUARANTINE)]
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        QQ_INDEX_DIR.mkdir(parents=True, exist_ok=True)
        self.reload_labels()
        self.load_indexes()

    # ---------- configuration ----------
    def allow_root(self, root: str) -> str:
        path = Path(root).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"文件夹不存在：{path}")
        if path.parent == path:
            raise ValueError("请不要扫描磁盘根目录")
        with self.lock:
            if _norm(str(path)) not in {_norm(item) for item in self.allowed_roots}:
                self.allowed_roots.append(str(path))
        return str(path)

    def roots(self) -> list[dict]:
        out: list[dict] = []
        for nt_data in QQ_ACCOUNTS:
            account = nt_data.parent.parent.name
            for kind in ("Pic", "Video"):
                d = nt_data / kind
                if d.is_dir():
                    out.append({"label": f"{account} · {kind}", "path": str(d), "account": account})
        if LIBRARY.is_dir():
            out.append({"label": "MineHub · NSFW 库", "path": str(LIBRARY), "account": ""})
        return out

    def config(self) -> dict:
        return {
            "roots": self.roots(),
            "default_root": self.roots()[0]["path"] if self.roots() else "",
            "move_default": str(LIBRARY / "review"),
            "indexes": self.index_status(),
            "categories": [
                ["all", "全部分类"], ["nsfw", "仅 NSFW"], ["safe", "仅安全"],
                ["daily", "日常"], ["screenshot", "截图"], ["anime", "二次元"],
                ["adult", "成人"], ["sexy", "性感"], ["sticker", "表情包"],
                ["review", "待复核"], ["other", "其他"],
            ],
            "levels": [["all", "全部等级"], ["safe", "安全"], ["suggestive", "擦边"], ["explicit", "露骨"]],
            "scanned": len(self.records),
            "scanned_at": int(self.scanned_at),
        }

    # ---------- labels ----------
    def reload_labels(self) -> dict:
        labels: dict[str, dict] = {}
        tag_counts: dict[str, int] = {}
        db = DATA / "minehub.sqlite"
        count = 0
        if db.is_file():
            con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=10)
            try:
                rows = con.execute(
                    """SELECT src_path, target_path, category, needs_review, origin, final_json, stage2_json
                       FROM files WHERE final_json IS NOT NULL OR stage2_json IS NOT NULL"""
                ).fetchall()
            finally:
                con.close()
            for src, target, category, review, origin, final_json, stage2_json in rows:
                data = None
                for text in (final_json, stage2_json):
                    if not text:
                        continue
                    try:
                        data = json.loads(text)
                        break
                    except json.JSONDecodeError:
                        continue
                if not isinstance(data, dict):
                    continue
                tags = [str(t).strip().lower() for t in (data.get("tags") or []) if str(t).strip()]
                label = {
                    "category": str(data.get("category") or category or ""),
                    "level": str(data.get("nsfw_level") or ""),
                    "tags": tags,
                    "needs_review": bool(review) or bool(data.get("needs_review")),
                    "origin": str(origin or ""),
                    "source": str(data.get("source") or ""),
                    "qq_md5": _parse_md5(Path(src).name) if src else "",
                }
                for p in (src, target):
                    if p:
                        labels[_norm(p)] = label
                for t in tags:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
                count += 1
        with self.lock:
            self.labels = labels
            self.label_tags = tag_counts
        return {"labels": count, "tags": len(tag_counts)}

    # ---------- QQ ownership index ----------
    def _index_file(self, account: str) -> Path:
        return QQ_INDEX_DIR / f"index_{account}.sqlite"

    def _load_index(self, account: str) -> dict:
        path = self._index_file(account)
        if not path.is_file() and account == LEGACY_ACCOUNT and LEGACY_INDEX.is_file():
            try:
                shutil.copy2(LEGACY_INDEX, path)
            except OSError:
                pass
        if not path.is_file():
            return {"account": account, "path": str(path), "exists": False, "chats": 0, "media": 0, "meta": {}}
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=10)
        try:
            chats = con.execute(
                "SELECT kind,chat_id,name,uin,media_count,last_time FROM chats ORDER BY media_count DESC"
            ).fetchall()
            media = con.execute("SELECT count(*) FROM media").fetchone()[0]
            meta = dict(con.execute("SELECT key,value FROM meta"))
        finally:
            con.close()
        return {
            "account": account, "path": str(path), "exists": True, "chats": len(chats),
            "media": media, "meta": meta, "rows": chats,
        }

    def load_indexes(self) -> None:
        indexes: dict[str, dict] = {}
        chats: list[dict] = []
        chat_map: dict[str, list[dict]] = {}
        for nt_data in QQ_ACCOUNTS:
            account = nt_data.parent.parent.name
            info = self._load_index(account)
            indexes[account] = {k: v for k, v in info.items() if k != "rows"}
            for kind, chat_id, name, uin, count, last in info.get("rows", []):
                chats.append({
                    "key": f"{account}|{kind}|{chat_id}", "account": account, "kind": kind,
                    "chat_id": chat_id, "name": name or "", "uin": uin or "",
                    "count": int(count or 0), "last": int(last or 0),
                })
        for account, info in indexes.items():
            if not info.get("exists"):
                continue
            con = sqlite3.connect(f"file:{info['path']}?mode=ro", uri=True, timeout=10)
            try:
                for md5, ck, cid, cname in con.execute("SELECT md5,chat_kind,chat_id,chat_name FROM media"):
                    chat_map.setdefault(md5, []).append({
                        "key": f"{account}|{ck}|{cid}", "account": account, "kind": ck,
                        "chat_id": cid, "name": cname or "",
                    })
            finally:
                con.close()
        with self.lock:
            self.indexes = indexes
            self.chats = sorted(chats, key=lambda c: ({"group": 0, "c2c": 1, "self": 2}.get(c["kind"], 3), -c["count"]))
            self.chat_map = chat_map

    def index_status(self) -> dict:
        with self.lock:
            return {"indexes": self.indexes, "job": dict(self.index_job)}

    def start_index(self, account: str) -> dict:
        with self.lock:
            if self.index_job.get("status") in ("running",):
                raise RuntimeError("已有索引任务在运行")
            self.index_job = {"status": "running", "account": account, "stage": "准备中", "current": 0, "total": 0}
        threading.Thread(target=self._build_index, args=(account,), daemon=True, name="qq-index").start()
        return self.index_status()

    def _build_index(self, account: str) -> None:
        nt_data = next((p for p in QQ_ACCOUNTS if p.parent.parent.name == account), None)
        if nt_data is None:
            with self.lock:
                self.index_job = {"status": "error", "error": f"未知账号 {account}"}
            return
        nt_qq = nt_data.parent
        db_path = nt_qq / "nt_db" / "nt_msg.db"
        if not db_path.is_file():
            with self.lock:
                self.index_job = {"status": "error", "error": f"未找到 {db_path}"}
            return
        key = self._cached_key(account)
        if key and not self._valid_key(db_path, key):
            key = ""
        try:
            if not key:
                self._progress("正在从 QQ 进程内存中查找密钥…", 0, 0)
                key = qq_keys.find_key(str(nt_qq), self._progress, None)
                if key:
                    self._save_key(account, key)
            if not key:
                raise RuntimeError("未能获取数据库密钥；请确认 QQ 已登录，或使用已保存的密钥")
            out = self._index_file(account)
            stats = build_index(str(nt_qq), key, str(out), self._progress, None)
            self._progress("完成", 1, 1)
            self.load_indexes()
            with self.lock:
                self.index_job = {
                    "status": "done", "account": account, "chats": stats.chats,
                    "media": stats.media_rows, "seconds": round(stats.seconds, 1),
                }
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                self.index_job = {"status": "error", "account": account, "error": str(exc)[:300]}

    def _progress(self, stage: str, cur: int, total: int) -> None:
        with self.lock:
            if self.index_job.get("status") == "running":
                self.index_job.update({"stage": stage, "current": int(cur), "total": int(total)})

    def _key_file(self, account: str) -> Path:
        return QQ_INDEX_DIR / f"key_{account}.bin"

    def _cached_key(self, account: str) -> str:
        p = self._key_file(account)
        if not p.is_file():
            legacy = LEGACY_INDEX.parent / "qqkey.bin"
            if account == LEGACY_ACCOUNT and legacy.is_file():
                try:
                    key = qq_keys.dpapi_unprotect(legacy.read_bytes()).decode("ascii")
                    self._save_key(account, key)
                    return key
                except Exception:
                    return ""
            return ""
        try:
            return qq_keys.dpapi_unprotect(p.read_bytes()).decode("ascii")
        except Exception:
            return ""

    def _save_key(self, account: str, key: str) -> None:
        try:
            self._key_file(account).write_bytes(qq_keys.dpapi_protect(key.encode("ascii")))
        except OSError:
            pass

    def _valid_key(self, db_path: Path, key: str) -> bool:
        import tempfile

        head = Path(tempfile.gettempdir()) / "minehub_key_head.db"
        try:
            qq_keys.make_head_copy(str(db_path), str(head))
            return qq_keys.validate_key(str(head), key)
        finally:
            try:
                head.unlink()
            except OSError:
                pass

    # ---------- scan ----------
    def scan(self, roots: list[str], extra_roots: list[str] | None = None) -> dict:
        roots = [os.path.abspath(r) for r in roots if r and os.path.isdir(r)]
        extra = [os.path.abspath(r) for r in (extra_roots or []) if r and os.path.isdir(r)]
        all_roots: list[str] = []
        for r in roots + extra:
            if _norm(r) not in {_norm(x) for x in all_roots}:
                all_roots.append(r)
        if not all_roots:
            raise ValueError("没有可扫描的目录")
        cache_key = tuple(sorted(_norm(r) for r in all_roots))
        records = self._walk(all_roots[0], all_roots)
        with self.lock:
            self.records = records
            self.record_roots = cache_key
            self.scanned_at = time.time()
            for r in all_roots:
                if _norm(r) not in {_norm(x) for x in self.allowed_roots}:
                    self.allowed_roots.append(r)
        return {"records": len(records), "cached": False, "roots": all_roots}

    def _walk(self, root: str, roots: list[str]) -> list[FileRec]:
        exts = IMAGE_EXTS | VIDEO_EXTS
        records: list[FileRec] = []
        seen: set[str] = set()
        for scan_root in roots:
            stack = [scan_root]
            while stack:
                cur = stack.pop()
                try:
                    entries = list(os.scandir(cur))
                except OSError:
                    continue
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if not entry.name.startswith("."):
                                stack.append(entry.path)
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext not in exts:
                            continue
                        if entry.path in seen:
                            continue
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    seen.add(entry.path)
                    parent = os.path.basename(cur).lower()
                    records.append(FileRec(
                        path=entry.path,
                        name=entry.name,
                        rel_dir="" if os.path.normcase(cur) == os.path.normcase(scan_root) else os.path.relpath(cur, scan_root),
                        size=st.st_size,
                        mtime=st.st_mtime,
                        kind="image" if ext in IMAGE_EXTS else "video",
                        md5=_parse_md5(entry.name),
                        variant=parent if parent in ("ori", "thumb") else "",
                    ))
        return records

    # ---------- query ----------
    def query(self, payload: dict) -> dict:
        page = max(1, int(payload.get("page") or 1))
        page_size = max(20, min(500, int(payload.get("page_size") or 120)))
        kind = payload.get("kind") or "all"
        scope = payload.get("scope") or "all"
        min_bytes = int(payload.get("min_bytes") or 0)
        max_bytes = int(payload.get("max_bytes") or 0)
        text = str(payload.get("text") or "").strip().casefold()
        chat_mode = payload.get("chat_mode") or "off"
        checked = set(payload.get("checked_chats") or [])
        include_unknown = bool(payload.get("include_unknown"))
        only_mapped = bool(payload.get("only_mapped"))
        only_groups = bool(payload.get("only_groups"))
        cat = payload.get("mh_cat") or "all"
        level = payload.get("mh_level") or "all"
        tags = [str(t).strip().casefold() for t in (payload.get("mh_tags") or []) if str(t).strip()]
        only_labeled = bool(payload.get("only_labeled"))
        only_review = bool(payload.get("only_review"))
        sort = payload.get("sort") or "size"
        desc = str(payload.get("dir") or "desc") != "asc"

        with self.lock:
            recs = self.records
            labels = self.labels
            chat_map = self.chat_map

        out: list[FileRec] = []
        total_size = 0
        mapped = 0
        labeled = 0
        for rec in recs:
            if kind != "all" and rec.kind != kind:
                continue
            if scope != "all" and rec.variant != scope:
                continue
            if min_bytes and rec.size < min_bytes:
                continue
            if max_bytes and rec.size > max_bytes:
                continue
            if text and text not in (rec.name + " " + rec.rel_dir).casefold():
                continue
            label = labels.get(_norm(rec.path)) if rec.path else None
            refs = self._refs(rec, label, chat_map, only_groups)
            if only_groups and not refs:
                continue
            if only_mapped and not refs:
                continue
            if chat_mode == "include":
                keys = {r["key"] for r in refs}
                if not refs:
                    if not include_unknown:
                        continue
                elif not (keys & checked):
                    continue
            elif chat_mode == "exclude" and refs:
                if any(r["key"] in checked for r in refs):
                    continue
            if not self._label_pass(label, cat, level, tags, only_labeled, only_review):
                continue
            if refs:
                mapped += 1
            if label is not None:
                labeled += 1
            out.append(rec)
            total_size += rec.size

        key = {
            "name": lambda r: r.name.casefold(),
            "chat": lambda r: (self._refs(r, labels.get(_norm(r.path)), chat_map, only_groups) or [{}])[0].get("name", "").casefold(),
            "mtime": lambda r: r.mtime,
            "path": lambda r: (r.rel_dir + "/" + r.name).casefold(),
            "size": lambda r: r.size,
        }.get(sort, lambda r: r.size)
        out.sort(key=key, reverse=desc)
        pages = max(1, (len(out) + page_size - 1) // page_size)
        page = min(page, pages)
        start = (page - 1) * page_size
        rows = [self._row(r, labels, chat_map, only_groups) for r in out[start:start + page_size]]
        return {
            "total": len(out), "total_size": total_size, "mapped": mapped, "labeled": labeled,
            "page": page, "pages": pages, "page_size": page_size, "records": rows,
        }

    @staticmethod
    def _label_pass(label: dict | None, cat: str, level: str, tags: list[str],
                    only_labeled: bool, only_review: bool) -> bool:
        if label is None:
            return not (only_labeled or only_review or cat != "all" or level != "all" or tags)
        if only_review and not label["needs_review"]:
            return False
        if cat == "nsfw" and label["level"] == "safe":
            return False
        if cat == "safe" and label["level"] != "safe":
            return False
        if cat not in ("all", "nsfw", "safe") and label["category"] != cat:
            return False
        if level != "all" and label["level"] != level:
            return False
        if tags:
            hay = " ".join(label["tags"])
            if any(t not in hay for t in tags):
                return False
        return True

    @staticmethod
    def _refs(rec: FileRec, label: dict | None, chat_map: dict,
              only_groups: bool = False) -> list[dict]:
        seen: set[str] = set()
        out: list[dict] = []
        for md5 in (rec.md5, (label or {}).get("qq_md5") or ""):
            for ref in chat_map.get(md5, []) if md5 else []:
                if only_groups and ref.get("kind") != "group":
                    continue
                if ref["key"] not in seen:
                    seen.add(ref["key"])
                    out.append(ref)
        return out

    def group_paths(self, paths: list[str]) -> set[str]:
        """Return paths whose QQ filename MD5 belongs to at least one group chat."""
        with self.lock:
            chat_map = self.chat_map
        out: set[str] = set()
        for raw in paths:
            md5 = _parse_md5(Path(raw).name)
            if md5 and any(ref.get("kind") == "group" for ref in chat_map.get(md5, [])):
                out.add(_norm(raw))
        return out

    def _row(self, rec: FileRec, labels: dict, chat_map: dict,
             only_groups: bool = False) -> dict:
        label = labels.get(_norm(rec.path))
        refs = self._refs(rec, label, chat_map, only_groups)
        return {
            "path": rec.path, "name": rec.name, "rel_dir": rec.rel_dir, "size": rec.size,
            "mtime": int(rec.mtime), "kind": rec.kind, "md5": rec.md5, "variant": rec.variant,
            "account": _account_of(rec.path),
            "chats": [{"key": c["key"], "label": ({"group": "群", "self": "自己"}.get(c["kind"], "好友")) + " · " + (c["name"] or c["chat_id"])} for c in refs[:4]],
            "label": label,
        }

    # ---------- files ----------
    def _allowed(self, path: str) -> bool:
        if not path or not os.path.isfile(path):
            return False
        with self.lock:
            roots = list(self.allowed_roots)
        return any(_under(path, r) for r in roots)

    def thumbnail(self, path: str, size: int = 320) -> bytes:
        if not self._allowed(path):
            raise PermissionError("路径不在允许范围内")
        size = max(64, min(MAX_THUMB, int(size or 320)))
        st = os.stat(path)
        digest = hashlib.sha1(f"{_norm(path)}|{st.st_mtime_ns}|{st.st_size}|{size}".encode()).hexdigest()
        cache = CACHE_DIR / f"{digest}.jpg"
        if cache.is_file():
            return cache.read_bytes()
        with self.thumb_sem:
            data = self._render_thumb(path, size)
        if data is None:
            data = self._placeholder(size)
        try:
            cache.write_bytes(data)
        except OSError:
            pass
        return data

    def _render_thumb(self, path: str, size: int) -> bytes | None:
        from PIL import Image, ImageOps

        thumb_path = _find_thumb(path)
        if thumb_path is not None:
            path = str(thumb_path)
        if Path(path).suffix.lower() in VIDEO_EXTS or Path(path).suffix.lower() == ".mp4":
            frame = self._video_frame(path, size)
            if frame:
                return frame
        try:
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im)
                im.thumbnail((size, size))
                if im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                out = io.BytesIO()
                im.save(out, "JPEG", quality=82)
                return out.getvalue()
        except Exception:
            return self._video_frame(path, size)

    def _video_frame(self, path: str, size: int) -> bytes | None:
        exe = FFMPEG if FFMPEG.is_file() else Path(shutil.which("ffmpeg") or "")
        if not exe or not str(exe):
            return None
        for seek in ("1", "0"):
            try:
                proc = subprocess.run(
                    [str(exe), "-v", "error", "-ss", seek, "-i", path, "-frames:v", "1",
                     "-vf", f"scale={size}:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                    capture_output=True, timeout=25,
                )
                if proc.returncode == 0 and proc.stdout:
                    return proc.stdout
            except (OSError, subprocess.TimeoutExpired):
                continue
        return None

    @staticmethod
    def _placeholder(size: int) -> bytes:
        from PIL import Image

        im = Image.new("RGB", (size, size), (24, 32, 40))
        out = io.BytesIO()
        im.save(out, "JPEG", quality=70)
        return out.getvalue()

    def move(self, paths: list[str], dest_dir: str) -> dict:
        dest = os.path.abspath(dest_dir)
        if not os.path.isdir(dest):
            raise ValueError(f"目标文件夹不存在: {dest}")
        moved, errors = [], []
        for path in paths:
            try:
                if not self._allowed(path):
                    raise PermissionError("路径不在允许范围内")
                if os.path.normcase(os.path.dirname(os.path.abspath(path))) == os.path.normcase(dest):
                    errors.append(f"{path}: 已在目标文件夹中")
                    continue
                target = self._unique(Path(dest) / Path(path).name, set())
                shutil.move(path, target)
                moved.append([path, str(target)])
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{path}: {exc}")
        self._remove_from_cache([p for p, _ in moved])
        return {"moved": moved, "errors": errors}

    def move_to_library(self, paths: list[str]) -> dict:
        """Move selected QQ/review files into LIBRARY/<category>/<YYYY-MM>."""
        from .db import Ledger
        from .stage3 import target_name

        with self.lock:
            labels = dict(self.labels)
        moved: list[list[str]] = []
        errors: list[str] = []
        scan_dirs: set[str] = set()
        for path in paths:
            try:
                if not self._allowed(path):
                    raise PermissionError("路径不在允许范围内")
                label = labels.get(_norm(path)) or {}
                category = str(label.get("category") or "review")
                if category not in {"daily", "sexy", "adult", "anime", "sticker",
                                    "screenshot", "review", "other"}:
                    category = "review"
                mtime = os.path.getmtime(path)
                month = time.strftime("%Y-%m", time.localtime(mtime))
                dest_dir = LIBRARY / category / month
                dest_dir.mkdir(parents=True, exist_ok=True)
                target = self._unique(dest_dir / target_name(path), set())
                shutil.move(path, target)
                moved.append([path, str(target)])
                scan_dirs.add(str(dest_dir))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{path}: {exc}")
        if moved:
            led = Ledger()
            try:
                now = time.time()
                candidates = list(dict.fromkeys(
                    value for src, dst in moved for value in (src, dst)
                ))
                by_src: dict[str, sqlite3.Row] = {}
                by_target: dict[str, sqlite3.Row] = {}
                for start in range(0, len(candidates), 300):
                    chunk = candidates[start:start + 300]
                    marks = ",".join("?" for _ in chunk)
                    rows = led.conn.execute(
                        f"SELECT id, src_path, target_path FROM files "
                        f"WHERE target_path IN ({marks}) OR src_path IN ({marks}) ORDER BY id",
                        chunk + chunk,
                    ).fetchall()
                    for row in rows:
                        if row["src_path"]:
                            by_src.setdefault(str(row["src_path"]), row)
                        if row["target_path"]:
                            by_target.setdefault(str(row["target_path"]), row)
                for src, dst in moved:
                    row = by_src.get(src) or by_target.get(src) or by_target.get(dst) or by_src.get(dst)
                    if row:
                        led.conn.execute(
                            "UPDATE files SET target_path=?, move_state='moved', stash_state='pending', "
                            "needs_review=1, updated_at=? WHERE id=?",
                            (dst, now, row["id"]),
                        )
                led.commit()
            finally:
                led.close()
            self._remove_from_cache([src for src, _dst in moved])
        return {"moved": moved, "errors": errors, "scan_dirs": sorted(scan_dirs)}

    @staticmethod
    def _unique(target: Path, taken: set[str]) -> Path:
        if not target.exists() and os.path.normcase(str(target)) not in taken:
            taken.add(os.path.normcase(str(target)))
            return target
        i = 1
        while True:
            cand = target.with_name(f"{target.stem} ({i}){target.suffix}")
            if not cand.exists() and os.path.normcase(str(cand)) not in taken:
                taken.add(os.path.normcase(str(cand)))
                return cand
            i += 1

    def recycle(self, paths: list[str]) -> dict:
        from send2trash import send2trash

        deleted, errors = [], []
        for path in paths:
            try:
                if not self._allowed(path):
                    raise PermissionError("路径不在允许范围内")
                send2trash(os.path.normpath(path))
                deleted.append(path)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{path}: {exc}")
        self._remove_from_cache(deleted)
        return {"deleted": deleted, "errors": errors}

    def open_path(self, path: str) -> None:
        if not self._allowed(path):
            raise PermissionError("路径不在允许范围内")
        os.startfile(path)  # type: ignore[attr-defined]

    def _remove_from_cache(self, paths: list[str]) -> None:
        gone = {_norm(p) for p in paths}
        with self.lock:
            self.records = [r for r in self.records if _norm(r.path) not in gone]
