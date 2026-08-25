# Phase: Retire

管理已经正式提交且不再继续使用的论文、课程报告等学术交付物。默认来源为 `paper/`，也可以显式指定项目内其他目录，例如 `term_paper/`。本流程只用于科研和论文项目，不用于普通工程项目的发布包或文档归档。详细目录职责见 [schema.md](schema.md)。

底层确定性操作使用：

```bash
python3 <skill-dir>/scripts/retire.py --root "$PWD" --slug <slug> ...
```

## `/research retire <slug> [source-dir] [--pdf <path>] [--main-tex <path>]`

### 1. 确认交付身份和来源

1. 确认交付物已经实际提交，且这份工作稿不再继续编辑。未确认实际提交 PDF 时停止。
2. `source-dir` 缺省时使用 `paper/`；用户显式给出 `term_paper/` 等项目内目录时，以该目录为准。存在多个可能来源且无法从上下文唯一判断时，先询问用户。
3. 明确这份交付物的身份：项目做什么、归档版本是什么、是否实际提交、提交到哪里，以及它和其他草稿或最终版本的关系。
4. 校验 slug 为 lowercase-kebab-case，目标 `archive/docs/paper/YYYY-MM-DD-<slug>/` 不存在且不会被 Git 忽略。

### 2. 智能体验证源码和提交 PDF

`retire` 默认采用混合模式：智能体负责理解项目并验证交付物，`retire.py` 负责路径约束、文件清单、原子复制和校验和。不得只凭文件存在或退出码推断验证通过。

1. 阅读 source 内与构建有关的文件，例如 `README.md`、`Makefile`、`.latexmkrc`、主 TeX 文件和构建脚本，确定项目自己的构建入口和依赖。
2. 建立源码清单。除了 TeX、BibTeX、样式和图片，还要保留复现所需的 README、构建脚本、图表脚本、模板和生成提示词。默认规则未覆盖的必要文件用 `--include <relative-path>` 显式加入。
3. 在 source 的隔离副本中运行项目原生构建命令，不在活跃工作稿上制造或覆盖构建产物。
4. 按项目类型检查构建成功、未解析引用或引文、页数和页面尺寸、字体嵌入等。需要确认提交 PDF 与源码对应时，可比较提取文本或逐页栅格结果。可复现 PDF 因时间戳等元数据导致 SHA-256 不同，不单独视为失败。
5. 计算实际提交 PDF 的 SHA-256，并写入结构化验证报告。`status: passed` 只用于所有列出的检查均通过；验证失败时停止归档。确实无法运行验证时写 `status: not-run`，说明原因，并在用户确认后配合 `--allow-unverified`。

验证报告使用 UTF-8 JSON：

```json
{
  "schema_version": 1,
  "status": "passed",
  "method": "agent-isolated-build",
  "submitted_pdf_sha256": "<64 位小写 SHA-256>",
  "build_command": [
    "latexmk -xelatex -interaction=nonstopmode -halt-on-error main.tex"
  ],
  "build_cwd": "tex",
  "checks": [
    {
      "name": "isolated-build",
      "status": "passed",
      "detail": "隔离构建成功，无未解析引用或引文"
    },
    {
      "name": "submitted-pdf",
      "status": "passed",
      "detail": "19 页 A4，字体全部嵌入"
    }
  ]
}
```

- `method` 使用 lowercase-kebab-case。
- `build_cwd` 是相对 source 的现存目录，source 根目录写 `.`。
- `build_command` 逐项记录实际执行的命令；不把自然语言说明混入命令。
- `checks` 的每项都必须有具体 `name`、`status` 和 `detail`。整体为 `passed` 时，不得包含 `not-run` 检查。
- 报告中的 `submitted_pdf_sha256` 必须匹配本次归档的 PDF；脚本会重新计算并拒绝不一致的报告。

### 3. 编写归档 README 正文

智能体根据实际项目编写 README 正文，不使用只有路径、commit 和校验状态的通用占位说明。正文必须以准确的论文或交付物名称作为一级标题，并包含以下二级标题：

