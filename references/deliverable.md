# Phase: Deliverable

管理论文、课程报告等正式交付物。默认来源为 `paper/`；详细目录职责见 [schema.md](schema.md)。

底层确定性操作使用：

```bash
python3 <skill-dir>/scripts/deliverable.py <command> --root "$PWD" ...
```

## `status [source-dir]`

运行：

```bash
python3 <skill-dir>/scripts/deliverable.py status --root "$PWD" --source paper
```

只读列出活跃工作稿、Git 跟踪状态、可冻结源码、构建垃圾、当前 deliverable 和冷归档。

## `freeze <slug> [source-dir] [--pdf <path>] [--main-tex <path>]`

1. 校验 slug 为 lowercase-kebab-case，目标 `docs/deliverables/<slug>/` 不存在。
2. 默认 PDF 为 `<source-dir>/main.pdf`；不存在时停止并让用户给出 `--pdf`。主文件默认 `main.tex`，其他布局使用 `--main-tex` 指定相对 source 的路径。
3. 先运行不带 `--apply` 的 dry-run，展示最终 PDF、将收录源码、排除项、Git commit、dirty 状态和大小。
4. 用户确认后加 `--apply`。脚本以临时目录构建，成功后原子移动到目标；不得覆盖已有包。
5. 对 LaTeX 项目，在隔离副本中验证主文件可编译；编译器不可用时明确记录 `verification: not-run`，需用户确认才能接受。
6. 校验 `SHA256SUMS`，明确报告编译验证结果和生成路径。
7. 检查该包未被忽略，只展示 `docs/deliverables/<slug>/` 的精确 Git diff；确认后仅 `git add -- docs/deliverables/<slug>` 并创建一次交付物 commit。不得顺带提交工作树中的其他改动。

提交包固定为：

```text
docs/deliverables/<slug>/
├── README.md
├── submitted.pdf
├── source/
└── SHA256SUMS
```

源码候选包括 `.tex/.bib/.sty/.cls/.bst`、LaTeX 配置和图片；排除编译缓存、顶层中间 PDF、review/audit 状态文件和输出目录。作为源码依赖的顶层 PDF 用 `--include <relative-path>` 显式加入。单文件达到 100 MiB 时拒绝；总包超过 50 MiB 时警告。

## `retire <slug>`

1. 先运行 dry-run：校验当前包哈希，并比较活跃来源与 `source/`。
2. 存在未覆盖的重要源码时拒绝退役，列出精确路径。
3. 检查目标不会被 Git 忽略；用户确认后加 `--apply`，移动到 `archive/docs/YYYY-MM-DD-<slug>/` 并更新状态为 `archived`。
4. 展示精确 Git diff，确认后仅用 `git add -A -- docs/deliverables/<slug> archive/docs/YYYY-MM-DD-<slug>` 记录这次移动并创建归档 commit。
5. 脚本不删除 `paper/`。随后单独展示已覆盖源码和构建垃圾清单，再次确认后优先移入系统废纸篓；不可恢复时停止，不执行裸 `rm -rf`。

冻结和退役不会修改 `results.md`、方法文档或论文叙事。提交包是历史交付物，不是研究权威来源。
