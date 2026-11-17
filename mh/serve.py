"""llama-server lifecycle helper shared by eval and pipeline."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .config import DATA, LLAMA, LLAMA_HOST, LLAMA_PORT, VLM_HUIHUI, VLM_NSFW

MODEL_DIRS = {"nsfw": VLM_NSFW, "huihui": VLM_HUIHUI}


class LlamaServer:
    def __init__(self, model: str, slots: int = 1, ctx: int = 8192, port: int = LLAMA_PORT) -> None:
        base: Path = MODEL_DIRS[model]
        gguf = next(base.glob("*.Q5_K_M.gguf"))
        mmproj = next(base.glob("*mmproj-f16.gguf"))
        self.model_name = model
        self.port = port
        self.cmd = [
            str(LLAMA / "llama-server.exe"),
            "-m", str(gguf), "--mmproj", str(mmproj),
            "-c", str(ctx), "-ngl", "99", "--flash-attn", "on",
            "--host", LLAMA_HOST, "--port", str(port),
            "-np", str(slots), "--jinja", "--no-warmup", "--metrics",
        ]
        self.log_path = DATA / "logs" / f"llama_{model}.log"
        self.proc: subprocess.Popen | None = None
        self.log = None

    def __enter__(self):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log = open(self.log_path, "w", encoding="utf-8", errors="replace")
        self.proc = subprocess.Popen(self.cmd, stdout=self.log, stderr=subprocess.STDOUT)
        from .vlm import VLM

        if not VLM(self.model_name, port=self.port).wait_ready(timeout=300):
            raise RuntimeError(f"llama-server ({self.model_name}) failed to start; see {self.log_path}")
        return self

    def __exit__(self, *exc) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.log:
            self.log.close()