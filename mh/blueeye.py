"""Blue-Eye 3-class content classifier (safe / suggestive / explicit) wrapper."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable, Sequence

from .config import MODELS

BLUE_EYE_MODEL = MODELS / "blue-eye"


class BlueEye:
    """Wraps the model's own inference.py (gated weights, DINOv3 ViT-L/16)."""

    def __init__(self, model_dir: Path | str = BLUE_EYE_MODEL, device: str = "cuda",
                 precision: str = "bf16", batch_size: int = 16) -> None:
        model_dir = Path(model_dir)
        if not (model_dir / "model.safetensors").exists():
            raise FileNotFoundError(
                f"Blue-Eye weights not found at {model_dir}. Accept the DINOv3 license at "
                "https://huggingface.co/pp1618/Blue-Eye and download the repository there."
            )
        sys.path.insert(0, str(model_dir))
        from inference import classify, get_model  # type: ignore

        self.model_dir = model_dir
        self.device = device
        self.precision = precision
        self.batch_size = batch_size
        self._classify = classify
        self.model = get_model(str(model_dir), device=device)

    def classify_paths(self, paths: Sequence[str | Path], batch_size: int | None = None) -> list[dict]:
        return self._classify(
            [str(p) for p in paths], model=self.model, device=self.device,
            precision=self.precision, batch_size=batch_size or self.batch_size,
        )

    @staticmethod
    def nsfw_score(probabilities: dict) -> float:
        return float(probabilities.get("suggestive", 0.0)) + float(probabilities.get("explicit", 0.0))

    def score_paths(self, paths: Iterable[str | Path], batch_size: int | None = None) -> list[dict]:
        paths = list(paths)
        out = []
        bs = batch_size or self.batch_size
        for i in range(0, len(paths), bs):
            for r in self.classify_paths(paths[i:i + bs], batch_size=bs):
                if "probabilities" in r:
                    r = {**r, "nsfw_score": self.nsfw_score(r["probabilities"])}
                out.append(r)
        return out
