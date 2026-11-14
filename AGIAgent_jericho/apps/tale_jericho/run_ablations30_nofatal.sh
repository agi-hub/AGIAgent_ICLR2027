#!/bin/bash
# ============================================================
# Round 30 — glm-5.2, FULL pipeline minus FATAL hard interception
#   AGIA_WIKI_ABLATION=no_fatal_guard:
#     - knowledge/experiences/world_model retrieval: ON (unchanged)
#     - loop detection: ON (unchanged)
#     - [FATAL] entries remain in knowledge files and retrievable —
#       the LLM sees them via wiki_memory_read and decides itself.
#       Only the *pre-execution hard block* (_check_fatal_action) is off.
# Protocol: same as abl19/25/26/27/28 — 6 games × 10 iter × 110 steps,
#   phase_m 30, parallel 6. Control: the n=5 full statistics.
# ============================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

GAME_INDICES="13,24,51,53,8,44"

echo "=== Round 30: glm-5.2 FULL minus FATAL hard guard ==="
echo "Games: $GAME_INDICES"
echo ""

export AGIA_WIKI_ABLATION=no_fatal_guard

echo "Launching: -> abl30_glm52_no_fatal_r2 (10 iter, p=6)"
setsid nohup python3 "$PROJECT_ROOT/apps/tale_jericho/run_all_tasks.py" \
  --task-list "[$GAME_INDICES]" \
  --play-loops 110 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 6 \
  --experiment-name abl30_glm52_no_fatal_r2 \
  --ablation no_fatal_guard \
  > "$PROJECT_ROOT/nohup_abl30_glm52_no_fatal_r2.out" 2>&1 < /dev/null &
echo "  PID: $!"
