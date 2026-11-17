"""Google SigLIP2 base image/text embeddings for semantic search."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from .config import SIGLIP2_MODEL


class Siglip2Embedder:
    def __init__(self, device: str = "cpu", model_dir: Path = SIGLIP2_MODEL) -> None:
        import torch
        from transformers import AutoModel, AutoProcessor

        self.torch = torch
        self.device = device
        dtype = torch.float16 if device == "cuda" else torch.float32
        self.processor = AutoProcessor.from_pretrained(str(model_dir), local_files_only=True)
        self.model = AutoModel.from_pretrained(
            str(model_dir), local_files_only=True, torch_dtype=dtype
        ).to(device).eval()

    def _features(self, output) -> "object":
        if self.torch.is_tensor(output):
            return output
        emb = getattr(output, "pooler_output", None)
        if emb is None:
            emb = output.last_hidden_state.mean(dim=1)
        return emb

    def image_embeddings(self, images: Iterable) -> np.ndarray:
        from PIL import Image

        batch = [im.convert("RGB") if isinstance(im, Image.Image) else im for im in images]
        inputs = self.processor(images=batch, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with self.torch.inference_mode():
            emb = self._features(self.model.get_image_features(**inputs))
            emb = self.torch.nn.functional.normalize(emb.float(), dim=-1)
        return emb.cpu().numpy().astype(np.float32)

    def image_embedding(self, image) -> np.ndarray:
        return self.image_embeddings([image])[0]

    def text_embeddings(self, texts: Sequence[str]) -> np.ndarray:
        inputs = self.processor(text=list(texts), padding="max_length", truncation=True, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with self.torch.inference_mode():
            emb = self._features(self.model.get_text_features(**inputs))
            emb = self.torch.nn.functional.normalize(emb.float(), dim=-1)
        return emb.cpu().numpy().astype(np.float32)

    def text_embedding(self, text: str) -> np.ndarray:
        return self.text_embeddings([text])[0]
