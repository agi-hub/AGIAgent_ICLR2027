#!/bin/bash
# ============================================================
# Round 23 — glm-5.2, 6 games (same pool as abl19/21/22)
# abl23_glm52_autom = abl22 (pure ReAct) + AutoManual core ideas ONLY
#
# Base (identical to abl22_glm52_react):
#   - --ablation no_wiki            (wiki_memory_read disabled, no FATAL guard)
#   - AGIA_REACT_PROMPT=1           (system_prompt_react.txt, no scaffolding)
#   - AGIA_DISABLE_LOOP_DETECT=1    (no loop warnings)
#   - 10 iter x 110 play loops, phase_m 30, parallel=6
#
# Added single variable (AutoManual ideas, env-gated):
#   - AGIA_CURATOR_STYLE=autom:
#       phase_m curator gets discipline addon (phase_m_prompt_autom.txt):
#         30-entry budget + merge rules, WIKI_GAP/EXECUTION_ERROR/EXPLORATION
#         failure attribution, [ok N/M] validation markers
#       play (attempt>=2) gets the curated manual injected directly into the
#       prompt (AutoManual manual-as-context), capped at 6000 chars.
#       No retrieval tools, no query_wm guidance, no FATAL guard — react stays pure.
#
# Control arm: abl22_glm52_react (178.7 avg)
# ============================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

GAME_INDICES="13,24,51,53,8,44"

echo "=== Round 23: glm-5.2, 6 games, react + AutoManual ideas ==="
echo "Games: $GAME_INDICES"
echo ""

export AGIA_REACT_PROMPT=1
export AGIA_DISABLE_LOOP_DETECT=1
export AGIA_CURATOR_STYLE=autom

echo "Launching: autom -> abl23_glm52_autom (10 iter, p=6)"
setsid nohup python3 "$PROJECT_ROOT/apps/tale_jericho/run_all_tasks.py" \
  --task-list "[$GAME_INDICES]" \
  --play-loops 110 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 6 \
  --experiment-name abl23_glm52_autom \
  --ablation no_wiki \
  > "$PROJECT_ROOT/nohup_abl23_glm52_autom.out" 2>&1 < /dev/null &
echo "  PID: $!"

echo ""
echo "Launched: abl23_glm52_autom (control: abl22_glm52_react)"
