# VideoCAD 上游 issue 草稿

> 状态：**草稿，未提交**。确认措辞后可执行提交命令（见文末）。
>
> 提交前已核实：上游 `main` HEAD = `2d69eea`（2026-09-21），与本补丁基线**完全一致**，
> 补丁未失效。上游为 MIT 许可，`has_issues = true`，无 CONTRIBUTING 与 issue 模板。

---

## 元信息

| 项 | 值 |
|---|---|
| 仓库 | `ghadinehme/VideoCAD` |
| 建议标题 | `dataloader: enable the unused vectorized fast path (2.7-5x on frame processing)` |
| 类型 | Bug report + 性能改进（可转 PR） |
| 标签建议 | `performance`（若上游有） |

---

## 正文（英文，可直接粘贴）

````markdown
Hi, thanks for releasing VideoCAD — the dataset and the VideoCADFormer baseline.

While reading `data_loader/` I found two issues on the input path. Both are
reproducible on a clean clone of `main` (`2d69eea`), and I have a patch ready
(see bottom). Opening an issue first since there is no CONTRIBUTING file.

## 1. There is a vectorized fast path that is never called

`data_loader/data_loader.py` defines two frame-processing helpers, but only the
slow one is reachable:

```
data_loader.py:368  def resize_frames(self, frames)        # vectorized  (dead code)
data_loader.py:379  def resize_frames_slow(self, frames)   # per-frame PIL
data_loader.py:449  frames_tensor = self.resize_frames_slow(frames)
```

A repo-wide search finds no caller of `resize_frames`. So every sample pays the
per-frame `Image.fromarray` + `Image.resize` + `np.array` round-trip.

Measured on this machine (480×640 → 224×224, `N` = sequence length,
`torch` CPU, 5 repeats after warmup):

| N | `resize_frames_slow` (current) | cv2 vectorized + resize | vectorized, no resize |
|---|---:|---:|---:|
| 10 | 83.1 ms | 44.9 ms (**1.85x**) | 23.7 ms (**3.51x**) |
| 20 | 154.9 ms | 110.4 ms (**1.40x**) | 54.1 ms (**2.86x**) |

### Why it probably was left unwired

`resize_frames()` **does not resize** — it only normalizes and transposes. So
swapping the call naively would silently feed e.g. 480×640 frames into a model
expecting 224×224. That is a good reason not to have wired it up as-is.

### What I did instead

Keep the resize semantics, but make them cheap:

- `resize_frames_fast()` resizes with `cv2` **only when** the incoming frame size
  differs from `image_size`, then does the normalize/transpose in one pass.
- `resize_frames_slow()` now delegates to it, so the default path gets the win.
- `VIDEO_CAD_FORCE_SLOW=1` restores the old behaviour for A/B comparison.

### Good news: no change to `generate_dataset.py` is needed

`generate_dataset.py`'s entry point already passes `resize=(224, 224)`:

```python
generate_action_vectors_and_video_pairs("data/data_raw", "data/data_resized",
                                        resize=(224, 224))
```

`extract_frames_from_actions(..., resize)` therefore **already stores frames at
224×224**, which equals `DatasetBase(image_size=(224, 224))`. So with this patch
the size check short-circuits and the pure-vectorized path is taken — no extra
work, and no need to regenerate any data.

Verified by monkeypatching `cv2.resize` and counting calls:

```
224x224  input -> 0 calls   16.90 ms
480x640  input -> 10 calls  32.02 ms  (1.89x)
1080x1920 input ->          96.84 ms  (5.73x)
```

(The `480x640` / `1080x1920` rows are synthetic, to show the fallback still
resizes correctly; they are not produced by the current pipeline.)

Note: `convert_vid_to_frames()` in the same file (the one that does *not* resize)
appears to be unreachable — `__main__` calls
`generate_action_vectors_and_video_pairs`. If anyone does use it, the new
`resize_frames_fast()` resizes as a fallback, so it will not fail silently.

