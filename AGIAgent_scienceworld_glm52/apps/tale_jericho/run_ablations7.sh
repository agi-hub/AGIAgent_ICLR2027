#!/bin/bash
# ============================================================
# Ablation experiment round 7 — deepseek-v4-pro, 11 games.
# full: 10 iterations, no_wiki: 3 iterations
# Random seeds (no --game-seed)
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUNNER="$PROJECT_ROOT/apps/tale_jericho/run_all_tasks.py"

PLAY_LOOPS=200
PHASE_M_LOOPS=30
GAME_INDICES="3,4,5,11,12,13,15,25,30,46,50"

echo "=== Ablation Round 7 (deepseek-v4-pro) ==="
echo "Games: $GAME_INDICES"
echo ""

# full: 10 iterations
echo "Launching: full -> abl7_full (10 iterations)"
setsid nohup python3 "$RUNNER" \
  --task-list "[$GAME_INDICES]" \
  --play-loops "$PLAY_LOOPS" \
  --phase-m-loops "$PHASE_M_LOOPS" \
  --max-iterations 10 \
  --parallel-tasks 11 \
  --experiment-name abl7_full \
  > "$PROJECT_ROOT/nohup_abl7_full.out" 2>&1 < /dev/null &
echo "  PID: $!"

# no_wiki: 3 iterations
echo "Launching: no_wiki -> abl7_no_wiki (3 iterations)"
setsid nohup python3 "$RUNNER" \
  --task-list "[$GAME_INDICES]" \
  --play-loops "$PLAY_LOOPS" \
  --phase-m-loops "$PHASE_M_LOOPS" \
  --max-iterations 3 \
  --parallel-tasks 11 \
  --experiment-name abl7_no_wiki \
  --ablation no_wiki \
  > "$PROJECT_ROOT/nohup_abl7_no_wiki.out" 2>&1 < /dev/null &
echo "  PID: $!"

echo ""
echo "Launched: full (10 iter) + no_wiki (3 iter)"
echo "Monitor:"
echo "  ps aux | grep agia.py | grep -v grep | wc -l"
