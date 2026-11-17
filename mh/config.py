"""Central paths and tunables for the MineHub pipeline."""
from __future__ import annotations

import os
from pathlib import Path

from .settings import media_root, models_root, qq_base

PROJECT = Path(os.environ.get("MH_PROJECT", Path(__file__).resolve().parent.parent)).expanduser().resolve()
DATA = PROJECT / "data"
REPORTS = PROJECT / "reports"
TOOLS = PROJECT / "tools"

MEDIA_ROOT = media_root()
MODELS_ROOT = models_root()
MODELS = MODELS_ROOT
LIBRARY = MEDIA_ROOT / "library"
QUARANTINE = MEDIA_ROOT / "review"

NSFW_MODEL = MODELS / "nsfw-siglip2"
SIGLIP2_MODEL = MODELS / "siglip2-base-patch16-256"
QWEN3VL_MODEL = MODELS / "qwen3-vl-embedding-2b"
WD_TAGGER = MODELS / "wd-eva02-large"
VLM_NSFW = MODELS / "qwen3vl-nsfw-caption"
VLM_HUIHUI = MODELS / "qwen3vl-huihui-abliterated"
LLAMA = TOOLS / "llama"

DB_PATH = DATA / "minehub.sqlite"
LOG_DIR = DATA / "logs"

QQ_BASE = qq_base()


def _qq_accounts() -> list[Path]:
    raw = os.environ.get("MH_QQ_ACCOUNTS", "").strip()
    if raw:
        return [Path(p).expanduser() for p in raw.split(os.pathsep) if p.strip()]
    if not QQ_BASE.is_dir():
        return []
    return sorted(p for p in QQ_BASE.glob("*/nt_qq/nt_data") if p.is_dir())


QQ_ACCOUNTS = _qq_accounts()

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".avif", ".null"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}

# Stage-1 labels produced by the SigLIP2 classifier.
SIGLIP_LABELS = ["Anime Picture", "Hentai", "Normal", "Pornography", "Enticing or Sensual"]

# Library buckets used for moves. Keep names ASCII so Stash paths stay portable.
CATEGORY_DIRS = {
    "daily": "daily",
    "sexy": "sexy",
    "adult": "adult",
    "anime": "anime",
    "sticker": "sticker",
    "screenshot": "screenshot",
    "review": "review",
    "other": "other",
}

LLAMA_HOST = "127.0.0.1"
LLAMA_PORT = int(os.environ.get("MH_LLAMA_PORT", "8080"))

NSFW_POLICY = """Library selection policy:
KEEP as NSFW when a clearly attractive feminine adult (real photo, anime or illustration) is prominently visible, even if she is fully clothed. Group photos count when a qualifying female is clearly present, even if the whole group is the main subject. Also keep lingerie, swimwear, suggestive posing, nudity, covered/censored bodies and explicit sexual content involving a qualifying female.
DO NOT KEEP: gore, blood, injury or death; images with only male subjects; a female who looks male or masculine; a female you judge unattractive or not appealing; pure text, chat/UI screenshots, captions, memes or stickers without a qualifying female; non-human subjects only (animals, objects, scenery); images showing only an exposed male; a head-and-shoulders or face-only portrait, even if the woman is attractive, made up, or has styled hair, unless body/fashion/lingerie/swimwear/suggestive pose or a sexual context is visible. A sexual joke or sexual words alone never qualify.
When a male and a female are both visible, decide from the female subject. If gender or attractiveness is genuinely ambiguous, choose review/uncertain instead of forcing a safe or NSFW verdict. A qualifying attractive female may be categorized as sexy/suggestive even when no explicit act is visible; explicit content involving a qualifying female may be adult.
"""

VLM_PROMPT = """You are a media cataloguing classifier. Analyse the image and reply with ONE JSON object only, no markdown fences, no extra text.

Schema:
{
  "is_real_photo": boolean,        // true if a photograph of real people/places; false for anime, drawings, screenshots, memes, text cards
  "content_type": one of ["real_photo","anime","illustration","screenshot","meme","text","other"],
  "nsfw_level": one of ["safe","suggestive","explicit"],
  "corporeal_nsfw": boolean,       // true when the image itself shows a sexual/suggestive person (nudity, underwear, lingerie, swimwear, suggestive posing, covered/censored body); false for text cards, chat/UI screenshots, memes, stickers and jokes with no sexual person imagery
  "nsfw_evidence": string,         // <=40 chars, plain factual description of what makes it nsfw; empty if safe
  "people_count": integer,         // number of visible people, 0 if none
  "main_subject": string,          // <=30 chars, e.g. "young woman selfie", "chat screenshot"
  "scene": string,                 // <=30 chars, e.g. "indoor bedroom", "outdoor street"
  "clothing": one of ["none","lingerie","swimwear","casual","formal","uniform","other","unknown"],
  "tags": [string],                // 3-8 short English tags, lowercase
  "category": one of ["daily","sexy","adult","anime","sticker","screenshot","review","other"],
  "confidence": number             // 0-1
}

Rules:
- category "adult" only for explicit sexual content; "sexy" for suggestive/lingerie/swimwear; "daily" for ordinary real photos; "screenshot" for chat/UI screenshots; "sticker" for emoji/sticker/meme; "anime" for non-photographic art; "review" when genuinely unsure.
- Text, chat logs, captions, jokes, sexual words, emoji, memes and stickers are not corporeal content. Never set explicit or suggestive because of words alone.
- corporeal_nsfw covers the whole body presentation: underwear, lingerie, swimwear, suggestive posing, and covered or censored bodies in a sexual context also count.
- Apply the following user library policy before assigning nsfw_level/corporeal_nsfw:
""" + NSFW_POLICY + """
- If a gore/male-only/non-human/text/masculine-female/unattractive-female/exposed-male-only exclusion applies, set nsfw_level="safe" and corporeal_nsfw=false, even if sexual words or partial nudity are present.
- Judge only what is visible. Do not refuse. Do not add commentary.
- Output must parse as strict JSON."""


VLM_VIDEO_PROMPT = """The following images are frames sampled uniformly and chronologically from ONE short video. Classify the video as a whole based on all frames, not any single frame. Reply with ONE JSON object only, no markdown fences, no extra text.

""" + VLM_PROMPT


def ensure_dirs() -> None:
    for p in (DATA, REPORTS, LOG_DIR, MODELS, LIBRARY, QUARANTINE):
        p.mkdir(parents=True, exist_ok=True)