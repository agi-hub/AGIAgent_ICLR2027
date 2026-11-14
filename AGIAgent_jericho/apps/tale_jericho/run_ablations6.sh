#!/bin/bash
# ============================================================
# Ablation experiment round 6 — 11 games, 2 conditions.
#
# Games: Advent(#3), Adventureland(#4), Afflicted(#5), Cutthroat(#11),
#        Deephome(#12), Detective(#13), Enchanter(#15), Loose(#25),
#        Murdac(#30), Tryst205(#46), Zenon(#50)
# Conditions: full (control), no_wiki
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUNNER="$PROJECT_ROOT/apps/tale_jericho/run_all_tasks.py"

PLAY_LOOPS=200
PHASE_M_LOOPS=30
MAX_ITERATIONS=10
PARALLEL_TASKS=11
GAME_INDICES="3,4,5,11,12,13,15,25,30,46,50"

declare -A CONDITIONS=(
  ["full"]=""
  ["no_wiki"]="no_wiki"
)

echo "=== Ablation Round 6 (11 games, 2 conditions) ==="
echo "Games: $GAME_INDICES"
echo "Conditions: ${!CONDITIONS[*]}"
echo ""

for cond_name in "${!CONDITIONS[@]}"; do
  abl_value="${CONDITIONS[$cond_name]}"
  exp_name="abl6_${cond_name}"
  log_file="$PROJECT_ROOT/nohup_abl6_${cond_name}.out"

  echo "Launching: $cond_name -> $exp_name"

  ARGS=(
    python3 "$RUNNER"
    --task-list "[$GAME_INDICES]"
    --play-loops "$PLAY_LOOPS"
    --phase-m-loops "$PHASE_M_LOOPS"
    --max-iterations "$MAX_ITERATIONS"
    --parallel-tasks "$PARALLEL_TASKS"
    --experiment-name "$exp_name"
    --no-resume
  )

  if [[ -n "$abl_value" ]]; then
    ARGS+=(--ablation "$abl_value")
  fi

  setsid nohup "${ARGS[@]}" > "$log_file" 2>&1 < /dev/null &
  echo "  PID: $!"
done

echo ""
echo "All 2 conditions launched (22 agia processes). Monitor:"
echo "  ps aux | grep agia.py | grep -v grep | wc -l"
echo "  tail -f nohup_abl6_*.out"
