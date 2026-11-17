"""Read-only image similarity index over Stash thumbnails (SQLite + numpy)."""
from __future__ import annotations

import json
import re
import sqlite3
import time
from io import BytesIO
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

import numpy as np
import requests

from .config import DATA
from .stash import ENDPOINT as STASH_ENDPOINT, Stash

INDEX_DB = DATA / "vectors.sqlite"
INDEX_NPY = DATA / "embeddings.npy"
INDEX_DB_SIGLIP2 = DATA / "vectors_siglip2.sqlite"
INDEX_NPY_SIGLIP2 = DATA / "embeddings_siglip2.npy"
INDEX_DB_QWEN3VL = DATA / "vectors_qwen3vl.sqlite"
INDEX_NPY_QWEN3VL = DATA / "embeddings_qwen3vl.npy"
MODEL_NSFW = "nsfw-siglip2"
MODEL_SIGLIP2 = "siglip2-base-patch16-256"
MODEL_QWEN3VL = "qwen3-vl-embedding-2b"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    row             INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL,       -- image | scene
    stash_id        TEXT NOT NULL,
    title           TEXT,
    thumbnail_url   TEXT NOT NULL,
    page_url        TEXT NOT NULL,
    source_path     TEXT,
    tags            TEXT,
    UNIQUE(kind, stash_id)
);
CREATE INDEX IF NOT EXISTS idx_items_kind ON items(kind);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
    if "tags" not in columns:
        conn.execute("ALTER TABLE items ADD COLUMN tags TEXT")


def _page_url(kind: str, sid: str) -> str:
    return f"/{'images' if kind == 'image' else 'scenes'}/{sid}"


def iter_stash_items(kind: str, per_page: int = 500) -> Iterable[dict]:
    """Yield Stash image or scene thumbnail metadata without touching local files."""
    stash = Stash()
    page = 1
    seen = 0
    field = "findImages" if kind == "image" else "findScenes"
    sub = "images" if kind == "image" else "scenes"
    thumb = "thumbnail" if kind == "image" else "screenshot"
    path_expr = ('visual_files { ... on ImageFile { path } ... on VideoFile { path } }'
                 if kind == "image" else "files { path }")
    while True:
        q = f"""query {{ {field}(filter:{{page:{page}, per_page:{per_page}}}) {{
            count {sub} {{ id title tags {{ name }} paths {{ {thumb} }} {path_expr} }}
        }} }}"""
        data = stash.graphql(q)[field]
        batch = data[sub]
        if not batch:
            break
        seen += len(batch)
        for item in batch:
            url = (item.get("paths") or {}).get(thumb)
            if not url:
                continue
            parsed = urlsplit(url)
            if parsed.scheme and parsed.hostname in ("127.0.0.1", "localhost"):
                url = parsed.path + (("?" + parsed.query) if parsed.query else "")
            files = item.get("visual_files") if kind == "image" else item.get("files")
            source_path = next((f.get("path") for f in (files or []) if f.get("path")), None)
            yield {
                "kind": kind,
                "stash_id": str(item["id"]),
                "title": item.get("title") or "",
                "thumbnail_url": url,
                "page_url": _page_url(kind, str(item["id"])),
                "source_path": source_path,
                "tags": ",".join(str(tag.get("name") or "") for tag in (item.get("tags") or [])),
            }
        if seen >= int(data.get("count", 0)):
            break
        page += 1


