"""Tiny local Top-K image similarity viewer for the Stash index."""
from __future__ import annotations

import base64
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .index import SimilarityIndex
from .manager import Manager

PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MineHub 相似图片</title>
<style>
:root{color-scheme:dark}body{margin:0;background:#14181d;color:#e6edf3;font:14px system-ui,sans-serif}
header{padding:18px 24px;border-bottom:1px solid #2a333f}h1{font-size:18px;margin:0 0 4px}
.sub{color:#93a4b8;font-size:12px}.wrap{max-width:1400px;margin:0 auto;padding:18px 24px}
.bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:16px}
#drop{border:2px dashed #3b4a5c;border-radius:12px;padding:22px;text-align:center;color:#9fb0c4;flex:1;min-width:280px;cursor:pointer}
#drop.hot{border-color:#5aa9ff;background:#172231}input,select,button{background:#1d2733;color:#e6edf3;border:1px solid #334154;border-radius:8px;padding:9px 11px}
button{cursor:pointer;background:#1f6feb;border-color:#1f6feb}button:disabled{opacity:.5;cursor:not-allowed}
#msg{color:#9fb0c4;font-size:12px;margin:8px 0}#grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px}
.card{background:#1a222c;border:1px solid #2a3644;border-radius:10px;overflow:hidden;position:relative}
.card img{display:block;width:100%;height:160px;object-fit:cover;background:#0d1117}
.meta{padding:8px 9px;font-size:12px;color:#aab8c8}.score{color:#6ee7a8;font-weight:600}
a{color:#8ab4ff;text-decoration:none}.id{color:#c9d5e3}
</style></head>
<body><header><h1>MineHub 相似图片</h1>
<div class="sub">只读 Stash 缩略图 · <span id="status">索引加载中…</span> · 点击结果跳转 Stash</div></header>
<div class="wrap">
<div class="bar">
  <label id="drop">拖入一张图片，或点击选择<input id="file" type="file" accept="image/*" hidden></label>
  <input id="text" placeholder="中文/英文描述搜图" size="26">
  <input id="sid" placeholder="或输入 Stash 图片 ID" size="18">
  <select id="kind"><option value="auto">自动</option><option value="image">图片</option><option value="scene">场景</option></select>
  <input id="top" type="number" value="20" min="1" max="100" style="width:70px" title="Top-K">
  <button id="go">搜索</button>
</div>
<div id="msg"></div><div id="grid"></div>
</div>
<script>
const $=s=>document.querySelector(s), grid=$('#grid'), msg=$('#msg');
let busy=false;
async function status(){try{const r=await fetch('/status');const s=await r.json();$('#status').textContent=`${s.count} 个索引 · ${s.dim} 维 · ${s.device||''} · ${s.model||''}`}catch(e){$('#status').textContent='索引未就绪'}}
status();
function setBusy(v){busy=v;$('#go').disabled=v;if(v)msg.textContent='搜索中…'}
function render(items){grid.innerHTML='';if(!items.length){msg.textContent='没有结果';return}for(const it of items){
 const d=document.createElement('div');d.className='card';
 const a=document.createElement('a');a.href=it.page_url;a.target='_blank';a.rel='noreferrer';
 const im=document.createElement('img');im.loading='lazy';im.src=it.thumbnail_url;a.appendChild(im);d.appendChild(a);
 const m=document.createElement('div');m.className='meta';
 const score=document.createElement('div');score.className='score';score.textContent=`${(it.score*100).toFixed(1)}%`;
 const ident=document.createElement('div');ident.className='id';ident.textContent=`${it.kind} #${it.stash_id}`;
 const title=document.createElement('div');title.textContent=(it.title||'').slice(0,60);
 m.append(score,ident,title);d.appendChild(m);grid.appendChild(d)}}
async function post(payload){if(busy)return;setBusy(true);try{const r=await fetch('/search',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});const j=await r.json();if(!r.ok)throw new Error(j.error||'搜索失败');render(j.results||[])}catch(e){msg.textContent=e.message}finally{setBusy(false)}}
$('#go').onclick=()=>{const text=$('#text').value.trim(), sid=$('#sid').value.trim();if(text)post({text,top:parseInt($('#top').value)||20});else if(sid)post({stash_id:sid,kind:$('#kind').value,top:parseInt($('#top').value)||20})};
$('#sid').onkeydown=e=>{if(e.key==='Enter')$('#go').click()};
$('#text').onkeydown=e=>{if(e.key==='Enter')$('#go').click()};
$('#drop').onclick=()=>$('#file').click();
$('#file').onchange=e=>{const f=e.target.files[0];if(f)sendFile(f)};
async function sendFile(f){const b=await f.arrayBuffer();const bytes=new Uint8Array(b);let s='';for(let i=0;i<bytes.length;i+=0x8000)s+=String.fromCharCode(...bytes.subarray(i,i+0x8000));post({image_b64:btoa(s),top:parseInt($('#top').value)||20})}
for(const ev of ['dragenter','dragover'])document.addEventListener(ev,e=>{e.preventDefault();$('#drop').classList.add('hot')});
for(const ev of ['dragleave','drop'])document.addEventListener(ev,e=>{e.preventDefault();$('#drop').classList.remove('hot')});
document.addEventListener('drop',e=>{const f=e.dataTransfer.files[0];if(f)sendFile(f)});
const params=new URLSearchParams(location.search), qid=params.get('id')||'', qkind=params.get('kind')||'auto';
if(qid){$('#sid').value=qid;$('#kind').value=(qkind==='image'||qkind==='scene')?qkind:'auto';post({stash_id:qid,kind:$('#kind').value,top:parseInt($('#top').value)||20})}
</script></body></html>"""


class App:
    def __init__(self, device: str = "cpu", model: str = "nsfw") -> None:
        self.index = SimilarityIndex(model=model)
        self.embedder = self.index.make_embedder(device)
        self.lock = threading.Lock()
        self.manager = Manager()

    def reload(self) -> dict:
        with self.lock:
            self.index._items = None
            self.index._emb = None
            return self.index.status()

    def search(self, payload: dict) -> list[dict]:
        top = max(1, min(100, int(payload.get("top") or 20)))
        raw_min = payload.get("min_score")
        min_score = None
        if raw_min is not None and str(raw_min).strip() != "":
            min_score = max(-1.0, min(1.0, float(raw_min)))
        text = str(payload.get("text") or "").strip()
        if text:
            if self.index.model != "siglip2":
                raise ValueError("文本搜图需要 siglip2 索引")
            with self.lock:
                q = self.embedder.text_embedding(text)
                return self.index.search_vector(q, topk=top, min_score=min_score)
        if payload.get("image_b64"):
            from PIL import Image

            raw = payload["image_b64"]
            if "," in raw and raw.startswith("data:"):
                raw = raw.split(",", 1)[1]
            img = Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGB")
            with self.lock:
                q = self.embedder.image_embedding(img)
                return self.index.search_vector(q, topk=top, min_score=min_score)
        sid = str(payload.get("stash_id") or "").strip()
        if not sid:
            raise ValueError("需要图片或 Stash ID")
        kind = payload.get("kind") or "auto"
        kinds = ["image", "scene"] if kind == "auto" else [kind]
        for k in kinds:
            with self.lock:
                result = self.index.search_id(k, sid, topk=top, min_score=min_score)
            if result is not None:
                return result
        raise LookupError(f"索引中没有 {kind} #{sid}")


ALLOWED_ORIGINS = {
    "http://127.0.0.1:9999", "http://localhost:9999",
    "http://127.0.0.1:8765", "http://localhost:8765",
}


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def _origin(self) -> str | None:
            origin = self.headers.get("Origin")
            return origin if origin in ALLOWED_ORIGINS else None

        def _origin_ok(self) -> bool:
            origin = self.headers.get("Origin")
            return not origin or origin in ALLOWED_ORIGINS

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("content-type", ctype)
            self.send_header("cache-control", "no-store")
            origin = self._origin()
            if origin:
                self.send_header("access-control-allow-origin", origin)
                self.send_header("vary", "origin")
            self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
            self.send_header("access-control-allow-headers", "content-type")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:
            if not self._origin_ok():
                self._send(403, b'{"error":"origin not allowed"}')
                return
            self.send_response(204)
            origin = self._origin()
            if origin:
                self.send_header("access-control-allow-origin", origin)
                self.send_header("vary", "origin")
            self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
            self.send_header("access-control-allow-headers", "content-type")
            self.send_header("content-length", "0")
            self.end_headers()

        def _json(self, code: int, obj: dict) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode())

        def _body(self) -> dict:
            ctype = (self.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
            if ctype != "application/json":
                raise ValueError("content-type must be application/json")
            n = int(self.headers.get("content-length") or 0)
            if n <= 0 or n > 30 * 1024 * 1024:
                raise ValueError("请求过大")
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self) -> None:
            if not self._origin_ok():
                self._send(403, b'{"error":"origin not allowed"}')
                return
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if path in ("/", "/index.html"):
                    self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
                elif path == "/status":
                    self._json(200, app.index.status())
                elif path == "/health":
                    self._send(200, b'{"status":"ok"}')
                elif path == "/pm/config":
                    self._json(200, app.manager.config())
                elif path == "/pm/chats":
                    self._json(200, {"chats": app.manager.chats, **app.manager.index_status()})
                elif path == "/pm/index/status":
                    self._json(200, app.manager.index_status())
                elif path == "/pm/thumb":
                    qs = parse_qs(parsed.query)
                    raw = app.manager.thumbnail(qs.get("path", [""])[0], int(qs.get("size", ["320"])[0]))
                    self._send(200, raw, "image/jpeg")
                else:
                    self._send(404, b'{"error":"not found"}')
            except PermissionError as exc:
                self._json(403, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(400, {"error": str(exc)[:300]})

        def do_POST(self) -> None:
            if not self._origin_ok():
                self._send(403, b'{"error":"origin not allowed"}')
                return
            path = urlparse(self.path).path
            try:
                if path == "/reload":
                    self._json(200, app.reload())
                    return
                if path == "/reload-labels":
                    self._json(200, app.manager.reload_labels())
                    return
                if path == "/pm/scan":
                    payload = self._body()
                    self._json(200, app.manager.scan(payload.get("roots") or [], payload.get("extra_roots") or []))
                    return
                if path == "/pm/query":
                    self._json(200, app.manager.query(self._body()))
                    return
                if path == "/pm/move":
                    payload = self._body()
                    self._json(200, app.manager.move(payload.get("paths") or [], payload.get("dest") or ""))
                    return
                if path == "/pm/recycle":
                    payload = self._body()
                    self._json(200, app.manager.recycle(payload.get("paths") or []))
                    return
                if path == "/pm/open":
                    payload = self._body()
                    app.manager.open_path(payload.get("path") or "")
                    self._json(200, {"ok": True})
                    return
                if path == "/pm/index":
                    payload = self._body()
                    self._json(200, app.manager.start_index(str(payload.get("account") or "")))
                    return
                if path != "/search":
                    self._send(404, b'{"error":"not found"}')
                    return
                payload = self._body()
                results = app.search(payload)
                self._json(200, {"results": results})
            except LookupError as exc:
                self._json(404, {"error": str(exc)})
            except PermissionError as exc:
                self._json(403, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(400, {"error": str(exc)[:300]})

        def log_message(self, *_args) -> None:
            pass

    return Handler


def serve(port: int = 8765, device: str = "cpu", model: str = "nsfw") -> None:
    app = App(device=device, model=model)
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    print(f"similarity viewer: http://127.0.0.1:{port} ({model}, {device})", flush=True)
    srv.serve_forever()
