# Phase: Init

`/research init [<project-name>] [--full]`

先读取 [schema.md](schema.md)。默认创建最小结构；只有显式 `--full` 才预建可选模块。所有写入前展示计划并确认。

## 1. 判断场景

- `docs/` 不存在：新建。
- `docs/README.md` 的 `schema_version` 小于 4 或缺失：迁移。
- `schema_version: 4`：只报告缺失的必需文档骨架和项目入口状态，不创建可选模块。

项目名优先使用参数，否则使用当前目录名。读取已有 `README.md`、`CLAUDE.md`、`AGENTS.md` 和顶层配置，已存在的用户内容不覆盖。

## 2. 新建计划

最小模式创建：

- Git 仓库（仅当 `.git/` 不存在时执行 `git init -b main`）。
- `docs/README.md`（`schema_version: 4`）、`docs/project/overview.md`。
- `docs/handoffs/history/resolved/.gitkeep`、`docs/handoffs/history/superseded/.gitkeep`、`archive/docs/.gitkeep`。
- 缺失时创建根 `README.md` 和 `.gitignore`。若 `CLAUDE.md`、`AGENTS.md` 两者都不存在，则冷启动创建两者；已有任意一个时只维护实际存在者，不补建另一个。

`--full` 额外创建 `paper-plan.md`、evaluation/methods/data 骨架、dashboard、journal、ARIS 与 scratch 入口。默认模式不创建这些空模块。

## 3. `.gitignore` 基线

新文件使用以下原则；现有 `.gitignore` 只追加明确缺失且不冲突的行，不机械复制整块：

```gitignore
# OS / Python / secrets / logs
.DS_Store
__pycache__/
*.py[cod]
.venv/
.ipynb_checkpoints/
.env
/logs/

# large runtime data
/data/
/hf_staging/

# scratch
/scratch/*
!/scratch/README.md

# document archive is tracked; other archive classes stay local
/archive/*
!/archive/docs/
!/archive/docs/**

# LaTeX build outputs
*.aux
*.log
*.out
*.fls
*.fdb_latexmk
*.synctex.gz
*.bbl
*.blg
/paper/*.pdf
```

不得默认忽略 `/docs/` 或整个 `/paper/`。`.tex`、`.bib`、`.sty`、`.cls` 和必要图片默认可跟踪；正式 PDF 由 retire 归档保存。

如果现有规则包含 `/docs/`、`/paper/` 或无法重新纳入 `archive/docs/**` 的 `/archive/`，列出规则、受影响的重要文件和精确修改计划，等待确认后再改。

## 4. 项目入口

先扫描项目根的 `CLAUDE.md` 与 `AGENTS.md`：

- 两者都不存在：这是冷启动，确认后分别创建最小骨架。
- 只存在一个：只维护这个文件，不创建另一个。
- 两者都存在：分别维护两者。

对实际存在或本次冷启动创建的入口，只维护 `## Documentation` 和 `## Last Handoff` 两个 section，规则见 schema。入口链接同一个文档索引和 active handoff，但不互相覆盖，也不复制对方的其他项目规则。

两个最小骨架都包含：

```markdown
## Documentation

- [项目文档索引](docs/README.md)

## Last Handoff

- 当前无 active handoff
```

不得假设 Codex 会通过 `AGENTS.md` 自动读取 `CLAUDE.md`，也不得把 `AGENTS.md` 仅创建成 `@ CLAUDE.md` 指针。已有任一入口文件时，只更新实际存在者的上述两个受管 section，保留其余内容。

## 5. v1-v3 → v4 迁移

先输出 dry-run 计划，至少检查：

- `docs/handoffs/resolved/` → `docs/handoffs/history/resolved/`。
- `docs/handoffs/history/*.md` 按 frontmatter 状态分别迁入 `history/resolved/` 或 `history/superseded/`；状态无法判断时只报告。
- 仅包含 `@ CLAUDE.md` 指针、缺少受管 section 的旧 `AGENTS.md` → 独立的一等入口。
- 根目录多个 active handoff：按 handoff 流程合并未完成事项，原文件以 `resolved` 或 `superseded` 状态进入 history。
- `.gitignore` 是否错误忽略 docs、paper 源码或 archive/docs。
- 旧 `docs/archive/`、编号目录、SCREAMING_CASE 文件与散落 HTML。
- `docs/README.md` schema 版本和索引。

用户确认后优先使用 `git mv` 保留历史；未跟踪文件使用普通移动。迁移中不得删除内容，无法判断的事项保留并标记 `待确认`。

已有可选目录和文档不因 v4 的按需策略而删除。完成后写 `schema_version: 4`，并仅在路径发生变化时同步索引和项目入口。

## 6. 输出

报告新建、修改、移动、跳过的路径，以及仍需用户决定的冲突。不要默认建议立即创建 handoff 或 journal；让用户继续实际研究工作即可。
