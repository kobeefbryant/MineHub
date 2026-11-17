"""Vision embeddings from the existing SigLIP2 NSFW model."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np

from .config import NSFW_MODEL


class SiglipEmbedder:
    def __init__(self, device: str = "cpu", model_dir: Path = NSFW_MODEL) -> None:
        import torch
        from transformers import AutoImageProcessor, SiglipForImageClassification

        self.torch = torch
        self.device = device
        dtype = torch.float16 if device == "cuda" else torch.float32
        self.processor = AutoImageProcessor.from_pretrained(str(model_dir), local_files_only=True)
        self.model = SiglipForImageClassification.from_pretrained(
            str(model_dir), local_files_only=True, torch_dtype=dtype
        ).to(device).eval()
        base = getattr(self.model, "siglip", None) or getattr(self.model, "model", None) or self.model
        self.vision = base.vision_model

    def image_embeddings(self, images: Iterable) -> np.ndarray:
        import torch
        from PIL import Image

        batch = [im.convert("RGB") if isinstance(im, Image.Image) else im for im in images]
        inputs = self.processor(images=batch, return_tensors="pt")
        pixel_values = inputs["pixel_values"].to(self.device)
        with torch.inference_mode():
            out = self.vision(pixel_values=pixel_values)
            emb = getattr(out, "pooler_output", None)
            if emb is None:
                emb = out.last_hidden_state.mean(dim=1)
        emb = torch.nn.functional.normalize(emb.float(), dim=-1)
        return emb.cpu().numpy().astype(np.float32)

    def image_embedding(self, image) -> np.ndarray:
        return self.image_embeddings([image])[0]
