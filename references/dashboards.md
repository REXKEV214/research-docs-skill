# Phase: Dashboard

**目标**：管理 `docs/dashboards/` 下的 HTML 交互看板（L2 界面层），把实验数据的机器渲染、人工校对、论文引用三条链清晰分开。

`docs/dashboards/` 不存在时由首次 `new` 按需创建；默认 `init` 不预建。本流程需要同步索引时遵循 [schema.md](schema.md)。

**参数**：`/research dashboard [list|new <slug>|render <slug>|status]`

- `list`（或无参数）：列出所有已有 dashboard 和上次渲染时间
- `new <slug>`：创建生成器骨架和占位 HTML
- `render <slug>`：运行生成器重渲染
- `status`：检查每个 dashboard 的 stale 状态

---

## 核心概念

### Dashboard 在三档 HTML 中的位置

| 档 | 位置 | 特征 |
|---|---|---|
| L3 | `memebench-studio/` 等独立 app | 写回、复杂 join、多人长期用（skill 不管） |
| **L2** | **`docs/dashboards/`** | **重复使用、有固定数据源、值得维护生成器** |
| L1 | `scratch/` | 一次性、用完即走（skill 只管命名和归档入口） |

### Dashboard 三条硬约定

1. **成对存在**：每个 `<slug>.html` 必须有对应的 `render/<slug>.py` 生成器
2. **不被引用**：dashboard 是机器产物，论文和其他 MD 文档不引用 dashboard；需要权威数字走 `docs/evaluation/results.md`
3. **双击可开**：HTML 必须能直接 `file://` 打开，不依赖 dev server 或打包器

### 数字权威链中的位置

```
json / eval 产物（源头）
    ↓ 机器渲染
docs/dashboards/*.html（本 phase 管辖）
    ↓ 人工校对摘抄
docs/evaluation/results.md（被引用权威）
    ↓ 链接
其他文档
```

Dashboard 是**机器产物**，随时可以重建。它的价值是提供交互、可视化、过滤能力，不是作为引用源。

---

## 生成器约定

### 脚本结构

`docs/dashboards/render/<slug>.py` 最小可跑版本：

```python
"""Render dashboards/<slug>.html from <data sources>."""
from __future__ import annotations
import json
from pathlib import Path

# 源数据路径（相对项目根）
SOURCES = {
    "results": "data/output/comparison_report.json",
    # 其他源...
}

# 输出路径（与生成器成对）
OUTPUT = Path("docs/dashboards/<slug>.html")

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-50">
<div id="root" class="max-w-6xl mx-auto p-6"></div>
<script>
const DATA = {data_json};
// 渲染逻辑：读 DATA → 操作 #root
</script>
</body>
</html>
"""

def load_sources(root: Path) -> dict:
    data = {}
    for key, rel in SOURCES.items():
        with open(root / rel) as f:
            data[key] = json.load(f)
    return data

def render(root: Path) -> None:
    data = load_sources(root)
    html = HTML_TEMPLATE.format(
        title="<Dashboard Title>",
        data_json=json.dumps(data, ensure_ascii=False),
    )
    (root / OUTPUT).write_text(html, encoding="utf-8")
    print(f"wrote {OUTPUT}")

if __name__ == "__main__":
    render(Path.cwd())
```

### 输出要求

- **Inline data**：所有数据 `json.dumps` 嵌入 `<script>` 块，不做 `fetch`、不读本地文件
- **CDN 资源**：Tailwind 用 `cdn.tailwindcss.com`；图表库用 `unpkg` / `cdn.jsdelivr.net`
- **单文件**：整个 dashboard 是一个 `.html`，双击在浏览器打开即可用
- **完整覆盖**：每次 render 整个覆盖输出 HTML，不做增量
- **中文优先**：UI 文字用中文，保留英文技术术语

### 命名规则

- 成对：`docs/dashboards/<slug>.html` ↔ `docs/dashboards/render/<slug>.py`
- slug 用 lowercase-kebab-case：`results`、`vikr-coverage`、`kar-failures`
- 一个生成器只产出一个 HTML，不做多输出

---

## 执行流程

### `list`（或无参数）

**a. 扫描**

列出 `docs/dashboards/*.html` 和 `docs/dashboards/render/*.py`，按 slug 配对。

**b. 输出表格**

```
| slug | html | 生成器 | 上次渲染 | 状态 |
|------|------|--------|---------|------|
| results | ✅ | ✅ | 2026-04-27 14:30 | ok |
| vikr-coverage | ✅ | ❌ | 2026-04-20 09:15 | 缺生成器 |
| kar-failures | ❌ | ✅ | — | 未渲染 |
```

