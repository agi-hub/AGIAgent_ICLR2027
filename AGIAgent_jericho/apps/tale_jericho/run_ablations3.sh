#!/bin/bash
# ============================================================
# Ablation experiment round 3 — 5 games, 3 conditions only.
#
# Games: Night(#31), Zenon(#50), Inhumane(#21), Deephome(#12), Omniquest(#32)
# Conditions: full (control), no_wiki, no_knowledge
# Based on latest optimized code (compressed knowledge, query limits,
# snippet fix, dimension consistency, auto-hint disabled by default)
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUNNER="$PROJECT_ROOT/apps/tale_jericho/run_all_tasks.py"

PLAY_LOOPS=200
PHASE_M_LOOPS=30
MAX_ITERATIONS=10
PARALLEL_TASKS=5
GAME_INDICES="31,50,21,12,32"

declare -A CONDITIONS=(
  ["full"]=""
  ["no_wiki"]="no_wiki"
  ["no_knowledge"]="no_knowledge"
)

echo "=== Ablation Round 3 (optimized code, 3 conditions) ==="
echo "Games: $GAME_INDICES (Night, Zenon, Inhumane, Deephome, Omniquest)"
echo "Conditions: ${!CONDITIONS[*]}"
echo ""

for cond_name in "${!CONDITIONS[@]}"; do
  abl_value="${CONDITIONS[$cond_name]}"
  exp_name="abl3_${cond_name}"
  log_file="$PROJECT_ROOT/nohup_abl3_${cond_name}.out"

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
echo "All 3 conditions launched (15 agia processes). Monitor:"
echo "  ps aux | grep agia.py | grep -v grep | wc -l"
echo "  tail -f nohup_abl3_*.out"
