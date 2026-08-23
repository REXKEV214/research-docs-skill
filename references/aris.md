# Phase: Aris

**目标**：扫描 ARIS skills 产出的英文文档，翻译为中文，归档到 `docs/aris/` 统一管理。

`docs/aris/` 不存在时按需创建；默认 `init` 不预建。本流程需要同步索引时遵循 [schema.md](schema.md)，不读取其他 phase。

**参数**：`/research aris [--dry-run] [--force]`

- `--dry-run`：只输出将要处理的文件列表，不执行任何写入
- `--force`：跳过去重过滤，强制重新处理所有文件

## ARIS 产出路径注册表

| 扫描位置 | 目标文件 | 归入 `docs/aris/` 子目录 |
|---------|---------|------------------------|
| 项目根 | `IDEA_REPORT.md`, `IDEA_CANDIDATES.md` | `ideas/` |
| 项目根 | `NARRATIVE_REPORT.md`, `STORY.md` | `narrative/` |
| 项目根 | `PAPER_PLAN.md`, `refine-logs/FINAL_PROPOSAL.md` | `planning/` |
| 项目根 + `refine-logs/` | `EXPERIMENT_LOG.md`, `EXPERIMENT_TRACKER.md`, `EXPERIMENT_PLAN.md`, `CLAIMS_FROM_RESULTS.md` | `experiments/` |
| 项目根 + `refine-logs/` | `AUTO_REVIEW.md`, `REVIEW_SUMMARY.md` | `reviews/` |
| `refine-logs/` | `REFINEMENT_REPORT.md` | `methods/` |
| `research-wiki/` | `papers/`, `ideas/`, `gap_map.md`, `index.md` 等 | `wiki/` |
| `paper/sections/` | 每个 `*.tex` 文件独立翻译为独立 `.md` 文件 | `paper/`（**禁止合并**，每个 section 一个文件） |
| 项目根 | `findings.md` | `findings/` |

**跳过的文件**（运行时状态，不属于文档）：
- `REFINE_STATE.json`、`REVIEW_STATE.json`
- `paper/` 原始 LaTeX 文件（保持原位不动，仅翻译内容到 `docs/aris/paper/`）
- `figures/`（与 paper 编译绑定，保持原位）

## 执行流程

**a. 扫描**

按注册表扫描所有已知路径，收集存在的 ARIS 产出文件列表。

`paper/sections/` 目录需展开为单个 `.tex` 文件列表（如 `introduction.tex`、`method.tex`），每个文件独立处理。

> ⚠️ **禁止将多个 `.tex` 文件合并为一个翻译文件**。每个 `.tex` 文件必须产出独立的翻译文件，不得出现"论文正文.md"这样的合并文件。

如果使用 `--dry-run`，输出将要处理的文件列表和目标路径，不执行任何写入，然后结束。

**b. 去重过滤**

如果使用 `--force`，跳过此步骤。

对扫描结果中的每个文件，按以下规则判断是否需要处理：

**非 paper/sections/ 文件**（单文件类型，如 `IDEA_REPORT.md`、`AUTO_REVIEW.md` 等）：
- 扫描 `docs/aris/` 下所有 `.md` 文件的 `original_path` frontmatter 字段
- 如果该路径已存在于已处理集合中，跳过

