"""Stage-1 fast pass: SigLIP2 NSFW 5-class classifier, optional WD Eva02 tagger."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from .config import NSFW_MODEL, SIGLIP_LABELS, WD_TAGGER


@dataclass
class PrefilterResult:
    label: str
    scores: dict[str, float]


class SiglipNSFW:
    """SigLIP2 image classifier, 5 classes, 256px input - very fast on GPU."""

    def __init__(self, model_dir: Path = NSFW_MODEL, device: str | None = None) -> None:
        import torch
        from transformers import AutoImageProcessor, SiglipForImageClassification

        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.processor = AutoImageProcessor.from_pretrained(str(model_dir), local_files_only=True)
        self.model = SiglipForImageClassification.from_pretrained(
            str(model_dir), local_files_only=True, torch_dtype=torch.float16
        )
        self.model.to(self.device).eval()
        self.labels = [self.model.config.id2label[i] for i in range(len(self.model.config.id2label))]

    def classify_batch(self, images: Sequence) -> list[PrefilterResult]:
        import torch

        if not images:
            return []
        inputs = self.processor(images=list(images), return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items() if hasattr(v, "to")}
        with torch.inference_mode():
            logits = self.model(**inputs).logits.float()
            probs = torch.softmax(logits, dim=-1).cpu().numpy()
        out: list[PrefilterResult] = []
        for row in probs:
            scores = {label: float(p) for label, p in zip(self.labels, row)}
            out.append(PrefilterResult(label=max(scores, key=scores.get), scores=scores))
        return out

    def classify(self, image) -> PrefilterResult:
        return self.classify_batch([image])[0]


class WDTagger:
    """WD Eva02 large tagger (ONNX). Used for anime/sticker screening + tag enrichment."""

    SIZE = 448

    def __init__(self, model_dir: Path = WD_TAGGER, prefer_cuda: bool = True) -> None:
        import onnxruntime as ort
        from PIL import Image

        self.Image = Image
        providers = []
        if prefer_cuda:
            providers.append("CUDAExecutionProvider")
        providers.append("CPUExecutionProvider")
        self.session = ort.InferenceSession(str(model_dir / "model.onnx"), providers=providers)
        self.provider = self.session.get_providers()[0]
        self.input_name = self.session.get_inputs()[0].name
        tags = []
        with open(model_dir / "selected_tags.csv", newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                tags.append((row["name"], int(row["category"])))
        self.tags = tags
        self.rating_idx = [i for i, (_, c) in enumerate(tags) if c == 9]
        self.rating_names = [tags[i][0] for i in self.rating_idx]

    def _prep(self, image) -> np.ndarray:
        img = image.convert("RGB")
        w, h = img.size
        scale = self.SIZE / max(w, h)
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), self.Image.BICUBIC)
        canvas = self.Image.new("RGB", (self.SIZE, self.SIZE), (255, 255, 255))
        canvas.paste(img, ((self.SIZE - img.width) // 2, (self.SIZE - img.height) // 2))
        arr = np.asarray(canvas, dtype=np.float32)
        return arr[None, ...]

    def tag_batch(self, images: Iterable) -> list[dict]:
        out = []
        for image in images:
            x = self._prep(image)
            preds = self.session.run(None, {self.input_name: x})[0][0]
            probs = np.asarray(preds, dtype=np.float32)
            rating = {self.rating_names[j]: float(probs[idx]) for j, idx in enumerate(self.rating_idx)}
            out.append({"ratings": rating, "anime_score": float(rating.get("questionable", 0) + rating.get("explicit", 0))})
        return out


def map_stage1(label: str) -> str:
    """Collapse SigLIP labels into an initial routing bucket."""
    return {
        "Normal": "daily",
        "Enticing or Sensual": "sexy",
        "Pornography": "adult",
        "Hentai": "anime",
        "Anime Picture": "anime",
    }.get(label, "review")