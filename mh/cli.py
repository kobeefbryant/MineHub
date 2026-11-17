"""Unified CLI: python -m mh.cli <command>."""
from __future__ import annotations

import argparse
import json
import sys
import time

from .config import ensure_dirs
from .db import Ledger


def cmd_status(_: argparse.Namespace) -> None:
    led = Ledger()
    s = led.stats()
    led.close()
    print(json.dumps(s, ensure_ascii=False, indent=1))


def cmd_scan(args: argparse.Namespace) -> None:
    from .scanner import scan

    scan(include_thumb=args.include_thumb)


def cmd_stage1(args: argparse.Namespace) -> None:
    from .stage1 import run_stage1

    print(run_stage1(args.batch, args.limit, args.include_thumb, args.quiet))


def cmd_stage2(args: argparse.Namespace) -> None:
    from .stage2 import finalize, run_a, run_b

    if args.pass_ == "a":
        print(run_a(args.slots, args.ctx, args.workers, args.limit, args.quiet))
    elif args.pass_ == "b":
        print(run_b(args.slots, args.ctx, args.workers, args.limit, args.quiet))
    else:
        print(finalize(), "rows finalized")


def cmd_move(args: argparse.Namespace) -> None:
    from .stage3 import move_all, rollback

    if args.rollback:
        print(rollback(args.limit))
    else:
        print(move_all(args.limit, args.dry_run, not args.no_md5))


def cmd_content_audit(args: argparse.Namespace) -> None:
    from .direct_audit import run_audit, run_restore, stats

    if args.stage == "audit":
        print(run_audit(model=args.model, slots=args.slots, workers=args.workers,
                        limit=args.limit, dry_run=args.dry_run))
    elif args.stage == "restore":
        print(run_restore(limit=args.limit, dry_run=args.dry_run))
    else:
        print(json.dumps(stats(), ensure_ascii=False, indent=1))


def cmd_baseline(args: argparse.Namespace) -> None:
    from .hash_baseline import hash_kept

    print(hash_kept(args.limit))


def cmd_thumbs(args: argparse.Namespace) -> None:
    from .thumb_migrate import move_nsfw_thumbs

    print(move_nsfw_thumbs(args.dry_run, args.limit))


def cmd_thumb_audit(args: argparse.Namespace) -> None:
    from . import thumb_audit

    if args.stage == "scan":
        print(thumb_audit.scan(args.limit))
    elif args.stage == "siglip":
        print(thumb_audit.run_siglip(args.limit))
    elif args.stage == "promote":
        print(thumb_audit.promote_candidates())
    elif args.stage == "repair":
        print(thumb_audit.repair_states())
    elif args.stage == "repair-vlm":
        print(thumb_audit.repair_vlm_errors())
    elif args.stage == "vlm":
        print(thumb_audit.run_vlm(args.slots, args.workers, args.limit))
    elif args.stage == "move":
        print(thumb_audit.run_move(args.limit, args.dry_run, args.move_originals))
    elif args.stage == "incremental":
        print(thumb_audit.incremental(args.slots, args.workers, args.limit, args.dry_run))
    elif args.stage == "all":
        print(thumb_audit.run_all(args.slots, args.workers, args.limit, args.dry_run))
    else:
        print(json.dumps(thumb_audit.status(), ensure_ascii=False, indent=1))


def cmd_rescan(args: argparse.Namespace) -> None:
    from . import rescan

    print(json.dumps(rescan.run(args.limit, args.dry_run, args.slots, args.workers),
                     ensure_ascii=False, indent=1))


def cmd_reaudit(args: argparse.Namespace) -> None:
    from . import reaudit

    if args.stage == "select":
        print(reaudit.select(args.limit))
    elif args.stage == "run":
        print(reaudit.run(args.model, args.slots, args.workers, args.limit))
    else:
        print(json.dumps(reaudit.status(), ensure_ascii=False, indent=1))