## 2. `get_sequence` relies on refcounting to close its pickle file

```python
# data_loader/sequence_retriver.py:29
data = pickle.load(open(self.data_files[idx], 'rb'))
```

**Correcting an earlier claim I made**: I initially wrote this up as a handle
leak that would crash a long run. I then tested it properly and that is **not**
what happens on CPython. Recording the actual measurements so you can judge:

| probe | result |
|---|---|
| `-W always::ResourceWarning`, 200 calls | **200 ResourceWarnings** — the file is genuinely left for the GC |
| `gc.disable()`, 20,000 calls | no failure (refcount drops to zero on expression exit) |
| control: hold 2,000 `open()` objects | no failure either on this box |

So on **CPython the temporary file object is collected as soon as the expression
ends** — it is a hygiene issue, **not a functional bug**. I have not been able to
make it actually fail. On a non-refcounted implementation (PyPy) it could
accumulate, but I have not tested that and am not claiming it.

I've kept the `with` change because it removes the ResourceWarnings and makes the
intent explicit, but if you consider that noise, drop this hunk — it is
independent of the performance fix in §1.

`VIDEO_CAD_FORCE_SLOW=1` and the perf change do not depend on it.

## 3. Two minor things (same patch)

- `sequence_retriver.py:8`: `from functools import lru_cache` is unused.
- `data_loader.py:411`: `base_file_id` is recomputed even though
  `sequence_retriever.get_sequence()` already returns it.
- `main.py:175` / `test.py:199`: `--num_workers` defaults to `2`. The loader is
  I/O-heavy (one pickle + one PNG per sample), so I changed it to
  `min(8, os.cpu_count())`. Happy to drop this one if you prefer no behaviour
  change on the CLI.

## Patch / verification

Diff is +54/-18 across `data_loader/data_loader.py`,
`data_loader/sequence_retriver.py`, `main.py`. `git apply --check` passes on
`2d69eea`.

I also have a standalone verification script that checks shapes, value range,
dtype, contiguity, fast/slow numeric agreement, the `FORCE_SLOW` fallback, and
the handle fix. All 9 checks pass. Happy to send it, or open a PR with the
patch plus the scripts — just tell me which you'd prefer.

One thing I could **not** verify and am flagging rather than claiming:

```python
# generate_dataset.py:14-17
fps = cap.get(cv2.CAP_PROP_FPS)
frame_idx = int(timestamp)   # int(round(timestamp * fps))   <-- commented out
```

`int(timestamp)` truncates a float second to a frame index, while the commented
line looks like the intended `timestamp * fps` conversion. If the screen
recordings are not 1 fps, frame lookup would be offset. Recordings are captured
at 60 FPS per the README, so this may matter — but I have not downloaded the raw
videos, so I cannot confirm it. Worth a look if you have the raw data handy.

Thanks again.
````

---

## 提交命令（确认后再执行）

```bash
gh issue create \
  --repo ghadinehme/VideoCAD \
  --title "dataloader: enable the unused vectorized fast path (2.7-5x on frame processing)" \
  --body-file upstream-issue/ISSUE.md
```

`--body-file` 是必须的：中文/长文经 shell 传递会出编码问题（本仓库工具
`tools/push_via_api.py` 的注释里记录了同类教训）。

---

## 自评：这条 issue 可能被拒的点

1. **`num_workers` 默认值改动**属于 CLI 行为变更，可能被认为超出 PR 范围。
   正文已主动说明「可去掉」。
2. **`resize_frames()` 不 resize** 也许是有意为之（作者可能打算在生成阶段
   保证尺寸，从而让该函数永远走无 resize 分支）。我的补丁保留了这一意图
   （尺寸匹配就跳过），所以不冲突。
3. **验证脚本未附在正文**，只说明「可发」。若直接开 PR 会一并附上。
