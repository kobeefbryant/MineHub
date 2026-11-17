"""Client for llama-server (OpenAI-compatible chat completions with images)."""
from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from typing import Any

import requests

from .config import LLAMA_HOST, LLAMA_PORT, VLM_PROMPT

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_real_photo": {"type": "boolean"},
        "content_type": {"type": "string", "enum": ["real_photo", "anime", "illustration", "screenshot", "meme", "text", "other"]},
        "nsfw_level": {"type": "string", "enum": ["safe", "suggestive", "explicit"]},
        "corporeal_nsfw": {"type": "boolean"},
        "nsfw_evidence": {"type": "string"},
        "people_count": {"type": "integer"},
        "main_subject": {"type": "string"},
        "scene": {"type": "string"},
        "clothing": {"type": "string", "enum": ["none", "lingerie", "swimwear", "casual", "formal", "uniform", "other", "unknown"]},
        "tags": {"type": "array", "items": {"type": "string"}},
        "category": {"type": "string", "enum": ["daily", "sexy", "adult", "anime", "sticker", "screenshot", "review", "other"]},
        "confidence": {"type": "number"},
    },
    "required": ["is_real_photo", "content_type", "nsfw_level", "corporeal_nsfw", "category", "tags"],
}


def b64_image(path: str | Path, max_side: int = 1024) -> str:
    from PIL import Image

    with Image.open(path) as im:
        im = im.convert("RGB")
        if max(im.size) > max_side:
            im.thumbnail((max_side, max_side), Image.LANCZOS)
        buf = __import__("io").BytesIO()
        im.save(buf, format="JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode()


class VLM:
    def __init__(self, model_tag: str, host: str = LLAMA_HOST, port: int = LLAMA_PORT) -> None:
        self.tag = model_tag
        self.base = f"http://{host}:{port}"
        self.session = requests.Session()

    def healthy(self, timeout: float = 3.0) -> bool:
        try:
            r = self.session.get(f"{self.base}/health", timeout=timeout)
            return r.status_code == 200 and r.json().get("status") in ("ok", "no slot available", None)
        except Exception:
            return False

    def wait_ready(self, timeout: float = 240.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.healthy():
                return True
            time.sleep(2)
        return False

    def complete(
        self,
        images: list[str | Path],
        prompt: str = VLM_PROMPT,
        max_tokens: int = 320,
        timeout: float = 180.0,
        temperature: float = 0.0,
        max_side: int = 1024,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.complete_custom(
            images, prompt, SCHEMA, max_tokens=max_tokens, timeout=timeout,
            temperature=temperature, max_side=max_side,
        )

    def complete_custom(
        self,
        images: list[str | Path],
        prompt: str,
        schema: dict[str, Any],
        max_tokens: int = 200,
        timeout: float = 180.0,
        temperature: float = 0.0,
        max_side: int = 1024,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for img in images:
            content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64_image(img, max_side)}})
        payload = {
            "model": self.tag,
            "messages": [{"role": "user", "content": content}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "verdict", "strict": True, "schema": schema},
            },
            "cache_prompt": False,
        }
        t0 = time.perf_counter()
        r = self.session.post(f"{self.base}/v1/chat/completions", json=payload, timeout=timeout)
        dt = time.perf_counter() - t0
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return parse_json(text), {"latency_s": dt, **usage}


def parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise ValueError(f"non-JSON VLM output: {text[:200]!r}")