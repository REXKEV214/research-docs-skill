# Phase: Log

`/research log [YYYY-MM-DD] [--commit]`

Journal 是可选的叙事记录。Git 历史已经足够清晰时可以不使用本命令。

## 默认：只写 journal

日期参数缺省为今天。按需创建 `docs/journal/`，文件为 `YYYY-MM-DD-devlog.md`。

首次创建：

```markdown
---
date: YYYY-MM-DD
---

<本次有长期价值的进展、决策或问题>
```

同日再次运行时读取已有内容，只追加不重复的信息。普通文件编辑、命令流水账和已清楚体现在 commit 中的内容不重复记录。

## `--commit`：显式提交

只有显式参数才执行 Git 分组提交：

1. 读取 `git status --porcelain`、相关 diff 和最近 commit 风格。
2. 按 docs、代码、结果、测试、配置、论文等语义分组。
3. 无论文件数多少，都展示每组文件和 commit message，等待确认。
4. 使用 `git add -- <精确路径>`，禁止 `git add -A`、`.` 或 `--all`。
5. 每组独立 commit；失败立即停止，不 retry、不 `--no-verify`、不 amend。

跳过并警告 `.env`、`*.key`、`*.pem`、`credentials*`、`secrets*`。检测到冲突标记或远端 behind 时停止相关提交；本命令不 push。
