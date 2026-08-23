# Phase: Retire

管理已经正式提交且不再继续使用的论文、课程报告等交付物。默认来源为 `paper/`；详细目录职责见 [schema.md](schema.md)。

底层确定性操作使用：

```bash
python3 <skill-dir>/scripts/retire.py --root "$PWD" --slug <slug> ...
```

## `/research retire <slug> [source-dir] [--pdf <path>] [--main-tex <path>]`

1. 确认工作稿已经正式提交且不再继续使用；未确认实际提交 PDF 时停止。
2. 校验 slug 为 lowercase-kebab-case，目标 `archive/docs/paper/YYYY-MM-DD-<slug>/` 不存在且不会被 Git 忽略。
3. 默认 PDF 为 `<source-dir>/main.pdf`；不存在时停止并让用户给出 `--pdf`。主文件默认 `main.tex`，其他布局使用 `--main-tex` 指定相对 source 的路径。
4. 先运行不带 `--apply` 的 dry-run，展示最终 PDF、将收录源码、排除项、Git commit、dirty 状态和大小。
5. 用户确认后加 `--apply`。脚本在归档父目录中暂存，以临时目录完成复制和校验后原子移动到目标；不得覆盖已有归档。
6. 对 LaTeX 项目，在隔离副本中验证主文件可编译；编译器不可用时明确记录 `verification: not-run`，需用户确认才能接受。
7. 生成并复核 `SHA256SUMS`。归档包固定为：

```text
archive/docs/paper/YYYY-MM-DD-<slug>/
├── README.md
├── submitted.pdf
├── source/
└── SHA256SUMS
```

源码候选包括 `.tex/.bib/.sty/.cls/.bst`、LaTeX 配置和图片；排除编译缓存、顶层中间 PDF、review/audit 状态文件和输出目录。作为源码依赖的顶层 PDF 用 `--include <relative-path>` 显式加入。单文件达到 100 MiB 时拒绝；总包超过 50 MiB 时警告。

归档成功后只展示 `archive/docs/paper/YYYY-MM-DD-<slug>/` 的精确 Git diff；确认后仅暂存该目录并创建一次归档 commit，不得顺带提交工作树中的其他改动。

脚本不删除 `paper/`。归档验证和提交完成后，单独展示已覆盖源码和构建垃圾清单；再次确认后才优先移入系统废纸篓，不执行裸 `rm -rf`。

退役不会修改 `results.md`、方法文档或论文叙事。归档包是历史提交证据，不是研究权威来源。
