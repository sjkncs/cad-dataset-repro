# CAD 数据集复现报告（L1 结构 + L2 评测可行性 + 优化线索）

> 复现对象：Markov `cad-1000-hours` / `cad-environments` / `autocad-bench-tasks`，MIT **VideoCAD**（NeurIPS 2025）
> 本机：SketchUp Pro 2023 (23.0.367) · Python 3.11.9 · RTX 4060 Laptop 8 GB · C 盘剩余 ~5 GB
> 日期：2026-10-14

---

## 一、结论速览

| 层级 | 内容 | 状态 |
|---|---|---|
| L1 | `cad-1000-hours` 元数据 | ✅ **509/509 任务**，1527 文件，1.51 MB |
| L1 | `cad-environments` 元数据 | ✅ 114 文件，0.13 MB（SketchUp 7 个全成功） |
| L1 | `autocad-bench-tasks` 评测定义 | ✅ 50 任务 + SHA256 校验清单 |
| L1 | 输入文件（SketchUp 组） | ✅ 25 文件 / 15.06 MB |
| L1 | 标准答案 gold | ✅ 2 个 SKP / 23.16 MB |
| L1 | VideoCAD 代码 | ✅ 克隆 10.45 MB |
| L2 | rubrics 可判定性分析 | ✅ 完成，**结论颠覆原设想** |
| L2 | 标准答案结构 + 多视角渲染 | ✅ 完成 |
| **优化** | **VideoCAD 优化补丁** | ✅ **已产出并验证（1.86x~3.14x）** |
| L3 | VideoCAD 数据预处理 | ❌ 未做（需数百 GB 原始视频） |
| L4 | 模型训练 | ❌ 不可行（8 GB 显存 + 磁盘不足） |

全部落盘约 **50 MB**（刻意只取文本元数据）。

---

## 二、L1 关键发现

### 2.1 `cad-1000-hours` 规模

1,018.12 小时 · 509 任务 · 5,455 公开对象 · **207.18 GiB**（无法本地全量）

| 软件 | 任务 | 小时 | 占比 |
|---|---:|---:|---:|
| AutoCAD | 312 | 675.40 | 66.3% |
| Revit | 24 | 116.76 | 11.5% |
| SOLIDWORKS | 114 | 100.91 | 9.9% |
| **SketchUp** | **30** | **94.70** | **9.3%** |
| CATIA V5 | 7 | 17.76 | 1.7% |
| Siemens NX | 20 | 10.05 | 1.0% |
| V-Ray | 2 | 2.54 | 0.2% |

领域：建筑制图 55.6% · 机械 CAD 19.3% · 室内设计 10.9% · BIM 8.9%
任务时长：最小 12.2 / P25 67.7 / **中位 96.1** / P75 209.3 / 最大 505.4 min

SketchUp 子集输入格式：PDF 13 · DWG 11 · 图片 6 · SKP 2

### 2.2 每个任务的完整结构

```
{software}/{task_id}/
├── task_desc.json      任务描述（domain / application / input_files / deliverables）
├── rubrics.json        评分标准（schema_version 1.0 + rubrics 数组）
├── task_overview.pdf   任务+评分+参考图 合并文档
├── clip.mp4            完整屏幕录像（本例 807 MB）
├── frame_events.json   逐帧同步事件（本例 120 MB）
├── narration.json      逐帧解说
├── metadata.json       时长/帧数/事件数/fps/platform
├── input_files/        输入图纸
└── output_files/       标准答案
```

---

## 三、L2 关键发现（决定评测架构）

### 3.1 rubrics 是自然语言，**不能机械化校验**

SketchUp 30 任务共 **224 条 rubric**：

| 模式 | 命中 | 占比 |
|---|---:|---:|
| 存在性（shall include / contains） | 166 | 74.1% |
| 空间关系（along / flanking / within） | 47 | 21.0% |
| 标高/层数 | 21 | 9.4% |
| 材质/颜色 | 10 | 4.5% |
| 坡度/倾斜 | 6 | 2.7% |
| **显式数量（21 bays）** | **1** | **0.4%** |
| **显式尺寸（40 feet）** | **1** | **0.4%** |

