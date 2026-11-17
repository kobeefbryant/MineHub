"""Qwen3-VL-Embedding-2B image/text embeddings for semantic search."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from .config import QWEN3VL_MODEL


class Qwen3VLEmbedder:
    INSTRUCTION = "Represent the user's input."
    QUERY_INSTRUCTION = "Retrieve images that match the description."

    def __init__(self, device: str = "cpu", model_dir: Path = QWEN3VL_MODEL,
                 max_side: int = 384) -> None:
        import torch
        from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

        self.torch = torch
        self.device = device
        self.max_side = max(128, int(max_side))
        dtype = torch.bfloat16 if device == "cuda" else torch.float32
        self.processor = AutoProcessor.from_pretrained(
            str(model_dir), local_files_only=True, padding_side="right"
        )
        self.model = Qwen3VLForConditionalGeneration.from_pretrained(
            str(model_dir),
            local_files_only=True,
            dtype=dtype,
            attn_implementation="sdpa",
        ).to(device).eval()
        self.model.config.use_cache = False

    def _conversations(self, texts: Sequence[str], images: list | None = None) -> list[list[dict]]:
        conversations = []
        for index, text in enumerate(texts):
            content = []
            if images is not None:
                content.append({"type": "image", "image": images[index]})
            if images is None or text:
                content.append({"type": "text", "text": text or "NULL"})
            conversations.append([
                {"role": "system", "content": [{"type": "text", "text": self.INSTRUCTION}]},
                {"role": "user", "content": content},
            ])
        return conversations

    def _embed(self, texts: Sequence[str], images: list | None = None) -> np.ndarray:
        conversations = self._conversations(texts, images)
        prompts = self.processor.apply_chat_template(
            conversations, add_generation_prompt=True, tokenize=False
        )
        kwargs = {
            "text": prompts,
            "return_tensors": "pt",
            "padding": True,
            "truncation": True,
            "max_length": 8192,
        }
        if images is not None:
            kwargs["images"] = images
        inputs = self.processor(**kwargs)
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with self.torch.inference_mode():
            outputs = self.model.model(**inputs)
            hidden = outputs.last_hidden_state
            attention = inputs["attention_mask"]
            flipped = attention.flip(dims=[1])
            last_positions = flipped.argmax(dim=1)
            columns = attention.shape[1] - last_positions - 1
            rows = self.torch.arange(hidden.shape[0], device=hidden.device)
            embeddings = hidden[rows, columns]
            embeddings = self.torch.nn.functional.normalize(embeddings.float(), dim=-1)
        return embeddings.cpu().numpy().astype(np.float32)

    def image_embeddings(self, images: Iterable) -> np.ndarray:
        from PIL import Image

        batch = []
        for im in images:
            im = im.convert("RGB") if isinstance(im, Image.Image) else im
            if max(im.size) > self.max_side:
                im = im.copy()
                im.thumbnail((self.max_side, self.max_side), Image.Resampling.LANCZOS)
            batch.append(im)
        return self._embed([""] * len(batch), batch)

    def image_embedding(self, image) -> np.ndarray:
        return self.image_embeddings([image])[0]

    def text_embeddings(self, texts: Sequence[str]) -> np.ndarray:
        return self._embed(list(texts))

    def text_embedding(self, text: str) -> np.ndarray:
        return self.text_embeddings([text])[0]

    def query_embeddings(self, texts: Sequence[str]) -> np.ndarray:
        prefix = "Instruct: " + self.QUERY_INSTRUCTION + chr(10) + "Query: "
        return self.text_embeddings([prefix + str(t) for t in texts])

    def query_embedding(self, text: str) -> np.ndarray:
        return self.query_embeddings([text])[0]
