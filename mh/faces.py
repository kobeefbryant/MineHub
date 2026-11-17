"""Face detection, clustering and Stash performer integration."""
from __future__ import annotations

import base64
import json
import math
import os
import shutil
import sqlite3
import threading
import time
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
import onnxruntime as ort
import requests
from PIL import Image, ImageOps

from .config import DATA, MEDIA_ROOT, MODELS_ROOT
from .stash import Stash

FACE_DB = DATA / "faces.sqlite"
FACE_CACHE = MEDIA_ROOT / "cache" / "faces"
FACE_MODEL_DIR = MODELS_ROOT / "insightface" / "buffalo_l"
FACE_MODEL_ZIP = MODELS_ROOT / "insightface" / "buffalo_l.zip"
FACE_MODEL_URL = os.environ.get(
    "MH_FACE_MODEL_URL",
    "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip",
)
DET_MODEL = FACE_MODEL_DIR / "det_10g.onnx"
REC_MODEL = FACE_MODEL_DIR / "w600k_r50.onnx"

DEFAULT_THRESHOLD = 0.6
DEFAULT_MIN_IMAGES = 3

ARCFACE_DST = np.array(
    [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
     [41.5493, 92.3655], [70.7299, 92.2041]],
    dtype=np.float32,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    stash_id    TEXT PRIMARY KEY,
    path        TEXT,
    size        INTEGER,
    mtime       REAL,
    title       TEXT,
    state       TEXT NOT NULL DEFAULT 'pending',
    face_count  INTEGER NOT NULL DEFAULT 0,
    error       TEXT,
    updated_at  REAL
);
CREATE TABLE IF NOT EXISTS faces (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    stash_id    TEXT NOT NULL,
    face_index  INTEGER NOT NULL,
    bbox        TEXT,
    det_score   REAL,
    embedding   BLOB NOT NULL,
    crop_path   TEXT,
    cluster_id  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_faces_image ON faces(stash_id);
CREATE INDEX IF NOT EXISTS idx_faces_cluster ON faces(cluster_id);
CREATE TABLE IF NOT EXISTS clusters (
    id                  INTEGER PRIMARY KEY,
    size                INTEGER NOT NULL,
    image_count         INTEGER NOT NULL,
    representative_face INTEGER,
    name                TEXT,
    performer_id        TEXT,
    updated_at          REAL
);
CREATE TABLE IF NOT EXISTS cluster_images (
    cluster_id INTEGER NOT NULL,
    stash_id   TEXT NOT NULL,
    PRIMARY KEY (cluster_id, stash_id)
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(FACE_DB, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return str(row["value"]) if row else default


def _set_meta(conn: sqlite3.Connection, key: str, value: object) -> None:
    conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, str(value)))


def _safe_unlink(path: str | None) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def _relative_url(url: str | None) -> str:
    if not url:
        return ""
    parsed = urlsplit(url)
    if parsed.scheme and parsed.hostname in ("127.0.0.1", "localhost"):
        return parsed.path + (("?" + parsed.query) if parsed.query else "")
    return url


def _similarity_matrix(src: np.ndarray) -> np.ndarray:
    rows = []
    values = []
    for (x, y), (u, v) in zip(src, ARCFACE_DST):
        rows.append([x, -y, 1.0, 0.0])
        values.append(u)
        rows.append([y, x, 0.0, 1.0])
        values.append(v)
    a, b, tx, ty = np.linalg.lstsq(np.asarray(rows, dtype=np.float64),
                                   np.asarray(values, dtype=np.float64), rcond=None)[0]
    return np.array([[a, -b, tx], [b, a, ty], [0.0, 0.0, 1.0]], dtype=np.float64)


def _align_face(image: Image.Image, kps: np.ndarray) -> Image.Image:
    matrix = np.linalg.inv(_similarity_matrix(np.asarray(kps, dtype=np.float64)))
    coeffs = (
        matrix[0, 0], matrix[0, 1], matrix[0, 2],
        matrix[1, 0], matrix[1, 1], matrix[1, 2],
    )
    return image.transform((112, 112), Image.Transform.AFFINE, coeffs,
                           resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0))


def _nms(dets: np.ndarray, threshold: float = 0.4) -> list[int]:
    x1, y1, x2, y2 = dets[:, 0], dets[:, 1], dets[:, 2], dets[:, 3]
    scores = dets[:, 4]
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1 + 1)
        h = np.maximum(0.0, yy2 - yy1 + 1)
        inter = w * h
        overlap = inter / (areas[i] + areas[order[1:]] - inter)
        order = order[np.where(overlap <= threshold)[0] + 1]
    return keep


