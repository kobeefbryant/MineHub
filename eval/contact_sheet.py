"""Contact sheets for human verification of sampled media."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CELL = 220
COLS = 6
PAD = 26


def sheet(items: list[dict], out: Path, cols: int = COLS) -> None:
    rows = (len(items) + cols - 1) // cols
    W, H = cols * CELL, rows * (CELL + PAD)
    canvas = Image.new("RGB", (W, H), (18, 18, 18))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 15)
    except OSError:
        font = ImageFont.load_default()
    for i, item in enumerate(items):
        r, c = divmod(i, cols)
        x, y = c * CELL, r * (CELL + PAD)
        try:
            with Image.open(item["path"]) as im:
                im = im.convert("RGB")
                im.thumbnail((CELL - 6, CELL - 6), Image.LANCZOS)
                canvas.paste(im, (x + (CELL - im.width) // 2, y + (CELL - im.height) // 2))
        except Exception:
            draw.rectangle([x, y, x + CELL - 6, y + CELL - 6], outline=(120, 40, 40))
        label = item.get("label", "")
        draw.text((x + 6, y + CELL + 3), f"{i:02d} {label}"[:34], fill=(230, 230, 230), font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, quality=88)
    print(f"sheet -> {out} ({len(items)} items)")


def main() -> None:
    src = Path(sys.argv[1])
    out = Path(sys.argv[2])
    data = json.loads(src.read_text(encoding="utf-8"))
    items = data["items"] if isinstance(data, dict) else data
    cols = int(sys.argv[3]) if len(sys.argv) > 3 else COLS
    sheet(items, out, cols)


if __name__ == "__main__":
    main()