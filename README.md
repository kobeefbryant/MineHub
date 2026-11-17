# MineHub — 本地媒体智能检索与 Stash 原生集成

MineHub 是围绕 Stash 的本地媒体智能层，目标是把现代媒体库能力带进本地：以图搜图、文本语义搜图、重复/相似检测、人脸聚类、原生预览与批量管理。QQ 聊天缓存导入和 NSFW 自动归档只是一个可选的数据入口与真实规模验证场景，不是项目主线；不导入 QQ 也可以直接管理任意 Stash 库。

当前运行状态、索引进度与 safe 复核计划见 `docs/STATUS-2026-11-18.md`。

## 核心能力（已实现）

- **以图搜图**：SigLIP2 图像向量 + 余弦 Top-K，图片/场景详情页「找相似」直接跳转；相似页会显示源图原图，默认返回 48 张，默认阈值无结果时自动降低一档；
- **文本语义搜图**：中英文描述搜图，支持多关键词、全部/任一命中、图片/场景范围筛选；
- **正则/标签检索**：按文件名、路径、Stash 标签、ID 匹配，带可点击模板；
- **重复/相似检测**：256 位 aHash/dHash/pHash、BK-tree、严格全连接、阈值可调；支持任意文件夹图片+视频（视频 5 帧 pHash）和 Stash 场景 pHash；
- **人脸聚类**：InsightFace buffalo_l 检测 + 512 维特征，余弦相似度阈值聚类，按人物浏览后批量写入 Stash 演员并关联图片；
- **Stash 原生体验**：图片/场景页原位搜索（名称/特征 + 正则开关），结果使用 Stash 原生卡片网格；“特征”同时利用 SigLIP2 语义与文件名/路径/标签关键词；独立 `/mh` 页面、语义星图、原生预览、默认按文件大小排序、中文托盘、同源 9999 入口；
- **可选 QQ/NSFW 流水线**：QQ 缓存扫描、SigLIP2/Qwen3-VL 打标、NSFW 归档；默认只移动 NSFW，普通文件留在原路径。

## 路线图

- **场景人脸**：从视频抽帧后归入同一套人物聚类（当前只处理 Stash 图片）；
- **OCR**：图内文字检索；
- **视频智能**：场景/关键帧语义检索与时间轴标记。

## 一键启动

Windows 下双击项目根目录的 `启动MineHub.bat`。脚本会调用 `.venv` 的 `pythonw` 隐藏启动中文托盘、Stash（内部 9998）和同源网关（9999），健康检查通过后打开 `http://127.0.0.1:9999/mh`。托盘菜单顶部为「搜索」「打开 MineHub」，下面可直接打开视频、图片、集合等库；退出使用「退出 MineHub」。

## 可配置数据目录

`/mh` →「设置」可以修改：

- **资料库根目录**：`library`、`review`、`cache`、`qq_thumbs`、`safe`、Stash 生成文件；
- **模型目录**：SigLIP2、Qwen3-VL 等模型；可以和资料库分开放在不同磁盘；
- **QQ 数据根目录**：可选的 QQ 缓存扫描和归属索引。

保存后写入项目 `data/settings.json`；`MH_MEDIA_ROOT` / `MH_MODELS_ROOT` / `MH_QQ_BASE` 环境变量优先于设置文件。设置只切换路径，不会自动搬移现有文件；保存后关闭托盘中的 MineHub，再双击一键启动脚本即可应用。Stash 的生成预览会在新的 generated 目录下按需重建。

## 可选数据入口：QQ 缓存 / NSFW 归档现状（2026-11-18 01:20）

