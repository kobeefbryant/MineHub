# MineHub — 本地媒体智能检索与 Stash 原生集成

MineHub 是围绕 Stash 的本地媒体智能层，目标是把现代媒体库能力带进本地：以图搜图、文本语义搜图、重复/相似检测、人脸聚类、原生预览与批量管理。QQ 聊天缓存导入和 NSFW 自动归档只是一个可选的数据入口与真实规模验证场景，不是项目主线；不导入 QQ 也可以直接管理任意 Stash 库。

## 核心能力（已实现）

- **以图搜图**：SigLIP2 图像向量 + 余弦 Top-K，图片/场景详情页「找相似」直接跳转；
- **文本语义搜图**：中英文描述搜图，支持多关键词、全部/任一命中、图片/场景范围筛选；
- **正则/标签检索**：按文件名、路径、Stash 标签、ID 匹配，带可点击模板；
- **重复/相似检测**：256 位 aHash/dHash/pHash、BK-tree、严格全连接、阈值可调；支持任意文件夹图片+视频（视频 5 帧 pHash）和 Stash 场景 pHash；
- **Stash 原生体验**：独立 `/mh` 页面、原生预览、默认按文件大小排序、中文托盘、同源 9999 入口；
- **可选 QQ/NSFW 流水线**：QQ 缓存扫描、SigLIP2/Qwen3-VL 打标、NSFW 归档；默认只移动 NSFW，普通文件留在原路径。

## 路线图

- **人脸聚类**：InsightFace 特征 + 离线聚类，按人物浏览并写回标签/演员；当前只保留入口，尚未运行；
- **OCR**：图内文字检索；
- **视频智能**：场景/关键帧语义检索与时间轴标记。

## 可选数据入口：QQ 缓存 / NSFW 归档现状（2026-11-17 10:55）