class FaceEngine:
    def __init__(self) -> None:
        self.det: ort.InferenceSession | None = None
        self.rec: ort.InferenceSession | None = None
        self.device = ""
        self._anchor_cache: dict[tuple[int, int, int], np.ndarray] = {}
        self._lock = threading.Lock()

    @staticmethod
    def ready() -> bool:
        try:
            return DET_MODEL.stat().st_size > 1024 * 1024 and REC_MODEL.stat().st_size > 1024 * 1024
        except OSError:
            return False

    def ensure_models(self, progress=None) -> None:
        if self.ready():
            return
        FACE_MODEL_DIR.mkdir(parents=True, exist_ok=True)
        tmp = FACE_MODEL_ZIP
        tmp.parent.mkdir(parents=True, exist_ok=True)
        if not tmp.exists() or tmp.stat().st_size < 100 * 1024 * 1024:
            with requests.get(FACE_MODEL_URL, stream=True, timeout=120, allow_redirects=True) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length") or 0)
                done = 0
                with tmp.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=4 * 1024 * 1024):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total)
        wanted = {"det_10g.onnx": DET_MODEL, "w600k_r50.onnx": REC_MODEL}
        with zipfile.ZipFile(tmp) as archive:
            names = {Path(name).name: name for name in archive.namelist()}
            for name, target in wanted.items():
                member = names.get(name)
                if not member:
                    raise RuntimeError(f"人脸模型包缺少 {name}")
                with archive.open(member) as source, target.open("wb") as dest:
                    shutil.copyfileobj(source, dest)
        _safe_unlink(str(tmp))
        if not self.ready():
            raise RuntimeError("人脸模型文件不完整")

    def _load(self) -> None:
        with self._lock:
            if self.det is not None and self.rec is not None:
                return
            self.ensure_models()
            options = ort.SessionOptions()
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            available = ort.get_available_providers()
            providers = (["CUDAExecutionProvider", "CPUExecutionProvider"]
                         if "CUDAExecutionProvider" in available else ["CPUExecutionProvider"])
            try:
                det = ort.InferenceSession(str(DET_MODEL), sess_options=options, providers=providers)
                rec = ort.InferenceSession(str(REC_MODEL), sess_options=options, providers=providers)
            except Exception:
                providers = ["CPUExecutionProvider"]
                det = ort.InferenceSession(str(DET_MODEL), sess_options=options, providers=providers)
                rec = ort.InferenceSession(str(REC_MODEL), sess_options=options, providers=providers)
            self.det = det
            self.rec = rec
            self.device = "cuda" if providers[0] == "CUDAExecutionProvider" else "cpu"

    def _anchors(self, height: int, width: int, stride: int) -> np.ndarray:
        key = (height, width, stride)
        if key in self._anchor_cache:
            return self._anchor_cache[key]
        centers = np.stack(np.mgrid[:height, :width][::-1], axis=-1).astype(np.float32)
        centers = (centers * stride).reshape(-1, 2)
        centers = np.stack([centers, centers], axis=1).reshape(-1, 2)
        if len(self._anchor_cache) < 16:
            self._anchor_cache[key] = centers
        return centers

    def _detect(self, image: Image.Image) -> tuple[np.ndarray, np.ndarray]:
        self._load()
        width, height = image.size
        ratio = height / max(1, width)
        if ratio > 1.0:
            new_h = 640
            new_w = max(1, int(640 / ratio))
        else:
            new_w = 640
            new_h = max(1, int(640 * ratio))
        det_scale = new_h / max(1, height)
        resized = np.asarray(image.resize((new_w, new_h), Image.Resampling.BILINEAR), dtype=np.uint8)
        canvas = np.zeros((640, 640, 3), dtype=np.uint8)
        canvas[:new_h, :new_w] = resized
        blob = ((canvas.astype(np.float32) - 127.5) / 128.0).transpose(2, 0, 1)[None]
        outputs = self.det.run(None, {self.det.get_inputs()[0].name: blob})
        scores_all: list[np.ndarray] = []
        boxes_all: list[np.ndarray] = []
        kps_all: list[np.ndarray] = []
        for index, stride in enumerate((8, 16, 32)):
            scores = np.asarray(outputs[index]).reshape(-1)
            boxes = np.asarray(outputs[index + 3]).reshape(-1, 4) * stride
            kps = np.asarray(outputs[index + 6]).reshape(-1, 10) * stride
            feature_h, feature_w = 640 // stride, 640 // stride
            anchors = self._anchors(feature_h, feature_w, stride)
            if len(anchors) != len(scores):
                raise RuntimeError("人脸检测输出与锚点数量不一致")
            keep = np.where(scores >= 0.5)[0]
            if not len(keep):
                continue
            points = anchors[keep]
            selected = boxes[keep]
            x1 = points[:, 0] - selected[:, 0]
            y1 = points[:, 1] - selected[:, 1]
            x2 = points[:, 0] + selected[:, 2]
            y2 = points[:, 1] + selected[:, 3]
            boxes_all.append(np.stack([x1, y1, x2, y2], axis=1))
            scores_all.append(scores[keep])
            kps_all.append(kps[keep].reshape(-1, 5, 2) + points[:, None, :])
        if not scores_all:
            return np.empty((0, 5), dtype=np.float32), np.empty((0, 5, 2), dtype=np.float32)
        scores = np.concatenate(scores_all)
        boxes = np.concatenate(boxes_all) / det_scale
        kps = np.concatenate(kps_all) / det_scale
        order = scores.argsort()[::-1]
        scores, boxes, kps = scores[order], boxes[order], kps[order]
        dets = np.hstack([boxes, scores[:, None]]).astype(np.float32)
        keep = _nms(dets)
        boxes = boxes[keep]
        scores = scores[keep]
        kps = kps[keep]
        boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, width)
        boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, height)
        valid = ((boxes[:, 2] - boxes[:, 0]) >= 28) & ((boxes[:, 3] - boxes[:, 1]) >= 28)
        boxes, scores, kps = boxes[valid][:10], scores[valid][:10], kps[valid][:10]
        return np.hstack([boxes, scores[:, None]]).astype(np.float32), kps.astype(np.float32)

    def _embed(self, crops: list[Image.Image]) -> np.ndarray:
        if not crops:
            return np.zeros((0, 512), dtype=np.float32)
        arrays = []
        for crop in crops:
            rgb = np.asarray(crop, dtype=np.float32)
            arrays.append(rgb.transpose(2, 0, 1))
        blob = (np.stack(arrays) - 127.5) / 127.5
        output = self.rec.run(None, {self.rec.get_inputs()[0].name: blob})[0]
        output = np.asarray(output, dtype=np.float32).reshape(len(crops), -1)
        norms = np.linalg.norm(output, axis=1, keepdims=True)
        return output / np.maximum(norms, 1e-12)

    def analyze(self, image: Image.Image) -> list[dict]:
        dets, landmarks = self._detect(image)
        if not len(dets):
            return []
        crops = []
        kept = []
        for det, kps in zip(dets, landmarks):
            try:
                aligned = _align_face(image, kps)
            except (ValueError, np.linalg.LinAlgError):
                continue
            crops.append(aligned)
            kept.append((det, kps, aligned))
        if not crops:
            return []
        embeddings = self._embed(crops)
        faces = []
        for (det, _kps, aligned), embedding in zip(kept, embeddings):
            faces.append({
                "bbox": [round(float(value), 2) for value in det[:4]],
                "det_score": round(float(det[4]), 5),
                "embedding": embedding.astype(np.float32),
                "aligned": aligned,
            })
        return faces