| 项目 | 状态 |
|---|---|
| 环境 | Python 3.11.7 venv + torch 2.9.1+cu128（RTX 5060 Ti sm_120 已验证）+ onnxruntime-gpu + llama.cpp b12415 CUDA 13.5 |
| 模型 | SigLIP2 NSFW、google/siglip2-base-patch16-256、WD Eva02 tagger、Qwen3-VL-8B-NSFW-Caption Q5_K_M、Huihui-Qwen3-VL-8B-abliterated Q5_K_M、InsightFace buffalo_l（均在 `E:\1Codes\MineHub\models`，约 21 GB；`d3-mini` A/B 模型另约 9.1 GB） |
| 小样本评测 | 完成，见 `reports/eval_report.md`（30 图 + 5 视频） |
| 数据规模 | 89,634 条：910 个视频 + 88,724 张图片（含仅存在于 Thumb 的唯一图片与 .null 原图） |
| Stage 1 | 完成：88,724 张图片全部 SigLIP2 预筛（910 个视频不经过 Stage 1） |
| Stage 2 A | 完成：49,697 条（全部视频 + 图片） |
| Stage 2 B | 完成：6,641 条（仅仲裁 explicit / 低置信度 / review） |
| 复核 | 2,947/2,964 条 SigLIP-only explicit 用 VLM 复检；5,542 张安全二次元已搬回 QQ |
| Stage 3 | 历史累计已移动 **15,131** 条记录（2026-11-17 库内 12,941：adult 6,504 / sexy 3,379 / anime 3,311 / review 1,552 / screenshot 347 / other 38；另有 2,181 张缩略图在 `qq_thumbs`），**74,499** 个普通文件留在 QQ 原地；2026-11-18 当前 `library` 为 **9,844** 个文件（9,361 张图片），差额来自 safe 分离 |
| Stash | 历史扫描并清理丢失条目后为 **482** scene + **12,404** image；2026-11-18 当前 **482** scene + **9,332** image，累计 **12,720** 条 tagged |
| 缩略图审计 | 132,616 张 QQ Thumb 已扫描；已迁出 **17,982** 张 NSFW，94,472 张 SigLIP safe + 20,010 张 VLM safe；62 张 1 字节占位 PNG 无法读图；无待处理项 |
| Blue-Eye safe 复核 | 全库 12,462 张三分类：**safe 3,503 / suggestive 5,519 / explicit 3,440**；已移动 **3,500** 张到 `F:\MineHubData\safe\<分类>\<月份>\`，3 张因同图非 safe 兄弟文件跳过；复核清单 `safe\blueeye_safe_manifest_*.csv` |
| 当前库与索引（2026-11-18） | `library` **9,844** 个文件（**9,361** 张图片）；`safe` **2,923** 张图片（1.3 GB）；Stash **9,332 image / 482 scene**；SigLIP2 索引 **9,416** 条；Qwen3-VL-Embedding 索引正在按当前 9,332 张图片重建（旧索引为空） |
| 增量复扫 | `mh.cli rescan` 已实测：2026-11-17 一轮耗时 122 s，迁出 2 个新 NSFW 原图 + 591 张残留 NSFW 缩略图；已修复 Stage 1 后计数未刷新导致新文件跳过 Stage 2 的问题，补入 24 个 `.null` 原图（VLM 全部判 safe，0 移动） |
| 定向补漏 | 70 个 .null/点名文件 VLM：18 个 NSFW；490 张 GIF/.null 缩略图强制 VLM：11 个 NSFW、9 个原 GIF；257 个仅 SigLIP 的 kept GIF 逐帧 VLM：8 个 NSFW；合计新增 28 个原图 + 32 张缩略图 |
| 第二轮复核 | 7,938 条已检查，622 条 flagged，0 错误；501 条源文件已移动、1 条源文件缺失，已归位状态 |
| 视频时间轴 | **492/492 个场景均有 preview+sprite+vtt**（1,476 个文件 / 1.5 GB）；scene 50 已单独转码 H.264 修复，原文件备份在 `F:\MineHubData\backups\` |
| 相似搜索 | 双索引：旧 `nsfw-siglip2`（`vectors.sqlite` / `embeddings.npy`）+ 新 `google/siglip2-base-patch16-256`（`vectors_siglip2.sqlite` / `embeddings_siglip2.npy`）；当前 **9,416 条**，0 错误，768 维；支持图搜、中英文文本搜图、多关键词和正则/标签搜索；Stash 图片/场景页搜索框旁可切换名称/特征，并用正则开关把输入解释为正则，结果用原生卡片网格在当前页展开，不跳转；语义星图把 9,416 条 768 维向量投影到二维平面 |
| 人脸聚类 | InsightFace buffalo_l（det_10g + w600k_r50，ONNX Runtime CUDA/CPU）；完成 **13,563/13,566** 张图片扫描（3 张源文件缺失），**8,122 张人脸 / 6,586 张含人脸图片**；阈值 `0.60` 下 **3,729 个聚类**，其中 **282 个 ≥3 张图片**；已创建 **282 个演员**并关联 **4,106 张图片**，0 警告；人脸特征在 `data\faces.sqlite`（35 MB），裁剪在 `F:\MineHubData\cache\faces`（67 MB） |
| 访问入口 | 统一使用 `http://127.0.0.1:9999`；同源网关把 Stash 内部 `127.0.0.1:9998` 与 MineHub API `/mh/api/*` 合并在同一端口，不再需要单独打开 8765 |
| MineHub 原生集成 | 插件 `tools\stash\plugins\minehub`（1.0.26）：顶部「搜索」打开独立 `/mh` 页面，原生页面与 `/mh` 之间使用 SPA 路由切换；图片/视频页搜索框旁提供名称/特征模式按钮和正则开关，结果直接以 Stash 原生卡片网格和计数样式显示；图片/视频列表默认预览墙模式、每页 200 个并按文件大小降序（首个 GraphQL 请求即为 filesize/200/desc，不再先显示日期排序）；图片墙卡片右上角有找相似按钮，图片和视频墙卡片中心都有预览按钮（视频打开内置播放浮层），点击卡片其他位置进入详情；动画 GIF 详情页提供可点击/拖动的帧时间轴，详情页原生「找相似」按钮，以及搜索 / 语义星图 / QQ 缓存 / 人脸聚类 / 重复检测 / 文件夹 / 九宫格 / 设置八个页签；搜索页带特征搜索、正则开关、相似度预设、结果数预设和手动数量，支持多关键词、正则模板、勾选批量删除和 Stash 原生预览；点击原生卡片标签数可查看 MineHub 特征面板（Top5 语义 + 全部关键词）；单帧 GIF 会在文件信息里提示；图片列表勾选后可在删除键与省略号之间点「训练集」移动到 `F:\MineHubData\embeddingsafedata`；「文件夹」页签可浏览 `safe` 等目录，点击图片即选中，支持 Shift 连选和左键拖拽框选，批量移到 `library` 或 `embeddingsafedata`。 QQ 缓存页签支持仅群聊内容、QQ 查重和按分类/月份移到 `library`；新增「九宫格」页签，Huihui 以 4 路并发独立判定 9 张图，给出第几行第几列保留/排除，再把保留项批量移到 `library`。中文托盘菜单可打开各库并退出 |
| QQ 缓存面板 | 在 Stash 内完成扫描、聊天归属筛选、MineHub 标签筛选、照片墙/预览、移动、回收站、切换目录和重建归属索引；支持「仅群聊内容」；「查重 QQ」可只统计群聊归属图，按组选择后移入回收站或按分类/月份移到 `library`；普通文件仍留在 QQ，不进入 Stash 库 |
| 重复检测 | 相似图片页签实现 256 位 aHash/dHash/pHash + BK-tree，改为严格全连接分组，阈值 0–40 可调并缓存；新增指定文件夹递归扫描（图片+视频），视频按 5 帧 pHash 全帧距离比较；Stash 场景 pHash 距离可调（10 时 8 组/23 个场景）；完全相同文件复用账本 MD5（865 组/1,964 个）。QQ 群聊范围实测 **229 组 / 616 个文件 / 387 个重复项**，首次分组约 154 s，缓存后约 0.13 s |
| 界面 | Stash 使用内置 `zh-CN`，品牌/标题替换为 MineHub，托盘菜单全中文；文件信息补译「文件大小」「制作日期」；备份在 `data\backups\config-20261116-192957.yml` 与 `stash-go-20261116-192957.sqlite` |

