#!/bin/bash
# ============================================================
# Round 36 — glm-5.2, FULL minus FATAL hard interception
#   NATIVE tool calling (Tool_calling_format=True) — matches
#   abl34/abl35 protocol; chat-based runs abl29-31 not comparable.
#   AGIA_WIKI_ABLATION=no_fatal_guard:
#     - knowledge/experiences/world_model retrieval: ON (unchanged)
#     - loop detection: ON (unchanged)
#     - [FATAL] entries remain in knowledge files and retrievable —
#       the LLM sees them via wiki_memory_read and decides itself.
#       Only the *pre-execution hard block* (_check_fatal_action) is off.
# Protocol: same as abl34/35 — 6 games × 10 iter × 110 steps,
#   phase_m 30, parallel 6. Control: native full n=2 (abl34+35).
# ============================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0/")/../.." && pwd)"

GAME_INDICES="13,24,51,53,8,44"

echo "=== Round 36: glm-5.2 FULL minus FATAL hard guard (native tool calling) ==="
echo "Games: $GAME_INDICES"
echo ""

export AGIA_WIKI_ABLATION=no_fatal_guard

echo "Launching: -> abl36_glm52_no_fatal_native_r1 (10 iter, p=6)"
setsid nohup python3 "$PROJECT_ROOT/apps/tale_jericho/run_all_tasks.py" \
  --task-list "[$GAME_INDICES]" \
  --play-loops 110 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 6 \
  --experiment-name abl36_glm52_no_fatal_native_r1 \
  --ablation no_fatal_guard \
  > "$PROJECT_ROOT/nohup_abl36_glm52_no_fatal_native_r1.out" 2>&1 < /dev/null &
echo "  PID: $!"
