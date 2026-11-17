# MineHub 小样本模型评测报告

生成时间：2026-11-16 00:01 · 样本：30 张图片 + 5 个视频（QQ 原图抽样）

## 1. 速度与显存

| 模型 | 单图延迟 | 吞吐 | 加载耗时 | 显存峰值 | 备注 |
|---|---|---|---|---|---|
| SigLIP2 NSFW (fp16, 256px) | 38.2 ms | 81.8 img/s (batch 30) | 8.06 s | 5383 MB | cuda |
| WD Eva02-large tagger (ONNX) | 88.5 ms | 11.2 img/s | - | 5383 MB | CUDAExecutionProvider |
| Qwen3-VL-8B huihui (Q5_K_M) | 1.56 s | 19.2 img/s | - | 10821 MB | llama.cpp |
| Qwen3-VL-8B nsfw (Q5_K_M) | 1.52 s | 19.7 img/s | - | 10846 MB | llama.cpp |

视频（6 帧/条，含 ffmpeg 抽帧）：

| 模型 | 抽帧 | 推理 | 端到端/条 |
|---|---|---|---|
| SigLIP2 | 0.89 s | 0.05 s | 0.94 s |
| Qwen3-VL huihui | 0.91 s | 3.79 s | 4.7 s |
| Qwen3-VL nsfw | 0.91 s | 3.72 s | 4.64 s |

## 2. NSFW 三分类准确率（safe / suggestive / explicit）

| 模型 | 三分类准确率 | NSFW 二分 精确率/召回率 | explicit 精确率/召回率 |
|---|---|---|---|
| SigLIP2 | 0.967 | 1.0/1.0 | 0.833/1.0 |
| WD Eva02 tagger | 0.7 | 0.818/0.75 | 0.5/0.6 |
| Qwen3-VL huihui | 0.767 | 0.846/0.917 | 0.667/0.4 |
| Qwen3-VL nsfw | 0.733 | 0.846/0.917 | 0.5/0.6 |

## 3. 内容类型判别（VLM）

| 模型 | 类型准确率 | JSON 有效率 | 平均输出 token |
|---|---|---|---|
| Qwen3-VL huihui | 0.733 | 30/30 | 69 |
| Qwen3-VL nsfw | 0.667 | 30/30 | 66 |

## 4. 逐图结果对照

| # | GT | SigLIP | WD rating | VLM huihui | VLM nsfw |
|---|---|---|---|---|
| 00 | daily/safe | Normal | sensitive | anime/safe | anime/suggestive |
| 01 | daily/safe | Normal | general | daily/safe | daily/safe |
| 02 | daily/safe | Normal | general | daily/safe | daily/safe |
| 03 | daily/safe | Normal | general | screenshot/safe | screenshot/safe |
| 04 | daily/safe | Normal | general | anime/safe | screenshot/safe |
| 05 | daily/safe | Normal | general | other/safe | screenshot/safe |
| 06 | screenshot/safe | Normal | general | other/safe | other/safe |
| 07 | screenshot/safe | Normal | general | screenshot/safe | screenshot/safe |
| 08 | screenshot/safe | Normal | sensitive | screenshot/safe | screenshot/safe |
| 09 | screenshot/safe | Normal | general | screenshot/safe | other/safe |
| 10 | sticker/safe | Anime Picture | general | sticker/safe | screenshot/safe |
| 11 | sticker/safe | Anime Picture | general | sticker/safe | sticker/safe |
| 12 | sticker/safe | Anime Picture | general | anime/safe | anime/safe |
| 13 | sticker/safe | Anime Picture | general | anime/safe | anime/safe |
| 14 | anime/safe | Anime Picture | general | anime/suggestive | anime/safe |
| 15 | anime/safe | Anime Picture | general | anime/safe | anime/safe |
| 16 | anime/safe | Anime Picture | general | sexy/suggestive | sexy/suggestive |
| 17 | anime/safe | Anime Picture | general | sticker/safe | sticker/safe |
| 18 | sexy/suggestive | Enticing or Sensual | sensitive | sexy/suggestive | sexy/suggestive |
| 19 | sexy/suggestive | Enticing or Sensual | questionable | sexy/suggestive | sexy/explicit |
| 20 | sexy/suggestive | Enticing or Sensual | general | sexy/suggestive | sexy/suggestive |
| 21 | sexy/suggestive | Enticing or Sensual | sensitive | sexy/suggestive | sexy/explicit |
| 22 | sexy/suggestive | Enticing or Sensual | questionable | sexy/explicit | adult/explicit |
| 23 | sexy/suggestive | Enticing or Sensual | general | daily/safe | daily/safe |
| 24 | adult/explicit | Pornography | sensitive | sexy/suggestive | sexy/suggestive |
| 25 | adult/explicit | Pornography | explicit | adult/explicit | adult/explicit |
| 26 | adult/explicit | Pornography | explicit | adult/explicit | adult/explicit |
| 27 | adult/explicit | Pornography | explicit | sexy/suggestive | adult/explicit |
| 28 | adult/explicit | Pornography | general | sexy/suggestive | sexy/suggestive |
| 29 | anime/suggestive | Hentai | questionable | sexy/suggestive | sexy/suggestive |