| 项目 | 状态 |
|---|---|
| 环境 | Python 3.11.7 venv + torch 2.9.1+cu128（RTX 5060 Ti sm_120 已验证）+ onnxruntime-gpu + llama.cpp b12415 CUDA 13.5 |
| 模型 | SigLIP2 NSFW、google/siglip2-base-patch16-256、WD Eva02 tagger、Qwen3-VL-8B-NSFW-Caption Q5_K_M、Huihui-Qwen3-VL-8B-abliterated Q5_K_M（均在 `F:\MineHubData\models`，16.2 GB） |
| 小样本评测 | 完成，见 `reports/eval_report.md`（30 图 + 5 视频） |
| 数据规模 | 89,634 条：910 个视频 + 88,724 张图片（含仅存在于 Thumb 的唯一图片与 .null 原图） |
| Stage 1 | 完成：88,724 张图片全部 SigLIP2 预筛（910 个视频不经过 Stage 1） |
| Stage 2 A | 完成：49,697 条（全部视频 + 图片） |
| Stage 2 B | 完成：6,641 条（仅仲裁 explicit / 低置信度 / review） |
| 复核 | 2,947/2,964 条 SigLIP-only explicit 用 VLM 复检；5,542 张安全二次元已搬回 QQ |
| Stage 3 | 已移动 16,439 个 NSFW 文件，73,193 个普通文件留在 QQ 原地 |
| Stash | 增量扫描完成；累计 **14,139** 条 tagged；当前 492 scene + **13,568** image |
| 缩略图审计 | 132,616 张 QQ Thumb 已扫描；已迁出 **17,982** 张 NSFW，94,472 张 SigLIP safe + 20,010 张 VLM safe；62 张 1 字节占位 PNG 无法读图；无待处理项 |
| 增量复扫 | `mh.cli rescan` 已实测：2026-11-17 一轮耗时 122 s，迁出 2 个新 NSFW 原图 + 591 张残留 NSFW 缩略图；已修复 Stage 1 后计数未刷新导致新文件跳过 Stage 2 的问题，补入 24 个 `.null` 原图（VLM 全部判 safe，0 移动） |
| 定向补漏 | 70 个 .null/点名文件 VLM：18 个 NSFW；490 张 GIF/.null 缩略图强制 VLM：11 个 NSFW、9 个原 GIF；257 个仅 SigLIP 的 kept GIF 逐帧 VLM：8 个 NSFW；合计新增 28 个原图 + 32 张缩略图 |
| 第二轮复核 | 7,938 条已检查，622 条 flagged，0 错误；501 条源文件已移动、1 条源文件缺失，已归位状态 |
| 视频时间轴 | **492/492 个场景均有 preview+sprite+vtt**（1,476 个文件 / 1.5 GB）；scene 50 已单独转码 H.264 修复，原文件备份在 `F:\MineHubData\backups\` |
| 相似搜索 | 双索引：旧 `nsfw-siglip2`（`vectors.sqlite` / `embeddings.npy`）+ 新 `google/siglip2-base-patch16-256`（`vectors_siglip2.sqlite` / `embeddings_siglip2.npy`）；**14,060 条**，0 错误，768 维；支持图搜、中英文文本搜图、多关键词和正则/标签搜索；Stash 图片/场景页的搜索框回车会转到 `/mh` 语义结果 |
| 访问入口 | 统一使用 `http://127.0.0.1:9999`；同源网关把 Stash 内部 `127.0.0.1:9998` 与 MineHub API `/mh/api/*` 合并在同一端口，不再需要单独打开 8765 |
| MineHub 原生集成 | 插件 `tools\stash\plugins\minehub`：顶部「MineHub」打开独立 `/mh` 页面，图片/场景列表默认按文件大小降序，详情页原生「找相似」按钮，以及搜索 / QQ 缓存 / 人脸聚类 / 重复检测 / 设置五个页签；搜索页带语义/正则模式、相似度预设、结果数预设和手动数量，支持多关键词、正则模板、勾选批量删除和 Stash 原生预览；单帧 GIF 会在文件信息里提示；中文托盘菜单可打开各库并退出 |
| QQ 缓存面板 | 在 Stash 内完成扫描、聊天归属筛选、MineHub 标签筛选、照片墙/预览、移动、回收站、切换目录和重建归属索引；普通文件仍留在 QQ，不进入 Stash 库 |
| 重复检测 | 相似图片页签实现 256 位 aHash/dHash/pHash + BK-tree，改为严格全连接分组，阈值 0–40 可调并缓存；新增指定文件夹递归扫描（图片+视频），视频按 5 帧 pHash 全帧距离比较；Stash 场景 pHash 距离可调（10 时 8 组/23 个场景）；完全相同文件复用账本 MD5（865 组/1,964 个） |
| 界面 | Stash 使用内置 `zh-CN`，品牌/标题替换为 MineHub，托盘菜单全中文；文件信息补译「文件大小」「制作日期」；备份在 `data\backups\config-20261116-192957.yml` 与 `stash-go-20261116-192957.sqlite` |

可选数据来源：`D:\Tencent Files\<QQ号>\nt_qq\nt_data\{Pic,Video}\**\Ori`（QQ 根目录可用 `MH_QQ_BASE` 覆盖）
目标库：`F:\MineHubData\library\{sexy,adult,anime,review}\YYYY-MM\`

**移动策略（2026-11-16 调整）**：只移动 NSFW 内容（`nsfw_level` 为 suggestive / explicit，含 hentai）；安全内容（daily/screenshot/sticker/普通 anime）保持在 QQ 原始路径不动，数据库中标记为 `move_state='kept'`。

## 目录

```
E:\1Codes\MineHub
├─ mh\                核心代码：检索 / 网关 / 库管理 / 可选 QQ 流水线
│  ├─ config.py       路径、Prompt、分类定义
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
│  ├─ manager.py      QQ 缓存面板后端：扫描/筛选/缩略图/移动/回收站
│  ├─ gateway.py      同源网关：9999 公开端口代理 Stash 9998 + /mh/api
│  ├─ dupes.py        图片/视频感知哈希重复检测：aHash/dHash/pHash、5 帧视频签名、严格全连接、阈值
│  ├─ desktop.py      中文托盘：隐藏启动 Stash/网关并抑制 Stash 自带托盘
│  ├─ qq\             QQNT 归属索引：密钥读取、消息库解密、MD5→聊天映射
│  ├─ siglip2_embed.py google SigLIP2 图文双塔 embedding
│  ├─ index.py        相似索引（SQLite + numpy，支持 nsfw / siglip2 双模型）
│  ├─ index_server.py 旧版独立 Top-K 查看页（仅调试；日常走网关）
│  ├─ rescan.py       手动增量复扫（新原图 + 新缩略图）
│  ├─ after_audit.py  等 VLM 跑完后自动迁移 / 复核 / 补标 / 重建索引
│  ├─ serve.py        llama-server 生命周期
│  ├─ vlm.py          OpenAI 兼容客户端（JSON Schema 强约束）
│  └─ frames.py       ffmpeg 均匀抽帧
├─ eval\              抽样与评测脚本
├─ data\              minehub.sqlite、日志、评测结果、移动审计 CSV
├─ reports\           eval_report.md
└─ tools\             llama.cpp、stash、下载脚本
   └─ stash\plugins\minehub\  Stash 原生插件：语义搜索 / 找相似 / 重复检测 / QQ 缓存面板
