"""Read-only image similarity index over Stash thumbnails (SQLite + numpy)."""
from __future__ import annotations

import json
import sqlite3
import time
from io import BytesIO
from pathlib import Path
from typing import Iterable

import numpy as np
import requests

from .config import DATA
from .stash import ENDPOINT, Stash

INDEX_DB = DATA / "vectors.sqlite"
INDEX_NPY = DATA / "embeddings.npy"
INDEX_DB_SIGLIP2 = DATA / "vectors_siglip2.sqlite"
INDEX_NPY_SIGLIP2 = DATA / "embeddings_siglip2.npy"
WEB = ENDPOINT.rsplit("/graphql", 1)[0]
MODEL_NSFW = "nsfw-siglip2"
MODEL_SIGLIP2 = "siglip2-base-patch16-256"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    row             INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL,       -- image | scene
    stash_id        TEXT NOT NULL,
    title           TEXT,
    thumbnail_url   TEXT NOT NULL,
    page_url        TEXT NOT NULL,
    source_path     TEXT,
    UNIQUE(kind, stash_id)
);
CREATE INDEX IF NOT EXISTS idx_items_kind ON items(kind);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _page_url(kind: str, sid: str) -> str:
    return f"{WEB}/{'images' if kind == 'image' else 'scenes'}/{sid}"


def iter_stash_items(kind: str, per_page: int = 500) -> Iterable[dict]:
    """Yield Stash image or scene thumbnail metadata without touching local files."""
    stash = Stash()
    page = 1
    seen = 0
    field = "findImages" if kind == "image" else "findScenes"
    sub = "images" if kind == "image" else "scenes"
    thumb = "thumbnail" if kind == "image" else "screenshot"
    while True:
        q = f"""query {{ {field}(filter:{{page:{page}, per_page:{per_page}}}) {{
            count {sub} {{ id title paths {{ {thumb} }} }}
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
            if url.startswith("/"):
                url = WEB + url
            yield {
                "kind": kind,
                "stash_id": str(item["id"]),
                "title": item.get("title") or "",
                "thumbnail_url": url,
                "page_url": _page_url(kind, str(item["id"])),
                "source_path": (item.get("paths") or {}).get("path"),
            }
        if seen >= int(data.get("count", 0)):
            break
        page += 1


class SimilarityIndex:
    def __init__(self, db_path: Path | None = None, npy_path: Path | None = None,
                 model: str = "nsfw") -> None:
        self.model = model
        if db_path is None:
            db_path = INDEX_DB_SIGLIP2 if model == "siglip2" else INDEX_DB
        if npy_path is None:
            npy_path = INDEX_NPY_SIGLIP2 if model == "siglip2" else INDEX_NPY
        self.db_path = Path(db_path)
        self.npy_path = Path(npy_path)
        self._items: list[dict] | None = None
        self._emb: np.ndarray | None = None
        self.session = requests.Session()

    def make_embedder(self, device: str = "cpu"):
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
        arr = np.vstack(embs).astype(np.float32) if embs else np.zeros((0, 768), dtype=np.float32)
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
        model_name = MODEL_SIGLIP2 if self.model == "siglip2" else MODEL_NSFW
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
                    """INSERT OR REPLACE INTO items(row,kind,stash_id,title,thumbnail_url,page_url,source_path)
                       VALUES (?,?,?,?,?,?,?)""",
                    (start + i, meta["kind"], meta["stash_id"], meta["title"],
                     meta["thumbnail_url"], meta["page_url"], meta.get("source_path")),
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
                    r = self.session.get(meta["thumbnail_url"], timeout=30)
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

    def _load(self) -> tuple[list[dict], np.ndarray]:
        if self._items is not None and self._emb is not None:
            return self._items, self._emb
        conn = self._conn()
        self._items = [dict(r) for r in conn.execute("SELECT * FROM items ORDER BY row")]
        conn.close()
        if not self.npy_path.exists():
            self._emb = np.zeros((0, 768), dtype=np.float32)
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

    def search_vector(self, query: np.ndarray, topk: int = 20,
                      exclude: tuple[str, str] | None = None,
                      min_score: float | None = None) -> list[dict]:
        items, emb = self._load()
        if not items or emb.size == 0:
            return []
        q = np.asarray(query, dtype=np.float32).reshape(-1)
        q = q / max(float(np.linalg.norm(q)), 1e-12)
        scores = emb @ q
        if exclude:
            for i, item in enumerate(items):
                if (item["kind"], str(item["stash_id"])) == exclude:
                    scores[i] = -2.0
        if min_score is not None:
            valid = np.flatnonzero(scores >= float(min_score))
            if valid.size == 0:
                return []
        else:
            valid = np.arange(len(items))
        k = min(max(1, topk), valid.size)
        idx = valid[np.argpartition(-scores[valid], k - 1)[:k]]
        idx = idx[np.argsort(-scores[idx])]
        out = []
        for i in idx:
            item = items[int(i)]
            out.append({
                "score": round(float(scores[int(i)]), 5),
                "kind": item["kind"],
                "stash_id": item["stash_id"],
                "title": item["title"],
                "thumbnail_url": item["thumbnail_url"],
                "page_url": item["page_url"],
                "source_path": item["source_path"],
            })
        return out

    def search_id(self, kind: str, stash_id: str, topk: int = 20,
                  min_score: float | None = None) -> list[dict] | None:
        items, emb = self._load()
        for i, item in enumerate(items):
            if item["kind"] == kind and str(item["stash_id"]) == str(stash_id):
                return self.search_vector(emb[i], topk=topk, exclude=(kind, str(stash_id)),
                                          min_score=min_score)
        return None

    def search_image(self, image, topk: int = 20, device: str = "cpu",
                     min_score: float | None = None) -> list[dict]:
        embedder = self.make_embedder(device)
        return self.search_vector(embedder.image_embedding(image), topk=topk, min_score=min_score)

    def search_text(self, text: str, topk: int = 20, device: str = "cpu",
                    min_score: float | None = None) -> list[dict]:
        if self.model != "siglip2":
            raise RuntimeError("文本搜图需要 --model siglip2 索引")
        embedder = self.make_embedder(device)
        return self.search_vector(embedder.text_embedding(text), topk=topk, min_score=min_score)
