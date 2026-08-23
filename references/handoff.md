# Phase: Handoff

`/research handoff` 只用于暂停一天以上、切换任务/代理、长实验仍在运行或上下文已经难以恢复的边界。普通短 session 不创建 handoff。

## 1. 目录与不变量

标准目录：

```text
docs/handoffs/
├── history/
└── YYYY-MM-DD-HHMM-slug.md   # 最多一个 status: active
```

`history/` 不存在时按需创建。检测到 `resolved/` 时报告 v3 残留；本次 handoff 可在确认后将其内容原样移动到 `history/`。

## 2. 合并旧 active

读取根目录全部 handoff，提取每个文件的“下一步”：

- 已有证据表明完成：不带入新 handoff，旧文件最终为 `resolved`。
- 明确未完成：去重后带入新 handoff，旧文件最终为 `superseded`。
- 无法判断：保留并标记 `待确认`，旧文件为 `superseded`。

不得因为创建新 handoff 而静默丢弃旧事项。存在多个 active 时，全部合并到一个新 handoff。

## 3. 收集当前 session

以对话上下文为首要来源，记录具体文件、函数、命令、结果、决策和风险。项目文档只用于补充；不读取 Git log，不自动运行 status/update。

## 4. 写入顺序

先生成并完整写入新的 draft 文件：

```yaml
---
updated: YYYY-MM-DD
status: draft
scope: session 交接
---
```

正文固定为：`已完成 / 当前状态 / 关键决策 / 下一步 / 注意事项`。“下一步”使用可执行祈使句。

Draft 成功后才处理旧 active：更新状态为 `resolved` 或 `superseded`，再使用 `git mv`（已跟踪）或 `mv`（未跟踪）移入 `history/`。全部旧 active 处理成功后，最后把新文件状态切为 `active`。

任一步失败都停止并报告 draft 路径，不把 draft 宣称为最新 handoff。这个顺序允许短暂出现零个 active，但不会留下两个 active；已有内容仍可从 draft 与 history 恢复。

## 5. 入口同步

`CLAUDE.md` 的 `## Last Handoff` 只保留：

- 最新 active handoff 链接。
- 一句当前状态。

不复制全文，不列历史链。最后验证根目录恰好一个 active handoff，并报告迁入 history 的文件及状态。
