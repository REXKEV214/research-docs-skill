---
name: research
description: "为科研/论文项目提供轻量、事件驱动的文档与交付物管理（init/update/status/handoff/log/retire/aris/dashboard）。用于初始化科研记忆层、维护实验结果/方法/论文规划的单一来源、跨 session 交接，以及归档不再使用的论文等正式交付物；不适用于普通前后端工程文档。"
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, Agent
---

# Research: 轻量科研项目管理

操作目标：**$ARGUMENTS**

## 核心原则

- **事件驱动**：正常编码和实验不调用本 skill；只在权威信息变化、上下文切换、阶段检查或正式交付时调用。
- **单一来源**：实验数字 → `docs/evaluation/results.md`；方法 → `docs/methods/`；论文叙事 → `docs/project/paper-plan.md`。
- **按需创建**：`init` 默认只建最小骨架；journal、dashboard、ARIS 等模块首次使用时再创建。
- **入口按存在同步**：扫描项目根的 `CLAUDE.md` 与 `AGENTS.md`，只更新实际存在者；两者都有才同时更新，普通流程不补建缺失入口。
- **一个 active handoff**：`docs/handoffs/` 根目录最多一个 active 文件；历史统一进入 `docs/handoffs/history/`。
- **危险操作先 dry-run**：迁移、退役、提交和清理必须先展示精确计划；未经确认不覆盖、不删除。
- **安装与项目初始化分离**：`install.sh` 只安装全局 skill；只有 `/research init` 可以创建项目级 `CLAUDE.md`、`AGENTS.md` 和 `docs/`。

完整 schema、状态枚举、索引与入口同步规则见 [references/schema.md](references/schema.md)。仅在初始化、迁移或需要理解目录职责时读取。

## 子命令路由

只读取当前子命令对应的 reference；不要预读其他流程。

| 子命令 | Reference | 默认写入行为 |
|---|---|---|
| `init [name] [--full]` | [references/init.md](references/init.md) | 新建需确认；迁移必确认 |
| `status [--full]`（或无参数） | [references/status.md](references/status.md) | 只读 |
| `update [results|methods|project]` | [references/update.md](references/update.md) | 无参数只报告；指定目标才修改 |
| `handoff` | [references/handoff.md](references/handoff.md) | 写一个新 active，历史化旧 active |
| `log [date] [--commit]` | [references/log.md](references/log.md) | 默认只写 journal；commit 必确认 |
| `retire <slug> [source-dir]` | [references/retire.md](references/retire.md) | 先 dry-run；确认后直接归档 |
| `dashboard ...` | [references/dashboards.md](references/dashboards.md) | 按子命令 |
| `aris ...` | [references/aris.md](references/aris.md) | 先列清单 |

## 轻量默认工作流

1. 日常工作：直接编码、实验和 Git commit，不维护额外文档。
2. 权威内容变化：运行 `/research update <target>`。
3. 暂停一天以上、切换任务/代理或上下文难以恢复：运行 `/research handoff`。
4. 阶段里程碑：运行 `/research status --full`。
5. 正式提交完成且工作稿不再使用：运行 `/research retire <slug>`。

不要仅因日期变旧而改文档，也不要为普通短 session 创建 handoff 或 journal。
