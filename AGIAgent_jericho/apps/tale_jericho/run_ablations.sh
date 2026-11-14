#!/bin/bash
# ============================================================
# Ablation experiment launcher — runs all conditions in parallel.
#
# Each condition gets its own:
#   - experiment name (isolates wiki namespace + output dirs)
#   - AGIA_WIKI_ABLATION env var (controls retrieval filtering)
#   - nohup log file
#
# Usage:
#   bash run_ablations.sh           # run all 5 conditions
#   bash run_ablations.sh no_wiki   # run a single condition
#
# NOTE: Do NOT run this yet. Review first.
# Resource estimate: 5 conditions × N games × (1 play + 1 curate) = many processes.
# With 7 games and --parallel-tasks 7, that's 35 concurrent agia.py per condition,
# 175 total if all 5 run at once. Reduce --parallel-tasks or GAME_INDICES if needed.
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUNNER="$PROJECT_ROOT/apps/tale_jericho/run_all_tasks.py"

# --- Configurable parameters ---
PLAY_LOOPS=${PLAY_LOOPS:-200}
PHASE_M_LOOPS=${PHASE_M_LOOPS:-30}
MAX_ITERATIONS=${MAX_ITERATIONS:-10}
PARALLEL_TASKS=${PARALLEL_TASKS:-3}
# Override game list here (1-based indices). Empty = use TASK_INDEX_LIST in run_all_tasks.py
GAME_INDICES=${GAME_INDICES:-"13,51,8"}  # Detective, Zork1, Balances

# All ablation conditions: name -> env value
# "full" is the control group (no ablation)
declare -A CONDITIONS=(
  ["full"]=""                          # Control: all sections available
  ["no_wiki"]="no_wiki"                # Disable all wiki retrieval
  ["no_world_model"]="no_world_model"  # Disable world_model only
  ["no_experiences"]="no_experiences"  # Disable experiences only
  ["no_knowledge"]="no_knowledge"      # Disable knowledge only
)

# Filter to a single condition if passed as argument
if [[ $# -gt 0 ]]; then
  CONDITION_FILTER="$1"
  for key in "${!CONDITIONS[@]}"; do
    if [[ "$key" != "$CONDITION_FILTER" ]]; then
      unset 'CONDITIONS[$key]'
    fi
  done
  if [[ ${#CONDITIONS[@]} -eq 0 ]]; then
    echo "ERROR: Unknown condition '$CONDITION_FILTER'. Valid: ${!CONDITIONS[*]}"
    exit 1
  fi
fi

echo "=== Ablation Experiment Launcher ==="
echo "Project root: $PROJECT_ROOT"
echo "Conditions: ${!CONDITIONS[*]}"
echo "Games: $GAME_INDICES"
echo "Parallel tasks per condition: $PARALLEL_TASKS"
echo "Max iterations: $MAX_ITERATIONS"
echo ""

# Launch each condition in background
for cond_name in "${!CONDITIONS[@]}"; do
  abl_value="${CONDITIONS[$cond_name]}"
  exp_name="abl_${cond_name}"
  log_file="$PROJECT_ROOT/nohup_abl_${cond_name}.out"

  echo "Launching: $cond_name (ablation=$abl_value) -> $log_file"

  # Build the command
  ARGS=(
    python3 "$RUNNER"
    --play-loops "$PLAY_LOOPS"
    --phase-m-loops "$PHASE_M_LOOPS"
    --max-iterations "$MAX_ITERATIONS"
    --parallel-tasks "$PARALLEL_TASKS"
    --experiment-name "$exp_name"
    --no-resume
  )

  if [[ -n "$GAME_INDICES" ]]; then
    ARGS+=(--task-list "[$(echo "$GAME_INDICES" | tr ',' ',')]")
  fi

  if [[ -n "$abl_value" ]]; then
    ARGS+=(--ablation "$abl_value")
  fi

  # Launch with setsid for full process-tree detachment
  setsid nohup "${ARGS[@]}" > "$log_file" 2>&1 < /dev/null &
  echo "  PID: $!"
done

echo ""
echo "All conditions launched. Monitor with:"
echo "  tail -f nohup_abl_*.out"
echo ""
echo "Check progress:"
echo "  ps aux | grep run_all_tasks | grep -v grep"
