# Schema v4

仅在初始化、迁移或需要判断文件职责时读取本文件。

## 最小结构

`/research init` 默认创建：

```text
项目根/
├── docs/
│   ├── README.md
│   ├── project/
│   │   └── overview.md
│   └── handoffs/
│       └── history/
├── archive/
│   └── docs/
├── CLAUDE.md
└── AGENTS.md
```

以下模块首次使用时再创建：

| 模块 | 创建时机 | 职责 |
|---|---|---|
| `docs/project/paper-plan.md` | 开始规划论文 | 论文定位、贡献、叙事、图表与时间线的唯一来源 |
| `docs/evaluation/results.md` | 首次记录结果 | 可被其他文档引用的实验数字权威 |
| `docs/methods/` | 首次正式记录方法 | 方法设计与约束的唯一来源 |
| `docs/journal/` | 首次 `/research log` | 可选的日期日志 |
| `docs/dashboards/` | 首次 dashboard 操作 | 可重建的机器渲染界面 |
| `docs/deliverables/` | 首次 freeze | 尚在使用期的不可变提交包 |
| `docs/aris/` | 首次 ARIS 归档 | ARIS 产出的中文归档 |
| `scratch/` | 首次创建一次性 HTML | gitignored 的临时界面 |

## 文档与交付物生命周期

```text
paper/（唯一活跃工作稿）
  → freeze
docs/deliverables/<slug>/（已提交、进入 Git）
  → retire
archive/docs/YYYY-MM-DD-<slug>/（冷归档）
```

Handoff 状态：

- `active`：当前唯一有效 handoff；根目录最多一个。
- `resolved`：所有后续事项已完成。
- `superseded`：未完成事项已迁入更新 handoff。

`resolved` 与 `superseded` 文件都进入 `docs/handoffs/history/`。

普通文档状态：`draft | active | stale | archived`。日期变旧不自动等于 `stale`；仅在内容与权威来源不一致或被显式标记时判定 stale。

## 单一来源

```text
原始 JSON / eval 产物
  ↓ 机器渲染
docs/dashboards/*.html（不可引用）
  ↓ 人工校对
docs/evaluation/results.md（数字权威）
  ↓ 链接
论文和其他文档
```

- 方法描述只在 `docs/methods/` 维护。
- 论文叙事只在 `docs/project/paper-plan.md` 维护。
- `overview.md` 只放状态、进度和入口，不复制数字、方法或叙事。
- `scratch/` 不进入权威链。

## 命名与 frontmatter

- 文件和目录使用 lowercase-kebab-case。
- 不用 `final-v2`、`results-v3` 等版本后缀表达历史；使用 Git 或带日期的不可变快照。
- Handoff：`YYYY-MM-DD-HHMM-slug.md`。
- 文档 frontmatter：

```yaml
---
updated: YYYY-MM-DD
status: active
scope: 本文档覆盖什么
out-of-scope: 本文档不覆盖什么
---
```

## 索引同步

只在新增、删除、移动文档或 dashboard 时更新 `docs/README.md`。内容更新不重建索引。

- 扫描 `docs/**/*.md` 和 `docs/dashboards/*.html`。
- 排除 `docs/handoffs/history/`。
- 保留 `docs/README.md` 的 `schema_version` 和其他 frontmatter。
- 其他文档链接到权威来源，不复制实验数字。

## 项目入口同步

`CLAUDE.md` 与 `AGENTS.md` 都是一等项目入口。两者的 research 管理区分别只保留短入口：

- `## Documentation`：链接到 `docs/README.md` 与实际存在的权威文件。
- `## Last Handoff`：最新 active handoff 的链接和一句状态摘要；不复制 handoff 全文，不列历史 handoff。

对两个文件分别只修改目标 section，不覆盖用户的其他内容。不得假设 `AGENTS.md` 会自动读取 `CLAUDE.md`，也不得用一个入口代替另一个；不存在的入口文件只由 `init` 创建。
