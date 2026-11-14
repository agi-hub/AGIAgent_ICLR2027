#!/bin/bash
# ============================================================
# Round 9 ablation — full only, 2 models in parallel.
# deepseek-v4-pro via apps/tale_jericho_pro, glm-4.7 via apps/tale_jericho
# 6 games, 10 iterations each, random seeds.
# Includes: FATAL interception (fixed for Death Traps format) + loop detection
# ============================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PLAY_LOOPS=200
PHASE_M_LOOPS=30
GAME_INDICES="13,12,11,15,4,30"

echo "=== Round 9: full only, 2 models ==="
echo "Games: $GAME_INDICES (Detective, Deephome, Cutthroat, Enchanter, Adventureland, Murdac)"
echo ""

# glm-4.7 (apps/tale_jericho)
echo "Launching: glm-4.7 -> abl9_glm_full (10 iter)"
setsid nohup python3 "$PROJECT_ROOT/apps/tale_jericho/run_all_tasks.py" \
  --task-list "[$GAME_INDICES]" \
  --play-loops "$PLAY_LOOPS" --phase-m-loops "$PHASE_M_LOOPS" \
  --max-iterations 10 --parallel-tasks 3 \
  --experiment-name abl9_glm_full \
  > "$PROJECT_ROOT/nohup_abl9_glm_full.out" 2>&1 < /dev/null &
echo "  PID: $!"

# deepseek-v4-pro (apps/tale_jericho_pro)
echo "Launching: deepseek-v4-pro -> abl9_pro_full (10 iter)"
setsid nohup python3 "$PROJECT_ROOT/apps/tale_jericho_pro/run_all_tasks.py" \
  --task-list "[$GAME_INDICES]" \
  --play-loops "$PLAY_LOOPS" --phase-m-loops "$PHASE_M_LOOPS" \
  --max-iterations 10 --parallel-tasks 3 \
  --experiment-name abl9_pro_full \
  > "$PROJECT_ROOT/nohup_abl9_pro_full.out" 2>&1 < /dev/null &
echo "  PID: $!"

echo ""
echo "Launched 2 experiments (6 procs each = 12 total)"