## 5. 视频抽样结果

| # | GT | SigLIP 帧标签 | VLM huihui | VLM nsfw |
|---|---|---|---|
| 00 | daily/safe | Anime Picture,Normal | daily/safe | daily/safe |
| 01 | sexy/suggestive | Enticing or Sensual,Normal | sexy/suggestive | adult/explicit |
| 02 | sexy/suggestive | Enticing or Sensual | sexy/suggestive | sexy/suggestive |
| 03 | daily/safe | Normal | daily/safe | screenshot/safe |
| 04 | daily/safe | Anime Picture,Normal | daily/safe | daily/safe |

## 6. 结论与建议（待确认）

**语料结构（重要）**：QQ 缓存中 Pic 的 Ori 原图 48,017 张 / 16.3GB，Thumb 缩略图 132,729 张 / 38.7GB（每张原图约 2.8 个尺寸的副本，只有 16 张缩略图没有原图）；视频实际为 909 个 mp4 / 5.2GB（另 10,547 张 png 为封面图）。因此全量处理应只针对 **Ori + mp4，共 48,926 个文件 / 21.5GB**，无需处理 13.3 万张重复缩略图。

**模型定位**：

- SigLIP2 是合格的 Stage-1 粗筛：explicit 精确率 0.83 / 召回 1.0，NSFW 二分 1.0/1.0，单图 38ms、批量 82 张/秒，显存约 5.4GB。适合 4.9 万文件全量扫一遍（约 20–30 分钟）。
- WD Eva02 tagger 只适合动漫/表情包细分与标签补充，三分类准确率 0.70，且 11 张/秒偏慢，不建议进入全量主链路。
- Qwen3-VL NSFW-Caption（A）：explicit 召回 0.6，高于 Huihui 的 0.4；但会把动漫/擦边图过度判为 explicit。适合只对真人候选图与视频做精标。
- Huihui abliterated（B）：对 suggestive 更稳（视频 5/5 正确），explicit 偏保守；适合作为 A 的二次意见，专门仲裁 explicit/suggestive 边界。
- 两者 JSON Schema 强制输出均 30/30 一次通过，无 markdown 包裹，平均 66–69 token；A 平均 1.52s/图、B 1.56s/图，视频 6 帧约 3.7–3.8s。显存峰值均约 10.8GB（Q5_K_M + f16 mmproj + 8K ctx）。

**建议流水线**：Stage 1 SigLIP 全量（Pornography ≥ 0.5 直接进 adult；Hentai/Anime ≥ 0.5 进 anime，不走 VLM；Enticing ≥ 0.5 进 sexy 候选；Normal 中疑似截屏/表情包分流到 screenshot/sticker，其余 daily）。Stage 2 仅对 sexy 候选 + 视频 + 低置信度样本跑 VLM A，A 输出 explicit 或置信度 < 0.85 时用 B 复核；仍不确定的进 review。Stage 3 移动 + Stash GraphQL 打标。

**已知漏检**：紧身/白丝一类擦边图（样本 #23）SigLIP 判 Enticing 0.79，A/B 均判 safe，建议此类进入 review 而非直接 daily。

**容量**：F 盘剩余 77GB。模型占 14.7GB，移动 21.5GB 媒体后仍余约 40GB，可通过「先移动、校验、再删源」的安全顺序执行。
