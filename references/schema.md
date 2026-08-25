# Schema v4

仅在初始化、迁移或需要判断文件职责时读取本文件。

## 最小结构

`/research init` 默认创建以下文档骨架。入口文件按项目现状处理：冷启动时两者都不存在才创建两者；已有任意一个时只维护实际存在者。

```text
项目根/
├── docs/
│   ├── README.md
│   ├── project/
│   │   └── overview.md
│   └── handoffs/
│       └── history/
│           ├── resolved/
│           └── superseded/
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
| `docs/aris/` | 首次 ARIS 归档 | ARIS 产出的中文归档 |
| `scratch/` | 首次创建一次性 HTML | gitignored 的临时界面 |

## 文档与交付物生命周期

```text
paper/（默认活跃工作稿）或显式指定的项目内 source/
  → retire
archive/docs/paper/YYYY-MM-DD-<slug>/（不可变冷归档）
```

`retire` 只处理论文、课程报告等学术交付物；普通工程项目的发布包和工程文档不进入这条生命周期。归档包保存提交 PDF、可复现源码、项目化 README、结构化验证报告和 SHA-256 清单。

Handoff 状态：

- `active`：当前唯一有效 handoff；根目录最多一个。
- `resolved`：所有后续事项已完成。
- `superseded`：未完成事项已迁入更新 handoff。

`resolved` 文件进入 `docs/handoffs/history/resolved/`；`superseded` 文件进入 `docs/handoffs/history/superseded/`。`history/` 根目录不直接存放 handoff。

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
- 排除 `docs/handoffs/history/` 及其全部子目录。
- 保留 `docs/README.md` 的 `schema_version` 和其他 frontmatter。
- 其他文档链接到权威来源，不复制实验数字。

## 项目入口同步

`CLAUDE.md` 与 `AGENTS.md` 都可以独立作为项目入口。每次同步先扫描项目根，只处理实际存在的入口：只有 `CLAUDE.md` 就只更新它，只有 `AGENTS.md` 就只更新它，两者都有才同时更新。各入口的 research 管理区只保留短入口：

- `## Documentation`：链接到 `docs/README.md` 与实际存在的权威文件。
- `## Last Handoff`：最新 active handoff 的链接和一句状态摘要；不复制 handoff 全文，不列历史 handoff。

对实际存在的文件分别只修改目标 section，不覆盖用户的其他内容。`update`、`handoff` 和其他普通流程不得创建缺失入口；只有显式 `init` 在两个入口都不存在的冷启动场景创建两者。
