# 评测设计：为什么用 autocad-bench，而不是自造 rubrics

## 一、结论

**直接用 `markov-ai/autocad-bench-tasks` 作为评测基准。**
不要试图把 `cad-1000-hours` 的自然语言 rubrics 机械化成几何断言——实测做不到。

---

## 二、为什么不从 rubrics 自造评测器

对 `cad-1000-hours` 的 SketchUp 子集（30 任务）**224 条 rubric** 做模式分析：

| 模式 | 命中 | 占比 |
|---|---:|---:|
| 存在性（`shall include` / `contains`） | 166 | **74.1%** |
| 空间关系（`along` / `flanking` / `within`） | 47 | 21.0% |
| 标高/层数 | 21 | 9.4% |
| 材质/颜色 | 10 | 4.5% |
| 坡度/倾斜 | 6 | 2.7% |
| **显式数量**（如 `21 bays`） | **1** | **0.4%** |
| **显式尺寸**（如 `40 feet`） | **1** | **0.4%** |

复现命令：

```bash
python tools/rubric_probe.py sketchup
```

**只有 0.4% 的 rubric 含可计算数字。** 绝大多数形如：

> "The model **shall include** a row of nine bays along the upper edge
> served by the driveway behind it."

这条同时要求数量（9）、空间关系（along / behind）、功能语义（driveway served）——
纯几何探针无法判定，只能看图 + 理解语义。

**因此**：rubrics 路线要么退化成「LLM 自由发挥打分」（不可复现），
要么只能覆盖极小一部分需求。两条路都不如直接用规范化的 bench。

---

## 三、autocad-bench-tasks 规格

```bash
python tools/fetch_bench.py     # 约 35 KB
```

| 维度 | 内容 |
|---|---|
| 任务总数 | **50** |
| 类型 | 21 个 2D 制图 + 29 个 3D 建模 |
| 难度 | basic 10 / intermediate 12 / advanced 14 / project 14 |
| 单位 | **mm**（全部任务统一） |
| 动作预算 | `max_actions = 5000`（全部任务） |
| 时限 | 2D = 900 s；3D = 1800 s |
| 每题产物 | `reference.png`（给模型）+ `gold.dwg`（评测侧） |
| 校验 | 每题 `reference_sha256` + `gold_sha256` |
| DWG 格式 | AutoCAD 2018 `AC1032` |
| 许可 | **CC-BY-4.0** |

### 文件布局

```
data/task-001/
├── reference.png
└── gold.dwg
```

### `tasks.jsonl` 字段

```
drawing_type, gold_bytes, gold_dwg, gold_sha256, level, max_actions,
prompt_path, reference_bytes, reference_image, reference_sha256,
split, task_id, task_name, time_limit_s, units
```

---

## 四、⚠️ 评测边界（上游明确要求，必须遵守）

上游 README 原文规定的边界：

> The model should receive **only** the task prompt and `reference.png`.
> The gold DWG is an **evaluator-side artifact** and must never be mounted
> in the model-controlled desktop, included in the model prompt, or otherwise
> made available to the agent during a rollout.

**落地检查项**：

- [ ] 模型可见域内**不存在** `gold.dwg`
- [ ] prompt 中**不含** gold 的任何信息（不要贴 gold 的 SHA256 或尺寸线索）
- [ ] 评测脚本与模型运行环境**进程/文件系统隔离**
- [ ] 提交口径：2D = Model Space 完整标注图；3D = Model Space 真实三维几何 + `Layout1` 完整图纸

---

## 五、三层评测架构

```
任务 prompt + reference.png
         ↓
   [被测系统 / agent]
         ↓ 产出交付物
┌─────────────────────────────────────────────┐
│ 第 1 层：确定性校验（可靠、可复现、无 LLM）      │
│   · SHA256 校验产物完整性                     │
│   · 几何探针：实体计数 / 包围盒 / 单位 / 图层    │
│   · 预算核对：max_actions / time_limit_s      │
├─────────────────────────────────────────────┤
│ 第 2 层：语义裁判（仅覆盖第 1 层测不到的维度）    │
│   · 多视角离屏渲染                            │
│   · 与 reference.png 对比，逐条打分            │
│   · 必须引用渲染图中的具体证据（禁止无据评分）    │
├─────────────────────────────────────────────┤
│ 第 3 层：阳性对照（评测器自身的有效性检验）       │
│   · 用 gold.dwg 跑同一评测器，必须满分          │
│   · gold 不通过 ⇒ 评测器有 bug，不是被测系统的问题 │
└─────────────────────────────────────────────┘
```

### 为什么必须有第 3 层

如果评测器连上游作者本人的正确交付物都判不通过，那它测的是**评测器的 bug**，
而不是被测系统的能力。第 3 层是评测结论可信的前提，成本却很低（一次跑 gold）。

---

## 六、第 1 层已实现的部分（离线、不依赖 CAD）

`tools/verify_bench_manifest.py` + `tools/fetch_bench_sample.py` 已落地第 1 层的
**前提**：验证拿到的数据本身可信。

```bash
python tools/fetch_bench.py            # 只拉评测定义（tasks.jsonl 等）
python tools/fetch_bench_sample.py     # 拉 2 个任务的 reference.png + gold.dwg
python tools/verify_bench_manifest.py  # 对 manifest 做逐字节校验
```

