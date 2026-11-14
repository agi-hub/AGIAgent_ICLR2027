#!/bin/bash
# ============================================================
# Ablation experiment round 5 — 10 games (Full>200, best-scoring), 2 conditions.
#
# Games: Detective(#13), Deephome(#12), Advent(#3), Zork1(#51),
#        Murdac(#30), Zork2(#52), Pentari(#34), Ztuu(#54),
#        Tryst205(#46), Enter(#16)
# Conditions: full (control), no_wiki
# Total max score: 3560
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUNNER="$PROJECT_ROOT/apps/tale_jericho/run_all_tasks.py"

PARALLEL_TASKS=20
PLAY_LOOPS=200
PHASE_M_LOOPS=30
MAX_ITERATIONS=10
GAME_INDICES="13,12,3,51,30,52,34,54,46,16"

declare -A CONDITIONS=(
  ["full"]=""
  ["no_wiki"]="no_wiki"
)

echo "=== Ablation Round 5 (10 games, Full>200, 2 conditions) ==="
echo "Games: $GAME_INDICES"
echo "Conditions: ${!CONDITIONS[*]}"
echo ""

for cond_name in "${!CONDITIONS[@]}"; do
  abl_value="${CONDITIONS[$cond_name]}"
  exp_name="abl5_${cond_name}"
  log_file="$PROJECT_ROOT/nohup_abl5_${cond_name}.out"

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
echo "All 2 conditions launched (20 agia processes). Monitor:"
echo "  ps aux | grep agia.py | grep -v grep | wc -l"
echo "  tail -f nohup_abl5_*.out"
