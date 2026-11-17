"""Persistent media path settings, with environment variables taking precedence."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PROJECT = Path(os.environ.get("MH_PROJECT", Path(__file__).resolve().parent.parent)).expanduser().resolve()
DATA = PROJECT / "data"
SETTINGS_FILE = DATA / "settings.json"
DEFAULT_MEDIA_ROOT = r"F:\MineHubData"
DEFAULT_MODELS_ROOT = PROJECT / "models"
DEFAULT_QQ_BASE = r"D:\Tencent Files"


def load() -> dict[str, Any]:
    try:
        if SETTINGS_FILE.is_file():
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser().resolve() if raw else None


def media_root() -> Path:
    env = _env_path("MH_MEDIA_ROOT")
    if env:
        return env
    raw = str(load().get("media_root") or DEFAULT_MEDIA_ROOT).strip()
    return Path(raw).expanduser().resolve()


def models_root() -> Path:
    env = _env_path("MH_MODELS_ROOT")
    if env:
        return env
    raw = str(load().get("models_root") or "").strip()
    return Path(raw).expanduser().resolve() if raw else DEFAULT_MODELS_ROOT.resolve()


def qq_base() -> Path:
    env = _env_path("MH_QQ_BASE")
    if env:
        return env
    raw = str(load().get("qq_base") or DEFAULT_QQ_BASE).strip()
    return Path(raw).expanduser().resolve()


def _path(value: str, label: str, *, create: bool) -> Path:
    raw = (value or "").strip().strip('"')
    if not raw:
        raise ValueError(f"{label}不能为空")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{label}必须是绝对路径")
    path = path.resolve()
    if path.parent == path:
        raise ValueError(f"{label}不能是磁盘根目录")
    if path.exists() and not path.is_dir():
        raise ValueError(f"{label}不是文件夹：{path}")
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def status() -> dict[str, Any]:
    media = media_root()
    models = models_root()
    qq = qq_base()
    return {
        "media_root": str(media),
        "models_root": str(models),
        "qq_base": str(qq),
        "settings_file": str(SETTINGS_FILE),
        "overrides": {
            "media_root": bool(os.environ.get("MH_MEDIA_ROOT", "").strip()),
            "models_root": bool(os.environ.get("MH_MODELS_ROOT", "").strip()),
            "qq_base": bool(os.environ.get("MH_QQ_BASE", "").strip()),
        },
        "checks": {
            "media_exists": media.is_dir(),
            "media_writable": media.is_dir() and os.access(media, os.W_OK),
            "models_exists": models.is_dir(),
            "library_exists": (media / "library").is_dir(),
            "qq_exists": qq.is_dir(),
        },
    }


def save(*, media_root: str, models_root: str = "", qq_base: str = "") -> dict[str, Any]:
    media = _path(media_root, "资料库根目录", create=True)
    models = (_path(models_root, "模型目录", create=False)
              if (models_root or "").strip() else DEFAULT_MODELS_ROOT.resolve())
    qq = _path(qq_base, "QQ 数据根目录", create=False) if (qq_base or "").strip() else Path(DEFAULT_QQ_BASE).resolve()
    data = load()
    data.update({
        "media_root": str(media),
        "models_root": str(models),
        "qq_base": str(qq),
    })
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_name(SETTINGS_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, SETTINGS_FILE)
    return status()
