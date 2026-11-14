#!/bin/bash
# ============================================================
# Round 10 ablation — deepseek-v4-pro, 6 new games.
# full(10 iter) + no_wiki(10 iter), random seeds.
# Includes: [FATAL:keywords] interception + loop detection + nav guard
# ============================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

GAME_INDICES="2,17,39,37,10,23"

echo "=== Round 10: deepseek-v4-pro, 6 new games ==="
echo "Games: $GAME_INDICES (Acorncourt, Gold, Sherlock, Reverb, Curses, Karn)"
echo ""

# full: 10 iterations
echo "Launching: full -> abl10_pro_full (10 iter, p=3)"
setsid nohup python3 "$PROJECT_ROOT/apps/tale_jericho_pro/run_all_tasks.py" \
  --task-list "[$GAME_INDICES]" \
  --play-loops 200 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 3 \
  --experiment-name abl10_pro_full \
  > "$PROJECT_ROOT/nohup_abl10_pro_full.out" 2>&1 < /dev/null &
echo "  PID: $!"

# no_wiki: 10 iterations
echo "Launching: no_wiki -> abl10_pro_no_wiki (10 iter, p=3)"
setsid nohup python3 "$PROJECT_ROOT/apps/tale_jericho_pro/run_all_tasks.py" \
  --task-list "[$GAME_INDICES]" \
  --play-loops 200 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 3 \
  --experiment-name abl10_pro_no_wiki \
  --ablation no_wiki \
  > "$PROJECT_ROOT/nohup_abl10_pro_no_wiki.out" 2>&1 < /dev/null &
echo "  PID: $!"

echo ""
echo "Launched: full (10 iter) + no_wiki (10 iter)"
echo "Total concurrent: 6 (3+3)"