可选数据来源：`D:\Tencent Files\<QQ号>\nt_qq\nt_data\{Pic,Video}\**\Ori`（QQ 根目录可用 `MH_QQ_BASE` 覆盖）
目标库：`F:\MineHubData\library\{sexy,adult,anime,review}\YYYY-MM\`

**移动策略（2026-11-17 调整）**：只保留“人体向”的性感/NSFW 内容——裸露、内衣、泳装、 suggestive 姿势、遮挡/打码的人体都算；纯文字、聊天/UI 截图、表情包/meme、无性感人物的普通照片留在 QQ 原路径。已移动文件用 `mh.direct_audit` 做人体向二分类复核，`corporeal_nsfw=1` 才留在库里。

**2026-11-17 策略复核**：对易误判的 screenshot/review/other/daily 共 **3,194** 条做人体向二分类复核（Huihui-Qwen3-VL-8B-abliterated，二选一：`sexual_person` / `text_or_meme`）——保留 1,939 条，恢复 1,243 条，另补清 2 条纯文字/表情包；sticker 已全部恢复。当时库内 12,941 条，其中复核确认 `corporeal_nsfw=1` 1,937 条、`corporeal_nsfw=0` 1,245 条；2026-11-18 当前库内 9,844 个文件（9,361 张图片）。命令：`python -m mh.cli content-audit audit|restore|status`。

**d3-mini A/B（2026-11-17）**：`vllm-sr/d3-mini`（4.54B，BF16）已下载到 `E:\1Codes\MineHub\models\d3-mini`，独立依赖 `tools/d3lib`（transformers 5.17.0）。100 张固定样本（A 漏判 25 / B 普通 25 / C 误移 25 / D 高severity 25，512px）上与 Huihui 判定 **100/100 一致，Cohen κ=1.0**；GPU 单张平均 **199 ms**，Huihui 为 **1,779 ms（约 9×）**。注意：样本标签来自现有账本与复核，不是人工逐张标注，极端分组偏容易；报告在 `data/reports/d3_ab_report.json`。

**九图判定实测（2026-11-18）**：同一组 9 张图、长边 768px，对比三种方式：

| 方式 | 耗时 | 输入量 | 与人工标签一致 |
|---|---:|---:|---:|
| 原生一次传 9 张 | 11.0 s 推理 | 2,077 prompt tokens | 7/9 |
| 3×3 拼成一张 | 约 22 s | 单张拼图 | 6/9，9 张全判保留 |
| 独立单图 × 4 并发 | 18.9 s 墙钟；接口约 21 s | 11,239 prompt + 748 completion | **9/9** |

原生多图更快，但会把纯人脸特写和新闻图误判为保留；拼图会损失单格分辨率并放大小图误判。最终采用独立单图、4 路并发，每个请求独立上下文，避免串图。限制：这 9 张参与了提示词调整，9/9 是样本内结果；不能当作生产准确率，后续需要未参与调参的样本复测。

## 目录

```
E:\1Codes\MineHub
├─ 启动MineHub.bat    一键启动：托盘 + Stash 9998 + 网关 9999
├─ mh\                核心代码：检索 / 网关 / 库管理 / 可选 QQ 流水线
│  ├─ config.py       路径、Prompt、分类定义
│  ├─ settings.py     资料库/模型/QQ 路径设置（data/settings.json）
│  ├─ db.py           SQLite 任务账本（断点续跑）
│  ├─ scanner.py      枚举 QQ 缓存
│  ├─ prefilter.py    SigLIP2 / WD tagger
│  ├─ stage1.py       全量预筛
│  ├─ stage2.py       VLM A 精标 + B 仲裁 + 合并
│  ├─ stage3.py       MD5 去重 + 移动 + 回滚
│  ├─ stash.py        Stash 配置 / GraphQL 扫描与打标
│  ├─ pipeline.py     无人值守编排（A→B→合并→移动→Stash）
│  ├─ thumb_audit.py  QQ 缩略图补漏：匹配 / SigLIP / 分组 VLM / 迁移
│  ├─ reaudit.py      保留原图的第二轮 VLM 复核
│  ├─ siglip_embed.py SigLIP2 视觉塔 768 维 embedding
│  ├─ manager.py      QQ 缓存面板后端：扫描/筛选/缩略图/移动/回收站/群聊过滤/重复检测
│  ├─ gateway.py      同源网关：9999 公开端口代理 Stash 9998 + /mh/api
│  ├─ dupes.py        图片/视频感知哈希重复检测：aHash/dHash/pHash、5 帧视频签名、严格全连接、阈值
│  ├─ faces.py        InsightFace 人脸检测/特征、增量扫描、聚类与演员写入
│  ├─ folder_ops.py   文件夹浏览、批量移动、Stash 批量移除
│  ├─ nine_grid.py    九图读取与 Huihui 4 路并发独立判定
│  ├─ direct_audit.py 人体向内容复核与恢复
│  ├─ safe_reclass.py Huihui 复核 safe 目录，命中项移回 library
│  ├─ blueeye.py      Blue-Eye 三分类评分与 safe 分离
│  ├─ desktop.py      中文托盘：隐藏启动 Stash/网关并抑制 Stash 自带托盘
│  ├─ qq\             QQNT 归属索引：密钥读取、消息库解密、MD5→聊天映射
│  ├─ siglip2_embed.py google SigLIP2 图文双塔 embedding
│  ├─ qwen3vl_embed.py Qwen3-VL-Embedding-2B 多模态 embedding（可选）
│  ├─ semantic.py     72 个语义标签 Prompt、标签分组、768→2D PCA 投影
│  ├─ index.py        相似索引（SQLite + numpy，支持 nsfw / siglip2 / qwen3vl）
│  ├─ index_server.py 旧版独立 Top-K 查看页（仅调试；日常走网关）
│  ├─ rescan.py       手动增量复扫（新原图 + 新缩略图）
│  ├─ after_audit.py  等 VLM 跑完后自动迁移 / 复核 / 补标 / 重建索引
│  ├─ serve.py        llama-server 生命周期
│  ├─ vlm.py          OpenAI 兼容客户端（JSON Schema 强约束）
│  └─ frames.py       ffmpeg 均匀抽帧
├─ eval\              抽样与评测脚本
├─ data\              minehub.sqlite、日志、评测结果、移动审计 CSV
├─ reports\           eval_report.md、人体向复核与 d3-mini A/B 报告
└─ tools\             llama.cpp、stash、下载脚本
   └─ stash\plugins\minehub\  Stash 原生插件：特征搜索 / 找相似 / 语义星图 / 重复检测 / QQ 缓存 / 九宫格
```

## 配置

默认路径针对本机布置（项目 `E:\1Codes\MineHub`、资料库 `F:\MineHubData`、模型 `E:\1Codes\MineHub\models`、QQ 根目录 `D:\Tencent Files`）。优先在设置页修改；也可以用环境变量覆盖，环境变量优先级更高：

| 变量 | 作用 | 默认 |
|---|---|---|
| `MH_PROJECT` | 项目根目录 | `mh/config.py` 上两级 |
| `MH_MEDIA_ROOT` | 资料库根目录：library/review/cache/qq_thumbs/safe/Stash generated | `F:\MineHubData` |
| `MH_MODELS_ROOT` | 模型目录 | `E:\1Codes\MineHub\models` |
| `MH_QQ_BASE` | QQ 数据根目录，自动发现 `*\nt_qq\nt_data` | `D:\Tencent Files` |
| `MH_QQ_ACCOUNTS` | 显式指定账号 `nt_data` 路径，多个用系统路径分隔符 | 空 |

设置页保存到 `data/settings.json`，该文件已被 `.gitignore` 排除。Stash 的实际配置 `tools\stash\config.yml` 含有 JWT/session 密钥，也已被 `.gitignore` 排除；模板见 `tools\stash\config.example.yml`。MineHub 生成的 Stash 配置会在桌面启动时按当前设置刷新。

## 常用命令

```bat
cd /d E:\1Codes\MineHub
set PYTHONPATH=.
.venv\Scripts\python.exe -m mh.cli status