```markdown
# <论文或交付物名称>

## 项目简介
## 版本定位
## 归档内容
## 编译与复现
## 验证
## 与其他版本的关系
## 权威来源
```

这七个章节必须按上述顺序各出现一次，且每节都要有正文；代码块中的同名标题不计入结构。

内容要求：

- `项目简介`：说明研究问题、数据或方法，不只复述论文标题。
- `版本定位`：明确是 ARIS 草稿、投稿版本、课程实际提交版本或其他具体身份；实际未提交的版本不得写成正式提交。
- `归档内容`：解释 `submitted.pdf` 和 `source/` 中关键文件或目录的用途。
- `编译与复现`：写出依赖、工作目录、完整命令和输出位置；命令必须与验证报告一致。
- `验证`：记录隔离构建、PDF 检查和必要的内容对应性检查，不夸大未执行的验证。
- `与其他版本的关系`：链接并区分已知草稿、投稿版或最终版。
- `权威来源`：说明归档是历史交付证据；实验数字、方法和当前论文规划仍由项目 `docs/` 中的权威文档维护。

README 正文单独保存为 UTF-8 Markdown 文件，交给脚本与元数据合并。

### 4. Dry-run 和原子归档

默认 PDF 为 `<source-dir>/main.pdf`；不存在时停止并让用户给出 `--pdf`。主文件默认 `main.tex`，其他布局使用 `--main-tex` 指定相对 source 的路径。

先运行不带 `--apply` 的 dry-run：

```bash
python3 <skill-dir>/scripts/retire.py \
  --root "$PWD" \
  --source term_paper \
  --slug <slug> \
  --pdf term_paper/<submitted.pdf> \
  --main-tex tex/main.tex \
  --verification-report <verification.json> \
  --readme-body <archive-readme.md>
```

复核输出中的最终 PDF、source、将收录源码、排除项、Git commit、dirty 状态、验证方法和总大小。用户确认后使用同一组参数增加 `--apply`。脚本在归档父目录中暂存，复制和校验完成后原子移动到目标；不得覆盖已有归档。

若 dry-run 报告 `VERIFICATION.json` 会被 Git 忽略，检查项目是否有全局 `*.json` 规则；在用户确认后增加仅针对 `/archive/docs/paper/**/VERIFICATION.json` 的反忽略规则，再重新 dry-run。不要使用强制 add 绕过项目规则。

`--verification-report` 与 `--readme-body` 必须成对提供。直接调用脚本且不提供这两个参数时，会保留内置 LaTeX 验证作为兼容路径；skill 执行 `/research retire` 时优先使用上述混合模式。

skill 默认混合模式生成的归档包固定为：

```text
archive/docs/paper/YYYY-MM-DD-<slug>/
├── README.md
├── VERIFICATION.json
├── submitted.pdf
├── source/
└── SHA256SUMS
```

`SHA256SUMS` 覆盖 `README.md`、`VERIFICATION.json`、`submitted.pdf` 和 `source/` 中全部文件。full audit 会同时复核报告 schema、提交 PDF 哈希绑定，以及 README 中的验证状态和方法。源码候选默认包括 `.tex/.bib/.sty/.cls/.bst`、LaTeX 配置和图片；排除编译缓存、顶层中间 PDF、review/audit 状态文件和输出目录。作为源码依赖的顶层 PDF 用 `--include <relative-path>` 显式加入。单文件达到 100 MiB 时拒绝；总包超过 50 MiB 时警告。

### 5. 提交和可选清理

归档成功后只展示 `archive/docs/paper/YYYY-MM-DD-<slug>/` 的精确 Git diff；确认后仅暂存该目录并创建一次归档 commit，不得顺带提交工作树中的其他改动。

脚本不删除 source。归档验证和提交完成后，单独展示已覆盖源码和构建垃圾清单；再次确认后才优先移入系统废纸篓，不执行裸 `rm -rf`。

退役不会修改 `results.md`、方法文档或论文叙事。归档包是历史提交证据，不是研究权威来源。