class SimilarityIndex:
    def __init__(self, db_path: Path | None = None, npy_path: Path | None = None,
                 model: str = "nsfw") -> None:
        self.model = model
        if db_path is None:
            if model == "qwen3vl":
                db_path = INDEX_DB_QWEN3VL
            elif model == "siglip2":
                db_path = INDEX_DB_SIGLIP2
            else:
                db_path = INDEX_DB
        if npy_path is None:
            if model == "qwen3vl":
                npy_path = INDEX_NPY_QWEN3VL
            elif model == "siglip2":
                npy_path = INDEX_NPY_SIGLIP2
            else:
                npy_path = INDEX_NPY
        self.dim = 2048 if model == "qwen3vl" else 768
        self.db_path = Path(db_path)
        self.npy_path = Path(npy_path)
        self._items: list[dict] | None = None
        self._emb: np.ndarray | None = None
        self.session = requests.Session()

    def make_embedder(self, device: str = "cpu"):
        if self.model == "qwen3vl":
            from .qwen3vl_embed import Qwen3VLEmbedder

            return Qwen3VLEmbedder(device=device)
        if self.model == "siglip2":
            from .siglip2_embed import Siglip2Embedder

            return Siglip2Embedder(device=device)
        from .siglip_embed import SiglipEmbedder

        return SiglipEmbedder(device=device)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=60)
        conn.row_factory = sqlite3.Row
        _schema(conn)
        return conn

    def reset(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists():
            self.db_path.unlink()
        if self.npy_path.exists():
            self.npy_path.unlink()
        self._items = None
        self._emb = None
        conn = self._conn()
        conn.close()

    def _save_embeddings(self, embs: list[np.ndarray]) -> None:
        arr = np.vstack(embs).astype(np.float32) if embs else np.zeros((0, self.dim), dtype=np.float32)
        np.save(self.npy_path, arr)
        conn = self._conn()
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('count',?)", (str(len(arr)),))
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('dim',?)", (str(arr.shape[1] if arr.ndim == 2 else 0),))
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('updated_at',?)", (str(time.time()),))
        conn.commit()
        conn.close()

    def build(self, kinds: Iterable[str] = ("image", "scene"), limit: int = 0,
              device: str = "cpu", batch_size: int = 32) -> dict:
        from PIL import Image

        self.reset()
        embedder = self.make_embedder(device)
        model_name = (MODEL_QWEN3VL if self.model == "qwen3vl"
                      else MODEL_SIGLIP2 if self.model == "siglip2" else MODEL_NSFW)
        conn = self._conn()
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('model',?)", (model_name,))
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('device',?)", (device,))
        conn.commit()
        embs: list[np.ndarray] = []
        images: list[Image.Image] = []
        metas: list[dict] = []
        errors = 0
        seen = 0
        t0 = time.time()

        def flush() -> None:
            nonlocal images, metas
            if not images:
                return
            vecs = embedder.image_embeddings(images)
            start = len(embs)
            for i, (meta, vec) in enumerate(zip(metas, vecs)):
                conn.execute(
                    """INSERT OR REPLACE INTO items(row,kind,stash_id,title,thumbnail_url,page_url,source_path,tags)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (start + i, meta["kind"], meta["stash_id"], meta["title"],
                     meta["thumbnail_url"], meta["page_url"], meta.get("source_path"),
                     meta.get("tags")),
                )
                embs.append(vec)
            conn.commit()
            images = []
            metas = []
            print(f"[index] {len(embs)} embedded, {errors} errors, "
                  f"{len(embs) / max(1, time.time() - t0):.1f}/s", flush=True)

        for kind in kinds:
            for meta in iter_stash_items(kind):
                if limit and seen >= limit:
                    break
                try:
                    url = meta["thumbnail_url"]
                    if url.startswith("/"):
                        url = STASH_ENDPOINT.rsplit("/", 1)[0] + url
                    r = self.session.get(url, timeout=30)
                    r.raise_for_status()
                    img = Image.open(BytesIO(r.content)).convert("RGB")
                except Exception:
                    errors += 1
                    continue
                seen += 1
                images.append(img)
                metas.append(meta)
                if len(images) >= batch_size:
                    flush()
            if limit and seen >= limit:
                break
        flush()
        self._save_embeddings(embs)
        count = len(embs)
        conn.close()
        self._items = None
        self._emb = None
        return {"indexed": count, "errors": errors, "dim": int(embs[0].shape[0]) if embs else 0,
                "elapsed_s": round(time.time() - t0, 1), "db": str(self.db_path), "npy": str(self.npy_path)}

    def refresh_metadata(self) -> dict:
        updated = 0
        conn = self._conn()
        for kind in ("image", "scene"):
            for meta in iter_stash_items(kind):
                cur = conn.execute(
                    """UPDATE items SET title=?, thumbnail_url=?, page_url=?, source_path=?, tags=?
                       WHERE kind=? AND stash_id=?""",
                    (meta["title"], meta["thumbnail_url"], meta["page_url"],
                     meta.get("source_path"), meta.get("tags"), meta["kind"], meta["stash_id"]),
                )
                if cur.rowcount > 0:
                    updated += cur.rowcount
            conn.commit()
        conn.close()
        self._items = None
        self._emb = None
        return {"updated": updated}

    def _load(self) -> tuple[list[dict], np.ndarray]:
        if self._items is not None and self._emb is not None:
            return self._items, self._emb
        conn = self._conn()
        self._items = [dict(r) for r in conn.execute("SELECT * FROM items ORDER BY row")]
        conn.close()
        if not self.npy_path.exists():
            self._emb = np.zeros((0, self.dim), dtype=np.float32)
            return self._items, self._emb
        arr = np.load(self.npy_path).astype(np.float32)
        if arr.ndim != 2:
            arr = arr.reshape(len(self._items), -1)
        self._emb = arr
        return self._items, self._emb

    def status(self) -> dict:
        items, emb = self._load()
        conn = self._conn()
        meta = {r["key"]: r["value"] for r in conn.execute("SELECT key,value FROM meta")}
        conn.close()
        return {**meta, "count": len(items), "dim": int(emb.shape[1]) if emb.ndim == 2 else 0,
                "db": str(self.db_path), "npy": str(self.npy_path)}

    @staticmethod
    def _result(item: dict, score: float | None = None) -> dict:
        return {
            "score": score,
            "kind": item["kind"],
            "stash_id": item["stash_id"],
            "title": item["title"],
            "thumbnail_url": item["thumbnail_url"],
            "page_url": item["page_url"],
            "source_path": item["source_path"],
            "tags": item.get("tags") or "",
        }

    def _rank_scores(self, scores: np.ndarray, items: list[dict], topk: int,
                     min_score: float | None = None, kinds: list[str] | None = None,
                     exclude: tuple[str, str] | None = None) -> list[dict]:
        scores = np.asarray(scores, dtype=np.float32).copy()
        blocked = np.zeros(len(items), dtype=bool)
        if kinds:
            allowed = set(kinds)
            for i, item in enumerate(items):
                if item["kind"] not in allowed:
                    blocked[i] = True
        if exclude:
            for i, item in enumerate(items):
                if (item["kind"], str(item["stash_id"])) == exclude:
                    blocked[i] = True
        scores[blocked] = -2.0
        valid = np.flatnonzero(~blocked)
        if min_score is not None:
            valid = valid[scores[valid] >= float(min_score)]
        if valid.size == 0:
            return []
        k = min(max(1, topk), valid.size)
        idx = valid[np.argpartition(-scores[valid], k - 1)[:k]]
        idx = idx[np.argsort(-scores[idx])]
        return [self._result(items[int(i)], round(float(scores[int(i)]), 5)) for i in idx]

    def search_vector(self, query: np.ndarray, topk: int = 20,
                      exclude: tuple[str, str] | None = None,
                      min_score: float | None = None,
                      kinds: list[str] | None = None) -> list[dict]:
        items, emb = self._load()
        if not items or emb.size == 0:
            return []
        q = np.asarray(query, dtype=np.float32).reshape(-1)
        q = q / max(float(np.linalg.norm(q)), 1e-12)
        return self._rank_scores(emb @ q, items, topk, min_score=min_score,
                                 kinds=kinds, exclude=exclude)

    def search_vectors(self, queries: list[np.ndarray], topk: int = 20,
                       min_score: float | None = None, kinds: list[str] | None = None,
                       aggregate: str = "all") -> list[dict]:
        items, emb = self._load()
        if not items or emb.size == 0 or not queries:
            return []
        qs = []
        for query in queries:
            q = np.asarray(query, dtype=np.float32).reshape(-1)
            qs.append(q / max(float(np.linalg.norm(q)), 1e-12))
        if len(qs) == 1:
            scores = emb @ qs[0]
        else:
            stacked = np.stack([emb @ q for q in qs], axis=0)
            scores = stacked.max(axis=0) if aggregate == "any" else stacked.min(axis=0)
        return self._rank_scores(scores, items, topk, min_score=min_score, kinds=kinds)

    def search_regex(self, patterns: list[re.Pattern], topk: int = 20,
                     kinds: list[str] | None = None, match_all: bool = True,
                     fields: list[str] | None = None) -> list[dict]:
        items, _ = self._load()
        allowed = set(kinds) if kinds else None
        selected = set(fields) if fields else {"title", "path", "basename", "tags", "id"}
        predicate = all if match_all else any
        out = []
        for item in items:
            if allowed and item["kind"] not in allowed:
                continue
            source_path = str(item.get("source_path") or "")
            values = {
                "title": item.get("title"),
                "path": source_path,
                "basename": source_path.replace("/", "\\").rsplit("\\", 1)[-1],
                "tags": item.get("tags"),
                "id": item.get("stash_id"),
            }
            haystacks = [str(values[name]) for name in ("title", "path", "basename", "tags", "id")
                         if name in selected and values.get(name)]
            if predicate(any(pattern.search(value) for value in haystacks)
                         for pattern in patterns):
                out.append(self._result(item))
        return out[:topk]

    def find_vector(self, kind: str, stash_id: str) -> tuple[dict, np.ndarray] | None:
        items, emb = self._load()
        for i, item in enumerate(items):
            if item["kind"] == kind and str(item["stash_id"]) == str(stash_id):
                return item, emb[i]
        return None

    def search_id(self, kind: str, stash_id: str, topk: int = 20,
                  min_score: float | None = None) -> list[dict] | None:
        found = self.find_vector(kind, stash_id)
        if found is None:
            return None
        return self.search_vector(found[1], topk=topk, exclude=(kind, str(stash_id)),
                                  min_score=min_score)

    def search_image(self, image, topk: int = 20, device: str = "cpu",
                     min_score: float | None = None) -> list[dict]:
        embedder = self.make_embedder(device)
        return self.search_vector(embedder.image_embedding(image), topk=topk, min_score=min_score)

    def search_text(self, text: str, topk: int = 20, device: str = "cpu",
                    min_score: float | None = None) -> list[dict]:
        if self.model not in ("siglip2", "qwen3vl"):
            raise RuntimeError("文本搜图需要 --model siglip2 或 qwen3vl 索引")
        embedder = self.make_embedder(device)
        vec = (embedder.query_embedding(text) if hasattr(embedder, "query_embedding")
               else embedder.text_embedding(text))
        return self.search_vector(vec, topk=topk, min_score=min_score)
