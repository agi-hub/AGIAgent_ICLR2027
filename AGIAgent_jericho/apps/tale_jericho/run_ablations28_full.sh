#!/bin/bash
# ============================================================
# Round 28 — glm-5.2, FULL pipeline rerun (all mechanisms)
# Same protocol as abl19_glm52_full:
#   games: Detective(13), Library(24), Zork1(51), Zork3(53), Balances(8), Temple(44)
#   10 iterations x 110 play loops, phase_m 30 loops, parallel=6
# Full mechanisms: knowledge/experience retrieval (wiki_memory_read),
#   world model (query_wm), FATAL guard, loop detection, evidence links.
# ============================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

GAME_INDICES="13,24,51,53,8,44"

echo "=== Round 28: glm-5.2 FULL rerun, 6 games ==="
echo "Games: $GAME_INDICES"
echo ""

echo "Launching: full -> abl28_glm52_full_r4 (10 iter, p=6)"
setsid nohup python3 "$PROJECT_ROOT/apps/tale_jericho/run_all_tasks.py" \
  --task-list "[$GAME_INDICES]" \
  --play-loops 110 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 6 \
  --experiment-name abl28_glm52_full_r4 \
  > "$PROJECT_ROOT/nohup_abl28_glm52_full_r4.out" 2>&1 < /dev/null &
echo "  PID: $!"

echo ""
echo "Launched: abl28_glm52_full_r4"
