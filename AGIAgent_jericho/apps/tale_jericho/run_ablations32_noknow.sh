#!/bin/bash
# ============================================================
# Round 32 — glm-5.2, no_knowledge ablation rerun (r2)
# Same protocol as abl21_glm52_no_knowledge:
#   knowledge retrieval OFF (wiki knowledge section disabled,
#   FATAL gate off as dependent), experiences retrieval ON
#   with experiences-STRATEGY play prompt, WM/loop detect ON.
# 6 games x 10 iter x 110 steps, phase_m 30, parallel 6.
# ============================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

GAME_INDICES="13,24,51,53,8,44"

echo "=== Round 32: glm-5.2 no_knowledge rerun ==="
echo "Games: $GAME_INDICES"
echo ""

setsid nohup python3 "$PROJECT_ROOT/apps/tale_jericho/run_all_tasks.py" \
  --task-list "[$GAME_INDICES]" \
  --play-loops 110 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 6 \
  --experiment-name abl32_glm52_no_knowledge_r2 \
  --ablation no_knowledge \
  > "$PROJECT_ROOT/nohup_abl32_glm52_no_knowledge_r2.out" 2>&1 < /dev/null &
echo "  PID: $!"
