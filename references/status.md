# Phase: Status

`/research status [--full]`，无子命令时默认执行。整个流程只读。

## 快速状态（默认）

从项目根运行 skill 自带脚本：

```bash
python3 <skill-dir>/scripts/research_audit.py --root "$PWD"
```

报告：

- `docs/` 与 schema 版本。
- `docs/handoffs/` 根目录的 active 数量与最新文件。
- `resolved/` 等 v3 残留。
- `AGENTS.md` 是否仍是仅指向 `CLAUDE.md` 的旧占位入口。
- 被 Git ignore 的 `.md`、`.tex`、`.bib`、`.sty`、`.cls` 源码。
- 实际存在的权威文档入口。

默认扫描不读取所有文档正文，不按更新时间制造维护任务。

## 完整状态

`--full` 时运行：

```bash
python3 <skill-dir>/scripts/research_audit.py --root "$PWD" --full
```

额外报告：

- 显式 `status: stale` 的文档。
- LaTeX 构建产物和多个顶层 PDF。
- dashboard 是否成对、是否缺输出或生成器。
- active deliverable 与 archive 快照数量。
- 非标准历史目录和多个 active handoff。

脚本输出事实；模型只补充解释和优先级。发现问题时给出建议命令，不自动运行 `init`、`update`、`freeze`、`retire` 或清理。
