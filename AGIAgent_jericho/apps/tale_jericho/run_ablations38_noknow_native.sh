#!/bin/bash
# ============================================================
# Round 38 — glm-5.2, no_knowledge ablation (native tool calling)
#   NATIVE Tool_calling_format=True — matches abl34/35 full and
#   abl36/37 gate-arm protocol.
#   AGIA_WIKI_ABLATION=no_knowledge:
#     - knowledge retrieval OFF (wiki knowledge section disabled)
#     - FATAL gate off (dependent on knowledge)
#     - experiences retrieval ON, WM/loop detect ON
# Protocol: same as abl34-37 — 6 games × 10 iter × 110 steps,
#   phase_m 30, parallel 6. Control: native full n=2 (abl34+35).
# ============================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0/")/../.." && pwd)"

GAME_INDICES="13,24,51,53,8,44"

echo "=== Round 38: glm-5.2 no_knowledge (native tool calling) ==="
echo "Games: $GAME_INDICES"
echo ""

export AGIA_WIKI_ABLATION=no_knowledge

echo "Launching: -> abl38_glm52_no_knowledge_native_r1 (10 iter, p=6)"
setsid nohup python3 "$PROJECT_ROOT/apps/tale_jericho/run_all_tasks.py" \
  --task-list "[$GAME_INDICES]" \
  --play-loops 110 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 6 \
  --experiment-name abl38_glm52_no_knowledge_native_r1 \
  --ablation no_knowledge \
  > "$PROJECT_ROOT/nohup_abl38_glm52_no_knowledge_native_r1.out" 2>&1 < /dev/null &
echo "  PID: $!"
