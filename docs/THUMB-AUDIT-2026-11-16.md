# MineHub 缩略图补漏审计 — 2026-11-16

## 为什么 QQ 里还残留 NSFW

本轮发现并确认了四个独立原因：

1. **QQ 文件名哈希 ≠ 文件内容 MD5**
   - 账本 `files.md5` 是文件字节的 MD5，QQ 的 `Ori`/`Thumb` 文件名用的是 QQ 媒体哈希。
   - 对 JPEG/GIF/视频，两者经常不相等，旧 `mh.cli thumbs` 只按内容 MD5 匹配，漏掉了对应已移动 NSFW 文件的缩略图。
2. **同一媒体的缩略图有多个变体**
   - 典型名称：`<hash>_0.jpg`、`<hash>_720.jpg`、`<hash>_0.png`。
   - 旧逻辑只匹配账本中恰好那一个文件名；其它变体留在 QQ。
3. **仅缩略图账本行的文件名带变体后缀**
   - `import_thumbs` 导入的 40,682 条 `origin='thumb_only'` 记录，`src_path` 形如 `..._0.jpg` / `..._720.gif`。
   - 首次审计索引没有去掉 `_0` / `_720`，导致 33,744 条被误当成“孤儿缩略图”，VLM 即使判 NSFW 也无法回写主账本。
4. **fast-route 只过了 SigLIP**
   - `fast_route_thumbs()` 把 `Normal`/`Anime Picture` 的仅缩略图记录直接标记为 safe，没有 VLM。
   - SigLIP 对视频预览/低分辨率缩略图召回不足；本轮样本中出现 SigLIP=0.033、VLM=explicit 的视频预览图。
5. **Anime Picture 被硬编码为 safe**
   - `finalize_anime()` 曾把所有 Stage1 `Anime Picture` / `Hentai` 直接写入 final_json，其中 `Anime Picture` 的 `nsfw_level` 一律为 `safe`，完全跳过 VLM。
   - 用户点名的 `Pic/2026-10/Ori/0458...jpg`、`4a32...gif`、`916b...gif` 都属于这一类；本地 VLM 复判三张全部为 `explicit`。
   - 现已删除该硬编码路径；`stage2 A` 现在把 `Anime Picture` / `Hentai` 也纳入 VLM，reaudit 也优先复核未跑过 VLM 的 anime。

## 已做的修复

### 1. 精确匹配优先

新增 `mh/thumb_audit.py`：

- 用 `src_path` 的文件名 stem 和内容 MD5 双索引；
- 对所有账本行额外索引去掉 `_\d+$` 后的 stem，覆盖 `_0` / `_720` 变体；
- 匹配到 `move_state='moved'` 的源文件时，缩略图直接判为确定 NSFW，不经过模型。

### 2. 缩略图直接分类

- 枚举 QQ `Pic`/`Video` 下所有 `Thumb` 文件；
- 静态图：SigLIP 分类；
- GIF：最多取 4 帧，分别打分后取 NSFW 最大值，避免第一帧安全；
- 所有 Video 预览图强制进入 VLM；
- 仅缩略图 fast-route 记录使用更低 SigLIP 门槛（0.03），避免漏掉低分但明确的预览图；
- 强 SigLIP 证据不会被 VLM 的 safe 结论覆盖。

### 3. VLM 精判

- 模型 A：`qwen3vl-nsfw-caption`，4 slots / 4 workers；
- 输出分类、等级、标签、置信度；
- GIF 只把 SigLIP 选出的最高 NSFW 帧送给 VLM；
- 判为 `suggestive` / `explicit` 的缩略图进入 `ready_move`；
- VLM 判 NSFW 且缩略图能关联到仍留在 QQ 的 `Ori` 时，同时把 `Ori` 标记为 `pending`，由 `move_all` 按原子流程迁移；
- JSON 被 `max_tokens` 截断时自动用 640 tokens 重试；`repair-vlm` 可从已截断响应中恢复 `nsfw_level`，本轮恢复了 18 张（11 张 NSFW、7 张 safe）；
- 当前剩余 62 张为 QQ 写入的 1 字节占位 PNG，无图像可判，保留在 QQ。

### 4. 第二轮 kept 复核

新增 `mh/reaudit.py`：

- 对留在 QQ 的非 thumb-only 原图做第二遍 VLM（模型 B，`huihui`）；
- 选择条件：视频、`needs_review`、`sexy/adult/review`、未跑过 VLM 的 anime，或 SigLIP NSFW 概率 ≥0.1；
- 视频抽取 8 帧；
- 判为 suggestive/explicit 时更新主账本并标记 `pending`。

### 5. 流水线修复