:: 断点续跑（全部阶段幂等）
.venv\Scripts\python.exe -m mh.pipeline

:: 日常增量复扫：新原图 + 新缩略图，可随时手动执行
.venv\Scripts\python.exe -m mh.cli rescan --dry-run
.venv\Scripts\python.exe -m mh.cli rescan

:: 只跑缩略图增量
.venv\Scripts\python.exe -m mh.cli thumb-audit incremental

:: 单阶段
.venv\Scripts\python.exe -m mh.cli stage2 a --slots 4 --workers 4
.venv\Scripts\python.exe -m mh.cli stage2 b
.venv\Scripts\python.exe -m mh.cli stage2 finalize
.venv\Scripts\python.exe -m mh.cli move --dry-run
.venv\Scripts\python.exe -m mh.cli move --rollback --limit 100
.venv\Scripts\python.exe -m mh.cli baseline --limit 500

:: 把已移动 NSFW 对应的 QQ 缩略图也迁出（可重复执行）
.venv\Scripts\python.exe -m mh.cli thumbs --dry-run
.venv\Scripts\python.exe -m mh.cli thumbs

:: MineHub 托盘（隐藏启动 Stash 9998 + 网关 9999）
.venv\Scripts\pythonw.exe -m mh.desktop

:: 后台维护 Stash 扫描/打标（内部端口 9998）
.venv\Scripts\python.exe -m mh.cli stash --restart --scan --tag

:: QQ 缩略图补漏（可重复执行，后台）
.venv\Scripts\python.exe -m mh.cli thumb-audit status
.venv\Scripts\python.exe -m mh.cli thumb-audit scan
.venv\Scripts\python.exe -m mh.cli thumb-audit siglip
.venv\Scripts\python.exe -m mh.cli thumb-audit vlm --slots 4 --workers 4
.venv\Scripts\python.exe -m mh.cli thumb-audit repair-vlm
.venv\Scripts\python.exe -m mh.cli thumb-audit move

:: kept 原图第二轮复核
.venv\Scripts\python.exe -m mh.cli reaudit select
.venv\Scripts\python.exe -m mh.cli reaudit run --model huihui

:: 相似索引维护；日常查询走 MineHub 9999 内的页签
.venv\Scripts\python.exe -m mh.cli index build --kind all --model siglip2 --device cuda
.venv\Scripts\python.exe -m mh.cli index status --model siglip2
.venv\Scripts\python.exe -m mh.cli index refresh --model siglip2
.venv\Scripts\python.exe -m mh.cli index search --model siglip2 --kind image --id 123 --top 20
.venv\Scripts\python.exe -m mh.cli index search --model siglip2 --text "蓝发 动漫少女 海边" --top 20
.venv\Scripts\python.exe -m mh.cli index serve --port 8765 --model siglip2 --device cuda

:: 旧 NSFW SigLIP 索引仍可用（不删）
.venv\Scripts\python.exe -m mh.cli index status --model nsfw

:: 人脸聚类（页签与 CLI 共用 data\faces.sqlite；不要同时运行两个扫描）
.venv\Scripts\python.exe -m mh.cli faces status
.venv\Scripts\python.exe -m mh.cli faces scan --limit 200
.venv\Scripts\python.exe -m mh.cli faces scan
.venv\Scripts\python.exe -m mh.cli faces cluster --threshold 0.5 --min-images 3
.venv\Scripts\python.exe -m mh.cli faces apply --min-images 3 --prefix 人物
```

## 相似图片 / 文本搜图

正常使用不需要单独启动 8765。启动托盘或 `mh.gateway` 后，打开 `http://127.0.0.1:9999`，点击顶部「搜索」进入独立页面 `/mh`（与视频、图片一样是普通页面；「搜索」与原生导航之间使用 SPA 路由切换，不再整页刷新）：

- 输入中文或英文描述做文本搜图（原版 `google/siglip2-base-patch16-256`，运行在 CUDA）；多个关键词用 `； ; ， , 、 。 . \ |` 或换行分隔，再选择「全部命中 / 任一命中」；
- `特征搜索` 同时使用 SigLIP2 画面语义和文件名/路径/标签/ID 关键词：语义结果按相似度排序，关键词命中会加分且不会因低于语义阈值被丢掉；
- `正则` 不再是独立模式，而是名称/特征上的开关：名称+正则在标题/文件名中匹配；特征+正则把输入同时当作正则关键词，并从表达式中提取可读词继续做语义匹配；支持 `不区分大小写`、多正则全部/任一命中；
- 正则开关带模板：GIF、静态图、视频、`.null`、QQ 哈希名、电脑相关、二次元、QQ 标签，点击即填入并立即搜索；
- 相似度滑杆带预设：文本 `0.030 / 0.055 / 0.080 / 0.120 / 0.180`，图片 `0.650 / 0.750 / 0.820 / 0.900 / 0.950`，也可以继续手动拖动；
- 可限定范围：全部 / 仅图片 / 仅场景；文本搜索默认 24 条，相似图搜索默认 48 条，可点 `24 / 48 / 100` 预设，或手动输入 1–100；
- 相似图搜索如果默认相似度没有结果，会自动降低一档重试（例如 `0.820 → 0.750`），状态栏标注「已自动降档」；
- 语义星图把 9,416 条 768 维向量投影成二维散点：颜色按成人/性感/二次元/截图/日常分组，滚轮缩放、拖拽平移，悬停显示缩略图和标签，点击打开 Stash 详情；输入描述可高亮 Top 100 语义相近结果，高亮后只有高亮点可悬停/点击；
- 搜索结果可勾选多个条目，再选择「放入回收站」或「直接删除文件」；回收站使用系统回收站，直接删除会永久删除库中的原文件；
- 卡片左上角勾选框显示明确的蓝底勾选状态；图片卡片右上角是「找相似」SVG 按钮，点击直接按该图搜相似；悬停卡片出现放大镜，图片的放大镜打开 Stash 原生灯箱（左右切换、缩放和 Stash 工具栏），场景的放大镜打开原生场景页面；点击图片边缘或名称进入 MineHub 详情页；
- 图片/场景详情页点击「找相似」，会跳转到 `/mh?stash_id=<id>&kind=<image|scene>`，直接查同一索引的 Top-K；相似页顶部显示源图原图、Top 语义标签和关键词；
- Stash 原生 `图片` / `视频` 页搜索框旁有「名称 / 特征」模式按钮和 `.* 正则` 开关；输入时不会搜索，只有按 Enter 才执行，每批返回 100 条；特征模式另有「相似度 ≥」下拉筛选（不限 / 0.030 / 0.055 / 0.080 / 0.120 / 0.180），默认 0.055；
- 原生结果列表滚到接近底部时会自动按 `offset` 追加下一批并去重，不设 100 条总数上限；状态栏显示「已加载 N 项 · 向下滑动加载更多」，全部取完后显示「已全部加载 N 项」；
- 特征模式多关键词用 `； ; ， , 、 。 . \ |` 或换行分隔，按「全部命中」组合语义和关键词；关键词命中会加分，但不会因为语义分低被丢弃；
- 搜索结果直接注入原生 `ImageList` / `SceneList`，不跳转页面、不另建结果面板；原生格状、预览墙、缩放、悬停放大镜/原生灯箱和 `1-N of N` 计数都直接复用；结果激活时隐藏不适用于相似度排序的原生排序与每页数量控件；点「返回原生列表」或清空搜索框恢复原生结果；
- 页面切换使用 SPA 路由，不再触发整页 reload；网格标题限制为单行省略，分页切换不会改变卡片高度；
- 点击卡片上的标签数按钮会打开 MineHub 特征面板：显示该图 Top5 语义标签（含余弦分）和全部 Stash 关键词/标签。