**只有 0.4% 含可计算数字**。绝大多数形如
"The model **shall include** a row of nine bays along the upper edge…"，
需**理解语义 + 看图**才能判定。

> ⚠️ **推翻我此前的设想**：原以为可把 rubrics 转成确定性几何断言自动打分，
> 实际做不到——**必须引入视觉/LLM 裁判**。

### 3.2 标准答案规模远超预期

SketchUp 任务 `106249f1`（22.0.354 格式）实测：

| 指标 | 数值 |
|---|---:|
| 边 / 面 | **473,442 / 254,148** |
| 组件实例 / 组 | 643 / 341（嵌套最深 6 层） |
| 顶层实体 | 691 |
| 单位 | `LengthUnit = 0` → **英寸（英制）** |
| 包围盒 | 351 × 517 × 175 英寸 = **29.25 × 43.08 × 14.58 英尺** |
| 命名构件 | `window` / `glass` / `sill` / `sash_1` / `sash_2` / `handle`（8 套窗） |
| 材料 | `PLAN`(68) / `S steel`(42) / `CAISSON`(24) / `window1`(24) / `染色半透明玻璃` |

**含数十万面的生产级模型**，是 1~2 小时人工工作的成果。

### 3.3 两个可复用工程结论

**① SKP 文件头内嵌创建版本，可预筛兼容性**

```
偏移 0: FF FE                  ← UTF-16LE BOM
之后:   "SketchUp Model  {23.1.340}"
```

实测 `{23.1.340}` 在 SketchUp **23.0.367 上直接崩溃**；`{22.0.354}` 正常。
→ 批量处理前先读版本号，避免反复崩溃。

**② HuggingFace 直连被 DNS 污染，必须走镜像**

```
huggingface.co          → 108.160.166.137 (Dropbox 段)  TCP443 = False
cdn-lfs.huggingface.co  → 199.59.150.49  (Twitter 段)   TCP443 = False
hf-mirror.com           → TCP443 = True，API 与下载均 200  ✅
```

这解释了此前随机的 `URLError`。所有脚本已改为**镜像优先 + 重试退避**
（`hf_util.py`）。

---

## 四、L2 评测器设计

```
输入图纸 + 任务描述
      ↓
[被测系统]  ← SketchUp MCP 桥 / 参数化面板 / 任一 agent
      ↓ 产出交付物
┌──────────────────────────────────────────┐
│ 第 1 层：确定性校验（可靠、可复现）          │
│   · SHA256 校验产物完整性                  │
│   · 几何探针：实体计数/包围盒/单位/图层       │
│   · 预算核对：max_actions / time_limit_s    │
├──────────────────────────────────────────┤
│ 第 2 层：视觉裁判（覆盖语义需求）            │
│   · 多视角离屏渲染                         │
│   · 与 gold 渲染图对比，逐条打分             │
│   · 必须引用渲染图中的具体证据               │
├──────────────────────────────────────────┤
│ 第 3 层：阳性对照（评测器自身的有效性）       │
│   · 用 gold 跑同一评测器，必须满分           │
└──────────────────────────────────────────┘
```

已通过 SketchUp 桥验证可提取的探针：递归实体统计（类型/深度/名称/材料/标签）、
`model.bounds` + `LengthUnit` 换算真实尺寸、命名构件检索、`view.write_image()` 多视角渲染。

---

## 五、不可行项与原因（如实说明）

| 项 | 原因 |
|---|---|
| L3 VideoCAD 数据预处理 | 需数百 GB 原始视频；C 剩 ~5 GB、D 0.02 GB、E 0.18 GB |
| L4 VideoCADFormer 训练 | 8 GB 显存不足；PyTorch 是 CPU 版，装 CUDA 版需 ~2.5 GB |
| `clip.mp4` / `frame_events.json` | 单文件 0.8~120 MB，509 任务全量远超磁盘 |
| `markov-ai/autocad-bench` | 该 HF 仓库返回 401（gated）；但 `-tasks` 版本公开可用 |