- `mh.pipeline` 不再调用 `fast_route_thumbs`，仅缩略图记录也进入 stage2 A；
- 流水线在移动后执行 `thumb_audit` 的 scan/siglip/repair/promote/vlm/move，再执行 reaudit 和 `move_all`；
- `mh.cli thumbs` 本身也已改为 stem+MD5 双匹配，避免旧入口继续漏。

## 当前数据（本报告写入时）

| 项目 | 数量（2026-11-17 01:06） |
|---|---:|
| QQ 缩略图总数 | 132,616 |
| 已迁出 NSFW 缩略图 | 17,973 |
| 纯安全（SigLIP） | 94,481 |
| VLM 已判安全 | 20,010 |
| 精确匹配、安全或已迁 | 90 |
| VLM 精判队列 | 0 |
| 已确认、待迁 | 0 |
| 读图/解析失败 | 62（均为 1 字节占位 PNG，无实际图像） |

2026-11-17 的增量复扫又迁出 591 张 NSFW 缩略图（QQ 重开/浏览后再生，以及之前精确匹配但未执行移动的残留）；原图新增 2 条 NSFW 已同步迁移。随后对用户点名的 `.null`/现有文件做定向 VLM，并强制复查 490 张 GIF/.null 缩略图，再迁出 32 张缩略图、28 个原图。

迁出目标：

```text
F:\MineHubData\qq_thumbs\<账号>\<Pic|Video>\<YYYY-MM>\Thumb\
```

审计：

- `data\thumb_audit_moves.csv`：本轮逐文件迁移记录（含 match_state / level / category / siglip_nsfw / ledger_id）
- `data\minehub.sqlite` → `thumb_audit` 表：每张缩略图的状态机
- `data\minehub.sqlite` → `reaudit` 表：kept 原图第二遍复核
- `data\logs\thumb_siglip.log`、`data\logs\thumb_vlm.log`

## 2026-11-17 定向补漏

- QQ 的 `.null` 文件不是空文件：本批 32 个 `.null` 原图实际为 26 个 JPEG/6 个 GIF，之前被扩展名过滤器完全跳过；`.null` 现已加入图片扩展名，迁移时按实际格式恢复为 `.jpg/.png/.gif`。
- 对 70 个 `.null`/用户点名文件跑 Qwen3-VL：18 个 NSFW；5 个 `.null` 原图、1 个 GIF 原图搬迁。`4af…`、`6aac…`、`58be…` 虽被 VLM 判 safe，但按用户人工标注放入 `library/review`。
- 强制复查 490 张 GIF/`.null` 缩略图（不再只靠 SigLIP）：11 张 NSFW，连带定位并迁移 9 个原 GIF。`.gif` 与 `.null` 现在一律强制走 VLM。
- 对 257 个“只过 SigLIP、从未跑 VLM”的 kept GIF 原图做逐帧复查：8 个 NSFW（7 个 suggestive、1 个 explicit），同 stem 缩略图一并迁移。

## 常用命令

```bat
:: 日常：原图 + 缩略图一起增量复扫
python -m mh.cli rescan --dry-run
python -m mh.cli rescan

:: 只处理缩略图（保留旧状态，只跑新增/变化）
python -m mh.cli thumb-audit incremental

:: 需要拆阶段时
python -m mh.cli thumb-audit status
python -m mh.cli thumb-audit scan
python -m mh.cli thumb-audit siglip
python -m mh.cli thumb-audit repair
python -m mh.cli thumb-audit promote
python -m mh.cli thumb-audit vlm
python -m mh.cli thumb-audit repair-vlm
python -m mh.cli thumb-audit move

:: kept 原图第二轮复核
python -m mh.cli reaudit select
python -m mh.cli reaudit run --model huihui
python -m mh.cli reaudit status
```

## 验证

- 6 张用户点名的 `Video/2026-08`、`Video/2021-12`、`Video/2023-07` 缩略图已迁出，源路径不存在、目标文件存在；
- 当前累计 17,941 张确定 NSFW 缩略图迁出，迁移记录在 `data\thumb_audit_moves.csv`；
- 迁移后的目标文件逐张校验大小；
- 源文件删除后，账本同步更新。

## 后续维护

全量 VLM、迁移、reaudit、Stash 补标、索引重建均已完成；QQ 重开并浏览旧聊天后仍可能生成新的预览图，按需执行：

```bat
python -m mh.cli rescan
python -m mh.cli stash --scan --tag
python -m mh.cli index build --kind all --model siglip2 --device cuda
```

`rescan` 已串起原图扫描、Stage 1/2、原图移动、缩略图增量和缩略图移动；Stash 与索引重建保持手动，避免每次复扫都全量重扫 1.4 万条。`mh.after_audit` 仍保留为全量收尾编排。
