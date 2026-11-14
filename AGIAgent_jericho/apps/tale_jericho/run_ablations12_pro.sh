#!/bin/bash
# ============================================================
# Round 12 — deepseek-v4-pro, 9 games (same as R11 glm)
# full(10 iter, p=9) + no_wiki(10 iter, p=9)
# ============================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

GAME_INDICES="13,24,51,53,8,44,12,4,30"

echo "=== Round 12: deepseek-v4-pro, 9 games, parallel=9 ==="
echo "Games: $GAME_INDICES"
echo ""

# full: 10 iterations, parallel=9
echo "Launching: full -> abl12_pro_full (10 iter, p=9)"
setsid nohup python3 "$PROJECT_ROOT/apps/tale_jericho_pro/run_all_tasks.py" \
  --task-list "[$GAME_INDICES]" \
  --play-loops 200 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 9 \
  --experiment-name abl12_pro_full \
  > "$PROJECT_ROOT/nohup_abl12_pro_full.out" 2>&1 < /dev/null &
echo "  PID: $!"

# no_wiki: 10 iterations, parallel=9
echo "Launching: no_wiki -> abl12_pro_no_wiki (10 iter, p=9)"
setsid nohup python3 "$PROJECT_ROOT/apps/tale_jericho_pro/run_all_tasks.py" \
  --task-list "[$GAME_INDICES]" \
  --play-loops 200 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 9 \
  --experiment-name abl12_pro_no_wiki \
  --ablation no_wiki \
  > "$PROJECT_ROOT/nohup_abl12_pro_no_wiki.out" 2>&1 < /dev/null &
echo "  PID: $!"

echo ""
echo "Launched: full (10 iter, p=9) + no_wiki (10 iter, p=9)"
