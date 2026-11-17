"""Video frame sampling via ffmpeg, and small image helpers."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

FFMPEG = r"D:\ffmpeg\bin\ffmpeg.exe"
FFPROBE = r"D:\ffmpeg\bin\ffprobe.exe"


def probe_duration(path: str | Path) -> float:
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(json.loads(out.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def extract_frames(path: str | Path, count: int = 6, max_side: int = 1024) -> list[Path]:
    """Uniformly sample `count` frames; returns temp jpg paths (caller deletes dir)."""
    path = str(path)
    dur = probe_duration(path)
    tmpdir = Path(tempfile.mkdtemp(prefix="mh_frames_"))
    frames: list[Path] = []
    if dur <= 0:
        timestamps = [0.0]
    else:
        # skip the first/last 5% so black intros do not dominate
        lo, hi = dur * 0.05, dur * 0.95
        step = (hi - lo) / max(1, count - 1) if count > 1 else 0
        timestamps = [lo + i * step for i in range(count)]
    for i, ts in enumerate(timestamps):
        dst = tmpdir / f"f{i:02d}.jpg"
        cmd = [
            FFMPEG, "-v", "error", "-ss", f"{ts:.3f}", "-i", path,
            "-frames:v", "1", "-vf", f"scale='min({max_side},iw)':-2",
            "-q:v", "3", "-y", str(dst),
        ]
        subprocess.run(cmd, capture_output=True, timeout=60)
        if dst.exists() and dst.stat().st_size > 0:
            frames.append(dst)
        if i == 0 and dur <= 0 and frames:
            break
    return frames


def cleanup_frames(frames: list[Path]) -> None:
    parent = None
    for f in frames:
        parent = f.parent
        try:
            f.unlink()
        except OSError:
            pass
    if parent is not None:
        try:
            parent.rmdir()
        except OSError:
            pass