特征搜索使用 SigLIP2 图文语义向量 + 索引快照中的文件名/路径/标签：语义结果按余弦相似度排序，关键词命中会额外加 `0.14 × 命中词数`；关键词候选即使低于语义阈值也会保留。打开正则开关后，同一套匹配改为正则表达式；名称模式只看标题/文件名，特征模式还看路径、标签和 ID，并从正则中提取可读词做语义召回。Stash 标签变化后需要 `mh.cli index refresh --model siglip2` 更新元数据（不重算向量）。

Stash 原生搜索框本身把 `q` 交给后端，对图片 `title`、`details`、文件路径（目录 + 文件名）和文件指纹做字面匹配；MineHub 将这个输入框替换为 Enter 触发的独立输入，避免边打字边搜索。模式按钮的行为是：

- `名称`：只匹配标题和文件名；
- `特征`：SigLIP2 画面含义 + 文件名、路径、标签和 Stash ID 的关键词匹配；
- `正则`：上述字段的正则表达式匹配。

每张图的 Top5 语义标签不是额外安装的模型：网关用同一个 SigLIP2 文本塔编码 `mh/semantic.py` 中的 72 个中英概念，再和图片向量做余弦相似度，取前 5 个。

Qwen3-VL-Embedding 特征搜索的查询文本会自动加官方任务指令前缀 `Instruct: Retrieve images that match the description.` + 换行 + `Query: `（图像嵌入和标签嵌入不加）。默认索引仍是 SigLIP2；启用 Qwen 索引需 `--model qwen3vl` 并设置 `MH_INDEX_MODEL=qwen3vl`。