```

## 配置

默认路径针对本机布置（项目 `E:\1Codes\MineHub`、媒体库 `F:\MineHubData`、QQ 根目录 `D:\Tencent Files`）。迁移到其他机器时用环境变量覆盖，不需要改代码：

| 变量 | 作用 | 默认 |
|---|---|---|
| `MH_PROJECT` | 项目根目录 | `mh/config.py` 上两级 |
| `MH_MEDIA_ROOT` | 模型、库、预览、缓存根目录 | `F:\MineHubData` |
| `MH_QQ_BASE` | QQ 数据根目录，自动发现 `*\nt_qq\nt_data` | `D:\Tencent Files` |
| `MH_QQ_ACCOUNTS` | 显式指定账号 `nt_data` 路径，多个用系统路径分隔符 | 空 |

Stash 的实际配置 `tools\stash\config.yml` 含有 JWT/session 密钥，已被 `.gitignore` 排除；模板见 `tools\stash\config.example.yml`。

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
```

## 相似图片 / 文本搜图

正常使用不需要单独启动 8765。启动托盘或 `mh.gateway` 后，打开 `http://127.0.0.1:9999`，点击顶部「MineHub」进入独立页面 `/mh`（与短片、图片一样是普通页面，不再是全屏悬浮层）：

- 输入中文或英文描述做文本搜图（原版 `google/siglip2-base-patch16-256`，运行在 CUDA）；多个关键词用 `； ; ， , 、 |` 或换行分隔，再选择「全部命中 / 任一命中」；
- `语义搜索` 模式按画面含义匹配；`正则 / 关键词` 模式按文件名、路径、标签和 Stash ID 匹配，支持 `不区分大小写`、多正则全部/任一命中；
- 正则模式带模板：GIF、静态图、视频、`.null`、QQ 哈希名、电脑相关、二次元、QQ 标签，点击即填入并立即搜索；
- 相似度滑杆带预设：文本 `0.030 / 0.055 / 0.080 / 0.120 / 0.180`，图片 `0.650 / 0.750 / 0.820 / 0.900 / 0.950`，也可以继续手动拖动；正则模式不显示相似度；
- 可限定范围：全部 / 仅图片 / 仅场景；结果数默认 24，可点 `24 / 48 / 100` 预设，或手动输入 1–100；
- 搜索结果可勾选多个条目，再选择「放入回收站」或「直接删除文件」；回收站使用系统回收站，直接删除会永久删除库中的原文件；
- 卡片右上角勾选框会显示明确的蓝底勾选状态；悬停卡片出现放大镜，点击会打开 Stash 原生图片/场景页面预览；点击卡片本身进入 MineHub 详情页；
- 图片/场景详情页点击「找相似」，会跳转到 `/mh?stash_id=<id>&kind=<image|scene>`，直接查同一索引的 Top-K；
- Stash 原生 `图片` / `短片` 页的搜索框回车不再执行本地关键字筛选，而是转到 `/mh?q=...&kind=...` 的 MineHub 语义搜索。

