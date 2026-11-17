"""Semantic label prompts, tag groups and a lightweight 2-D embedding map."""
from __future__ import annotations

import numpy as np

LABELS: list[tuple[str, str]] = [
    ("person", "人物"),
    ("single person", "单人"),
    ("multiple people", "多人"),
    ("woman", "女性"),
    ("man", "男性"),
    ("face", "面部"),
    ("portrait", "肖像"),
    ("full body", "全身"),
    ("selfie", "自拍"),
    ("group photo", "合影"),
    ("smiling", "微笑"),
    ("looking at viewer", "看向镜头"),
    ("back view", "背影"),
    ("side view", "侧面"),
    ("indoor", "室内"),
    ("outdoor", "室外"),
    ("bedroom", "卧室"),
    ("bathroom", "浴室"),
    ("living room", "客厅"),
    ("office", "办公室"),
    ("classroom", "教室"),
    ("street", "街道"),
    ("beach", "海滩"),
    ("nature", "自然"),
    ("night", "夜景"),
    ("water", "水面"),
    ("bed", "床"),
    ("sofa", "沙发"),
    ("chair", "椅子"),
    ("mirror", "镜子"),
    ("window", "窗户"),
    ("clothing", "穿着衣物"),
    ("lingerie", "内衣"),
    ("swimsuit", "泳装"),
    ("uniform", "制服"),
    ("stockings", "丝袜"),
    ("dress", "裙装"),
    ("jeans", "牛仔"),
    ("pajamas", "睡衣"),
    ("nude", "裸露"),
    ("sitting", "坐姿"),
    ("standing", "站立"),
    ("lying down", "躺卧"),
    ("kneeling", "跪姿"),
    ("sports", "运动"),
    ("dancing", "舞蹈"),
    ("computer", "电脑"),
    ("smartphone", "手机"),
    ("text", "文字"),
    ("chat screenshot", "聊天截图"),
    ("meme", "表情包"),
    ("screenshot", "屏幕截图"),
    ("food", "食物"),
    ("animal", "动物"),
    ("plant", "植物"),
    ("anime", "二次元"),
    ("illustration", "插画"),
    ("realistic photo", "写实照片"),
    ("pixel art", "像素画"),
    ("black and white", "黑白"),
    ("close-up", "特写"),
    ("blurry", "模糊"),
    ("dark", "暗光"),
    ("bright", "明亮"),
    ("colorful", "鲜艳"),
    ("tattoo", "纹身"),
    ("glasses", "眼镜"),
    ("hat", "帽子"),
    ("long hair", "长发"),
    ("short hair", "短发"),
    ("black hair", "黑发"),
    ("blonde hair", "金发"),
]

GROUP_NAMES = ["成人", "性感", "二次元", "截图/文字", "日常", "其他"]


def top_labels(vector: np.ndarray, matrix: np.ndarray, limit: int = 5) -> list[dict]:
    scores = matrix @ np.asarray(vector, dtype=np.float32).reshape(-1)
    count = min(max(1, limit), len(scores))
    index = np.argpartition(-scores, count - 1)[:count]
    index = index[np.argsort(-scores[index])]
    return [
        {
            "key": LABELS[int(i)][0],
            "label": LABELS[int(i)][1],
            "score": round(float(scores[int(i)]), 4),
        }
        for i in index
    ]


def group_for_tags(tags: str) -> int:
    text = (tags or "").lower()
    if any(word in text for word in ("explicit", "porn", "adult", "露骨", "成人")):
        return 0
    if any(word in text for word in ("sexy", "suggestive", "enticing", "性感", "擦边")):
        return 1
    if any(word in text for word in ("anime", "hentai", "二次元")):
        return 2
    if any(word in text for word in ("screenshot", "chat", "text", "截图", "聊天", "文字")):
        return 3
    if any(word in text for word in ("daily", "sfw", "safe", "日常", "安全")):
        return 4
    return 5


def project(embeddings: np.ndarray) -> np.ndarray:
    """Project normalized embeddings onto their first two principal axes."""
    emb = np.asarray(embeddings, dtype=np.float32)
    if emb.ndim != 2 or emb.shape[0] == 0:
        return np.zeros((emb.shape[0] if emb.ndim == 2 else 0, 2), dtype=np.float32)
    if emb.shape[0] == 1:
        return np.zeros((1, 2), dtype=np.float32)
    centered = emb - emb.mean(axis=0, keepdims=True)
    covariance = (centered.T @ centered) / max(1, centered.shape[0] - 1)
    values, vectors = np.linalg.eigh(covariance)
    order = np.argsort(values)[-2:][::-1]
    xy = centered @ vectors[:, order]
    for axis in range(2):
        low, high = np.percentile(xy[:, axis], [2, 98])
        span = max(float(high - low), 1e-9)
        xy[:, axis] = np.clip((xy[:, axis] - low) / span, 0.0, 1.0)
    return (xy * 2.0 - 1.0).astype(np.float32)