**paper/sections/*.tex 文件**（内容频繁局部修改）：
- 对每个 `.tex` 文件，读取其当前 mtime（`stat -f %m` on macOS / `stat -c %Y` on Linux）
- 扫描 `docs/aris/paper/` 下对应 section 的翻译文件（匹配 `original_path` 字段），读取其 `ingested` frontmatter 时间戳
- 如果 `.tex` 文件的 mtime 早于或等于最近一次翻译的 `ingested` 时间，跳过该文件
- 如果 mtime 更新，说明文件有改动，加入处理队列

注意：`original_path` 必须是具体文件路径（如 `paper/sections/introduction.tex`），不能是通配符。

- 如果所有文件都已是最新，输出"无新文件需要处理"并结束
- 输出将要处理的文件列表（含原因：新文件/内容已更新），供用户确认

**c. 翻译**

逐个读取文件内容，将英文翻译为中文：
- 保留专业术语原文标注，格式：`中文术语(English Term)`，如 "注意力机制(attention mechanism)"
- 保留表格、代码块、公式等结构化内容的格式
- 对 `paper/sections/*.tex`：每个 `.tex` 文件单独翻译为一个 markdown 文件，文件名格式 `YYYY-MM-DD-HHMM-{section-name}.md`（如 `introduction.tex` → `2026-04-13-1200-introduction.md`），忽略 LaTeX 排版命令，只提取正文内容

> ⚠️ **禁止将多个 section 合并翻译为一个文件**。每个 `.tex` 对应一个独立的 `.md`，不得合并。

**d. 写入**

在 `docs/aris/` 对应子目录下创建中文版文件：
- 文件名格式：`YYYY-MM-DD-HHMM-slug.md`（与 handoff 命名规范一致）
- slug 为原文件名的简短描述，如 `IDEA_REPORT.md` → `2026-04-09-1530-想法报告.md`
- 每个文件添加 frontmatter：

```yaml
---
updated: YYYY-MM-DD
status: active
scope: ARIS 产出翻译
source: aris
ingested: YYYY-MM-DD HH:MM
original_path: 原始文件具体路径（如 paper/sections/introduction.tex，禁止使用通配符）
translated: true
---
```

> ⚠️ **禁止覆盖已有翻译文件**。内容更新时必须生成新的带时间戳文件，旧版保留。git 保留历史不是覆盖的理由。
>
> ⚠️ **`original_path` 禁止使用通配符**（如 `paper/sections/*.tex`）。必须是具体文件路径（如 `paper/sections/introduction.tex`），否则去重逻辑失效。

- 按需创建子目录（如 `docs/aris/ideas/` 不存在则创建）

**e. 生成完整版**

将本次所有已翻译的文件内容物理拼贴为一个完整版文档，放在 `docs/aris/` 根目录：

- 文件名：`YYYY-MM-DD-HHMM-完整翻译.md`（每次生成新文件，禁止覆盖旧版）
- 按以下顺序拼接各部分（跳过本次未处理的类别）：
  1. 想法报告（ideas/）
  2. 研究叙事（narrative/）
  3. 论文规划（planning/）
  4. 方法迭代（methods/）
  5. 实验记录（experiments/）
  6. 审稿记录（reviews/）
  7. 论文正文（`paper/`，从 `docs/aris/paper/` 下各 section 翻译文件读取，按 section 文件名字母顺序拼接，每个 section 用三级标题分隔）
  8. 研究发现（findings/）
  9. 知识库（wiki/）
- 每个类别用二级标题分隔，如 `## 论文规划`；内容为对应翻译文件的正文（去掉 frontmatter）
- 文件顶部添加 frontmatter：

```yaml
---
updated: YYYY-MM-DD
status: active
scope: 本次 aris 所有翻译的合并完整版（一站式阅读，内容与子文件重复属预期行为）
source: aris
ingested: YYYY-MM-DD HH:MM
translated: true
---
```

**f. 清理（不自动执行）**

将项目根目录散落的原始英文 ARIS 产出文件（不含 `refine-logs/`、`research-wiki/`、`paper/` 目录）列出，给出**手动归档建议命令**：

```
ℹ️  以下原始英文 ARIS 文件仍在项目根，建议手动归档（保留原文备查）：
    mkdir -p archive/docs/aris-raw
    mv IDEA_REPORT.md archive/docs/aris-raw/
    mv AUTO_REVIEW.md archive/docs/aris-raw/
    ...
```

**skill 不自动 `mv`**——archive 生命周期由用户管理。如果没有需要清理的文件，跳过此步骤。

**g. 日志**

在 `docs/aris/ingest-log.md` 追加本次操作记录：

```markdown
## YYYY-MM-DD HH:MM

处理文件：
- IDEA_REPORT.md → docs/aris/ideas/YYYY-MM-DD-HHMM-想法报告.md
- paper/sections/introduction.tex → docs/aris/paper/YYYY-MM-DD-HHMM-introduction.md
- ...
完整版：docs/aris/YYYY-MM-DD-HHMM-完整翻译.md
```

**h. 更新索引**

- 更新 `docs/aris/README.md`：列出所有子目录及其中的文件，以及完整版文件入口
- 因新增了文件，按 [schema.md](schema.md) 的索引同步规则更新 `docs/README.md`

**i. 输出**

输出本次处理的文件列表和目标路径，供用户确认。