搜索使用 SigLIP2 图文语义向量，不是标签精确匹配：结果可能画面里有电脑，但标签列表没有「电脑」；同样，带「电脑」标签也不保证一定排在前面。正则模式则是对索引快照中的文件名、路径、标签做真实文本匹配；Stash 标签变化后需要 `mh.cli index refresh --model siglip2` 更新元数据（不重算向量）。

底层 API 统一为同源 `/mh/api/search`（`mode` 为 `semantic` 或 `regex`，可带 `kind`、`match`、`ignore_case`）、`/mh/api/status`、`/mh/api/reload`、`/mh/api/media/info`（返回图片帧数，用于单帧 GIF 标注）、`/mh/api/library/delete`（批量回收/永久删除库文件）。索引数据：`data\vectors_siglip2.sqlite` + `data\embeddings_siglip2.npy`；旧 `nsfw-siglip2` 索引保留在 `data\vectors.sqlite` + `data\embeddings.npy`。只读 Stash 缩略图，不复制媒体文件。`mh.cli index serve --port 8765` 仅保留为脱离 Stash 的调试入口，日常不使用。

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
- 语义搜索页签：`搜索` / 详情页「找相似」下的“相似度 ≥”滑杆；文本默认 `0.055`，图片默认 `0.82`，可调到 `0.95+` 去掉只是“主题相近”的图。
- 场景页签：`重复检测` → `Stash 场景（视频 pHash）`，使用 Stash `findDuplicateScenes(distance)`，阈值可调。

扫描范围：`MineHub 库` 读取 13,642 张库图片；`QQ 图片缓存` 优先读取 QQ `Pic/**/Ori` 对应的 Thumb，缺失时退回原图；`指定文件夹` 递归扫描任意目录中的图片和视频，视频抽 5 帧并按最差帧 pHash 距离比较。三者都缓存到 `data\dupes.sqlite`，第二次只处理新增/变化文件。相似图片默认 pHash，也可切 dHash/aHash；分组为严格全连接，组内任意两张都必须低于阈值，避免只靠代表图把不同内容串成一组。

API：`/mh/api/dupes/status`、`/dupes/scan`、`/dupes/groups`、`/dupes/scenes`、`/dupes/exact`；只展示和打开，不自动移动或删除。

## MineHub 原生集成（插件）

`tools\stash\plugins\minehub\custom_minehub.js` 通过本地插件注入到 Stash，不打开独立程序窗口，也不使用 iframe：

- 顶部导航新增「MineHub」，打开独立 `/mh` 页面，内含搜索 / QQ 缓存 / 人脸聚类 / 重复检测 / 设置页签；
- 搜索页带语义/正则模式、范围、多关键词关系、相似度预设、结果数 `24/48/100` 预设和 1–100 手动输入；调整后自动重查；
- 正则模式提供可点击模板，点击后填入表达式并立即执行；文件名、路径、标签和 ID 都可匹配；
- 搜索结果卡片右上角有明确的勾选状态，悬停出现 Stash 原生预览入口（放大镜），点击进入原生图片/场景页面；
- Stash 原生 `图片` / `短片` 页的搜索框回车会转到 `/mh?q=...&kind=...`，使用 MineHub 语义搜索；
- `/images`、`/scenes` 首次访问自动使用 `sortby=filesize&sortdir=desc`；用户手动选择的时间/名称排序会保留；
- 图片/场景详情页工具栏显示原生「找相似」按钮，跳转到 `/mh?stash_id=...`；
- 图片文件信息面板若检测到单帧 GIF，会显示「单帧 GIF，不是查看器故障」；
- QQ 缓存页签扫描 Pic/Video 或 NSFW 库，按类型、Ori/Thumb、大小、文件名、QQ 好友/群、MineHub 分类/等级/标签筛选；支持照片墙、预览、系统打开、移动和移入回收站；可切换两个 QQ 账号并重建归属索引；
- 插件通过同源 `/mh/api/*` 调用本地服务，不再使用 `ui.csp.connect-src` 放行 8765；
- 人脸聚类和图像 pHash 目前是保留入口，尚未执行；场景 pHash 结果已可查询。

托盘入口为 `pythonw -m mh.desktop`：隐藏启动 Stash（内部 9998）和网关（公开 9999），用中文 pystray 菜单替代 Stash 自带英文托盘，并在启动后关闭 Stash 的 `SystrayClass` 窗口。关闭菜单中的「退出 MineHub」会结束本程序启动的网关和 Stash。

