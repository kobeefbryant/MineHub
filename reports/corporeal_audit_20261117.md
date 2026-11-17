# MineHub 人体向内容复核与 d3-mini A/B（2026-11-17）

## 1. 策略

库内只保留“人体向”的性感/NSFW 内容：

- 保留：裸露、生殖器/乳头、性行为；内衣、泳装、suggestive 姿势；遮挡、打码、局部遮挡的人体；含性感人物的动漫/插画。
- 排除：纯文字、聊天/UI 截图、表情包/meme、emoji、商品列表、性暗示文字/笑话但没有性感人物画面的图片；sticker 分类全部排除。
- 普通安全照片仍留在 QQ 原路径，不进入库。

阈值从 `nsfw_level in (suggestive, explicit)` 改为 `corporeal_nsfw=1`；旧数据回退到 explicit + sexy/anime/adult 的 suggestive。

## 2. 使用的模型

| 阶段 | 模型 | 说明 |
|---|---|---|
| 粗筛 | `nsfw-siglip2` | SigLIP2 5 类分类器，256px，GPU 批量 |
| 复核 | `qwen3vl-huihui-abliterated` | Qwen3-VL-8B abliterated，Q5_K_M GGUF，llama.cpp，4 slots，二选一：`sexual_person` / `text_or_meme` |
| A/B 新模型 | `vllm-sr/d3-mini` | 4.54B（Qwen3.5-4B + 0.33B 视觉编码器），BF16，`tools/d3lib` 独立依赖（transformers 5.17.0） |

复核路径：`mh/direct_audit.py`；CLI：`python -m mh.cli content-audit audit|restore|status`。

## 3. 复核结果

| 项目 | 数量 |
|---|---|
| 复核候选（screenshot/review/other/daily） | 3,194 |
| 判定保留（`sexual_person`） | 1,939 |
| 恢复 QQ（`text_or_meme`） | 1,243 |
| 补充清理（meme/text 误保留） | 2 |
| sticker 恢复 | 49（全部） |
| 错误 | 0 |
| 耗时 | 1,845 s（1.73/s） |

复核后库内（`F:\MineHubData\library`）：**12,941** 个文件

| 分类 | 数量 |
|---|---:|
| adult | 6,504 |
| sexy | 3,379 |
| anime | 3,311 |
| review | 1,552 |
| screenshot | 347 |
| other | 38 |

另有 2,181 张缩略图在 `F:\MineHubData\qq_thumbs`；QQ 原地保留 74,499 个普通文件。

## 4. Stash / 索引清理

- `metadataClean` 不删除文件已丢失的 DB 条目；用 `imagesDestroy` / `scenesDestroy`（`delete_file=false, delete_generated=true, destroy_file_entry=true`）清理了 **1,163 个 image + 10 个 scene** 幽灵记录。
- 清理后 Stash：**12,404 images + 482 scenes**。
- SigLIP2 索引重建：**12,886 条**，768 维，0 错误，107 s。
- 网关已恢复：`http://127.0.0.1:9999`；Ollama 已恢复。

## 5. d3-mini A/B

样本：100 张，四组各 25（512px）：

- A：kept 中 SigLIP 高风险、疑似漏判
- B：kept 普通安全照片
- C：复核恢复的误移内容（text/meme/chat）
- D：库内高置信 adult explicit

| 指标 | d3-mini | Huihui |
|---|---:|---:|
| 平均单张耗时 | **199 ms** | 1,779 ms |
| A 组 keep 率 | 0.00 | 0.00 |
| B 组 keep 率 | 0.00 | 0.00 |
| C 组 keep 率 | 0.04 | 0.04 |
| D 组 keep 率 | 1.00 | 1.00 |

- 一致率 **100/100**，Cohen κ = **1.0**。
- d3 的 D 组概率 0.835–0.998；C/B/A 组大多 <0.1，边界样本最高 0.568（与 Huihui 同判 keep）。
- 重要限制：标签来自现有账本和复核，不是人工逐张标注；四组是极端分组，任务偏容易。该结果说明 d3-mini 在这类二选一判定上与 Huihui 高度一致且快约 9 倍，不等于生产准确率。

产物：

- `data/reports/d3_ab_samples.json`（固定样本清单）
- `data/reports/d3_ab_d3_20261117_205956.json`
- `data/reports/d3_ab_huihui_20261117_205820.json`
- `data/reports/d3_ab_report.json`（汇总）

## 6. 复现

```bash
# 人体向复核（Huhui）
python -m mh.cli content-audit audit
python -m mh.cli content-audit restore
python -m mh.cli content-audit status

# d3-mini A/B
python tools/d3_ab.py build
python tools/d3_ab.py run --model huihui --max-side 512
python tools/d3_ab.py run --model d3 --max-side 512
python tools/d3_ab.py report
```

d3-mini 加载需要单卡约 15 GB 显存；A/B 时临时停掉了 Ollama 和网关，跑完已恢复。

## 7. 后续建议

1. 用人工抽检 30–50 张 C/D 组样本校准标签，再把 d3-mini 作为常规复核器；当前只证明了跨模型一致性。
2. 下一次新数据流水线可直接把 `corporeal_nsfw` 作为移动门槛；stage2 的 VLM 提示词已同步改为该定义。
3. 若要彻底去掉 Huihui 复核，先用 d3-mini 在更大随机样本（≥500）上测精确率/召回率。
