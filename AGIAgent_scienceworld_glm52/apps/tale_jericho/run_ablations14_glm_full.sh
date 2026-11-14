#!/bin/bash
# ============================================================
# Round 14 ablation — glm-4.7, 9 games, full only
# With: fixed loop detection (action@room), knowledge→experience links
# 10 iterations, 100 play-loops (91-95% of 200-loop scores), parallel=3
# ============================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# Detective(13), Library(24), Zork1(51), Zork3(53), Balances(8),
# Temple(44), Deephome(12), Adventureland(4), Murdac(30)
GAME_INDICES="13,24,51,53,8,44,12,4,30"

echo "=== Round 14: glm-4.7, 9 games, full ==="
echo "Games: $GAME_INDICES"
echo ""

echo "Launching: full -> abl14_glm_full (10 iter, p=3)"
setsid nohup python3 "$PROJECT_ROOT/apps/tale_jericho/run_all_tasks.py" \
  --task-list "[$GAME_INDICES]" \
  --play-loops 100 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 3 \
  --experiment-name abl14_glm_full \
  > "$PROJECT_ROOT/nohup_abl14_glm_full.out" 2>&1 < /dev/null &
echo "  PID: $!"
echo ""
echo "Launched: full (10 iter, 100 loops)"
