"""Build a deterministic candidate pool for the small-sample evaluation."""
from __future__ import annotations

import json
import random
from pathlib import Path

from mh.config import DATA, IMAGE_EXTS, QQ_ACCOUNTS, VIDEO_EXTS
from mh.frames import probe_duration

POOL_IMAGES = 600
CAND_VIDEOS = 25


def _iter(base: Path, exts: set[str], sub: str = "Ori"):
    for p in base.glob(f"**/{sub}/*"):
        if p.is_file() and p.suffix.lower() in exts:
            yield p


def main() -> None:
    out_dir = DATA / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    root = QQ_ACCOUNTS[0]
    imgs = [p for p in _iter(root / "Pic", IMAGE_EXTS) if p.stat().st_size > 15_000]
    vids = [p for p in _iter(root / "Video", VIDEO_EXTS)]
    rng = random.Random(42)
    rng.shuffle(imgs)
    rng.shuffle(vids)
    img_pool = imgs[:POOL_IMAGES]
    vid_cands = []
    for p in vids[:CAND_VIDEOS * 3]:
        d = probe_duration(p)
        if d >= 1.0:
            vid_cands.append({"path": str(p), "duration": round(d, 2), "size": p.stat().st_size})
        if len(vid_cands) >= CAND_VIDEOS:
            break
    manifest = {
        "total_ori_images": len(imgs),
        "total_videos": len(vids),
        "images": [str(p) for p in img_pool],
        "videos": vid_cands,
    }
    dst = out_dir / "pool.json"
    dst.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"pool: {len(img_pool)} images, {len(vid_cands)} video candidates -> {dst}")


if __name__ == "__main__":
    main()