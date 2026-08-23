# Phase: Update

`/research update [results|methods|project]`

## 无参数

只读检查现有权威文档与对应来源，列出可能不一致或显式 `status: stale` 的候选。不要因为 `updated` 超过固定天数而修改文件。

## 指定目标

只更新用户指定的类别：

- `results`：读取原始评测输出与分析产物，人工校对后更新 `docs/evaluation/results.md`。
- `methods`：读取实际代码、配置和实验设计，更新 `docs/methods/` 中对应文件。
- `project`：读取当前决策和真实进度，更新 `docs/project/overview.md`；论文叙事仍只写入 `paper-plan.md`。

若目标模块不存在，先展示将创建的路径和职责，确认后按需创建；不要补建无关模块。

## 写入规则

1. 读取当前文档、直接来源和立即相关的调用/配置。
2. 只修改过期或不一致的内容。
3. 其他文档中的重复实验数字替换为指向 `results.md` 的链接。
4. 仅在正文实际变化时更新 frontmatter 日期。
5. 只有新增、删除或移动文件时才同步 `docs/README.md` 索引。
6. 扫描项目根的 `CLAUDE.md` 与 `AGENTS.md`，只更新实际存在者的对应短入口；只有一个就只更新一个，两者都有才同时更新，均不存在则不创建。不要复制结论全文或覆盖其他内容。

完全过时的文件只列为归档候选；未经确认不移动到 `archive/docs/deprecated/`。
