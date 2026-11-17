"""MineHub same-origin gateway: public 9999, Stash internal 9998, MineHub API /mh/api."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, WSMsgType, web

from .dupes import DuplicateStore
from .index_server import App
from .library_ops import delete_items
from .stash import Stash

HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host",
    "content-length", "accept-encoding",
}


def _error(exc: Exception) -> tuple[int, dict]:
    if isinstance(exc, PermissionError):
        return 403, {"error": str(exc)}
    if isinstance(exc, LookupError):
        return 404, {"error": str(exc)}
    return 400, {"error": str(exc)[:300]}


async def _json_body(request: web.Request) -> dict:
    ctype = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if ctype != "application/json":
        raise ValueError("content-type must be application/json")
    return await request.json()


def make_app(public_port: int = 9999, internal_port: int = 9998) -> web.Application:
    upstream = f"http://127.0.0.1:{internal_port}"
    app_state = App(device="cuda", model="siglip2")
    manager = app_state.manager
    dupes = DuplicateStore()

    async def search(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            results = await asyncio.to_thread(app_state.search, payload)
            return web.json_response({"results": results})
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def status(_request: web.Request) -> web.Response:
        return web.json_response(app_state.index.status())

    async def media_info(request: web.Request) -> web.Response:
        try:
            kind = (request.query.get("kind") or "image").strip().lower()
            image_id = (request.query.get("id") or "").strip()
            if kind != "image" or not image_id:
                raise ValueError("需要 kind=image 和 id")
            path = await asyncio.to_thread(Stash().image_path, image_id)
            if not path:
                return web.json_response({"error": f"图片 #{image_id} 没有文件路径"}, status=404)
            from PIL import Image

            with Image.open(path) as im:
                frames = int(getattr(im, "n_frames", 1) or 1)
                fmt = str(im.format or "")
                width, height = im.size
            suffix = Path(path).suffix.lower()
            return web.json_response({
                "kind": "image",
                "id": image_id,
                "format": fmt,
                "suffix": suffix,
                "frames": frames,
                "animated": frames > 1,
                "is_gif": suffix == ".gif" or fmt.lower() == "gif",
                "width": width,
                "height": height,
            })
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def library_delete(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            items = payload.get("items") or []
            if not isinstance(items, list):
                raise ValueError("items 必须是数组")
            result = await asyncio.to_thread(delete_items, items, str(payload.get("mode") or ""))
            return web.json_response(result)
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def reload(_request: web.Request) -> web.Response:
        try:
            return web.json_response(await asyncio.to_thread(app_state.reload))
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def reload_labels(_request: web.Request) -> web.Response:
        try:
            return web.json_response(await asyncio.to_thread(manager.reload_labels))
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def pm_config(_request: web.Request) -> web.Response:
        return web.json_response(manager.config())

    async def pm_chats(_request: web.Request) -> web.Response:
        return web.json_response({"chats": manager.chats, **manager.index_status()})

    async def pm_index_status(_request: web.Request) -> web.Response:
        return web.json_response(manager.index_status())

    async def pm_thumb(request: web.Request) -> web.Response:
        try:
            body = await asyncio.to_thread(
                manager.thumbnail, request.query.get("path", ""), int(request.query.get("size", "320"))
            )
            return web.Response(body=body, content_type="image/jpeg")
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def pm_scan(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            result = await asyncio.to_thread(
                manager.scan, payload.get("roots") or [], payload.get("extra_roots") or []
            )
            return web.json_response(result)
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def pm_query(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            return web.json_response(await asyncio.to_thread(manager.query, payload))
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def pm_move(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            result = await asyncio.to_thread(
                manager.move, payload.get("paths") or [], payload.get("dest") or ""
            )
            return web.json_response(result)
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def pm_recycle(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            return web.json_response(await asyncio.to_thread(manager.recycle, payload.get("paths") or []))
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def pm_open(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            await asyncio.to_thread(manager.open_path, payload.get("path") or "")
            return web.json_response({"ok": True})
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def pm_index(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            return web.json_response(await asyncio.to_thread(manager.start_index, str(payload.get("account") or "")))
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def dupes_status(request: web.Request) -> web.Response:
        try:
            return web.json_response(await asyncio.to_thread(
                dupes.status, request.query.get("scope", "library")
            ))
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def dupes_scan(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            return web.json_response(await asyncio.to_thread(
                dupes.start,
                str(payload.get("scope") or "library"),
                int(payload.get("limit") or 0),
                bool(payload.get("force")),
            ))
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def dupes_groups(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            return web.json_response(await asyncio.to_thread(
                dupes.groups,
                str(payload.get("scope") or "library"),
                str(payload.get("algo") or "ahash"),
                int(payload.get("threshold") or 10),
                int(payload.get("limit") or 60),
            ))
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def dupes_scenes(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            return web.json_response(await asyncio.to_thread(
                dupes.scenes,
                int(payload.get("distance") or 10),
                int(payload.get("limit") or 60),
            ))
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def dupes_exact(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            return web.json_response(await asyncio.to_thread(
                dupes.exact, int(payload.get("limit") or 60)
            ))
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    def proxy_headers(request: web.Request) -> dict[str, str]:
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS}
        headers["host"] = request.host
        headers["accept-encoding"] = "identity"
        headers["x-forwarded-host"] = request.host
        headers["x-forwarded-proto"] = "http"
        return headers

    async def proxy_ws(request: web.Request) -> web.WebSocketResponse:
        protocols = [p.strip() for p in (request.headers.get("sec-websocket-protocol") or "").split(",") if p.strip()]
        ws = web.WebSocketResponse(protocols=protocols or ())
        await ws.prepare(request)
        headers = proxy_headers(request)
        headers.pop("sec-websocket-key", None)
        headers.pop("sec-websocket-version", None)
        headers.pop("sec-websocket-protocol", None)
        target = f"ws://127.0.0.1:{internal_port}{request.path_qs}"
        async with ClientSession() as session:
            async with session.ws_connect(target, headers=headers, protocols=protocols or ()) as upstream:
                async def pump(src, dst) -> None:
                    async for msg in src:
                        if msg.type == WSMsgType.TEXT:
                            await dst.send_str(msg.data)
                        elif msg.type == WSMsgType.BINARY:
                            await dst.send_bytes(msg.data)
                        elif msg.type == WSMsgType.CLOSE:
                            await dst.close()
                            return
                        elif msg.type == WSMsgType.ERROR:
                            return
                await asyncio.gather(pump(ws, upstream), pump(upstream, ws))
        return ws

    async def proxy(request: web.Request) -> web.StreamResponse:
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await proxy_ws(request)
        target = upstream + request.path_qs
        headers = proxy_headers(request)
        body = await request.read()
        async with ClientSession(auto_decompress=False) as session:
            async with session.request(request.method, target, headers=headers, data=body, allow_redirects=False) as resp:
                out_headers = [
                    (k, v) for k, v in resp.headers.items()
                    if k.lower() not in HOP_HEADERS and k.lower() not in {"content-encoding"}
                ]
                for i, (k, v) in enumerate(out_headers):
                    if k.lower() == "location" and v.startswith(f"http://127.0.0.1:{internal_port}"):
                        out_headers[i] = (k, v.replace(f"http://127.0.0.1:{internal_port}", f"http://127.0.0.1:{public_port}", 1))
                return web.Response(
                    status=resp.status,
                    headers=out_headers,
                    body=await resp.read(),
                )

    app = web.Application(client_max_size=512 * 1024 * 1024)
    app.router.add_get("/mh/api/health", health)
    app.router.add_get("/mh/api/status", status)
    app.router.add_get("/mh/api/media/info", media_info)
    app.router.add_post("/mh/api/library/delete", library_delete)
    app.router.add_post("/mh/api/search", search)
    app.router.add_post("/mh/api/reload", reload)
    app.router.add_post("/mh/api/reload-labels", reload_labels)
    app.router.add_get("/mh/api/pm/config", pm_config)
    app.router.add_get("/mh/api/pm/chats", pm_chats)
    app.router.add_get("/mh/api/pm/index/status", pm_index_status)
    app.router.add_get("/mh/api/pm/thumb", pm_thumb)
    app.router.add_post("/mh/api/pm/scan", pm_scan)
    app.router.add_post("/mh/api/pm/query", pm_query)
    app.router.add_post("/mh/api/pm/move", pm_move)
    app.router.add_post("/mh/api/pm/recycle", pm_recycle)
    app.router.add_post("/mh/api/pm/open", pm_open)
    app.router.add_post("/mh/api/pm/index", pm_index)
    app.router.add_get("/mh/api/dupes/status", dupes_status)
    app.router.add_post("/mh/api/dupes/scan", dupes_scan)
    app.router.add_post("/mh/api/dupes/groups", dupes_groups)
    app.router.add_post("/mh/api/dupes/scenes", dupes_scenes)
    app.router.add_post("/mh/api/dupes/exact", dupes_exact)
    app.router.add_route("*", "/{tail:.*}", proxy)
    return app


def main() -> None:
    public = int(sys.argv[1]) if len(sys.argv) > 1 else 9999
    internal = int(sys.argv[2]) if len(sys.argv) > 2 else 9998
    print(f"MineHub gateway: http://127.0.0.1:{public} -> Stash 127.0.0.1:{internal}", flush=True)
    web.run_app(make_app(public, internal), host="127.0.0.1", port=public, access_log=None)


if __name__ == "__main__":
    main()