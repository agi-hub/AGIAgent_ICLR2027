#!/bin/bash
# ============================================================
# Ablation experiment round 2 — 5 games, all conditions parallel.
#
# Games: Ludicorp(#27), Weapon(#47), Temple(#44), Ztuu(#54), Spirit(#43)
# Based on latest optimized code (compressed knowledge, query limits, snippet 200 chars)
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUNNER="$PROJECT_ROOT/apps/tale_jericho/run_all_tasks.py"

PLAY_LOOPS=200
PHASE_M_LOOPS=30
MAX_ITERATIONS=10
PARALLEL_TASKS=5
GAME_INDICES="27,47,44,54,43"

declare -A CONDITIONS=(
  ["full"]=""
  ["no_wiki"]="no_wiki"
  ["no_world_model"]="no_world_model"
  ["no_experiences"]="no_experiences"
  ["no_knowledge"]="no_knowledge"
)

echo "=== Ablation Round 2 (optimized code) ==="
echo "Games: $GAME_INDICES (Ludicorp, Weapon, Temple, Ztuu, Spirit)"
echo "Conditions: ${!CONDITIONS[*]}"
echo ""

for cond_name in "${!CONDITIONS[@]}"; do
  abl_value="${CONDITIONS[$cond_name]}"
  exp_name="abl2_${cond_name}"
  log_file="$PROJECT_ROOT/nohup_abl2_${cond_name}.out"

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
echo "All 5 conditions launched (25 agia processes). Monitor:"
echo "  ps aux | grep agia.py | grep -v grep | wc -l"
echo "  tail -f nohup_abl2_*.out"