---

## 六、优化线索（实测，非推测）

### 6.1 VideoCAD：帧处理路径「实现了但没接上」⭐ 最干净的优化

**代码事实**：

```
data_loader/data_loader.py:368  def resize_frames(self, frames)        ← 向量化快路径
data_loader/data_loader.py:379  def resize_frames_slow(self, frames)   ← 逐帧 PIL
data_loader/data_loader.py:449  frames_tensor = self.resize_frames_slow(frames)
```

全代码库搜索确认：**`resize_frames()` 定义了但从未被调用**（死快路径）。

**实测（480×640 → 224×224）**：

| 序列长度 | slow（现用） | cv2 向量化+resize | 纯向量化（预 resize 后） |
|---|---:|---:|---:|
| N=10 | 83.1 ms | 44.9 ms（**1.85x**） | 23.7 ms（**3.51x**） |
| N=20 | 154.9 ms | 110.4 ms（**1.40x**） | 54.1 ms（**2.86x**） |

**关键**：不能简单把 `slow` 换成 `fast` —— **`fast` 不做 resize**，
直接换会破坏语义（这很可能正是原作者没接上的原因）。
正确做法是让 `fast` 在帧尺寸不匹配时先 resize，尺寸匹配时完全跳过
（配合在 `generate_dataset.py` 预处理阶段预 resize 到 `image_size`）。

### 6.2 VideoCAD：pickle 文件句柄泄漏

```python
# sequence_retriver.py:29（原）
data = pickle.load(open(self.data_files[idx], 'rb'))   # 句柄永不关闭
```

每个 `__getitem__` 泄漏一个句柄。训练跑几百轮后累积，
Windows 上会触发 `Too many open files` / `PermissionError`。改用 `with`。

### 6.3 VideoCAD：`num_workers` 默认值偏小

`main.py:175` / `test.py:199` 默认 `num_workers=2`。每个样本要读一个
pickle + 一张 PNG，属 I/O 密集，2 个 worker 会饿住 GPU。建议按核数自适应。

### 6.4 其它清洁度问题

- `sequence_retriver.py:8` `from functools import lru_cache` 未使用
- `generate_dataset.py:9` `import lmdb` 未使用（而 LMDB 恰是本场景正解，见 6.5）
- `data_loader.py:411` `base_file_id` 重复计算（`get_sequence` 已返回）

### 6.5 更大的优化空间（未实施，需改数据管线）

1. **换 LMDB**：当前每样本读独立 pickle+PNG，随机读放大严重；
   代码已 import `lmdb` 却没接上——设计好的加速路径没做完。
2. **帧存 JPEG 而非 PNG**：224×224 帧存 PNG 体积远大于 JPEG。
3. **预 resize 后落盘**：见 6.1，一次性代价换每轮收益。

### 6.6 一处待核实的正确性疑点

```python
# generate_dataset.py:14-17
fps = cap.get(cv2.CAP_PROP_FPS)
frame_idx = int(timestamp)   # int(round(timestamp * fps))   ← 被注释掉的写法
```

直接把浮点秒截断成帧号，而注释掉的 `int(round(timestamp*fps))` 才是正确换算。
**若视频 fps≠1，帧定位会错位**。VideoCAD 采集为 60 FPS，故很可能有偏差。
（未下原始视频，无法实测，列为待核实项。）

### 6.7 已产出的补丁

`C:\cad_repro\videoCAD_optimizations.patch`（6,717 字节，6 个补丁块）
覆盖 6.1 + 6.2 + 6.3 + 6.4。已验证：

- `git apply --check` → **exit=0**
- 应用后 `py_compile` 通过
- 功能验证**全部通过**：形状 `[10,3,224,224]`、数值 ∈[0,1]、dtype float32、
  内存连续、默认路径 == 快路径（完全一致）、`VIDEO_CAD_FORCE_SLOW=1` 可回退
- 实测加速：**1.86x**（未预 resize）/ **3.14x**（预 resize）
- 验证后仓库已 `git checkout -- .` **还原干净**

