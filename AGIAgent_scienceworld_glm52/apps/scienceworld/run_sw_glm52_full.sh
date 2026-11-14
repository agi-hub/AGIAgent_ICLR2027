#!/bin/bash
# ScienceWorld test set experiment: GLM-5.2, full condition.
# Uses Wiki-Evolve design migrated from Jericho:
#   - Three-tier memory (knowledge + experiences + world model)
#   - Focus guard (hard protection for `focus on X` wrong-target failures)
#   - FATAL interception for confirmed death actions
#   - Iterative curation (play -> curate -> play, 10 iterations)
#
# Test set: 211 task-variation pairs across 24 tasks.
# Early-exit on win (won=true / progress=100% / score=full).

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "=== ScienceWorld Test: GLM-5.2, full (Wiki-Evolve) ==="
echo "Selection: fixed_total, test split (211 task-variation pairs)"
echo "Max iterations: 10 (early exit on win)"
echo "Parallel: 4"
echo ""

setsid nohup python3 "$PROJECT_ROOT/apps/scienceworld/run_all_tasks.py" \
  --selection-mode fixed_total \
  --fixed-dataset-split test \
  --play-loops 100 \
  --phase-m-loops 30 \
  --max-iterations 10 \
  --parallel-tasks 4 \
  --experiment-name sw_glm52_full \
  > "$PROJECT_ROOT/nohup_sw_glm52_full.out" 2>&1 < /dev/null &

echo "Launched PID: $!"
echo "Monitor: tail -f nohup_sw_glm52_full.out"