def cmd_index(args: argparse.Namespace) -> None:
    from .index import SimilarityIndex

    idx = SimilarityIndex(model=args.model)
    if args.stage == "build":
        kinds = {"images": ("image",), "scenes": ("scene",), "all": ("image", "scene")}[args.kind]
        print(idx.build(kinds=kinds, limit=args.limit, device=args.device, batch_size=args.batch_size))
    elif args.stage == "search":
        if args.text:
            print(json.dumps(idx.search_text(args.text, args.top, args.device),
                             ensure_ascii=False, indent=1))
        elif args.file:
            from PIL import Image

            with Image.open(args.file) as im:
                print(json.dumps(idx.search_image(im.convert("RGB"), args.top, args.device),
                                 ensure_ascii=False, indent=1))
        elif args.id:
            kinds = {"images": ["image"], "scenes": ["scene"], "all": ["image", "scene"],
                     "image": ["image"], "scene": ["scene"]}[args.kind]
            result = None
            for kind in kinds:
                result = idx.search_id(kind, args.id, args.top)
                if result is not None:
                    break
            if result is None:
                raise SystemExit(f"not found: {args.kind} {args.id}")
            print(json.dumps(result, ensure_ascii=False, indent=1))
        else:
            raise SystemExit("search needs --id or --file")
    elif args.stage == "serve":
        from .index_server import serve

        serve(args.port, args.device, args.model)
    elif args.stage == "refresh":
        print(json.dumps(idx.refresh_metadata(), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(idx.status(), ensure_ascii=False, indent=1))


def cmd_faces(args: argparse.Namespace) -> None:
    from .faces import Faces

    svc = Faces()
    if args.stage == "status":
        print(json.dumps(svc.status(args.min_images), ensure_ascii=False, indent=1))
        return
    if args.stage == "apply":
        print(json.dumps(svc.apply(args.min_images, args.prefix, args.cluster_ids or []),
                         ensure_ascii=False, indent=1))
        return
    if args.stage == "scan":
        svc.start_scan(args.force, args.limit)
    else:
        svc.start_cluster(args.threshold, args.min_images)
    last = None
    while True:
        state = svc.status(args.min_images)
        task = state.get("task") or {}
        marker = (task.get("stage"), task.get("done"), task.get("total"), task.get("message"))
        if marker != last:
            print(json.dumps(task, ensure_ascii=False), flush=True)
            last = marker
        if not task.get("running"):
            print(json.dumps(state, ensure_ascii=False, indent=1))
            return
        time.sleep(2)


def cmd_stash(args: argparse.Namespace) -> None:
    from .stash import Stash, start_stash

    if args.restart:
        import subprocess

        subprocess.run(["taskkill", "/IM", "stash-win.exe", "/F"], capture_output=True)
        time.sleep(2)
        p = start_stash()
        print("stash pid", p.pid)
    s = Stash()
    if not s.wait_ready(120):
        raise SystemExit("stash not reachable on :9999")
    if args.scan:
        s.scan()
        print("scan triggered")
    if args.tag:
        print(s.push_tags())
    if args.install_js:
        print(s.install_ui_plugin())


def main(argv: list[str] | None = None) -> int:
    ensure_dirs()
    ap = argparse.ArgumentParser(prog="mh")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status").set_defaults(func=cmd_status)

    p = sub.add_parser("scan")
    p.add_argument("--include-thumb", action="store_true")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("stage1")
    p.add_argument("--batch", type=int, default=96)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--include-thumb", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=cmd_stage1)

    p = sub.add_parser("stage2")
    p.add_argument("pass_", choices=["a", "b", "finalize"])
    p.add_argument("--slots", type=int, default=4)
    p.add_argument("--ctx", type=int, default=16384)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=cmd_stage2)

    p = sub.add_parser("move")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-md5", action="store_true")
    p.add_argument("--rollback", action="store_true")
    p.set_defaults(func=cmd_move)

    p = sub.add_parser("baseline")
    p.add_argument("--limit", type=int, default=0)
    p.set_defaults(func=cmd_baseline)

    p = sub.add_parser("thumbs")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    p.set_defaults(func=cmd_thumbs)

    p = sub.add_parser("thumb-audit")
    p.add_argument("stage", choices=["scan", "siglip", "promote", "repair", "repair-vlm",
                                     "vlm", "move", "incremental", "all", "status"])
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--move-originals", action="store_true")
    p.add_argument("--slots", type=int, default=4)
    p.add_argument("--workers", type=int, default=4)
    p.set_defaults(func=cmd_thumb_audit)

    p = sub.add_parser("rescan", help="incremental QQ rescan for new originals and thumbnails")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--slots", type=int, default=4)
    p.add_argument("--workers", type=int, default=4)
    p.set_defaults(func=cmd_rescan)

    p = sub.add_parser("reaudit")
    p.add_argument("stage", choices=["select", "run", "status"])
    p.add_argument("--model", default="huihui", choices=["huihui", "nsfw"])
    p.add_argument("--slots", type=int, default=4)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--limit", type=int, default=0)
    p.set_defaults(func=cmd_reaudit)

    p = sub.add_parser("content-audit", help="corporeal content audit and non-corporeal restore")
    p.add_argument("stage", choices=["audit", "restore", "status"])
    p.add_argument("--model", default="huihui", choices=["huihui", "nsfw"])
    p.add_argument("--slots", type=int, default=4)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_content_audit)

    p = sub.add_parser("index")
    p.add_argument("stage", choices=["build", "search", "serve", "refresh", "status"])
    p.add_argument("--kind", choices=["images", "scenes", "all", "image", "scene"], default="all")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    p.add_argument("--model", choices=["nsfw", "siglip2", "qwen3vl"], default="nsfw")
    p.add_argument("--id", default="")
    p.add_argument("--file", default="")
    p.add_argument("--text", default="")
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("faces", help="InsightFace scan, clustering and Stash performer assignment")
    p.add_argument("stage", choices=["status", "scan", "cluster", "apply"])
    p.add_argument("--force", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--threshold", type=float, default=0.5)
    p.add_argument("--min-images", type=int, default=3)
    p.add_argument("--prefix", default="人物")
    p.add_argument("--cluster-ids", type=int, nargs="*", default=[])
    p.set_defaults(func=cmd_faces)

    p = sub.add_parser("stash")
    p.add_argument("--restart", action="store_true")
    p.add_argument("--scan", action="store_true")
    p.add_argument("--tag", action="store_true")
    p.add_argument("--install-js", action="store_true")
    p.set_defaults(func=cmd_stash)

    args = ap.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())