**实测结果**（task-001 / task-002）：

| 产物 | 字节数 | sha256 对 manifest | 其他 |
|---|---|---|---|
| `task-001/gold.dwg` | 28,775 | ✅ `d64c1511…` | 版本签名 `AC1032`，熵 6.904 bit/B |
| `task-001/reference.png` | 66,044 | ✅ `1c4a406f…` | 827×612，非白占比 0.0552，平均亮度 247.4 |
| `task-002/gold.dwg` | 132,073 | ✅ `f7021e28…` | 版本签名 `AC1032`，熵 7.678 bit/B |
| `task-002/reference.png` | 44,270 | ✅ `664ed5e3…` | 487×713，非白占比 0.0897，平均亮度 241.4 |

**4/4 逐字节一致 → 阳性对照的前提成立**：上游 gold 在本校验器下完全可信。

DWG 的版本签名是前 6 字节 ASCII（`AC1032` = AutoCAD 2018），与上游 README 声明一致。

### 6.1 本层的定位

本层**只回答一个问题：拿到的数据本身可信吗？**
答案是可信（4/4 逐字节一致）。

它**不回答**「模型画得对」。

而「画得对不对」所需的几何探针**已经打通**（见第七节）——
DWG→DXF 通路已解决，不再需要 ODA 注册下载。

---

## 七、第 1 层几何探针（DWG→DXF 通路已打通）

瓶颈曾是 DWG 封闭格式。**已解决**：用 LibreDWG 的 `dwg2dxf` 转 DXF，
再交给 `ezdxf` 抽几何事实。LibreDWG 是 **GPL 开源、免注册、官方提供 Windows
预编译包**，比需要注册的 ODA File Converter 更适合自动化。

```bash
python tools/fetch_libredwg.py         # 拉取 dwg2dxf（~11.5 MB，带 sha256 校验）
python tools/probe_dwg_geometry.py --dwg bench/sample/task-001__GOLD__gold.dwg
```

### 7.1 对 gold 的实测（task-001）

| 探针 | 结果 | 与参考图对照 |
|---|---|---|
| 单位 | `$INSUNITS = 4`（毫米） | 与上游声明 `units: mm` 一致 ✅ |
| 图层 | `0 / Defpoints / dim / new` | 有专用 `dim` 标注层 ✅ |
| 模型空间实体 | 25 | — |
| 实体类型 | `DIMENSION 12` / `LINE 6` / **`CIRCLE 4`** / `LWPOLYLINE 2` / `ARC 1` | 图上 **4 个孔** ✅ |
| 图层分布 | `dim 12` / `0 7` / `new 6` | 标注全在 `dim` 层 ✅ |
| 包围盒 | `24.5669 × 17.0744` | — |
| 尺寸测量值 | `1.0, 1.0, 2.0, 2.0, 2.8, 3.0, 3.5, 3.5, 5.6, 6.0, 8.0, 12.0` | **逐个对上图纸标注** ✅ |
| 多重性前缀 | `2x<>`（5.6 / 2.8 / 2.0）、`4x<>`（1.0） | 对应 `2×Ø5.6`、`2×Ø2.8`、`2×R2`、`4×R1` ✅ |

**参考图上的标注全部命中、无一遗漏**：`R12`、`2×Ø5.6`、`2×Ø2.8`、`4×R1`、`2×R2`，
以及线性尺寸 `3 / 3.5 / 6 / 8 / 2`。

这使第 1 层从「格式校验」升级为**真正的几何校验**：
`probe_dwg_geometry.py` 的输出就是「正确答案的几何指纹」；
被测系统产出同格式文件后跑同一探针，逐项对比即可。

### 7.2 依赖说明

`dwg2dxf` 是 GPL 三方件，**不提交进仓库**（`.gitignore` 已排除 `tools/libredwg/`）。
用 `tools/fetch_libredwg.py` 按需下载，脚本内置 sha256 留档校验：

```
libredwg-0.14-win64.zip
sha256 = 1ad7e15344d20b3426c3435b078d82fb84b35062815946b2cca9c5fc9810fea8
```

### 7.3 仍未覆盖的

| 项 | 说明 |
|---|---|
| 3D 实体性（"genuine 3D geometry"） | 检查 `3DSOLID`/`REGION`/`MESH` 等类型；探针已按类型计数，可直接扩展 |
| `Layout1` 图纸完整性 | 需读 paper space 布局；当前只探了 model space |
| 独立 TEXT/MTEXT | task-001 的文本在 `DIMENSION.text` 字段（如 `2x<>`）而非独立实体；探针两者都收 |
| 语义需求（是否符合任务描述） | 需 LLM / 视觉裁判，属第 2 层 |

## 八、建议的落地顺序

1. **先做第 3 层**：拿 `gold.dwg` 跑通校验与渲染，确认评测管线本身正确
2. **再做第 1 层**：确定性探针 + 预算核对
3. **最后做第 2 层**：视觉裁判（成本最高，且需要 API 或本地 VLM）

按这个顺序，即使第 2 层暂时不做，第 1+3 层也能给出**可复现的定量结论**。
