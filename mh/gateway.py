"""MineHub same-origin gateway: public 9999, Stash internal 9998, MineHub API /mh/api."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, WSMsgType, web

from .dupes import DuplicateStore
from .faces import Faces
from .folder_ops import list_folder, media_kind, move_files, move_stash_items, resolve_media, thumbnail
from .index_server import App
from .library_ops import delete_items
from .nine_grid import list_images as list_nine_images, scan_folder as scan_nine_folder
from .settings import save as save_settings, status as settings_status
from .stash import Stash

HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host",
    "content-length", "accept-encoding",
}

# Runs before Stash's module bundle so the first list request already uses the
# MineHub defaults instead of rendering date order once and then snapping.
SORT_BOOTSTRAP = """<script data-mh-sort-bootstrap>
(function () {
  "use strict";
  function mhDefaultUrl(input, force) {
    try {
      var u = new URL(String(input), location.href);
      if (u.origin !== location.origin) return input;
      var p = u.pathname.replace(/\\/+$/, "");
      if (p !== "/images" && p !== "/scenes") return input;
      var changed = false;
      var sortby = u.searchParams.get("sortby");
      if (force) {
        if (!sortby || (sortby === "date" && !u.searchParams.has("sortdir"))) {
          u.searchParams.set("sortby", "filesize");
          u.searchParams.set("sortdir", "desc");
          changed = true;
        }
      } else if (!sortby) {
        u.searchParams.set("sortby", "filesize");
        u.searchParams.set("sortdir", "desc");
        changed = true;
      }
      if (!u.searchParams.has("disp")) { u.searchParams.set("disp", "2"); changed = true; }
      if (!u.searchParams.has("perPage")) { u.searchParams.set("perPage", "200"); changed = true; }
      return changed ? (u.pathname + u.search + u.hash) : input;
    } catch (e) {
      return input;
    }
  }
  var initial = mhDefaultUrl(location.href, false);
  if (initial !== location.href) {
    try { history.replaceState(history.state, "", initial); } catch (e) {}
  }
  function wrapHistory(name) {
    var original = history[name];
    if (typeof original !== "function") return;
    history[name] = function (state, title, url) {
      if (url != null) {
        try {
          var target = new URL(String(url), location.href);
          var current = location.pathname.replace(/\\/+$/, "");
          var next = target.pathname.replace(/\\/+$/, "");
          if (next !== current) url = mhDefaultUrl(url, true);
        } catch (e) {}
      }
      return original.call(this, state, title, url);
    };
  }
  wrapHistory("pushState");
  wrapHistory("replaceState");
})();
</script>"""

# The list components initialize their local state before reading the URL.
# Rewriting these few literals makes the very first GraphQL request use the
# MineHub defaults; the bootstrap above remains a fallback for navigation.
JS_REWRITES = [
    (
        'itemsPerPage=G0.itemsPerPage;sortDirection=G0.sortDirection',
        'itemsPerPage=(function(){var p=location.pathname.replace(/\\/+$/,"");if(p!=="/images"&&p!=="/scenes")return G0.itemsPerPage;var n=parseInt(new URLSearchParams(location.search).get("perPage"),10);return Number.isFinite(n)&&n>0?n:200;})();sortDirection=(function(){var p=location.pathname.replace(/\\/+$/,"");if(p!=="/images"&&p!=="/scenes")return G0.sortDirection;var q=new URLSearchParams(location.search),s=q.get("sortdir"),b=q.get("sortby");if(s==="asc")return Ba.Asc;if(s==="desc")return Ba.Desc;return (b===null||b==="filesize"||b==="date")?Ba.Desc:Ba.Asc;})()',
    ),
    (
        '(this.sortBy=a,this.sortBy==="date"&&(this.sortDirection=Ba.Desc))',
        '(this.sortBy=(function(){var p=location.pathname.replace(/\\/+$/,"");if(p!=="/images"&&p!=="/scenes")return a;return new URLSearchParams(location.search).get("sortby")||"filesize";})(),this.sortBy==="date"&&(this.sortDirection=Ba.Desc))',
    ),
    (
        'this.displayMode=i[0]',
        'this.displayMode=(function(){var p=location.pathname.replace(/\\/+$/,"");if(p!=="/images"&&p!=="/scenes")return i[0];var d=new URLSearchParams(location.search).get("disp");return d==="0"?or.Grid:d==="1"?or.List:d==="2"?or.Wall:d==="3"?or.Tagger:or.Wall;})()',
    ),
]


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
    app_state = App(device="cuda", model=os.environ.get("MH_INDEX_MODEL", "siglip2"))
    manager = app_state.manager
    dupes = DuplicateStore()
    faces = Faces()

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

    async def media_features(request: web.Request) -> web.Response:
        try:
            kind = (request.query.get("kind") or "image").strip().lower()
            image_id = (request.query.get("id") or "").strip()
            result = await asyncio.to_thread(app_state.features, kind, image_id)
            return web.json_response(result)
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def semantic_map(_request: web.Request) -> web.Response:
        try:
            result = await asyncio.to_thread(app_state.semantic_map)
            return web.json_response(result)
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

    async def library_move(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            items = payload.get("items") or []
            if not isinstance(items, list):
                raise ValueError("items 必须是数组")
            result = await asyncio.to_thread(
                move_stash_items, items, str(payload.get("dest") or "embeddingsafedata")
            )
            return web.json_response(result)
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def folder_list(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            result = await asyncio.to_thread(
                list_folder,
                str(payload.get("path") or ""),
                bool(payload.get("recursive", True)),
                str(payload.get("kind") or "all"),
                int(payload.get("page") or 1),
                int(payload.get("per_page") or 120),
            )
            return web.json_response(result)
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def folder_move(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            paths = payload.get("paths") or []
            if not isinstance(paths, list):
                raise ValueError("paths 必须是数组")
            result = await asyncio.to_thread(
                move_files, [str(p) for p in paths], str(payload.get("dest") or "")
            )
            return web.json_response(result)
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def folder_thumb(request: web.Request) -> web.Response:
        try:
            path = await asyncio.to_thread(
                thumbnail,
                request.query.get("path") or "",
                int(request.query.get("size") or 320),
            )
            return web.FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def folder_media(request: web.Request) -> web.Response:
        try:
            path = await asyncio.to_thread(resolve_media, request.query.get("path") or "")
            if not media_kind(path):
                raise ValueError("不是支持的图片或视频")
            return web.FileResponse(path)
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def settings_get(_request: web.Request) -> web.Response:
        return web.json_response(await asyncio.to_thread(settings_status))

    async def settings_save(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            before = await asyncio.to_thread(settings_status)
            result = await asyncio.to_thread(
                save_settings,
                media_root=str(payload.get("media_root") or ""),
                models_root=str(payload.get("models_root") or ""),
                qq_base=str(payload.get("qq_base") or ""),
            )
            changed = any(before[key] != result[key] for key in ("media_root", "models_root", "qq_base"))
            return web.json_response({
                "ok": True,
                "restart_required": changed,
                "settings": result,
            })
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

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

    async def pm_library(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            paths = payload.get("paths") or []
            if not isinstance(paths, list):
                raise ValueError("paths 必须是数组")
            result = await asyncio.to_thread(manager.move_to_library, [str(p) for p in paths])
            dirs = result.get("scan_dirs") or []
            if dirs:
                try:
                    result["scan_job"] = await asyncio.to_thread(Stash().scan, dirs)
                except Exception as exc:  # noqa: BLE001
                    result["errors"].append(f"Stash 扫描失败: {exc}")
            return web.json_response(result)
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def nine_list(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            paths = await asyncio.to_thread(list_nine_images, str(payload.get("folder") or ""))
            return web.json_response({"folder": str(payload.get("folder") or ""),
                                      "paths": [str(p) for p in paths], "count": len(paths)})
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def nine_scan(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            folder = str(payload.get("folder") or "")
            model = str(payload.get("model") or "huihui")
            return web.json_response(await asyncio.to_thread(scan_nine_folder, folder, model))
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
            scope = str(payload.get("scope") or "library")
            root = str(payload.get("root") or "").strip()
            recursive = bool(payload.get("recursive", True))
            if scope == "folder":
                if not root:
                    root = str((await asyncio.to_thread(dupes.status, "folder")).get("root") or "")
                if root:
                    root = manager.allow_root(root)
            return web.json_response(await asyncio.to_thread(
                dupes.start, scope, int(payload.get("limit") or 0),
                bool(payload.get("force")), root, recursive,
            ))
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def dupes_groups(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            scope = str(payload.get("scope") or "library")
            if scope == "folder":
                root = str((await asyncio.to_thread(dupes.status, "folder")).get("root") or "")
                if root:
                    manager.allow_root(root)
            only_groups = scope == "qq" and bool(payload.get("only_groups"))
            raw_limit = int(payload.get("limit") if payload.get("limit") is not None else 60)
            limit = max(1, min(200, raw_limit)) if raw_limit > 0 else 0
            data = await asyncio.to_thread(
                dupes.groups, scope,
                str(payload.get("algo") or "phash"),
                int(payload.get("threshold", 10)),
                0 if only_groups else (limit or 60),
            )
            if only_groups:
                all_paths = [
                    str(member.get("path") or "")
                    for group in data.get("groups", [])
                    for member in [group.get("representative"), *(group.get("members") or [])]
                    if member and member.get("path")
                ]
                group_paths = await asyncio.to_thread(manager.group_paths, all_paths)
                kept = []
                for group in data.get("groups", []):
                    members = [group.get("representative"), *(group.get("members") or [])]
                    members = [
                        member for member in members
                        if member and os.path.normcase(os.path.abspath(str(member.get("path") or "")))
                        in group_paths
                    ]
                    if len(members) < 2:
                        continue
                    kept.append({
                        **group,
                        "representative": members[0],
                        "members": members[1:],
                        "count": len(members),
                        "total_size": sum(int(m.get("size") or 0) for m in members),
                    })
                data["groups"] = kept[:limit] if limit else kept
                data["total_groups"] = len(kept)
                data["total_files"] = sum(int(g.get("count") or 0) for g in kept)
                data["returned"] = len(data["groups"])
                data["only_groups"] = True
            return web.json_response(data)
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def dupes_scenes(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            return web.json_response(await asyncio.to_thread(
                dupes.scenes,
                int(payload.get("distance", 10)),
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

    async def faces_status(request: web.Request) -> web.Response:
        try:
            raw_min = request.query.get("min_images")
            min_images = int(raw_min) if raw_min not in (None, "") else None
            return web.json_response(await asyncio.to_thread(faces.status, min_images))
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def faces_scan(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            return web.json_response(await asyncio.to_thread(
                faces.start_scan, bool(payload.get("force")), int(payload.get("limit") or 0)
            ))
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def faces_cluster(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            current = await asyncio.to_thread(faces.status)
            return web.json_response(await asyncio.to_thread(
                faces.start_cluster,
                float(payload.get("threshold") or current["threshold"]),
                int(payload.get("min_images") or current["min_images"]),
            ))
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def faces_clusters(request: web.Request) -> web.Response:
        try:
            current = await asyncio.to_thread(faces.status)
            return web.json_response(await asyncio.to_thread(
                faces.clusters,
                int(request.query.get("page") or 1),
                int(request.query.get("per_page") or 24),
                int(request.query.get("min_images") or current["min_images"]),
            ))
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def faces_cluster_detail(request: web.Request) -> web.Response:
        try:
            return web.json_response(await asyncio.to_thread(
                faces.cluster_detail,
                int(request.query.get("id") or 0),
                int(request.query.get("limit") or 80),
            ))
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def faces_thumb(request: web.Request) -> web.Response:
        try:
            body = await asyncio.to_thread(faces.thumb, int(request.query.get("id") or 0))
            return web.Response(body=body, content_type="image/jpeg",
                                headers={"cache-control": "private, max-age=86400"})
        except Exception as exc:  # noqa: BLE001
            code, body = _error(exc)
            return web.json_response(body, status=code)

    async def faces_apply(request: web.Request) -> web.Response:
        try:
            payload = await _json_body(request)
            current = await asyncio.to_thread(faces.status)
            return web.json_response(await asyncio.to_thread(
                faces.apply,
                int(payload.get("min_images") or current["min_images"]),
                str(payload.get("prefix") or "人物"),
                [int(item) for item in (payload.get("cluster_ids") or [])],
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
                body = await resp.read()
                if resp.content_type == "text/html" and b"</head>" in body:
                    html = body.decode("utf-8", "replace")
                    if "data-mh-sort-bootstrap" not in html:
                        if '<script type="module"' in html:
                            html = html.replace('<script type="module"', SORT_BOOTSTRAP + '<script type="module"', 1)
                        else:
                            html = html.replace("</head>", SORT_BOOTSTRAP + "</head>", 1)
                        html = re.sub(
                            r'(<script[^>]*type="module"[^>]*src=")([^"]+\.js)(")',
                            r"\1\2?mh=3\3",
                            html,
                            count=1,
                        )
                        body = html.encode("utf-8")
                elif resp.content_type in {"text/javascript", "application/javascript"}:
                    if any(old.encode() in body for old, _ in JS_REWRITES):
                        text = body.decode("utf-8", "replace")
                        for old, new in JS_REWRITES:
                            text = text.replace(old, new)
                        body = text.encode("utf-8")
                        out_headers = [
                            (k, v) for k, v in out_headers
                            if k.lower() not in {"cache-control", "etag", "content-md5"}
                        ]
                        out_headers.append(("cache-control", "no-store"))
                return web.Response(
                    status=resp.status,
                    headers=out_headers,
                    body=body,
                )

    app = web.Application(client_max_size=512 * 1024 * 1024)
    app.router.add_get("/mh/api/health", health)
    app.router.add_get("/mh/api/settings", settings_get)
    app.router.add_post("/mh/api/settings", settings_save)
    app.router.add_get("/mh/api/status", status)
    app.router.add_get("/mh/api/media/info", media_info)
    app.router.add_get("/mh/api/media/features", media_features)
    app.router.add_get("/mh/api/semantic/map", semantic_map)
    app.router.add_post("/mh/api/library/delete", library_delete)
    app.router.add_post("/mh/api/library/move", library_move)
    app.router.add_post("/mh/api/folder/list", folder_list)
    app.router.add_post("/mh/api/folder/move", folder_move)
    app.router.add_get("/mh/api/folder/thumb", folder_thumb)
    app.router.add_get("/mh/api/folder/media", folder_media)
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
    app.router.add_post("/mh/api/pm/library", pm_library)
    app.router.add_post("/mh/api/nine/list", nine_list)
    app.router.add_post("/mh/api/nine/scan", nine_scan)
    app.router.add_get("/mh/api/dupes/status", dupes_status)
    app.router.add_post("/mh/api/dupes/scan", dupes_scan)
    app.router.add_post("/mh/api/dupes/groups", dupes_groups)
    app.router.add_post("/mh/api/dupes/scenes", dupes_scenes)
    app.router.add_post("/mh/api/dupes/exact", dupes_exact)
    app.router.add_get("/mh/api/faces/status", faces_status)
    app.router.add_post("/mh/api/faces/scan", faces_scan)
    app.router.add_post("/mh/api/faces/cluster", faces_cluster)
    app.router.add_get("/mh/api/faces/clusters", faces_clusters)
    app.router.add_get("/mh/api/faces/cluster", faces_cluster_detail)
    app.router.add_get("/mh/api/faces/thumb", faces_thumb)
    app.router.add_post("/mh/api/faces/apply", faces_apply)
    app.router.add_route("*", "/{tail:.*}", proxy)
    return app


def main() -> None:
    public = int(sys.argv[1]) if len(sys.argv) > 1 else 9999
    internal = int(sys.argv[2]) if len(sys.argv) > 2 else 9998
    print(f"MineHub gateway: http://127.0.0.1:{public} -> Stash 127.0.0.1:{internal}", flush=True)
    web.run_app(make_app(public, internal), host="127.0.0.1", port=public, access_log=None)


if __name__ == "__main__":
    main()