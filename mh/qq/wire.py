from __future__ import annotations

from dataclasses import dataclass


class WireError(ValueError):
    pass


def read_varint(data: bytes, i: int) -> tuple[int, int]:
    shift = 0
    val = 0
    n = len(data)
    while True:
        if i >= n:
            raise WireError("truncated varint")
        b = data[i]
        i += 1
        val |= (b & 0x7F) << shift
        if not b & 0x80:
            return val, i
        shift += 7
        if shift > 63:
            raise WireError("varint too long")


def iter_fields(data: bytes):
    i = 0
    n = len(data)
    while i < n:
        key, i = read_varint(data, i)
        field_no, wire_type = key >> 3, key & 7
        if field_no == 0:
            raise WireError("field 0")
        if wire_type == 0:
            val, i = read_varint(data, i)
            yield field_no, wire_type, val
        elif wire_type == 1:
            if i + 8 > n:
                raise WireError("truncated fixed64")
            yield field_no, wire_type, data[i:i + 8]
            i += 8
        elif wire_type == 2:
            ln, i = read_varint(data, i)
            if i + ln > n:
                raise WireError("truncated bytes")
            yield field_no, wire_type, data[i:i + ln]
            i += ln
        elif wire_type == 5:
            if i + 4 > n:
                raise WireError("truncated fixed32")
            yield field_no, wire_type, data[i:i + 4]
            i += 4
        else:
            # groups (3/4) do not appear in these messages; stop parsing this blob
            raise WireError(f"unsupported wire type {wire_type}")


@dataclass(slots=True)
class MediaSegment:
    content_type: int  # 45002: 2 image, 3 file, 5 video
    media_sub: int  # 45003
    md5: str  # lowercase hex or ""
    filename: str
    file_size: int
    ext: str


def _first(fields: dict[int, list], no: int, default=None):
    vals = fields.get(no)
    return vals[0] if vals else default


def _as_text(v) -> str:
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v).decode("utf-8", "ignore")
    if isinstance(v, str):
        return v
    return ""


def _as_md5(fields: dict[int, list]) -> str:
    raw = _first(fields, 45406)
    if isinstance(raw, (bytes, bytearray, memoryview)) and len(raw) == 16:
        return bytes(raw).hex()
    alt = _first(fields, 45424)
    if isinstance(alt, (bytes, bytearray, memoryview)):
        b = bytes(alt)
        if len(b) == 16:
            return b.hex()
        text = b.decode("ascii", "ignore").strip().lower()
        if len(text) == 32 and all(c in "0123456789abcdef" for c in text):
            return text
    if isinstance(alt, str):
        text = alt.strip().lower()
        if len(text) == 32 and all(c in "0123456789abcdef" for c in text):
            return text
    return ""


def extract_media(blob: bytes) -> list[MediaSegment]:
    try:
        segments = [v for fn, wt, v in iter_fields(blob) if fn == 40800 and wt == 2]
    except WireError:
        return []
    if not segments:
        segments = [blob]
    out: list[MediaSegment] = []
    for seg in segments:
        try:
            fields: dict[int, list] = {}
            for fn, wt, val in iter_fields(seg):
                fields.setdefault(fn, []).append(val)
        except WireError:
            continue
        md5 = _as_md5(fields)
        if not md5:
            continue
        ct = _first(fields, 45002)
        sub = _first(fields, 45003)
        out.append(
            MediaSegment(
                content_type=ct if isinstance(ct, int) else 0,
                media_sub=sub if isinstance(sub, int) else 0,
                md5=md5,
                filename=_as_text(_first(fields, 45402)),
                file_size=_first(fields, 45405) if isinstance(_first(fields, 45405), int) else 0,
                ext=_as_text(_first(fields, 45419)),
            )
        )
    return out


def classify(seg: MediaSegment) -> str:
    if seg.content_type == 2:
        return "image"
    if seg.content_type == 5:
        return "video"
    if seg.content_type == 3:
        return "file"
    if seg.media_sub == 1:
        return "image"
    if seg.media_sub == 7:
        return "video"
    return "file"