补丁保留 resize 语义，不做等价性破坏；提供环境变量回退开关便于 A/B 对照。
生成器 `make_patch.py` 逐条锚点校验，锚点不存在即中止，避免误改。

---

## 七、L2 评测器应建在 autocad-bench 上（对第三节的重要修正）

`markov-ai/autocad-bench-tasks` 是可执行评测基准，远优于从 rubrics 自造：

| 维度 | 内容 |
|---|---|
| 任务 | 50（**21 个 2D 制图 + 29 个 3D 建模**） |
| 难度 | basic 10 / intermediate 12 / advanced 14 / project 14 |
| 单位 | **mm** |
| 约束 | `max_actions=5000`；时限 2D 900 s / 3D 1800 s |
| 每题产物 | `reference.png`（给模型）+ `gold.dwg`（**评测侧，不得进模型可见域**） |
| 校验 | 每题 `reference_sha256` + `gold_sha256` |
| 许可 | CC-BY-4.0 |
| 评估口径 | 2D：Model Space 完整标注图；3D：Model Space 真实三维几何 + `Layout1` 完整图纸 |
| DWG 格式 | AutoCAD 2018 `AC1032` |

**评测器设计据此改为**：

- **第 1 层（确定性）**：SHA256 校验产物 + 几何探针，直接读 `tasks.jsonl` 的
  `units` / `time_limit_s` / `max_actions`
- **第 2 层（语义）**：只对 bench 未覆盖的维度用视觉裁判；
  **不要试图机械化 cad-1000-hours 的 rubrics**（0.4% 可算）
- **第 3 层（阳性对照）**：用 `gold.dwg` 跑同一评测器，gold 必须满分

---

## 八、待你确认

1. **要复刻到哪个仓库？** 全程未出现仓库地址，需要你给出 URL 或本地路径
   （例如 `E:\gui agent_song\gui agent` 是否是目标）。
2. **补丁落地形式**：直接 `git apply` 这个 patch，还是按你的仓库结构重写一遍？
3. **L3/L4 是否推进？** 需二选一：清出 ≥50 GB 磁盘 + 装 CUDA 版 PyTorch，
   或接云 GPU（modal / vast.ai，需要你的账号）。

---

## 九、复现脚本清单

| 脚本 | 作用 |
|---|---|
| `hf_util.py` | HF 访问（镜像优先 + 重试退避） |
| `fetch_meta.py` | 拉元数据（跳过 mp4/事件文件） |
| `fetch_inputs.py` | 拉输入图纸（带单文件体积上限） |
| `fetch_gold.py` | 拉标准答案 |
| `fetch_bench.py` | 拉 autocad-bench 评测定义 |
| `analyze_meta.py` | 汇总统计与示例任务 |
| `rubric_probe.py` | rubrics 可判定性分析 |
| `probe_bench.py` | 探测各数据集可用性 |
| `inspect_gold.py` | 用 SketchUp 桥解析 gold 结构 |
| `render_views.py` | 导出 gold 多视角渲染图 |
| `bench_resize.py` | 帧处理路径基准测试 |
| `make_patch.py` | 生成优化补丁（锚点校验） |
| `verify_patch.py` | 补丁功能验证 |

```powershell
cd C:\cad_repro
$py = "C:\Users\Lenovo\AppData\Local\Programs\Python\Python311\python.exe"

# 拉取
& $py fetch_meta.py   --dataset markov-ai/cad-1000-hours --all
& $py fetch_inputs.py --dataset markov-ai/cad-1000-hours --software sketchup
& $py fetch_gold.py   --dataset markov-ai/cad-1000-hours --software sketchup --limit 3
& $py fetch_bench.py

# 分析
& $py analyze_meta.py markov-ai/cad-1000-hours
& $py rubric_probe.py sketchup
& $py probe_bench.py

# 优化补丁（在 VideoCAD 仓库内执行）
cd C:\cad_repro\VideoCAD
git apply ..\videoCAD_optimizations.patch
& $py ..\verify_patch.py
git checkout -- .          # 验证后还原
```
