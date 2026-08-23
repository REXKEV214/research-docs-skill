#!/bin/bash
# install.sh — research skill 安装脚本
# 安装 research skill 到 ~/.claude/skills/research/ 和 ~/.codex/skills/research/；报告旧 docs 安装。
#
# 用法：
#   ./install.sh                安装（已存在则跳过覆盖）
#   ./install.sh --update       git pull --ff-only 拉取最新并覆盖；
#                               工作区有未提交修改时会中止
#   ./install.sh --force        强制同步到远程（git fetch + reset --hard），
#                               丢弃本地对 skill / references 的任何改动
#   ./install.sh --local        不同步 git，直接用当前工作树覆盖安装副本

set -euo pipefail

UPDATE=0
FORCE=0
LOCAL=0
for arg in "$@"; do
  case "$arg" in
    --update) UPDATE=1 ;;
    --force)  FORCE=1 ;;
    --local)  LOCAL=1 ;;
    -h|--help)
      sed -n '2,11p' "$0"; exit 0 ;;
    *)
      echo "未知参数: $arg" >&2; exit 1 ;;
  esac
done
if [[ $(( UPDATE + FORCE + LOCAL )) -gt 1 ]]; then
  echo "--update、--force、--local 不能同时使用" >&2
  exit 1
fi
OVERWRITE=$(( UPDATE | FORCE | LOCAL ))

CLAUDE_SKILL_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/research"
CODEX_SKILL_DIR="${CODEX_HOME:-$HOME/.codex}/skills/research"
HOOKS_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/hooks"
SETTINGS_FILE="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json"
OLD_SKILL_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/docs"
OLD_HOOK_FILE="$HOOKS_DIR/docs-hook.sh"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== research skill 安装 ==="

# ── 0. 同步仓库（--update / --force；--local 明确跳过） ─────
if [[ "$UPDATE" -eq 1 || "$FORCE" -eq 1 ]]; then
  echo ""
  echo "→ 同步仓库 ($SCRIPT_DIR)"
  if ! git -C "$SCRIPT_DIR" rev-parse --is-inside-work-tree &>/dev/null; then
    echo "  ⚠️  $SCRIPT_DIR 不是 git 仓库，跳过同步" >&2
  elif [[ "$FORCE" -eq 1 ]]; then
    BRANCH=$(git -C "$SCRIPT_DIR" branch --show-current)
    UPSTREAM=$(git -C "$SCRIPT_DIR" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || echo "origin/$BRANCH")
    echo "  fetch + reset --hard $UPSTREAM （丢弃本地修改）"
    git -C "$SCRIPT_DIR" fetch "${UPSTREAM%%/*}"
    git -C "$SCRIPT_DIR" reset --hard "$UPSTREAM"
    if [[ -n "$(git -C "$SCRIPT_DIR" ls-files --others --exclude-standard)" ]]; then
      echo "  ⚠️  reset 后仍有未跟踪文件；为避免把残留文件装入 skill，已中止。" >&2
      echo "       请先检查并手动处理这些文件：" >&2
      git -C "$SCRIPT_DIR" ls-files --others --exclude-standard >&2
      exit 1
    fi
    echo "  完成"
  else
    if [[ -n "$(git -C "$SCRIPT_DIR" status --porcelain)" ]]; then
      echo "  ⚠️  工作区有未提交修改，已中止。" >&2
      echo "       · 若要保留本地修改：请先 commit / stash 后再重试 --update" >&2
      echo "       · 若要丢弃本地修改、强制同步到远程最新：改用 --force" >&2
      exit 1
    fi
    git -C "$SCRIPT_DIR" pull --ff-only
    echo "  完成"
  fi
fi

# ── 1. 安装 skill ──────────────────────────────────────────

install_to() {
  local target="$1"
  local label="$2"
  local stage
  local backup
  echo ""
  echo "→ 安装 skill 到 $target ($label)"

  if [[ -d "$target" && "$OVERWRITE" -ne 1 ]]; then
    echo "  已存在，跳过（--update 拉取最新并覆盖；--force 强制同步到远程）"
    return
  fi

  if [[ -e "$target" && ! -d "$target" ]]; then
    echo "  ⚠️  安装目标存在且不是目录，已中止：$target" >&2
    return 1
  fi

  stage=$(mktemp -d "${TMPDIR:-/tmp}/research-skill-install.XXXXXX")
  mkdir -p "$stage/references" "$stage/scripts"
  cp -f "$SCRIPT_DIR/SKILL.md" "$stage/SKILL.md"
  cp -f "$SCRIPT_DIR"/references/*.md "$stage/references/"
  cp -f "$SCRIPT_DIR"/scripts/*.py "$stage/scripts/"
  chmod +x "$stage"/scripts/*.py

  mkdir -p "$(dirname "$target")"
  if [[ -d "$target" ]]; then
    backup="${target}.backup.$$"
    if [[ -e "$backup" ]]; then
      echo "  ⚠️  临时备份目标已存在，已中止：$backup" >&2
      rm -rf -- "$stage"
      return 1
    fi
    mv "$target" "$backup"
    if mv "$stage" "$target"; then
      rm -rf -- "$backup"
    else
      mv "$backup" "$target"
      rm -rf -- "$stage"
      return 1
    fi
  else
    mv "$stage" "$target"
  fi
  echo "  完成"
}

install_to "$CLAUDE_SKILL_DIR" "Claude Code"
install_to "$CODEX_SKILL_DIR" "Codex"

# ── 2. 清理旧 docs 安装 ─────────────────────────────────────

echo ""
echo "→ 检查旧 docs 安装"

cleanup_needed=0

if [[ -d "$OLD_SKILL_DIR" ]]; then
  echo "  ⚠️  检测到旧 skill 目录：$OLD_SKILL_DIR"
  echo "       建议手动清理：rm -rf \"$OLD_SKILL_DIR\""
  cleanup_needed=1
fi

if [[ -f "$OLD_HOOK_FILE" ]]; then
  echo "  ⚠️  检测到旧 hook 脚本：$OLD_HOOK_FILE"
  echo "       建议手动清理：rm \"$OLD_HOOK_FILE\""
  cleanup_needed=1
fi

# settings.json 属于用户配置，安装器只报告，不自动修改。
if [[ -f "$SETTINGS_FILE" ]] && grep -q "docs-hook.sh" "$SETTINGS_FILE" 2>/dev/null; then
  echo "  ⚠️  settings.json 中存在 docs-hook.sh hook 条目"
  echo "       请确认后手动编辑 ${SETTINGS_FILE}；安装器未修改该文件"
  cleanup_needed=1
fi

if [[ "$cleanup_needed" -eq 0 ]]; then
  echo "  无遗留，跳过"
fi

# ── 3. 完成提示 ─────────────────────────────────────────────

echo ""
echo "✓ 安装完成。重启 Claude Code 后生效。"
echo ""
echo "使用方式："
echo "  /research init [<name>]        初始化（冷启动 / 迁移 / 升级，幂等）"
echo "  /research status               文档健康检查"
echo "  /research handoff              写 session 交接文档"
echo "  /research deliverable status   查看论文 / 交付物状态"
echo "  /research aris                 归档 ARIS 产出"
