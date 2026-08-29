#!/usr/bin/env bash
# agent-delegate.sh — 让 DSH（或任意 shell）把一个任务委派给本机外部 agent，
# 返回其输出。用途：多 agent 互通/委派（谁都能指派谁去干活）的轻量通道。
#
# 用法:
#   agent-delegate.sh opencode "做一件事"
#   agent-delegate.sh codex "做一件事"
#   agent-delegate.sh claude "做一件事"
#   OPENDOCE_MODEL=... 可覆盖 opencode 使用的模型（默认 opencode-go/deepseek-v4-flash）
set -u

agent="${1:-}"; shift || true
prompt="$*"
[ -z "$prompt" ] && { echo "usage: $0 <opencode|codex|claude> <prompt>"; exit 2; }

OPENCODE_MODEL="${OPENCODE_MODEL:-opencode-go/deepseek-v4-flash}"

case "$agent" in
  opencode)
    # 实测可用：用 DeepSeek 模型（默认 gpt-5.6-luna 在部分区域被拒）
    exec opencode run -m "$OPENCODE_MODEL" "$prompt"
    ;;
  codex)
    # 需先修 ~/.codex 的模型缓存报错（unknown variant "max"）
    exec codex exec --skip-git-repo-check "$prompt"
    ;;
  claude)
    # 需先 claude /login
    exec claude -p --output-format text "$prompt"
    ;;
  *)
    echo "unknown agent: $agent (use opencode|codex|claude)"; exit 2 ;;
esac