Blue-Eye（可选，DINOv3 ViT-L/16 三类分类器）已下载到 `models/blue-eye`（1.21 GB）；评分 = `p(suggestive)+p(explicit)`，评测脚本 `tools/blueeye_eval.py`。100 样本实测 5.4 s（0.054 s/图，约 18.5 图/秒），与 Huihui 标签 AUC 0.966；注意其 safe 类包含日常泳装/健身，泳装/擦边场景需要额外补充规则。全库三分类可用 `tools/blueeye_eval.py --folder F:/MineHubData/library`；`tools/blueeye_safe_split.py` 会把 `label=safe` 的图片移到 `F:\MineHubData\safe\<分类>\<月份>\`，生成带概率的复核清单，并从 Stash、语义索引和人脸库移除对应条目（默认 dry-run，确认后加 `--apply`）。

新增接口还包括 `/mh/api/pm/library`（QQ 选中项按分类/月移入 library）、`/mh/api/nine/list` 与 `/mh/api/nine/scan`（九图判定，返回 `mode=concurrent_single`、`slots=4` 和每格 `keep/level/reason`）；`/mh/api/dupes/groups` 在 `scope=qq` 时支持 `only_groups`，`limit=0` 返回全部群聊重复组。底层 API 统一为同源 `/mh/api/search`（`mode` 为 `semantic`、`hybrid`、`literal` 或 `regex`，可带 `regex`、`kind`、`match`、`ignore_case`、`fields`、`top`、`offset`；`hybrid + regex` 表示特征模式下的正则匹配）、`/mh/api/status`、`/mh/api/reload`、`/mh/api/media/info`（返回图片帧数，用于单帧 GIF 标注）、`/mh/api/media/features?kind=image&id=42`（Top5 语义标签 + 全部关键词 + `image_url` 原图地址）、`/mh/api/semantic/map`（二维语义投影）、`/mh/api/library/delete`（批量回收/永久删除库文件）。`top` 每次最多 100，`offset` 用于继续翻页；原生列表即按每批 100 自动追加。`fields` 可取 `title`、`path`、`basename`、`tags`、`id`，用于名称/特征/正则的字段范围。索引数据：`data\vectors_siglip2.sqlite` + `data\embeddings_siglip2.npy`；旧 `nsfw-siglip2` 索引保留在 `data\vectors.sqlite` + `data\embeddings.npy`。SigLIP2 原版双塔模型在 `F:\MineHubData\models\siglip2-base-patch16-256`（`model.safetensors` 约 1.40 GB，另有 tokenizer 约 34 MB），由索引构建脚本用 `huggingface-hub` 下载，不是系统级安装。只读 Stash 缩略图，不复制媒体文件。`mh.cli index serve --port 8765` 仅保留为脱离 Stash 的调试入口，日常不使用。

可选多模态模型 **Qwen3-VL-Embedding-2B** 已接入（2B、2048 维、30+ 语言、最后 token 池化），模型在 `F:\MineHubData\models\qwen3-vl-embedding-2b`（约 4.2 GB；从 ModelScope 或 hf-mirror 下载）。它使用独立的 `data\vectors_qwen3vl.sqlite` + `data\embeddings_qwen3vl.npy`，不会覆盖 SigLIP2 索引：

```bat
.venv\Scripts\python.exe -m mh.cli index build --model qwen3vl --device cuda --kind images
.venv\Scripts\python.exe -m mh.cli index search --model qwen3vl --device cuda --text "电脑屏幕" --top 5
```

要让网关切换到该索引，设置环境变量 `MH_INDEX_MODEL=qwen3vl` 后重启网关；默认仍是 `siglip2`。Qwen3-VL 的中英跨语言相似度明显更强，但 2B 模型在 5060 Ti 上实测约 **0.3 张/秒**（384px 输入），当前 9,332 张全量重建预计需要 **7–9 小时**；重建完成后才能切换，旧 Qwen 索引为空，SigLIP2 索引不受影响。

## 删除行为

- Stash 自带删除框里的「删除文件」才会删除原始媒体文件；不勾选时只移除 Stash 记录。
- 「删除已生成的附加文件」指 Stash 生成的缩略图、预览、sprite、phash 等缓存，不是原始媒体；取消勾选会保留这些生成文件。
- MineHub 搜索结果的「放入回收站」：把原文件移入 Windows 回收站，同时移除 Stash 记录和生成预览，可从回收站恢复。
- MineHub 搜索结果的「直接删除文件」：永久删除 `library`/`review` 中的原始文件，并移除 Stash 记录和生成预览；不可恢复。
- 两个批量操作只接受 MineHub 库或 review 目录内的路径，拒绝目录外文件。

## 重复检测与阈值（对照 Krokiet/czkawka）

Krokiet 的“重复文件 / 相似图片 / 相似视频”和 MineHub 原来的“找相似”不是同一类算法：

| 能力 | Krokiet / czkawka | MineHub 当前 |
|---|---|---|
| 完全相同文件 | 文件大小预筛 + 完整内容哈希（Blake3/XXH3/CRC32） | 直接复用账本已经算好的 MD5；865 组 / 1,964 个文件，不重复读盘 |
| 相似图片 | 256 位感知哈希 + 汉明距离 + BK-tree，阈值可调（默认 16 尺寸/mean/10） | 已新增 256 位 aHash/dHash/pHash + BK-tree；默认 pHash、阈值 10（0–40 可调）；严格全连接，改阈值只重新分组 |
| 相似视频 | 场景窗口签名（similario），可选音频 Chromaprint；阈值/窗口比例可调 | 指定文件夹扫描视频 5 帧 pHash，阈值 0–40；Stash 场景 pHash 距离可调；不做音频指纹 |
| 语义找相似 | 不作为重复检测 | SigLIP2 余弦相似度，已加最低分过滤；文本与图片使用不同分数区间 |

**为什么 Krokiet 会误报**：Krokiet 的阈值是感知哈希的汉明距离，数值越大越宽松；MineHub 原来的“找相似”是 SigLIP2 语义 Top-K，永远返回结果，分数低也会出现。现在两者分开：

- 感知哈希页签：`重复检测` → `相似图片`；阈值从默认 `10` 往下调（`5`、`2`、`0` 更严格），`0` 只接受哈希完全相同。
- 搜索页签 / 详情页「找相似」下的“相似度 ≥”滑杆：文本默认 `0.055`，图片默认 `0.82`，可调到 `0.95+` 去掉只是“主题相近”的图；特征模式的关键词命中不受该阈值影响。
- 场景页签：`重复检测` → `Stash 场景（视频 pHash）`，使用 Stash `findDuplicateScenes(distance)`，阈值可调。

扫描范围：`MineHub 库` 读取 13,642 张库图片；`QQ 图片缓存` 优先读取 QQ `Pic/**/Ori` 对应的 Thumb，缺失时退回原图；`指定文件夹` 递归扫描任意目录中的图片和视频，视频抽 5 帧并按最差帧 pHash 距离比较。三者都缓存到 `data\dupes.sqlite`，第二次只处理新增/变化文件。相似图片默认 pHash，也可切 dHash/aHash；分组为严格全连接，组内任意两张都必须低于阈值，避免只靠代表图把不同内容串成一组。

API：`/mh/api/dupes/status`、`/dupes/scan`、`/dupes/groups`、`/dupes/scenes`、`/dupes/exact`。QQ 查重弹窗可勾选「仅群聊内容」并按组选择重复项，再移入回收站或按分类/月份移到 `library`；库/文件夹/场景查重只展示，不自动移动或删除。

## 人脸聚类与演员

`/mh` →「人脸聚类」页签：

- 「扫描人脸」优先增量处理新增/变化的 Stash 图片；勾选「强制重扫」会重新处理全部图片。首次扫描会自动下载 `buffalo_l` 模型到 `F:\MineHubData\models\insightface\buffalo_l`；
- 检测使用 RetinaFace `det_10g.onnx`，对齐后由 ArcFace `w600k_r50.onnx` 生成 512 维归一化特征；优先 CUDA，失败时回退 CPU；
- 默认相似度阈值 `0.60`、最少图片数 `3`；调整后点「重新聚类」只重算分组，不重新检测人脸；
- 聚类卡片显示代表脸、图片数、人脸数和演员状态；「查看图片」展开该聚类的成员图片；
- 「写入演员」会为达到最少图片数的聚类创建演员（名前缀默认「人物」，如 `人物 001`），上传代表脸作为演员图片，并用 `bulkImageUpdate` 把同组图片写入演员；
- 再次聚类时会按人脸重叠保留已写入的演员映射，避免重复创建；新扫描到的图片在下一次「写入演员」时补入已有演员；
- 状态保存在 `data\faces.sqlite`，人脸裁剪在 `F:\MineHubData\cache\faces`；媒体文件不会被移动或删除。

API：`/mh/api/faces/status`、`/faces/scan`、`/faces/cluster`、`/faces/clusters`、`/faces/cluster?id=...`、`/faces/thumb?id=...`、`/faces/apply`。

## MineHub 原生集成（插件）

`tools\stash\plugins\minehub\custom_minehub.js` 通过本地插件注入到 Stash，不打开独立程序窗口，也不使用 iframe：

- 顶部导航新增「搜索」（MineHub 是项目名，不是功能名），打开独立 `/mh` 页面，内含搜索 / QQ 缓存 / 人脸聚类 / 重复检测 / 设置页签；原生页面与 `/mh` 之间通过 SPA 路由切换，不再整页刷新；
- 搜索页带特征搜索、正则开关、范围、多关键词关系、相似度预设、结果数 `24/48/100` 预设和 1–100 手动输入；调整后自动重查；
- 语义星图页带二维散点、分类图例、缩放/平移、悬停缩略图和 Top100 查询高亮；高亮后只允许选中高亮点；
- 打开正则开关后提供可点击模板，点击后填入表达式并立即执行；文件名、路径、标签和 ID 都可匹配；
- 搜索结果卡片左上角有明确的勾选状态，图片卡片右上角有「找相似」SVG 按钮，点击直接进入该图的相似搜索；悬停出现预览按钮，图片和场景进入统一的媒体浮层（视频可播放，← → 切换，Esc 关闭），点击卡片其他区域进入详情页；
- Stash 原生 `图片` / `视频` 页搜索框旁提供「名称 / 特征」模式按钮和 `.* 正则` 开关；输入不发请求，按 Enter 才搜索；特征模式可调「相似度 ≥」筛选；每批 100 条，滚动接近底部自动追加并去重；结果直接注入原生 `ImageList` / `SceneList`，格状和预览墙都复用原生组件、缩放和计数，不跳转、不另建面板；结果激活时隐藏原生排序/每页数量控件；点「返回原生列表」或清空搜索框恢复原生结果；原生图片卡片也使用左上勾选和右上「找相似」按钮；
- 原生卡片标题固定单行省略；分页/导航走 SPA，不再用 `location.replace` 整页重载，避免网格重新挂载抖动；
- 卡片标签数按钮改为 MineHub 特征面板，显示 Top5 语义标签和全部关键词；
- `/images`、`/scenes` 首次访问自动使用 `sortby=filesize&sortdir=desc&perPage=200&disp=2`；用户手动选择的时间/名称排序和每页数量会保留；
- 图片/场景详情页工具栏显示原生「找相似」按钮，跳转到 `/mh?stash_id=...`；
- 图片文件信息面板若检测到单帧 GIF，会显示「单帧 GIF，不是查看器故障」；
- QQ 缓存页签扫描 Pic/Video 或 NSFW 库，按类型、Ori/Thumb、大小、文件名、QQ 好友/群、MineHub 分类/等级/标签筛选；支持照片墙、预览、系统打开、移动和移入回收站；可切换两个 QQ 账号并重建归属索引；
- 插件通过同源 `/mh/api/*` 调用本地服务，不再使用 `ui.csp.connect-src` 放行 8765；
- 人脸聚类页签显示扫描进度、模型/设备、聚类总数和已写入演员数；支持增量/强制扫描、调整相似度阈值后重新聚类、最少图片数筛选、查看每个聚类的成员图片，以及「写入演员」；
- 人脸聚类只处理 Stash 图片（GIF 取首帧），不会移动或删除媒体文件；写入演员只调用 Stash GraphQL，不改原始文件。

托盘入口为 `pythonw -m mh.desktop`：隐藏启动 Stash（内部 9998）和网关（公开 9999），用中文 pystray 菜单替代 Stash 自带英文托盘，并在启动后关闭 Stash 的 `SystrayClass` 窗口。托盘菜单顶部为「搜索」「打开 MineHub」，下面直接打开视频、图片、集合、标记、图库、演员、工作室、标签；关闭菜单中的「退出 MineHub」会结束本程序启动的网关和 Stash。

如果 Stash 配置或插件目录被重置，重新安装：

```bat
.venv\Scripts\python.exe -m mh.cli stash --install-js
```

QQ 管理 API（`/pm/config`、`/pm/scan`、`/pm/query`、`/pm/thumb`、`/pm/move`、`/pm/recycle`、`/pm/open`、`/pm/index`）与搜索 API 都由网关在 9999 同源提供。QQ 归属索引保存在 `data\qq\index_<账号>.sqlite`，密钥用 Windows DPAPI 保存为 `data\qq\key_<账号>.bin`；首次会尝试迁移 PictureManager 的旧索引与密钥。主账号已重建为 310 个聊天 / 78,465 条媒体；第二账号未建索引。需要 `sqlcipher3`、`send2trash`、`aiohttp`、`pystray`、`pywin32`（已写入 `requirements.txt`）。

## 设计要点

- **断点续跑**：所有状态在 `data\minehub.sqlite`；任何阶段重跑只处理未完成行。
- **筛选口径**：库面向漂亮/有吸引力的女性图像，即使完全着装也可作为 suggestive 保留；血腥、仅男性、男性化或缺乏吸引力的女性、纯文字/UI、仅非人主体、仅暴露男性均排除，判断不清时进入 review。
- **先筛后标**：SigLIP2 单图 38ms、批量 82 张/秒、显存 5.4G；SigLIP 负责全量粗筛，Anime/Hentai 与仅缩略图记录也必须经 VLM 复核，不再按标签硬编码为 safe。
- **A/B 仲裁**：A（NSFW 专用）explicit 召回更高；B（Huihui abliterated）对 suggestive 更稳。A 判 explicit、置信度 <0.85、或 category 为 review/other 时由 B 复核；两者 explicit 不一致或 real/anime 冲突时进入 `review` 目录。
- **强约束 JSON**：llama.cpp `response_format.json_schema` + `--jinja`，两个模型 30/30 一次通过；缩略图 VLM 遇到截断 JSON 会自动用 640 tokens 重试，`thumb-audit repair-vlm` 可从已截断响应恢复等级。
- **去重**：移动时算 MD5，重复文件保留在 QQ 缓存原地、标记 `duplicate` 并记录 `dup_of`。
- **崩溃安全的移动**：先写 `move_state='moving'` + 目标路径作为意图日志；跨盘时先复制到同目录 `.mhpart`、fsync、校验大小，再原子 `os.replace` 到目标，最后删除源文件。启动时 `recover_moving()` 会自动完成或回退被中断的移动，不会出现「源已删、账本没记」。
- **MD5 基线**：`mh.cli baseline` 为留在 QQ 的普通文件补算 MD5，后续移动/去重可直接复用，不必重复读源文件。
- **缩略图补漏**：`thumb_audit.py` 按 QQ 文件名 stem（含 `_0/_720` 归一化）+ 内容 MD5 双索引匹配账本；对未匹配缩略图跑 SigLIP，视频/GIF/候选图再用 VLM 按 stem 分组精判，NSFW 迁到 `F:\MineHubData\qq_thumbs\<账号>\<Pic|Video>\<YYYY-MM>\Thumb\`。可重复执行，用来清理 QQ 重开浏览后重新生成的预览。
- **第二轮复核**：`reaudit.py` 用模型 B 复核 kept 中视频、`needs_review`、`sexy/adult/review`、未跑 VLM 的 anime 以及 SigLIP 高风险行；命中后回写主账本并交给同一套原子移动。
- **相似检索**：旧索引复用 NSFW SigLIP 视觉塔；新索引用原版 `google/siglip2-base-patch16-256` 图像/文本双塔，768 维归一化向量，SQLite + `embeddings.npy`，numpy 余弦 Top-K；不引入 FAISS/Qdrant。网关在 CUDA 上加载模型，MineHub 页签支持文本搜图和详情页「找相似」。多关键词特征搜索会分别编码后按“全部命中”（逐项取最低分）或“任一命中”（取最高分）合并，再与文件名/路径/标签关键词候选合并，关键词命中 `+0.14 × 命中词数`；正则开关作用于同一套候选，读取索引快照中的文件名、路径、Stash 标签和 ID，并从表达式提取可读词继续语义召回，索引 URL 保存为根相对路径，避免泄漏 9998 内部端口。标签变化后运行 `index refresh` 更新元数据，不重算向量。
- **语义标签与星图**：`mh/semantic.py` 用 72 个中英概念做零样本标签，复用同一 SigLIP2 文本塔编码，按余弦取 Top5；星图对全部 768 维图像向量做 PCA（协方差特征分解）投影到二维，按标签分组着色，结果缓存在网关进程内。悬停才加载单张缩略图，打开星图本身不会批量加载媒体。
- **同源网关**：`mh.gateway` 在公开 9999 上提供 `/mh/api/*` 并把其余 HTTP/WebSocket 反向代理到内部 Stash 9998；Host 头透传，媒体 URL 不会泄漏内部端口。插件只使用同源相对路径，不依赖 CSP 放行跨端口。pystray 中文托盘替代 Stash 自带托盘，并通过关闭 `SystrayClass` 窗口抑制重复图标。
- **MineHub 原生面板**：插件用普通 DOM 在 Stash 页面内渲染，顶部导航和详情页按钮沿用 Stash 的 Bootstrap 控件与主题色。QQ 扫描结果按 MD5 合并归属索引，并通过账本 `src_path/target_path` 回查 MineHub 标签；缩略图按路径+mtime+尺寸缓存到 `F:\MineHubData\cache\pm_thumbs`，视频优先复用 QQ Thumb，缺失时用 ffmpeg 抽帧，生成并发限制为 6。移动/删除只接受已知 QQ 媒体根目录或库目录内的文件，并同步从内存列表移除。
- **人脸聚类**：`mh.faces` 直接运行 InsightFace 的 ONNX 模型，不引入 insightface 包；按图片增量扫描，保留每张图片的 mtime/size 作为变更指纹。聚类对 512 维归一化特征按检测分从高到低做 leader/centroid 匹配，默认余弦阈值 0.60、最少 3 张图；不用单链连通避免传递性把不同人物串成超大簇。阈值只影响分组，不重算特征。写入演员前按人脸所在图片的重叠率继承旧聚类的 `performer_id`，因此重新聚类不会重复创建演员。
- **增量复扫**：`mh.cli rescan` 先枚举 QQ 原图（新文件才进 Stage 1），再复用 `thumb_audit` 的状态机处理新增/变化的缩略图；每阶段结束后重新读取 pending 计数，避免新文件停在 `stage2_pending`。已完成的 safe/moved 状态不会重跑，`--dry-run` 只预演缩略图移动。单轮无新内容约 2 分钟。
- **扩展名/动画盲区**：QQ 可把真实 JPEG/PNG/GIF 写成 `.null`；现在作为图片扫描，迁移时按实际格式恢复后缀。GIF/`.null` 缩略图一律强制过 VLM，不再只靠 SigLIP 的首帧分数。定向补漏结果在 `data\logs\target_audit_20261117.json`。
- **可回滚**：`data\moves.csv` 记录每条 src→dst；`mh.cli move --rollback` 原路搬回。
- **低优先级**：进程设为 BELOW_NORMAL，并调用 `SetThreadExecutionState` 防止系统睡眠。
- **Stash 打标**：按标签聚合后 `bulkImageUpdate/bulkSceneUpdate`（mode=ADD），不是逐文件调用。

## 容量

- 模型约 20.6 GB（含原版 SigLIP2、Qwen3-VL-Embedding-2B 与人脸模型）；F 盘剩余空间随库和预览增减变化，以实际磁盘为准。
- Stash 数据库/缩略图在 `E:\1Codes\MineHub\data\stash` 与 `F:\MineHubData\stash`；人脸数据库 `data\faces.sqlite` 约 35 MB，人脸裁剪 `F:\MineHubData\cache\faces` 约 67 MB。

## 已知限制

- 两模型都会漏「紧身/白丝」类擦边（评测样本 #23），此类依赖 `review` 人工复核。
- VLM 会把部分动漫/插画误判 explicit，因此 anime 结果也会进入 `review`，不会直接当作 safe。
- 移动的是 QQ 缓存原文件，NSFW 缩略图也会迁出；查看很早的聊天记录时，QQ 若发现缓存缺失可能从服务器重新下载，重新出现的文件需要再次扫描/打标。
- 设置页切换资料库或模型目录不会自动搬移文件；现有媒体和模型需要手动迁移到新目录，Stash 生成预览会在新 generated 目录下按需重建。
- 相似索引与查询必须使用同一模型和同一设备/精度重建或查询；重建索引后重启网关，否则内存中的向量可能仍是旧版本。
- Qwen3-VL-Embedding-2B 是可选索引：需单独构建 `vectors_qwen3vl.sqlite` 并设置 `MH_INDEX_MODEL=qwen3vl`；当前运行中的网关仍使用 SigLIP2，二者不能混用向量。
- 正则开关读取 `vectors_siglip2.sqlite` 中的文件名、路径、标签快照；Stash 标签或文件路径变化后，先运行 `mh.cli index refresh --model siglip2` 再搜索。
- MineHub 搜索结果的批量删除会移除 Stash 记录并隐藏当前结果，但语义索引不会即时重建；需要重建相似索引后，已删除条目才会从索引中彻底消失。
- 图片放大镜调用 Stash 原生灯箱（`PluginApi.hooks.useLightbox`），支持左右切换、缩放和 Stash 工具栏；场景放大镜仍打开 Stash 原生场景页面。
- `mh.cli baseline` 需要完整读一遍留在 QQ 的普通文件，首次运行耗时取决于磁盘；之后只处理新增行。
- QQ 好友/群归属只在「QQ 缓存」面板内筛选和显示，不会为每个聊天创建 Stash 标签；Stash 原生标签仍只表示 MineHub 分类/等级/内容标签。
- QQ 面板的「更新归属索引」需要 QQ 已登录（或已有可用的 DPAPI 密钥）；第二账号首次建立索引前，归属列可能为空。
- 人脸聚类目前只处理 Stash 图片，不处理视频场景；动漫/插画可能产生误检，阈值过高会拆散同一人，过低会把相似脸合并，写入演员前建议先查看聚类成员。
- 人脸演员默认使用「人物 001」这类占位名，需要你在 Stash 演员页改成真实姓名；删除演员不会自动删除 `faces.sqlite` 中的聚类记录。
- 首次扫描会下载约 276 MB 的 buffalo_l 模型包（解压后 det_10g + w600k_r50 约 183 MB）；扫描是 CPU 解码 + GPU 推理，耗时取决于图片数量，可在页签内查看进度。
- 当前 13,566 张图片中有 3 张 Stash 记录对应的原文件已缺失，扫描时记为 error，不会影响其他图片；需要先在 Stash 清理或重新扫描这些记录。
