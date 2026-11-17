"""Freeze the labelled 30-image sample + 5 videos used for model comparison."""
from __future__ import annotations

import json
import random
from pathlib import Path

from mh.config import DATA
from .contact_sheet import sheet
from mh.frames import cleanup_frames, extract_frames

OUT = DATA / "eval"


def build() -> dict:
    labeled = json.loads((OUT / "pool_labeled.json").read_text(encoding="utf-8"))
    pool = json.loads((OUT / "pool.json").read_text(encoding="utf-8"))
    by: dict[str, list[dict]] = {}
    for it in labeled:
        by.setdefault(it["label"], []).append(it)

    normal = by["Normal"]
    rng = random.Random(7)
    sheet_normal = rng.sample(normal, 42)
    rng2 = random.Random(11)
    normal2 = normal[:]
    rng2.shuffle(normal2)
    sheet_normal2 = normal2[:60]
    sheet_nsfw = by["Enticing or Sensual"] + by["Pornography"] + by["Hentai"]
    sheet_anime = by["Anime Picture"]

    picks = [
        # (sheet, idx, gt_category, gt_nsfw, note)
        ("normal2", 1, "daily", "safe", "outdoor woman photo"),
        ("normal2", 43, "daily", "safe", "expo crowd"),
        ("normal2", 46, "daily", "safe", "lecture hall"),
        ("normal2", 51, "daily", "safe", "hand close-up"),
        ("normal2", 54, "daily", "safe", "news photo"),
        ("normal2", 57, "daily", "safe", "male portrait"),
        ("normal", 3, "screenshot", "safe", "POS receipt table"),
        ("normal", 5, "screenshot", "safe", "app screenshot"),
        ("normal", 14, "screenshot", "safe", "chat log"),
        ("normal", 23, "screenshot", "safe", "financial table"),
        ("anime", 3, "sticker", "safe", "meme doodle"),
        ("anime", 24, "sticker", "safe", "cat sticker"),
        ("anime", 47, "sticker", "safe", "blue sticker"),
        ("anime", 53, "sticker", "safe", "bunny sticker"),
        ("anime", 9, "anime", "safe", "anime portrait"),
        ("anime", 21, "anime", "safe", "anime girl"),
        ("anime", 39, "anime", "safe", "anime green hair"),
        ("anime", 58, "anime", "safe", "anime girl"),
        ("nsfw", 0, "sexy", "suggestive", "cosplay back view"),
        ("nsfw", 8, "sexy", "suggestive", "lingerie"),
        ("nsfw", 17, "sexy", "suggestive", "cosplay lingerie"),
        ("nsfw", 18, "sexy", "suggestive", "sheer top"),
        ("nsfw", 22, "sexy", "suggestive", "white stockings"),
        ("nsfw", 26, "sexy", "suggestive", "tight top"),
        ("nsfw", 29, "adult", "explicit", "nude couple"),
        ("nsfw", 34, "adult", "explicit", "lingerie explicit"),
        ("nsfw", 36, "adult", "explicit", "nude close-up"),
        ("nsfw", 37, "adult", "explicit", "nude pose"),
        ("nsfw", 39, "adult", "explicit", "collage explicit"),
        ("nsfw", 44, "anime", "suggestive", "hentai-ish illustration"),
    ]
    sheets = {"normal": sheet_normal, "normal2": sheet_normal2, "nsfw": sheet_nsfw, "anime": sheet_anime}
    images = []
    for sheet_name, idx, cat, nsfw, note in picks:
        src = sheets[sheet_name][idx]
        images.append({
            "path": src["path"],
            "siglip_pred": src["label"],
            "gt_category": cat,
            "gt_nsfw": nsfw,
            "note": note,
        })
    manifest = {"images": images, "videos": []}
    pool_videos = json.loads((OUT / "pool.json").read_text(encoding="utf-8"))["videos"]
    video_picks = [
        (0, "daily", "safe", "cat on fence"),
        (1, "sexy", "suggestive", "tight outfit walking"),
        (2, "sexy", "suggestive", "cosplay on subway"),
        (3, "daily", "safe", "lecture recording"),
        (7, "daily", "safe", "street scene"),
    ]
    for idx, cat, nsfw, note in video_picks:
        v = pool_videos[idx]
        manifest["videos"].append({
            "path": v["path"], "duration": v["duration"], "size": v["size"],
            "gt_category": cat, "gt_nsfw": nsfw, "note": note,
        })
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"manifest: {len(images)} images -> {OUT / 'manifest.json'}")
    return manifest


def video_sheet(manifest: dict, n: int = 8) -> None:
    cands = json.loads((OUT / "pool.json").read_text(encoding="utf-8"))["videos"][:n]
    items = []
    temp_frames = []
    for vi, v in enumerate(cands):
        frames = extract_frames(v["path"], count=4, max_side=320)
        temp_frames.extend(frames)
        for f in frames:
            items.append({"path": str(f), "label": f"v{vi} {v['duration']}s"})
    sheet(items, OUT / "sheet_videos.jpg", cols=4)
    for f in temp_frames:
        f.unlink(missing_ok=True)
    print("video candidates:", json.dumps(cands, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    m = build()
    video_sheet(m)