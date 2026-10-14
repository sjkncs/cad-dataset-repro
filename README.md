# cad-dataset-repro

对四个 CAD / computer-use 公开数据集与代码库的**复现工具箱**：
元数据拉取、结构分析、评测设计，以及对 VideoCAD 数据加载链路的**实测优化补丁**。

> 本项目只包含**工具、补丁与文档**，不重新分发上游数据集或上游源码。
> 上游代码与数据的许可见 [Licensing](#licensing)。

---

## 复现对象

| # | 项目 | 类型 | 规模 | 本仓库产出 |
|---|---|---|---|---|
| 1 | [`markov-ai/cad-1000-hours`](https://huggingface.co/datasets/markov-ai/cad-1000-hours) | 数据集 | 1,018 h / **509 任务** / 207 GiB | 元数据拉取 + 分析工具 |
| 2 | [`markov-ai/cad-environments`](https://huggingface.co/datasets/markov-ai/cad-environments) | 数据集 | 99 h / 51 工作流 | 同上 |
| 3 | [`markov-ai/autocad-bench-tasks`](https://huggingface.co/datasets/markov-ai/autocad-bench-tasks) | **评测基准** | 50 任务（21×2D + 29×3D） | 评测设计文档 |
| 4 | [`ghadinehme/VideoCAD`](https://github.com/ghadinehme/VideoCAD) | 代码 + 数据 | 41,005 段 CAD 视频（NeurIPS 2025） | **优化补丁** |

---

## 核心产出：VideoCAD 数据加载优化

### 发现

`VideoCAD/data_loader/data_loader.py` 里有一个**向量化的快路径从未被调用**：

```
data_loader.py:368  def resize_frames(self, frames)        ← 向量化快路径（死代码）
data_loader.py:379  def resize_frames_slow(self, frames)   ← 逐帧 PIL
data_loader.py:449  frames_tensor = self.resize_frames_slow(frames)
```

### 实测（480×640 → 224×224）

| 序列长度 | slow（现用） | cv2 向量化 + resize | 纯向量化（预 resize 后） |
|---|---:|---:|---:|
| N=10 | 83.1 ms | 44.9 ms（**1.85×**） | 23.7 ms（**3.51×**） |
| N=20 | 154.9 ms | 110.4 ms（**1.40×**） | 54.1 ms（**2.86×**） |

### 为什么原作者没接上（关键洞察）

**不能简单把 `slow` 替换成 `fast`** —— `fast` **不做 resize**，
直接替换会改变语义。正确修法是：

1. `resize_frames_fast()` 在帧尺寸 ≠ `image_size` 时先 resize，尺寸匹配时完全跳过
2. 配合在 `generate_dataset.py` 预处理阶段把帧**预 resize 到 `image_size`** 后落盘
3. 这样每轮训练都能走零 resize 的纯向量化路径，拿到完整 3× 收益

补丁保留了 resize 语义，并提供 `VIDEO_CAD_FORCE_SLOW=1` 环境变量回退旧行为，
便于 A/B 对照。

### 顺带修掉的问题

| 问题 | 位置 | 影响 |
|---|---|---|
| `pickle.load(open(...))` 句柄永不关闭 | `sequence_retriver.py:29` | 每样本泄漏一个句柄，长训练触发 `Too many open files` |
| `num_workers` 默认 2（I/O 密集却偏小） | `main.py:175` / `test.py:199` | 饿住 GPU |
| 未使用的 `from functools import lru_cache` | `sequence_retriver.py:8` | 清洁度 |
| `base_file_id` 重复计算 | `data_loader.py:411` | 清洁度 |

### 应用补丁

```bash
git clone https://github.com/ghadinehme/VideoCAD.git
cd VideoCAD
git apply /path/to/cad-dataset-repro/patches/videocad_dataloader_optimizations.patch

# 验证（形状/数值/dtype/内存连续 + 快慢路径一致性）
python /path/to/cad-dataset-repro/tools/verify_patch.py
```

验证记录见 [`patches/README.md`](patches/README.md)。

---

## 沿用本仓库时需要知道的两个环境坑

### 1. HuggingFace 直连可能被 DNS 污染

在某些网络环境下：

```
huggingface.co          → 108.160.166.137 (Dropbox 段)   TCP 443 = False
cdn-lfs.huggingface.co  → 199.59.150.49  (Twitter 段)    TCP 443 = False
hf-mirror.com           → TCP 443 = True，API 与下载均 200  ✅
```

**所有 HF 访问请走 `hf-mirror.com`**。`tools/hf_util.py` 已实现
「镜像优先 + 重试退避」，设 `HF_ENDPOINT` 可覆盖。
直连**偶尔能通**（间歇放通），会造成随机 `URLError`，别误判成脚本 bug。

### 2. SKP 文件要先读版本号再打开

SKP 头部内嵌创建版本（UTF-16LE BOM `FF FE` 之后）：

```
偏移 0: FF FE                  ← UTF-16LE BOM
之后:   "SketchUp Model  {23.1.340}"
```

实测 `{23.1.340}` 在 SketchUp **23.0.367 上直接崩溃**，`{22.0.354}` 正常。
批量处理前先预筛，否则会反复把 SketchUp 弄崩。

---

## 评测设计：优先用 autocad-bench，不要用 rubrics

`autocad-bench-tasks` 是可执行基准，远优于从自然语言 rubrics 自造评测器：

| 维度 | 内容 |
|---|---|
| 任务 | 50（21 个 2D 制图 + 29 个 3D 建模） |
| 难度 | basic 10 / intermediate 12 / advanced 14 / project 14 |
| 单位 | **mm** |
| 约束 | `max_actions=5000`；时限 2D 900 s / 3D 1800 s |
| 每题产物 | `reference.png`（给模型）+ `gold.dwg`（**评测侧，不得进模型可见域**） |
| 校验 | 每题 `reference_sha256` + `gold_sha256` |
| 评估口径 | 2D：Model Space 完整标注图；3D：Model Space 真实三维几何 + `Layout1` 完整图纸 |

**为什么不用 `cad-1000-hours` 的 rubrics**：对 SketchUp 子集 224 条 rubric 的
模式分析显示——**只有 0.4% 含可计算的显式数量、0.4% 含显式尺寸**；
**74% 是 "shall include X" 这类存在性表述**，机器无法据此判定几何。
评测必须依赖视觉/LLM 裁判，且不如 bench 规范。

详见 [`bench/EVAL_DESIGN.md`](bench/EVAL_DESIGN.md)。

---

## 工具清单

| 工具 | 作用 |
|---|---|
| `tools/hf_util.py` | HF 访问（镜像优先 + 重试退避） |
| `tools/fetch_meta.py` | 拉元数据（自动跳过 `clip.mp4` / `frame_events.json` 等 GB 级文件） |
| `tools/fetch_inputs.py` | 拉输入图纸（带单文件体积上限，防止撑爆磁盘） |
| `tools/fetch_gold.py` | 拉标准答案（阳性对照用） |
| `tools/fetch_bench.py` | 拉 autocad-bench 评测定义 |
| `tools/analyze_meta.py` | 任务/领域/时长/rubrics 汇总统计 |
| `tools/rubric_probe.py` | rubrics 可机器判定性分析 |
| `tools/bench_resize.py` | 帧处理路径基准测试（复现上表数字） |
| `tools/make_patch.py` | 生成优化补丁（逐条锚点校验，锚点缺失即中止） |
| `tools/verify_patch.py` | 补丁功能验证 |

### 快速开始

```bash
python -m pip install numpy pillow opencv-python torch   # torch 仅 verify_patch 需要

# 只拉文本元数据（约 2 MB，不需要大磁盘）
python tools/fetch_meta.py --dataset markov-ai/cad-1000-hours --all
python tools/analyze_meta.py markov-ai/cad-1000-hours
python tools/rubric_probe.py sketchup

# 评测基准定义（约 35 KB）
python tools/fetch_bench.py

# 复现帧处理基准数字
python tools/bench_resize.py

# 生成 / 验证补丁
python tools/make_patch.py            # 需先用 --src 指向 VideoCAD 克隆
python tools/verify_patch.py          # 需先应用补丁
```

---

## 关键实测数据（供复现核对）

### `cad-1000-hours` 规模

1,018.12 小时 · 509 任务 · 5,455 公开对象 · 207.18 GiB

| 软件 | 任务 | 小时 |
|---|---:|---:|
| AutoCAD | 312 | 675.40 |
| Revit | 24 | 116.76 |
| SOLIDWORKS | 114 | 100.91 |
| **SketchUp** | **30** | **94.70** |
| CATIA V5 | 7 | 17.76 |
| Siemens NX | 20 | 10.05 |
| V-Ray | 2 | 2.54 |

任务时长：最小 12.2 / P25 67.7 / **中位 96.1** / P75 209.3 / 最大 505.4 分钟

### 标准答案规模（SketchUp 任务 `106249f1`，格式 22.0.354）

| 指标 | 数值 |
|---|---:|
| 边 / 面 | **473,442 / 254,148** |
| 组件实例 / 组 | 643 / 341（嵌套最深 6 层） |
| 单位 | `LengthUnit = 0` → 英寸（英制） |
| 包围盒 | 351 × 517 × 175 英寸 = 29.25 × 43.08 × 14.58 英尺 |

---

## 未完成项（如实说明）

| 项 | 原因 |
|---|---|
| VideoCAD 数据预处理复现 | 需数百 GB 原始视频（60 FPS 屏幕录像） |
| VideoCADFormer 训练 | 需 ≥1 张现代 GPU；原配置 `batch_size=2` 已很紧 |
| `cad-1000-hours` 全量下载 | 207 GiB |

本仓库刻意**只处理文本元数据**，使复现的磁盘成本降到 ~2 MB。

### 一处待核实的疑点

```python
# VideoCAD/generate_dataset.py:14-17
fps = cap.get(cv2.CAP_PROP_FPS)
frame_idx = int(timestamp)   # int(round(timestamp * fps))   ← 被注释掉的写法
```

把浮点秒直接截断成帧号，而注释掉的 `int(round(timestamp * fps))` 才是正确换算。
**若视频 fps ≠ 1，帧定位会错位**——VideoCAD 采集为 60 FPS，故很可能有偏差。
未下载原始视频，无法实测确认，列为待核实项。

---

## Licensing

本仓库自身以 **MIT** 发布（见 `LICENSE`）。

- **不重新分发**上游数据集或上游源码，只提供工具与补丁。
- `patches/` 中的补丁是针对 [`ghadinehme/VideoCAD`](https://github.com/ghadinehme/VideoCAD)
  的 diff，应用时请自行克隆上游并遵守上游许可。
- 数据集许可以上游声明为准：
  `autocad-bench-tasks` 为 **CC-BY-4.0**；其余 Markov 数据集请在使用前核对各自许可。
- 引用 VideoCAD 请使用其论文：

```bibtex
@article{man2026videocad,
  title={VideoCAD: A Dataset and Model for Learning Long-Horizon 3D CAD UI Interactions from Video},
  author={Man, King Yiu Brandon and Nehme, Ghadi and Alam, Md Ferdous and Ahmed, Faez},
  journal={Advances in Neural Information Processing Systems},
  volume={38},
  year={2026}
}
```
