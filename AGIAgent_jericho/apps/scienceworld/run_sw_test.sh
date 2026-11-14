#!/bin/bash
# ScienceWorld test with glm-4.7, full condition only.
# Early-exit on win (won=true / progress=100% / score=full).
# Max 10 iterations, parallel=6.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "=== ScienceWorld Test: glm-4.7, full, 30 tasks ==="
echo "Max iterations: 10 (early exit on win)"
echo "Parallel: 6"
echo ""

setsid nohup python3 "$PROJECT_ROOT/apps/scienceworld/run_all_tasks.py" \
  --play-loops 100 \
  --phase-m-loops 30 \
  --max-iterations 10 \
  --parallel-tasks 6 \
  --experiment-name sw_glm_full \
  > "$PROJECT_ROOT/nohup_sw_glm_full.out" 2>&1 < /dev/null &

echo "Launched PID: $!"
echo "Monitor: tail -f nohup_sw_glm_full.out"
