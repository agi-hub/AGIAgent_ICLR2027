#!/bin/bash
# deepseek-v4-pro ablation — 6 games, runs alongside glm-4.7 experiment
# Uses apps/tale_jericho_pro (separate config.txt with deepseek-v4-pro)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUNNER="$PROJECT_ROOT/apps/tale_jericho_pro/run_all_tasks.py"

PLAY_LOOPS=200
PHASE_M_LOOPS=30
GAME_INDICES="13,12,11,15,4,30"

echo "=== Pro Ablation (deepseek-v4-pro, 6 games, parallel=3) ==="
echo "Games: $GAME_INDICES"
echo ""

# full: 10 iterations
echo "Launching: full -> abl8_pro_full (10 iterations)"
setsid nohup python3 "$RUNNER" \
  --task-list "[$GAME_INDICES]" \
  --play-loops "$PLAY_LOOPS" \
  --phase-m-loops "$PHASE_M_LOOPS" \
  --max-iterations 10 \
  --parallel-tasks 3 \
  --experiment-name abl8_pro_full \
  > "$PROJECT_ROOT/nohup_abl8_pro_full.out" 2>&1 < /dev/null &
echo "  PID: $!"

# no_wiki: 3 iterations
echo "Launching: no_wiki -> abl8_pro_no_wiki (3 iterations)"
setsid nohup python3 "$RUNNER" \
  --task-list "[$GAME_INDICES]" \
  --play-loops "$PLAY_LOOPS" \
  --phase-m-loops "$PHASE_M_LOOPS" \
  --max-iterations 3 \
  --parallel-tasks 3 \
  --experiment-name abl8_pro_no_wiki \
  --ablation no_wiki \
  > "$PROJECT_ROOT/nohup_abl8_pro_no_wiki.out" 2>&1 < /dev/null &
echo "  PID: $!"

echo ""
echo "Launched pro full (10 iter) + pro no_wiki (3 iter)"
echo "Runs alongside glm-4.7 experiment (separate app dirs)"
