# research-docs-skill

面向 Claude Code 与 Codex 的轻量科研项目管理 skill。它维护科研记忆、跨 session 交接和正式交付物，但不介入普通日常开发。

## 设计原则

- **事件驱动**：只在权威信息变化、上下文切换、阶段检查或正式交付时调用。
- **单一来源**：实验数字 → `results.md`，方法 → `methods/`，论文叙事 → `paper-plan.md`。
- **按需创建**：默认 init 只建最小骨架，其他模块首次使用时创建。
- **一个 active handoff**：旧交接进入 `docs/handoffs/history/`，未完成事项自动迁入最新交接。
- **交付物可退役**：工作稿 → Git 中的最小提交包 → 冷归档。

## 命令

| 命令 | 说明 |
|---|---|
| `init [name] [--full]` | 初始化或迁移 schema v4；默认最小结构 |
| `status [--full]` | 快速或完整的只读健康检查 |
| `update [results\|methods\|project]` | 指定目标才修改；无参数只报告 |
| `handoff` | 创建唯一 active handoff，并历史化旧 handoff |
| `log [date] [--commit]` | 默认只写可选 journal；显式参数才提交 |
| `deliverable status\|freeze\|retire` | 查看、冻结和退役正式交付物；可指定 source/PDF/主 TeX |
| `dashboard ...` | 管理可重建 HTML dashboard |
| `aris ...` | 翻译归档 ARIS 产出 |

推荐节奏：日常直接工作；权威内容变化时 `update`；暂停一天以上或切换任务时 `handoff`；里程碑时 `status --full`；正式提交时 `deliverable freeze`。

## schema v4

默认最小结构：

```text
docs/
├── README.md
├── project/
│   └── overview.md
└── handoffs/
    └── history/
archive/docs/
CLAUDE.md
AGENTS.md
```

论文交付物生命周期：

```text
paper/
  → docs/deliverables/<slug>/
  → archive/docs/YYYY-MM-DD-<slug>/
```

冻结包只保留 `submitted.pdf`、最小可编译源码、说明和 SHA-256 校验；中间 PDF、编译缓存和 review 状态不进入。

## 安装

```bash
git clone https://github.com/REXKEV214/research-docs-skill
cd research-docs-skill
./install.sh
```

安装目标：

- `~/.claude/skills/research/`
- `~/.codex/skills/research/`

安装脚本只复制全局 skill，不创建或修改任何项目的 `CLAUDE.md`、`AGENTS.md` 或 `docs/`。项目文件只由显式 `/research init` 创建。

### 更新与本地开发

```bash
./install.sh --update   # 工作树干净时 pull --ff-only 后覆盖
./install.sh --force    # reset 到上游后覆盖，会丢弃本地修改
./install.sh --local    # 不同步 git，直接安装当前工作树
```

`--update`、`--force`、`--local` 互斥。