class Faces:
    def __init__(self) -> None:
        self.engine = FaceEngine()
        self._task_lock = threading.Lock()
        self._task: dict = {
            "kind": "idle", "running": False, "stage": "idle", "done": 0, "total": 0,
            "message": "", "error": "", "started_at": None, "finished_at": None,
        }

    def _update(self, **values) -> None:
        with self._task_lock:
            self._task.update(values)

    def _snapshot(self) -> dict:
        with self._task_lock:
            return dict(self._task)

    def _start(self, kind: str, target) -> dict:
        with self._task_lock:
            if self._task["running"]:
                return dict(self._task)
            self._task = {
                "kind": kind, "running": True, "stage": "starting", "done": 0, "total": 0,
                "message": "", "error": "", "started_at": time.time(), "finished_at": None,
            }
        thread = threading.Thread(target=target, name=f"minehub-faces-{kind}", daemon=True)
        thread.start()
        return self._snapshot()

    def _finish(self, error: str = "") -> None:
        self._update(running=False, stage="error" if error else "done", error=error,
                     finished_at=time.time(), message="")

    def status(self, min_images: int | None = None) -> dict:
        conn = _connect()
        counts = {
            "images": conn.execute("SELECT COUNT(*) FROM images").fetchone()[0],
            "images_done": conn.execute("SELECT COUNT(*) FROM images WHERE state='done'").fetchone()[0],
            "images_error": conn.execute("SELECT COUNT(*) FROM images WHERE state='error'").fetchone()[0],
            "images_pending": conn.execute("SELECT COUNT(*) FROM images WHERE state<>'done'").fetchone()[0],
            "faces": conn.execute("SELECT COUNT(*) FROM faces").fetchone()[0],
            "faces_images": conn.execute("SELECT COUNT(DISTINCT stash_id) FROM faces").fetchone()[0],
            "clusters": conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0],
            "clusters_applied": conn.execute("SELECT COUNT(*) FROM clusters WHERE performer_id IS NOT NULL").fetchone()[0],
        }
        threshold = float(_meta(conn, "threshold", str(DEFAULT_THRESHOLD)))
        if min_images is None:
            min_images = int(_meta(conn, "min_images", str(DEFAULT_MIN_IMAGES)))
        min_images = max(1, int(min_images))
        counts["clusters_eligible"] = conn.execute(
            "SELECT COUNT(*) FROM clusters WHERE image_count>=?", (min_images,)
        ).fetchone()[0]
        last_scan = _meta(conn, "last_scan_at")
        last_cluster = _meta(conn, "last_cluster_at")
        conn.close()
        return {
            "task": self._snapshot(),
            "counts": counts,
            "model_ready": self.engine.ready(),
            "model_dir": str(FACE_MODEL_DIR),
            "device": self.engine.device,
            "threshold": threshold,
            "min_images": min_images,
            "last_scan_at": float(last_scan) if last_scan else None,
            "last_cluster_at": float(last_cluster) if last_cluster else None,
            "db": str(FACE_DB),
        }

    def _iter_stash_images(self) -> list[dict]:
        stash = Stash()
        out: list[dict] = []
        page = 1
        seen = 0
        while True:
            data = stash.graphql(
                """query($p:Int!){ findImages(filter:{page:$p, per_page:500}) {
                    count
                    images { id title visual_files { ... on ImageFile{ path } ... on VideoFile{ path } } }
                } }""",
                {"p": page},
            )["findImages"]
            batch = data.get("images") or []
            if not batch:
                break
            seen += len(batch)
            for item in batch:
                path = next((str(f["path"]) for f in (item.get("visual_files") or []) if f.get("path")), "")
                out.append({
                    "stash_id": str(item["id"]),
                    "title": item.get("title") or "",
                    "path": path,
                })
            if seen >= int(data.get("count") or 0):
                break
            page += 1
        return out

    def start_scan(self, force: bool = False, limit: int = 0) -> dict:
        def worker() -> None:
            try:
                self._scan(force, limit)
            except Exception as exc:  # noqa: BLE001
                self._finish(str(exc)[:500])
            else:
                self._finish()

        return self._start("scan", worker)

    def _scan(self, force: bool, limit: int) -> None:
        self._update(stage="enumerating", message="读取 Stash 图片列表…")
        items = self._iter_stash_images()
        conn = _connect()
        todo: list[sqlite3.Row] = []
        now = time.time()
        for item in items:
            path = item["path"]
            size = 0
            mtime = 0.0
            if path:
                try:
                    stat = os.stat(path)
                    size, mtime = int(stat.st_size), float(stat.st_mtime)
                except OSError:
                    pass
            old = conn.execute(
                "SELECT path,size,mtime,state FROM images WHERE stash_id=?", (item["stash_id"],)
            ).fetchone()
            changed = (force or old is None or old["path"] != path or
                       int(old["size"] or 0) != size or abs(float(old["mtime"] or 0) - mtime) > 1e-6)
            state = "pending" if changed or not old or old["state"] != "done" else "done"
            conn.execute(
                """INSERT INTO images(stash_id,path,size,mtime,title,state,face_count,error,updated_at)
                   VALUES(?,?,?,?,?,?,COALESCE((SELECT face_count FROM images WHERE stash_id=?),0),NULL,?)
                   ON CONFLICT(stash_id) DO UPDATE SET path=excluded.path,size=excluded.size,
                   mtime=excluded.mtime,title=excluded.title,state=excluded.state,
                   error=CASE WHEN excluded.state='pending' THEN NULL ELSE images.error END,
                   updated_at=excluded.updated_at""",
                (item["stash_id"], path, size, mtime, item["title"], state,
                 item["stash_id"], now),
            )
        conn.commit()
        todo = list(conn.execute(
            "SELECT stash_id,path,size,mtime,title FROM images WHERE state<>'done' ORDER BY stash_id"
        ))
        if limit > 0:
            todo = todo[:limit]
        total = len(todo)
        self._update(stage="loading", total=total, done=0,
                     message="准备人脸模型…" if total else "没有新增或变化的图片")
        _set_meta(conn, "last_scan_at", time.time())
        conn.commit()
        if not total:
            self._auto_cluster(conn)
            conn.close()
            return
        self.engine.ensure_models(
            lambda done, size: self._update(message=(
                f"下载人脸模型 {done / 1048576:.0f} / {size / 1048576:.0f} MB"
                if size else f"下载人脸模型 {done / 1048576:.0f} MB"
            ))
        )
        self._update(stage="scanning", message="加载人脸模型…")
        self.engine._load()
        errors = 0
        for index, row in enumerate(todo, 1):
            self._update(stage="scanning", done=index - 1,
                         message=f"人脸扫描 {index}/{total} · {Path(row['path'] or '').name}")
            try:
                self._scan_image(conn, row)
            except Exception as exc:  # noqa: BLE001
                errors += 1
                conn.execute(
                    "UPDATE images SET state='error',error=?,updated_at=? WHERE stash_id=?",
                    (str(exc)[:500], time.time(), row["stash_id"]),
                )
                conn.commit()
        self._update(done=total, message=f"扫描完成：{total - errors} 张成功，{errors} 张失败")
        self._auto_cluster(conn)
        conn.close()

    def _scan_image(self, conn: sqlite3.Connection, row: sqlite3.Row) -> None:
        path = row["path"]
        if not path or not Path(path).is_file():
            raise FileNotFoundError("图片文件不存在")
        with Image.open(path) as opened:
            try:
                opened.draft("RGB", (1600, 1600))
            except Exception:
                pass
            image = ImageOps.exif_transpose(opened)
            if image.mode != "RGB":
                image = image.convert("RGB")
            faces = self.engine.analyze(image)
        old = conn.execute("SELECT crop_path FROM faces WHERE stash_id=?", (row["stash_id"],)).fetchall()
        for item in old:
            _safe_unlink(item["crop_path"])
        conn.execute("DELETE FROM faces WHERE stash_id=?", (row["stash_id"],))
        FACE_CACHE.mkdir(parents=True, exist_ok=True)
        stamp = int(time.time() * 1000)
        for index, face in enumerate(faces):
            crop_name = f"{row['stash_id']}_{stamp}_{index}.jpg"
            crop_path = FACE_CACHE / crop_name
            face["aligned"].resize((160, 160), Image.Resampling.LANCZOS).save(
                crop_path, "JPEG", quality=88
            )
            conn.execute(
                """INSERT INTO faces(stash_id,face_index,bbox,det_score,embedding,crop_path)
                   VALUES(?,?,?,?,?,?)""",
                (row["stash_id"], index, json.dumps(face["bbox"]), face["det_score"],
                 face["embedding"].astype(np.float32).tobytes(), str(crop_path)),
            )
        conn.execute(
            "UPDATE images SET state='done',face_count=?,error=NULL,updated_at=? WHERE stash_id=?",
            (len(faces), time.time(), row["stash_id"]),
        )
        conn.commit()

    def _auto_cluster(self, conn: sqlite3.Connection) -> None:
        threshold = float(_meta(conn, "threshold", str(DEFAULT_THRESHOLD)))
        min_images = int(_meta(conn, "min_images", str(DEFAULT_MIN_IMAGES)))
        self._update(stage="clustering", message="聚类人脸…")
        self._cluster_impl(conn, threshold, min_images)
        self._update(message="聚类完成，可在页面查看并按人物写入演员")

    def start_cluster(self, threshold: float = DEFAULT_THRESHOLD,
                      min_images: int = DEFAULT_MIN_IMAGES) -> dict:
        threshold = max(0.2, min(0.9, float(threshold)))
        min_images = max(1, min(100, int(min_images)))

        def worker() -> None:
            try:
                conn = _connect()
                self._cluster_impl(conn, threshold, min_images)
                conn.close()
            except Exception as exc:  # noqa: BLE001
                self._finish(str(exc)[:500])
            else:
                self._finish()

        return self._start("cluster", worker)

    def _cluster_impl(self, conn: sqlite3.Connection, threshold: float, min_images: int) -> None:
        rows = list(conn.execute(
            "SELECT id,stash_id,embedding,det_score,crop_path FROM faces ORDER BY id"
        ))
        if not rows:
            conn.execute("DELETE FROM clusters")
            conn.execute("DELETE FROM cluster_images")
            conn.execute("UPDATE faces SET cluster_id=NULL")
            _set_meta(conn, "threshold", threshold)
            _set_meta(conn, "min_images", min_images)
            _set_meta(conn, "last_cluster_at", time.time())
            conn.commit()
            return
        embeddings = np.stack([
            np.frombuffer(row["embedding"], dtype=np.float32) for row in rows
        ])
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings = embeddings / np.maximum(norms, 1e-12)
        count = len(rows)
        order = np.argsort([-float(row["det_score"] or 0) for row in rows])
        sums = np.zeros((count, embeddings.shape[1]), dtype=np.float32)
        norms = np.zeros(count, dtype=np.float32)
        labels = np.full(count, -1, dtype=np.int32)
        used = 0
        for position, index in enumerate(order, 1):
            vector = embeddings[index]
            if used:
                dots = sums[:used] @ vector
                similarities = dots / np.maximum(norms[:used], 1e-9)
                best = int(similarities.argmax())
                if float(similarities[best]) >= threshold:
                    labels[index] = best
                    sums[best] += vector
                    norms[best] = float(np.linalg.norm(sums[best]))
                else:
                    labels[index] = used
                    sums[used] = vector
                    norms[used] = 1.0
                    used += 1
            else:
                labels[index] = used
                sums[used] = vector
                norms[used] = 1.0
                used += 1
            if position % 500 == 0 or position == count:
                self._update(stage="clustering", done=position, total=count,
                             message=f"聚类人脸 {position}/{count}")
        groups: dict[int, list[int]] = {}
        for index, label in enumerate(labels):
            groups.setdefault(int(label), []).append(index)

        old = {}
        for cluster in conn.execute(
            "SELECT id,name,performer_id FROM clusters WHERE performer_id IS NOT NULL"
        ):
            old[int(cluster["id"])] = {
                "name": cluster["name"], "performer_id": cluster["performer_id"],
                "faces": set(), "images": set(),
            }
        for item in conn.execute("SELECT id,cluster_id FROM faces WHERE cluster_id IS NOT NULL"):
            cluster_id = int(item["cluster_id"])
            if cluster_id in old:
                old[cluster_id]["faces"].add(int(item["id"]))
        for item in conn.execute("SELECT cluster_id,stash_id FROM cluster_images"):
            cluster_id = int(item["cluster_id"])
            if cluster_id in old:
                old[cluster_id]["images"].add(str(item["stash_id"]))
        old_order = sorted(old.items(), key=lambda item: -len(item[1]["images"]))
        used_old: set[int] = set()
        ordered = sorted(
            groups.values(),
            key=lambda indices: (
                -len({rows[index]["stash_id"] for index in indices}),
                -len(indices),
                min(int(rows[index]["id"]) for index in indices),
            ),
        )
        conn.execute("DELETE FROM clusters")
        conn.execute("DELETE FROM cluster_images")
        conn.execute("UPDATE faces SET cluster_id=NULL")
        _set_meta(conn, "threshold", threshold)
        _set_meta(conn, "min_images", min_images)
        _set_meta(conn, "last_cluster_at", time.time())
        for cluster_id, indices in enumerate(ordered, 1):
            image_ids = {str(rows[index]["stash_id"]) for index in indices}
            face_ids = {int(rows[index]["id"]) for index in indices}
            representative = max(indices, key=lambda index: float(rows[index]["det_score"] or 0))
            best = None
            best_overlap = 0
            for old_id, info in old_order:
                if old_id in used_old:
                    continue
                if image_ids and info["images"]:
                    overlap = len(image_ids & info["images"])
                    required = max(1, math.ceil(0.5 * min(len(image_ids), len(info["images"]))))
                    if overlap >= required and overlap > best_overlap:
                        best, best_overlap = (old_id, info), overlap
                    continue
                overlap = len(face_ids & info["faces"])
                if overlap > best_overlap:
                    best, best_overlap = (old_id, info), overlap
            name = None
            performer_id = None
            if best and best_overlap >= 1:
                if best[1]["images"]:
                    required = max(1, math.ceil(0.5 * min(len(image_ids), len(best[1]["images"]))))
                    matched = best_overlap >= required
                else:
                    matched = best_overlap >= max(2, math.ceil(0.5 * min(len(face_ids), len(best[1]["faces"]))))
                if matched:
                    used_old.add(best[0])
                    name = best[1]["name"]
                    performer_id = best[1]["performer_id"]
            conn.execute(
                """INSERT INTO clusters(id,size,image_count,representative_face,name,performer_id,updated_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (cluster_id, len(indices), len(image_ids), int(rows[representative]["id"]),
                 name, performer_id, time.time()),
            )
            for image_id in image_ids:
                conn.execute(
                    "INSERT OR REPLACE INTO cluster_images(cluster_id,stash_id) VALUES(?,?)",
                    (cluster_id, image_id),
                )
            for index in indices:
                conn.execute("UPDATE faces SET cluster_id=? WHERE id=?", (cluster_id, int(rows[index]["id"])))
        conn.commit()

    def clusters(self, page: int = 1, per_page: int = 24,
                 min_images: int = DEFAULT_MIN_IMAGES) -> dict:
        conn = _connect()
        page = max(1, int(page))
        per_page = max(1, min(100, int(per_page)))
        min_images = max(1, int(min_images))
        total = conn.execute(
            "SELECT COUNT(*) FROM clusters WHERE image_count>=?", (min_images,)
        ).fetchone()[0]
        rows = list(conn.execute(
            """SELECT * FROM clusters WHERE image_count>=?
               ORDER BY image_count DESC, size DESC, id LIMIT ? OFFSET ?""",
            (min_images, per_page, (page - 1) * per_page),
        ))
        conn.close()
        items = []
        for row in rows:
            representative = row["representative_face"]
            items.append({
                "id": row["id"],
                "size": row["size"],
                "image_count": row["image_count"],
                "name": row["name"] or "",
                "performer_id": row["performer_id"],
                "thumb_url": f"/mh/api/faces/thumb?id={representative}" if representative else "",
            })
        return {"clusters": items, "total": total, "page": page, "per_page": per_page,
                "min_images": min_images}

    def cluster_detail(self, cluster_id: int, limit: int = 80) -> dict:
        conn = _connect()
        cluster = conn.execute("SELECT * FROM clusters WHERE id=?", (int(cluster_id),)).fetchone()
        if not cluster:
            conn.close()
            raise LookupError("人脸聚类不存在")
        face_rows = list(conn.execute(
            "SELECT id,stash_id,crop_path,det_score FROM faces WHERE cluster_id=? ORDER BY det_score DESC",
            (int(cluster_id),),
        ))
        conn.close()
        image_ids: list[str] = []
        seen = set()
        for face in face_rows:
            if face["stash_id"] not in seen:
                seen.add(face["stash_id"])
                image_ids.append(str(face["stash_id"]))
        image_ids = image_ids[:max(1, min(300, int(limit)))]
        thumbs = self._stash_thumbs(image_ids)
        faces = [{
            "id": face["id"],
            "stash_id": face["stash_id"],
            "thumb_url": f"/mh/api/faces/thumb?id={face['id']}",
            "det_score": face["det_score"],
        } for face in face_rows[:24]]
        return {
            "cluster": {
                "id": cluster["id"], "size": cluster["size"], "image_count": cluster["image_count"],
                "name": cluster["name"] or "", "performer_id": cluster["performer_id"],
            },
            "faces": faces,
            "images": [{"stash_id": image_id, **thumbs.get(image_id, {})} for image_id in image_ids],
        }

    @staticmethod
    def _stash_thumbs(image_ids: list[str]) -> dict[str, dict]:
        if not image_ids:
            return {}
        stash = Stash()
        out: dict[str, dict] = {}
        for start in range(0, len(image_ids), 200):
            ids = [item for item in image_ids[start:start + 200] if str(item).isdigit()]
            if not ids:
                continue
            try:
                data = stash.graphql(
                    "query($ids:[ID!]!){findImages(ids:$ids){images{id title paths{thumbnail preview}}}}",
                    {"ids": ids},
                )
            except Exception:  # noqa: BLE001
                continue
            for item in data["findImages"]["images"]:
                paths = item.get("paths") or {}
                out[str(item["id"])] = {
                    "title": item.get("title") or "",
                    "thumbnail_url": _relative_url(paths.get("thumbnail")),
                    "page_url": f"/images/{item['id']}",
                }
        return out

    def thumb(self, face_id: int) -> bytes:
        conn = _connect()
        row = conn.execute("SELECT crop_path FROM faces WHERE id=?", (int(face_id),)).fetchone()
        conn.close()
        if not row or not row["crop_path"]:
            raise LookupError("人脸缩略图不存在")
        path = Path(row["crop_path"]).resolve()
        root = FACE_CACHE.resolve()
        if root not in path.parents:
            raise PermissionError("人脸缩略图路径无效")
        if not path.is_file():
            raise LookupError("人脸缩略图文件不存在")
        return path.read_bytes()

    def apply(self, min_images: int = DEFAULT_MIN_IMAGES,
              prefix: str = "人物", cluster_ids: list[int] | None = None) -> dict:
        conn = _connect()
        min_images = max(1, min(100, int(min_images)))
        if cluster_ids:
            placeholders = ",".join("?" for _ in cluster_ids)
            rows = list(conn.execute(
                f"""SELECT * FROM clusters WHERE id IN ({placeholders})
                    AND image_count>=? ORDER BY image_count DESC""",
                [int(item) for item in cluster_ids] + [min_images],
            ))
        else:
            rows = list(conn.execute(
                "SELECT * FROM clusters WHERE image_count>=? ORDER BY image_count DESC",
                (min_images,),
            ))
        if not rows:
            conn.close()
            return {"clusters": 0, "created": 0, "updated": 0, "images": 0, "warnings": 0}
        stash = Stash()
        existing_names: set[str] = set()
        page = 1
        while True:
            data = stash.graphql(
                "query($p:Int!){findPerformers(filter:{page:$p, per_page:500}){count performers{name}}}",
                {"p": page},
            )["findPerformers"]
            batch = data.get("performers") or []
            existing_names.update(str(item.get("name") or "") for item in batch)
            if not batch or page * 500 >= int(data.get("count") or 0):
                break
            page += 1
        prefix = (prefix or "人物").strip()[:40]
        next_number = 1
        for name in existing_names:
            if name.startswith(prefix + " "):
                try:
                    next_number = max(next_number, int(name.rsplit(" ", 1)[1]) + 1)
                except ValueError:
                    pass
        created = updated = warnings = image_total = 0
        for cluster in rows:
            name = cluster["name"]
            performer_id = cluster["performer_id"]
            if not performer_id:
                candidate = f"{prefix} {next_number:03d}"
                while candidate in existing_names:
                    next_number += 1
                    candidate = f"{prefix} {next_number:03d}"
                next_number += 1
                data = stash.graphql(
                    "mutation($name:String!){performerCreate(input:{name:$name}){id name}}",
                    {"name": candidate},
                )
                performer_id = data["performerCreate"]["id"]
                name = candidate
                existing_names.add(candidate)
                created += 1
                crop = conn.execute(
                    "SELECT crop_path FROM faces WHERE id=?",
                    (cluster["representative_face"],),
                ).fetchone()
                if crop and crop["crop_path"] and Path(crop["crop_path"]).is_file():
                    encoded = "data:image/jpeg;base64," + base64.b64encode(
                        Path(crop["crop_path"]).read_bytes()
                    ).decode("ascii")
                    try:
                        stash.graphql(
                            "mutation($id:ID!,$image:String!){performerUpdate(input:{id:$id,image:$image}){id}}",
                            {"id": performer_id, "image": encoded},
                        )
                    except Exception:  # noqa: BLE001
                        warnings += 1
            else:
                updated += 1
                if not name:
                    name = f"{prefix} {cluster['id']:03d}"
            faces = list(conn.execute(
                "SELECT stash_id FROM faces WHERE cluster_id=?", (cluster["id"],)
            ))
            ids: list[str] = []
            seen = set()
            for face in faces:
                if face["stash_id"] not in seen:
                    seen.add(face["stash_id"])
                    ids.append(str(face["stash_id"]))
            for start in range(0, len(ids), 500):
                chunk = ids[start:start + 500]
                try:
                    stash.graphql(
                        """mutation($ids:[ID!]!,$p:[ID!]!){
                            bulkImageUpdate(input:{ids:$ids, performer_ids:{ids:$p, mode:ADD}}){id}
                        }""",
                        {"ids": chunk, "p": [performer_id]},
                    )
                except Exception:  # noqa: BLE001
                    warnings += 1
                    continue
                image_total += len(chunk)
            conn.execute(
                "UPDATE clusters SET performer_id=?,name=?,updated_at=? WHERE id=?",
                (performer_id, name, time.time(), cluster["id"]),
            )
            conn.commit()
        conn.close()
        return {"clusters": len(rows), "created": created, "updated": updated,
                "images": image_total, "warnings": warnings}
