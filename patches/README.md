# VideoCAD 数据加载优化补丁

> **已向上游提交**：[ghadinehme/VideoCAD#13](https://github.com/ghadinehme/VideoCAD/issues/13)
> — `dataloader: enable the unused vectorized fast path (2.7-5x on frame processing)`

针对 [`ghadinehme/VideoCAD`](https://github.com/ghadinehme/VideoCAD) 的
`data_loader` 链路优化。**仅含补丁，不含上游源码。**

- 补丁文件：`videocad_dataloader_optimizations.patch`（6.7 KB，6 个补丁块）
- 改动文件：`data_loader/sequence_retriver.py`、`data_loader/data_loader.py`、`main.py`
- 改动量：+54 / −18
- 基线：上游 `main` @ `2d69eea`（2026-09-21）

---

## 一、应用

```bash
git clone https://github.com/ghadinehme/VideoCAD.git
cd VideoCAD

git apply --check /path/to/videocad_dataloader_optimizations.patch   # 先检查
git apply         /path/to/videocad_dataloader_optimizations.patch   # 再应用
```

**基线**：补丁基于 VideoCAD `main` 分支生成（2026-10 拉取）。
若上游已变动导致 `git apply` 失败，用 `tools/make_patch.py` 重新生成
（它会逐条校验锚点，锚点不存在即中止，不会误改）。

---

## 二、优化项

### 2.1 帧处理向量化（主要收益）⭐

**问题**：`data_loader.py` 里有一个向量化快路径**从未被调用**。

```
data_loader.py:368  def resize_frames(self, frames)        ← 向量化快路径（死代码）
data_loader.py:379  def resize_frames_slow(self, frames)   ← 逐帧 PIL
data_loader.py:449  frames_tensor = self.resize_frames_slow(frames)
```

**实测**（480×640 → 224×224，`tools/bench_resize.py` 可复现）：

| 序列长度 | slow（现用） | cv2 向量化 + resize | 纯向量化（预 resize 后） |
|---|---:|---:|---:|
| N=10 | 83.1 ms | 44.9 ms（**1.85×**） | 23.7 ms（**3.51×**） |
| N=20 | 154.9 ms | 110.4 ms（**1.40×**） | 54.1 ms（**2.86×**） |

**为什么不能简单替换**：`resize_frames()` **不做 resize**，直接替换会改变语义
（帧若是 480×640 会被原样送进网络）。这很可能正是原作者没接上的原因。

**补丁做法**：

- 新增 `resize_frames_fast()`：帧尺寸 ≠ `image_size` 时先 resize，尺寸匹配时**完全跳过**
- `resize_frames_slow()` 默认委托给 `resize_frames_fast()`
- 保留 `VIDEO_CAD_FORCE_SLOW=1` 环境变量回退旧实现，便于 A/B 对照
- 输出 `np.ascontiguousarray`，避免下游额外拷贝

### 2.1.1 更正：无需修改 `generate_dataset.py`

> **本条更正了本文档早期版本的一个错误说法。**

早期版本称「要拿满 3× 必须在 `generate_dataset.py` 预 resize」。
**这是错的。** 实测与代码核对后确认：上游**已经这样做了**。

上游 `generate_dataset.py:206-209` 的入口是：

```python
generate_action_vectors_and_video_pairs("data/data_raw", "data/data_resized",
                                        resize=(224, 224))
```

该函数内部 `extract_frames_from_actions(vid_path, timesteps, resize)` 会
**在抽帧时就 resize 到 224×224** 再落盘。所以 `data_resized/*_data.pkl` 里的
帧本来就是 `image_size`，与 `DatasetBase(image_size=(224,224))` 一致。

**实证**（`tools/verify_preresize.py`，用 monkeypatch 统计 `cv2.resize` 调用次数）：

```
序列长度 N=10
  A 上游真实产物形状 224x224    16.90 ms   1.00x
  B 未预 resize 形状 480x640    32.02 ms   1.89x
  C 高清截图形状 1080x1920      96.84 ms   5.73x

cv2.resize 调用次数：
  224x224 输入 -> 0 次   ✅ 完全跳过 resize
  480x640 输入 -> 10 次
```

**结论**：走上游正常生成流程得到的数据，应用本补丁后即**直接进入零 resize 的
纯向量化路径**，无需任何额外改动。

**另注**：同文件的 `convert_vid_to_frames()`（不 resize 的那个）经核对是
**未被调用的死代码**——`__main__` 走的是 `generate_action_vectors_and_video_pairs`。
若有人误用它生成数据，才会出现未 resize 的情况；此时补丁的
`resize_frames_fast()` 也会自动 resize 兜底，不会静默出错。

### 2.2 `get_sequence` 依赖引用计数来关闭 pickle 文件

```python
# 原（sequence_retriver.py:29）
data = pickle.load(open(self.data_files[idx], 'rb'))
```

> **本条更正了本文档早期版本的一个错误说法。**

早期版本称这是「句柄泄漏，长训练会触发 `Too many open files`」。
**实测表明在 CPython 上不是功能性 bug**，实测记录如下：

| 探测 | 结果 |
|---|---|
| `-W always::ResourceWarning`，200 次调用 | **200 个 ResourceWarning**（文件确实交给了 GC） |
| `gc.disable()`，20,000 次调用 | **未失败**（表达式结束引用计数归零） |
| 阳性对照：真持有 2,000 个 `open()` 对象 | 本机也未触发上限 |

即：**CPython 的引用计数会在表达式结束时立即回收关闭该临时文件**，
因此这只是代码卫生问题，**不是会崩的 bug**。我无法让它真正失败。
非引用计数实现（PyPy）下才可能累积，但未实测，不作断言。

复现：`python tools/probe_leak_reality.py`

补丁仍改为 `with`——它消除 ResourceWarning 并使意图明确；
若上游认为这是噪音，该 hunk 可独立丢弃（与 §2.1 的性能修复无依赖）。

### 2.3 `num_workers` 默认值

`main.py:175` / `test.py:199` 原默认 `num_workers=2`。
每个样本要读一个 pickle + 一张 PNG，属 I/O 密集，2 个 worker 会饿住 GPU。
改为 `min(8, os.cpu_count())`。

### 2.4 清洁度

- 删除未使用的 `from functools import lru_cache`（`sequence_retriver.py:8`）
- 删除 `data_loader.py:411` 重复计算的 `base_file_id`
  （`sequence_retriever.get_sequence()` 已返回该值）

---

## 三、验证记录

### 3.1 补丁可应用性

```
git apply --check  →  exit=0
```

### 3.2 语法

```
python -m py_compile data_loader/sequence_retriver.py data_loader/data_loader.py main.py
→  exit=0
```

### 3.3 功能验证（`tools/verify_patch.py`，全部通过）

| 检查项 | 结果 |
|---|---|
| 输入 480×640 → 输出形状 `[10,3,224,224]` | ✅ |
| 数值落在 [0,1] | ✅ |
| dtype = float32 | ✅ |
| 内存连续（避免下游拷贝） | ✅ |
| 预 resize 输入 → 形状正确 | ✅ |
| 默认路径 == 快路径（补丁已生效） | ✅ 完全一致 |
| `VIDEO_CAD_FORCE_SLOW=1` 可回退旧实现 | ✅ |
| 句柄泄漏已修（`with` + `pickle.load(fh)`） | ✅ |
| 未使用的 `lru_cache` import 已删 | ✅ |

### 3.4 实测加速（同一脚本输出）

```
强制慢路径(PIL 逐帧)       70.31 ms
默认路径(补丁后快路径)      28.43 ms   加速 2.47x
预 resize 输入(零 resize)  16.82 ms   加速 4.18x
```

（此处数字略高于 §2.1 的基准表，因为基准表用的是固定 repeats 的独立测量；
两者量级一致，都体现 2~4× 的收益。）

### 3.5 验证后状态

验证完成后对上游克隆执行 `git checkout -- .` **还原干净**，
本补丁不会在工作副本留下未提交改动。

---

## 四、未包含在补丁里的更大优化（需改数据管线）

1. **换 LMDB**：当前每样本读独立的 pickle + PNG，随机读放大严重。
   上游 `generate_dataset.py:9` 已 `import lmdb` 却未接上——
   这是设计好但没完成的加速路径。
2. **帧存 JPEG 而非 PNG**：224×224 的帧存 PNG 体积远大于 JPEG，
   I/O 是瓶颈时可显著降低读放大。
3. **预 resize 后落盘**：见 §2.1，一次性代价换每轮收益。

这三项都需要原始视频或重跑数据生成管线，故未纳入补丁。

---

## 五、一处待核实的疑点

```python
# generate_dataset.py:14-17
fps = cap.get(cv2.CAP_PROP_FPS)
frame_idx = int(timestamp)   # int(round(timestamp * fps))   ← 被注释掉的写法
```

把浮点秒直接截断为帧号，而注释掉的 `int(round(timestamp * fps))` 才是正确换算。
**若视频 fps ≠ 1，帧定位会错位**——VideoCAD 采集为 60 FPS，故很可能存在偏差。

未下载原始视频，无法实测确认。**如果你有原始数据，这是值得优先核实的一处。**
