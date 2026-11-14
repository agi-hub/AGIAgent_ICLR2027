#!/bin/bash
# ============================================================
# Round 11 ablation — glm-4.7, 9 games (no Cutthroat/Enchanter)
# full(10 iter) + no_wiki(10 iter), parallel=3 each
# ============================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# Detective(13), Library(24), Zork1(51), Zork3(53), Balances(8),
# Temple(44), Deephome(12), Adventureland(4), Murdac(30)
GAME_INDICES="13,24,51,53,8,44,12,4,30"

echo "=== Round 11: glm-4.7, 9 games ==="
echo "Games: $GAME_INDICES"
echo ""

# full: 10 iterations, parallel=3
echo "Launching: full -> abl11_glm_full (10 iter, p=3)"
setsid nohup python3 "$PROJECT_ROOT/apps/tale_jericho/run_all_tasks.py" \
  --task-list "[$GAME_INDICES]" \
  --play-loops 200 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 3 \
  --experiment-name abl11_glm_full \
  > "$PROJECT_ROOT/nohup_abl11_glm_full.out" 2>&1 < /dev/null &
echo "  PID: $!"

# no_wiki: 10 iterations, parallel=3
echo "Launching: no_wiki -> abl11_glm_no_wiki (10 iter, p=3)"
setsid nohup python3 "$PROJECT_ROOT/apps/tale_jericho/run_all_tasks.py" \
  --task-list "[$GAME_INDICES]" \
  --play-loops 200 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 3 \
  --experiment-name abl11_glm_no_wiki \
  --ablation no_wiki \
  > "$PROJECT_ROOT/nohup_abl11_glm_no_wiki.out" 2>&1 < /dev/null &
echo "  PID: $!"

echo ""
echo "Launched: full (10 iter) + no_wiki (10 iter)"
echo "Total concurrent: 6 (3+3)"
