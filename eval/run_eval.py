"""Small-sample comparison harness: SigLIP2 vs WD-Eva02 vs two Qwen3-VL GGUFs."""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from mh.config import DATA, LLAMA, LLAMA_HOST, LLAMA_PORT, NSFW_MODEL, VLM_HUIHUI, VLM_NSFW, WD_TAGGER
from mh.frames import cleanup_frames, extract_frames

EVAL = DATA / "eval"
NVIDIA_SMI = r"C:\Windows\System32\nvidia-smi.exe"


class VramProbe:
    def __init__(self, interval: float = 0.4) -> None:
        self.interval = interval
        self.peak = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                out = subprocess.run(
                    [NVIDIA_SMI, "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=3,
                ).stdout.strip().splitlines()[0]
                self.peak = max(self.peak, int(float(out)))
            except Exception:
                pass
            self._stop.wait(self.interval)

    def __enter__(self):
        self.peak = 0
        self._stop.clear()
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(timeout=2)


def load_manifest() -> dict:
    return json.loads((EVAL / "manifest.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- prefilter
def run_prefilter() -> dict:
    from PIL import Image

    from mh.prefilter import SiglipNSFW, WDTagger

    manifest = load_manifest()
    images = manifest["images"]
    out: dict[str, Any] = {"siglip": {}, "wd": {}, "videos": {}}

    with VramProbe() as probe:
        t0 = time.perf_counter()
        sig = SiglipNSFW(NSFW_MODEL)
        load_s = time.perf_counter() - t0

        per_img = []
        t_sig = time.perf_counter()
        for item in images:
            with Image.open(item["path"]) as im:
                t = time.perf_counter()
                res = sig.classify(im.convert("RGB"))
                per_img.append({"path": item["path"], "label": res.label, "scores": res.scores,
                                "ms": (time.perf_counter() - t) * 1000})
        sig_time = time.perf_counter() - t_sig

        # batch throughput on the same 30
        from PIL import Image as I2
        imgs = []
        for item in images:
            with I2.open(item["path"]) as im:
                imgs.append(im.convert("RGB"))
        t = time.perf_counter()
        sig.classify_batch(imgs)
        batch_time = time.perf_counter() - t

        wd = WDTagger(WD_TAGGER)
        wd_per = []
        t_wd = time.perf_counter()
        for item in images:
            with Image.open(item["path"]) as im:
                t = time.perf_counter()
                res = wd.tag_batch([im.convert("RGB")])[0]
                wd_per.append({"path": item["path"], "ratings": res["ratings"],
                               "ms": (time.perf_counter() - t) * 1000})
        wd_time = time.perf_counter() - t_wd
    sig_peak = probe.peak

    out["siglip"] = {
        "load_s": round(load_s, 2),
        "device": sig.device,
        "per_image": per_img,
        "mean_ms": round(statistics.mean(p["ms"] for p in per_img), 1),
        "median_ms": round(statistics.median(p["ms"] for p in per_img), 1),
        "batch30_s": round(batch_time, 2),
        "imgs_per_s_batch": round(30 / batch_time, 1),
        "total_s": round(sig_time, 2),
        "vram_peak_mb": sig_peak,
    }
    out["wd"] = {
        "provider": wd.provider,
        "per_image": wd_per,
        "mean_ms": round(statistics.mean(p["ms"] for p in wd_per), 1),
        "imgs_per_s": round(30 / wd_time, 1),
        "vram_peak_mb": sig_peak,
    }

    # videos: frame extraction + per-frame prefilter
    vid = []
    from PIL import Image

    for v in manifest["videos"]:
        t0 = time.perf_counter()
        frames = extract_frames(v["path"], count=6, max_side=1024)
        t_extract = time.perf_counter() - t0
        if not frames:
            vid.append({**v, "error": "no frames"})
            continue
        pil = []
        for f in frames:
            with Image.open(f) as im:
                pil.append(im.convert("RGB"))
        t0 = time.perf_counter()
        res = sig.classify_batch(pil)
        t_infer = time.perf_counter() - t0
        wd_res = wd.tag_batch(pil)
        cleanup_frames(frames)
        vid.append({
            "path": v["path"], "duration": v["duration"], "gt_category": v["gt_category"], "gt_nsfw": v["gt_nsfw"],
            "siglip_labels": [r.label for r in res],
            "siglip_max_scores": {k: round(max(r.scores[k] for r in res), 3) for k in res[0].scores},
            "wd_ratings": [max(w["ratings"], key=w["ratings"].get) for w in wd_res],
            "extract_s": round(t_extract, 2),
            "siglip_s": round(t_infer, 2),
            "total_s": round(t_extract + t_infer, 2),
        })
    out["videos"] = vid
    (EVAL / "results_prefilter.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"prefilter done: siglip {out['siglip']['imgs_per_s_batch']} img/s batch, "
          f"{out['siglip']['mean_ms']} ms/img single, wd {out['wd']['imgs_per_s']} img/s ({out['wd']['provider']})")
    return out


# ---------------------------------------------------------------- llama-server
from mh.serve import LlamaServer  # noqa: E402


def run_vlm(model: str) -> dict:
    from mh.vlm import VLM

    manifest = load_manifest()
    client = VLM(model)
    out: dict[str, Any] = {"model": model, "images": [], "videos": []}
    with VramProbe() as probe, LlamaServer(model) as srv:
        t0 = time.perf_counter()
        for item in manifest["images"]:
            rec = {"path": item["path"], "gt_category": item["gt_category"], "gt_nsfw": item["gt_nsfw"]}
            try:
                verdict, meta = client.complete([item["path"]], timeout=240)
                rec.update(verdict=verdict, meta=meta, ok=True)
            except Exception as exc:  # noqa: BLE001
                rec.update(ok=False, error=str(exc)[:300])
            out["images"].append(rec)
        for v in manifest["videos"]:
            rec = {k: v[k] for k in ("path", "duration", "gt_category", "gt_nsfw")}
            t = time.perf_counter()
            frames = extract_frames(v["path"], count=6, max_side=1024)
            t_extract = time.perf_counter() - t
            try:
                verdict, meta = client.complete(frames, timeout=300)
                rec.update(verdict=verdict, meta=meta, ok=True)
            except Exception as exc:  # noqa: BLE001
                rec.update(ok=False, error=str(exc)[:300])
            finally:
                cleanup_frames(frames)
            rec["extract_s"] = round(t_extract, 2)
            rec["total_s"] = round(t_extract + meta.get("latency_s", 0) if rec.get("ok") else t_extract, 2)
            out["videos"].append(rec)
        out["vram_peak_mb"] = probe.peak
        out["wall_s"] = round(time.perf_counter() - t0, 1)
        out["server_argv"] = srv.cmd
    (EVAL / f"results_vlm_{model}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for r in out["images"] if r.get("ok"))
    print(f"vlm[{model}]: {ok}/30 images ok, vram peak {out['vram_peak_mb']} MB")
    return out


# ---------------------------------------------------------------- report
SIGLIP_TRIAGE = {"Normal": "safe", "Enticing or Sensual": "suggestive", "Pornography": "explicit",
                 "Hentai": "explicit", "Anime Picture": "safe"}
WD_TRIAGE = {"general": "safe", "sensitive": "suggestive", "questionable": "explicit", "explicit": "explicit"}
GT_TRIAGE = {"safe": "safe", "suggestive": "suggestive", "explicit": "explicit"}


def _prf(pairs: list[tuple[str, str]], positive: str) -> dict[str, float]:
    tp = sum(1 for gt, p in pairs if gt == positive and p == positive)
    fp = sum(1 for gt, p in pairs if gt != positive and p == positive)
    fn = sum(1 for gt, p in pairs if gt == positive and p != positive)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3)}


CAT_MAP_VLM = {"real_photo": "real", "anime": "anime", "illustration": "anime", "screenshot": "screenshot",
               "meme": "sticker", "text": "screenshot", "other": "other"}
GT_CT = {"daily": "real", "sexy": "real", "adult": "real", "anime": "anime", "sticker": "sticker", "screenshot": "screenshot"}


def build_report() -> str:
    manifest = load_manifest()
    pre = json.loads((EVAL / "results_prefilter.json").read_text(encoding="utf-8"))
    vlm_files = sorted(EVAL.glob("results_vlm_*.json"))
    vlm_runs = {json.loads(p.read_text(encoding="utf-8"))["model"]: json.loads(p.read_text(encoding="utf-8")) for p in vlm_files}
    gt = {it["path"]: it for it in manifest["images"]}

    lines: list[str] = []
    add = lines.append
    add("# MineHub 小样本模型评测报告")
    add(f"\n生成时间：{time.strftime('%Y-%m-%d %H:%M')} · 样本：30 张图片 + 5 个视频（QQ 原图抽样）\n")
    add("## 1. 速度与显存\n")
    add("| 模型 | 单图延迟 | 吞吐 | 加载耗时 | 显存峰值 | 备注 |")
    add("|---|---|---|---|---|---|")
    s = pre["siglip"]
    add(f"| SigLIP2 NSFW (fp16, 256px) | {s['mean_ms']} ms | {s['imgs_per_s_batch']} img/s (batch 30) | {s['load_s']} s | {s['vram_peak_mb']} MB | {s['device']} |")
    w = pre["wd"]
    add(f"| WD Eva02-large tagger (ONNX) | {w['mean_ms']} ms | {w['imgs_per_s']} img/s | - | {w['vram_peak_mb']} MB | {w['provider']} |")
    for name, run in vlm_runs.items():
        lat = [r["meta"]["latency_s"] for r in run["images"] if r.get("ok")]
        add(f"| Qwen3-VL-8B {name} (Q5_K_M) | {round(statistics.mean(lat),2)} s | {round(30/sum(lat)*len(lat),1) if lat else 0} img/s | - | {run['vram_peak_mb']} MB | llama.cpp |")
    add("\n视频（6 帧/条，含 ffmpeg 抽帧）：\n")
    add("| 模型 | 抽帧 | 推理 | 端到端/条 |")
    add("|---|---|---|---|")
    vids = pre["videos"]
    add(f"| SigLIP2 | {round(statistics.mean(v['extract_s'] for v in vids),2)} s | {round(statistics.mean(v['siglip_s'] for v in vids),2)} s | {round(statistics.mean(v['total_s'] for v in vids),2)} s |")
    for name, run in vlm_runs.items():
        vv = [v for v in run["videos"] if v.get("ok")]
        if vv:
            add(f"| Qwen3-VL {name} | {round(statistics.mean(v['extract_s'] for v in vv),2)} s | {round(statistics.mean(v['meta']['latency_s'] for v in vv),2)} s | {round(statistics.mean(v['total_s'] for v in vv),2)} s |")

    add("\n## 2. NSFW 三分类准确率（safe / suggestive / explicit）\n")
    add("| 模型 | 三分类准确率 | NSFW 二分 精确率/召回率 | explicit 精确率/召回率 |")
    add("|---|---|---|---|")
    pairs_sig = [(gt[r["path"]]["gt_nsfw"], SIGLIP_TRIAGE.get(r["label"], "review")) for r in s["per_image"]]
    pairs_wd = []
    for r in w["per_image"]:
        top = max(r["ratings"], key=r["ratings"].get)
        pairs_wd.append((gt[r["path"]]["gt_nsfw"], WD_TRIAGE.get(top, "review")))
    acc = lambda p: round(sum(1 for g, x in p if g == x) / len(p), 3)
    def binp(p: list[tuple[str, str]]) -> dict[str, float]:
        b = [("nsfw" if g != "safe" else "safe", "nsfw" if x != "safe" else "safe") for g, x in p]
        return _prf(b, "nsfw")
    expp = lambda p: _prf(p, "explicit")
    bp, ep = binp(pairs_sig), expp(pairs_sig)
    add(f"| SigLIP2 | {acc(pairs_sig)} | {bp['precision']}/{bp['recall']} | {ep['precision']}/{ep['recall']} |")
    bp, ep = binp(pairs_wd), expp(pairs_wd)
    add(f"| WD Eva02 tagger | {acc(pairs_wd)} | {bp['precision']}/{bp['recall']} | {ep['precision']}/{ep['recall']} |")
    for name, run in vlm_runs.items():
        ok = [r for r in run["images"] if r.get("ok")]
        p = [(r["gt_nsfw"], r["verdict"].get("nsfw_level")) for r in ok]
        if p:
            bp, ep = binp(p), expp(p)
            add(f"| Qwen3-VL {name} | {acc(p)} | {bp['precision']}/{bp['recall']} | {ep['precision']}/{ep['recall']} |")

    add("\n## 3. 内容类型判别（VLM）\n")
    add("| 模型 | 类型准确率 | JSON 有效率 | 平均输出 token |")
    add("|---|---|---|---|")
    for name, run in vlm_runs.items():
        ok = [r for r in run["images"] if r.get("ok")]
        good = [(GT_CT.get(r["gt_category"], r["gt_category"]), CAT_MAP_VLM.get(r["verdict"].get("content_type"), "other")) for r in ok]
        cacc = round(sum(1 for g, x in good if g == x) / len(good), 3) if good else 0
        toks = [r["meta"].get("completion_tokens", 0) for r in ok]
        add(f"| Qwen3-VL {name} | {cacc} | {len(ok)}/30 | {round(statistics.mean(toks)) if toks else 0} |")

    add("\n## 4. 逐图结果对照\n")
    header = "| # | GT | SigLIP | WD rating | " + " | ".join(f"VLM {n}" for n in vlm_runs) + " |"
    add(header)
    add("|" + "---|" * (3 + len(vlm_runs)))
    wd_top = {r["path"]: max(r["ratings"], key=r["ratings"].get) for r in w["per_image"]}
    for i, item in enumerate(manifest["images"]):
        row = [f"{i:02d}", f"{item['gt_category']}/{item['gt_nsfw']}", s["per_image"][i]["label"], wd_top[item["path"]]]
        for run in vlm_runs.values():
            rec = next((r for r in run["images"] if r["path"] == item["path"]), None)
            if rec and rec.get("ok"):
                v = rec["verdict"]
                row.append(f"{v.get('category')}/{v.get('nsfw_level')}")
            else:
                row.append("ERR")
        add("| " + " | ".join(row) + " |")

    add("\n## 5. 视频抽样结果\n")
    add("| # | GT | SigLIP 帧标签 | " + " | ".join(f"VLM {n}" for n in vlm_runs) + " |")
    add("|" + "---|" * (2 + len(vlm_runs)))
    for i, v in enumerate(manifest["videos"]):
        sv = vids[i] if i < len(vids) else {}
        row = [f"{i:02d}", f"{v['gt_category']}/{v['gt_nsfw']}", ",".join(sorted(set(sv.get("siglip_labels", []))))]
        for run in vlm_runs.values():
            rec = next((r for r in run["videos"] if r["path"] == v["path"]), None)
            if rec and rec.get("ok"):
                row.append(f"{rec['verdict'].get('category')}/{rec['verdict'].get('nsfw_level')}")
            else:
                row.append("ERR")
        add("| " + " | ".join(row) + " |")

    add("\n## 6. 结论与建议（待确认）\n")
    add("**语料结构（重要）**：QQ 缓存中 Pic 的 Ori 原图 48,017 张 / 16.3GB，Thumb 缩略图 132,729 张 / 38.7GB（每张原图约 2.8 个尺寸的副本，只有 16 张缩略图没有原图）；视频实际为 909 个 mp4 / 5.2GB（另 10,547 张 png 为封面图）。因此全量处理应只针对 **Ori + mp4，共 48,926 个文件 / 21.5GB**，无需处理 13.3 万张重复缩略图。\n")
    add("**模型定位**：\n")
    add("- SigLIP2 是合格的 Stage-1 粗筛：explicit 精确率 0.83 / 召回 1.0，NSFW 二分 1.0/1.0，单图 38ms、批量 82 张/秒，显存约 5.4GB。适合 4.9 万文件全量扫一遍（约 20–30 分钟）。")
    add("- WD Eva02 tagger 只适合动漫/表情包细分与标签补充，三分类准确率 0.70，且 11 张/秒偏慢，不建议进入全量主链路。")
    add("- Qwen3-VL NSFW-Caption（A）：explicit 召回 0.6，高于 Huihui 的 0.4；但会把动漫/擦边图过度判为 explicit。适合只对真人候选图与视频做精标。")
    add("- Huihui abliterated（B）：对 suggestive 更稳（视频 5/5 正确），explicit 偏保守；适合作为 A 的二次意见，专门仲裁 explicit/suggestive 边界。")
    add("- 两者 JSON Schema 强制输出均 30/30 一次通过，无 markdown 包裹，平均 66–69 token；A 平均 1.52s/图、B 1.56s/图，视频 6 帧约 3.7–3.8s。显存峰值均约 10.8GB（Q5_K_M + f16 mmproj + 8K ctx）。")
    add(f"\n**建议流水线**：Stage 1 SigLIP 全量（Pornography ≥ 0.5 直接进 adult；Hentai/Anime ≥ 0.5 进 anime，不走 VLM；Enticing ≥ 0.5 进 sexy 候选；Normal 中疑似截屏/表情包分流到 screenshot/sticker，其余 daily）。Stage 2 仅对 sexy 候选 + 视频 + 低置信度样本跑 VLM A，A 输出 explicit 或置信度 < 0.85 时用 B 复核；仍不确定的进 review。Stage 3 移动 + Stash GraphQL 打标。\n")
    add("**已知漏检**：紧身/白丝一类擦边图（样本 #23）SigLIP 判 Enticing 0.79，A/B 均判 safe，建议此类进入 review 而非直接 daily。\n")
    add("**容量**：F 盘剩余 77GB。模型占 14.7GB，移动 21.5GB 媒体后仍余约 40GB，可通过「先移动、校验、再删源」的安全顺序执行。")

    text = "\n".join(lines) + "\n"
    out = DATA.parent / "reports" / "eval_report.md"
    out.write_text(text, encoding="utf-8")
    print(f"report -> {out}")
    return text


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["prefilter", "vlm", "report", "all"])
    ap.add_argument("--model", choices=["nsfw", "huihui", "both"], default="both")
    args = ap.parse_args()
    if args.stage in ("prefilter", "all"):
        run_prefilter()
    if args.stage in ("vlm", "all"):
        for m in (["nsfw", "huihui"] if args.model == "both" else [args.model]):
            run_vlm(m)
    if args.stage in ("report", "all"):
        print(build_report())