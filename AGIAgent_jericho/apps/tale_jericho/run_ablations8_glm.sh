#!/bin/bash
# ============================================================
# Ablation experiment round 8 — glm-4.7, 6 games, 2 conditions.
# Reduced parallelism (3) to avoid 429 rate limits.
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUNNER="$PROJECT_ROOT/apps/tale_jericho/run_all_tasks.py"

PLAY_LOOPS=200
PHASE_M_LOOPS=30
GAME_INDICES="13,12,11,15,4,30"

echo "=== Ablation Round 8 (glm-4.7, parallel=3) ==="
echo "Games: $GAME_INDICES (Detective, Deephome, Cutthroat, Enchanter, Adventureland, Murdac)"
echo ""

# full: 10 iterations, parallel=3
echo "Launching: full -> abl8_glm_full (10 iterations, parallel=3)"
setsid nohup python3 "$RUNNER" \
  --task-list "[$GAME_INDICES]" \
  --play-loops "$PLAY_LOOPS" \
  --phase-m-loops "$PHASE_M_LOOPS" \
  --max-iterations 10 \
  --parallel-tasks 3 \
  --experiment-name abl8_glm_full \
  > "$PROJECT_ROOT/nohup_abl8_glm_full.out" 2>&1 < /dev/null &
echo "  PID: $!"

# no_wiki: 3 iterations, parallel=3
echo "Launching: no_wiki -> abl8_glm_no_wiki (3 iterations, parallel=3)"
setsid nohup python3 "$RUNNER" \
  --task-list "[$GAME_INDICES]" \
  --play-loops "$PLAY_LOOPS" \
  --phase-m-loops "$PHASE_M_LOOPS" \
  --max-iterations 3 \
  --parallel-tasks 3 \
  --experiment-name abl8_glm_no_wiki \
  --ablation no_wiki \
  > "$PROJECT_ROOT/nohup_abl8_glm_no_wiki.out" 2>&1 < /dev/null &
echo "  PID: $!"

echo ""
echo "Launched: full (10 iter, p=3) + no_wiki (3 iter, p=3)"
echo "Total concurrent: 6 (3+3)"
echo "Monitor:"
echo "  ps aux | grep agia.py | grep -v grep | wc -l"