如果 Stash 配置或插件目录被重置，重新安装：

```bat
.venv\Scripts\python.exe -m mh.cli stash --install-js
```

QQ 管理 API（`/pm/config`、`/pm/scan`、`/pm/query`、`/pm/thumb`、`/pm/move`、`/pm/recycle`、`/pm/open`、`/pm/index`）与搜索 API 都由网关在 9999 同源提供。QQ 归属索引保存在 `data\qq\index_<账号>.sqlite`，密钥用 Windows DPAPI 保存为 `data\qq\key_<账号>.bin`；首次会尝试迁移 PictureManager 的旧索引与密钥。主账号已重建为 310 个聊天 / 78,465 条媒体；第二账号未建索引。需要 `sqlcipher3`、`send2trash`、`aiohttp`、`pystray`、`pywin32`（已写入 `requirements.txt`）。

## 设计要点

- **断点续跑**：所有状态在 `data\minehub.sqlite`；任何阶段重跑只处理未完成行。
- **先筛后标**：SigLIP2 单图 38ms、批量 82 张/秒、显存 5.4G；SigLIP 负责全量粗筛，Anime/Hentai 与仅缩略图记录也必须经 VLM 复核，不再按标签硬编码为 safe。
- **A/B 仲裁**：A（NSFW 专用）explicit 召回更高；B（Huihui abliterated）对 suggestive 更稳。A 判 explicit、置信度 <0.85、或 category 为 review/other 时由 B 复核；两者 explicit 不一致或 real/anime 冲突时进入 `review` 目录。
- **强约束 JSON**：llama.cpp `response_format.json_schema` + `--jinja`，两个模型 30/30 一次通过；缩略图 VLM 遇到截断 JSON 会自动用 640 tokens 重试，`thumb-audit repair-vlm` 可从已截断响应恢复等级。
- **去重**：移动时算 MD5，重复文件保留在 QQ 缓存原地、标记 `duplicate` 并记录 `dup_of`。
- **崩溃安全的移动**：先写 `move_state='moving'` + 目标路径作为意图日志；跨盘时先复制到同目录 `.mhpart`、fsync、校验大小，再原子 `os.replace` 到目标，最后删除源文件。启动时 `recover_moving()` 会自动完成或回退被中断的移动，不会出现「源已删、账本没记」。
- **MD5 基线**：`mh.cli baseline` 为留在 QQ 的普通文件补算 MD5，后续移动/去重可直接复用，不必重复读源文件。
- **缩略图补漏**：`thumb_audit.py` 按 QQ 文件名 stem（含 `_0/_720` 归一化）+ 内容 MD5 双索引匹配账本；对未匹配缩略图跑 SigLIP，视频/GIF/候选图再用 VLM 按 stem 分组精判，NSFW 迁到 `F:\MineHubData\qq_thumbs\<账号>\<Pic|Video>\<YYYY-MM>\Thumb\`。可重复执行，用来清理 QQ 重开浏览后重新生成的预览。
- **第二轮复核**：`reaudit.py` 用模型 B 复核 kept 中视频、`needs_review`、`sexy/adult/review`、未跑 VLM 的 anime 以及 SigLIP 高风险行；命中后回写主账本并交给同一套原子移动。
- **相似检索**：旧索引复用 NSFW SigLIP 视觉塔；新索引用原版 `google/siglip2-base-patch16-256` 图像/文本双塔，768 维归一化向量，SQLite + `embeddings.npy`，numpy 余弦 Top-K；不引入 FAISS/Qdrant。网关在 CUDA 上加载模型，MineHub 页签支持文本搜图和详情页「找相似」。多关键词语义搜索会分别编码后按“全部命中”（逐项取最低分）或“任一命中”（取最高分）合并；正则搜索读取索引快照中的文件名、路径、Stash 标签和 ID，索引 URL 保存为根相对路径，避免泄漏 9998 内部端口。标签变化后运行 `index refresh` 更新元数据，不重算向量。
- **同源网关**：`mh.gateway` 在公开 9999 上提供 `/mh/api/*` 并把其余 HTTP/WebSocket 反向代理到内部 Stash 9998；Host 头透传，媒体 URL 不会泄漏内部端口。插件只使用同源相对路径，不依赖 CSP 放行跨端口。pystray 中文托盘替代 Stash 自带托盘，并通过关闭 `SystrayClass` 窗口抑制重复图标。
- **MineHub 原生面板**：插件用普通 DOM 在 Stash 页面内渲染，顶部导航和详情页按钮沿用 Stash 的 Bootstrap 控件与主题色。QQ 扫描结果按 MD5 合并归属索引，并通过账本 `src_path/target_path` 回查 MineHub 标签；缩略图按路径+mtime+尺寸缓存到 `F:\MineHubData\cache\pm_thumbs`，视频优先复用 QQ Thumb，缺失时用 ffmpeg 抽帧，生成并发限制为 6。移动/删除只接受已知 QQ 媒体根目录或库目录内的文件，并同步从内存列表移除。
- **增量复扫**：`mh.cli rescan` 先枚举 QQ 原图（新文件才进 Stage 1），再复用 `thumb_audit` 的状态机处理新增/变化的缩略图；每阶段结束后重新读取 pending 计数，避免新文件停在 `stage2_pending`。已完成的 safe/moved 状态不会重跑，`--dry-run` 只预演缩略图移动。单轮无新内容约 2 分钟。
- **扩展名/动画盲区**：QQ 可把真实 JPEG/PNG/GIF 写成 `.null`；现在作为图片扫描，迁移时按实际格式恢复后缀。GIF/`.null` 缩略图一律强制过 VLM，不再只靠 SigLIP 的首帧分数。定向补漏结果在 `data\logs\target_audit_20261117.json`。
- **可回滚**：`data\moves.csv` 记录每条 src→dst；`mh.cli move --rollback` 原路搬回。
- **低优先级**：进程设为 BELOW_NORMAL，并调用 `SetThreadExecutionState` 防止系统睡眠。
- **Stash 打标**：按标签聚合后 `bulkImageUpdate/bulkSceneUpdate`（mode=ADD），不是逐文件调用。

## 容量

- 模型 16.2 GB（含原版 SigLIP2）；F 盘剩余空间随库和预览增减变化，以实际磁盘为准。
- Stash 数据库/缩略图在 `E:\1Codes\MineHub\data\stash` 与 `F:\MineHubData\stash`。

## 已知限制

- 两模型都会漏「紧身/白丝」类擦边（评测样本 #23），此类依赖 `review` 人工复核。
- VLM 会把部分动漫/插画误判 explicit，因此 anime 结果也会进入 `review`，不会直接当作 safe。
- 移动的是 QQ 缓存原文件，NSFW 缩略图也会迁出；查看很早的聊天记录时，QQ 若发现缓存缺失可能从服务器重新下载，重新出现的文件需要再次扫描/打标。
- 相似索引与查询必须使用同一模型和同一设备/精度重建或查询；重建索引后重启网关，否则内存中的向量可能仍是旧版本。
- 正则搜索读取 `vectors_siglip2.sqlite` 中的文件名、路径、标签快照；Stash 标签或文件路径变化后，先运行 `mh.cli index refresh --model siglip2` 再搜索。
- MineHub 搜索结果的批量删除会移除 Stash 记录并隐藏当前结果，但语义索引不会即时重建；需要重建相似索引后，已删除条目才会从索引中彻底消失。
- 卡片放大镜复用 Stash 原生图片/场景页面，并在新标签页打开，不是 MineHub 自绘的灯箱；适合直接使用 Stash 原生查看器。
- `mh.cli baseline` 需要完整读一遍留在 QQ 的普通文件，首次运行耗时取决于磁盘；之后只处理新增行。
- QQ 好友/群归属只在「QQ 缓存」面板内筛选和显示，不会为每个聊天创建 Stash 标签；Stash 原生标签仍只表示 MineHub 分类/等级/内容标签。
- QQ 面板的「更新归属索引」需要 QQ 已登录（或已有可用的 DPAPI 密钥）；第二账号首次建立索引前，归属列可能为空。