**状态枚举**：
- `ok`：成对且 html 比生成器新
- `stale`：生成器比 html 新（生成器改了未重渲染）
- `缺生成器`：html 存在但无对应 `.py`
- `未渲染`：生成器存在但无 html

**c. 无 dashboard 时**

输出：`docs/dashboards/ 为空。运行 /research dashboard new <slug> 创建第一个 dashboard。`

---

### `new <slug>`

**a. 校验 slug**

- 必须是 lowercase-kebab-case
- 不能已存在：检查 `docs/dashboards/<slug>.html` 和 `render/<slug>.py`

冲突时报错并退出。

**b. 创建骨架**

写两个文件（目录不存在则创建）：

1. `docs/dashboards/render/<slug>.py`：上文"脚本结构"模板，`<slug>` 已替换
2. `docs/dashboards/<slug>.html`：占位 HTML，提示"未渲染，运行 `/research dashboard render <slug>` 生成"

占位 HTML 内容：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title><slug></title>
<script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-50 flex items-center justify-center h-screen">
<div class="text-center text-slate-500">
  <div class="text-lg mb-2">占位 dashboard</div>
  <div class="text-sm">运行 <code class="bg-slate-200 px-2 py-0.5 rounded">/research dashboard render &lt;slug&gt;</code> 生成内容</div>
</div>
</body>
</html>
```

**c. 提示**

输出：
- 骨架已创建路径
- 需要手动补充：`SOURCES` 数据路径、`HTML_TEMPLATE` 的 `<script>` 渲染逻辑
- 补完后运行 `/research dashboard render <slug>`

**d. 同步 README 索引**

新 dashboard 应按 [schema.md](schema.md) 的规则进入 `docs/README.md` 索引。

---

### `render <slug>`

**a. 校验**

- 生成器存在：`docs/dashboards/render/<slug>.py`
- 生成器声明的 `SOURCES` 中每个路径可读

其中一个不满足则报错退出（指明缺哪个）。

**b. 运行生成器**

```bash
python3 docs/dashboards/render/<slug>.py
```

从项目根运行，工作目录就是项目根。

**c. 校验输出**

- `docs/dashboards/<slug>.html` 存在且非空
- 文件大小 > 500 字节（防止写入失败或空模板）

**d. 提示**

输出：
- 渲染完成路径和文件大小
- 提示用户：如果这批数字要被论文或其他文档引用，记得同步更新 `docs/evaluation/results.md`

**注意**：render 不自动更新 `results.md`。人工校对是权威链的关键环节，skill 不做机器替代。

---

### `status`

**a. 扫描所有 dashboard 对**

对每个 `docs/dashboards/<slug>.html`：
- 读取 `<slug>.html` mtime
- 读取 `render/<slug>.py` mtime
- 读取生成器 `SOURCES` 中每个数据文件的 mtime

**b. 判定 stale**

dashboard 视为 stale 当：
- 生成器 mtime > html mtime（生成器改了没重渲染）
- 任一源数据 mtime > html mtime（数据更新了没重渲染）

**c. 输出报告**

```
| slug | html mtime | 生成器 mtime | 最新源数据 mtime | stale | 建议 |
|------|-----------|-------------|-----------------|-------|------|
| results | 2026-04-27 14:30 | 2026-04-20 10:00 | 2026-04-28 09:00 | ⚠️ | 源数据已更新，建议 render |
| vikr-coverage | 2026-04-20 09:15 | 2026-04-25 16:00 | 2026-04-18 12:00 | ⚠️ | 生成器已改，建议 render |
| kar-failures | 2026-04-26 11:00 | 2026-04-26 11:00 | 2026-04-26 10:50 | ✅ | 无需重渲染 |
```

**d. 汇总**

输出：`N 个 dashboard 中 M 个 stale。运行 /research dashboard render <slug> 重渲染。`

---

## 与其他 Phase 的协作

| Phase | 协作点 |
|-------|-------|
| Init | 仅 `--full` 预建 dashboard；默认由首次 `new` 按需创建 |
| Status | `--full` 扫描 dashboards，标记缺输出或缺生成器 |
| Schema | README 索引扫描 `docs/dashboards/*.html`，类型列标 `HTML` |

---

## 注意事项

- **不要写回数据**：dashboard 只读源数据，不修改 `data/output/`、`data/annotations/` 等
- **不要跨引用**：一个 dashboard 只负责一个主题；想要 cross-view 做独立的 dashboard
- **源数据路径用相对路径**：`SOURCES = {"results": "data/output/..."}`，从项目根起算；生成器在根目录运行
- **生成器自包含**：除了 stdlib 和已有项目依赖外，不引入新依赖
- **不追求完美**：dashboard 是研究工具不是产品。能回答问题就行，设计和交互不用过度打磨
