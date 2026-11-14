#!/bin/bash
# Re-run the 63 ScienceWorld test tasks whose iteration-1 was not full score
# (from sw_glm52_test_full), in no-memory baseline mode (single playthrough,
# no wiki memory), parallelism 6.
#
# Task list source: data/benchmark_results/sw_glm52_test_full/outputs/*_phase_records.json
# (iter1 play_score_rate < 1 or play_won false) -> apps/scienceworld/tasklist_63_nomem.json

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "=== ScienceWorld: 63-task no-memory baseline (GLM-5.2) ==="
echo "Parallel: 6, loops: 100, single attempt, no wiki memory"

setsid nohup python3 "$PROJECT_ROOT/apps/scienceworld/run_all_tasks.py" \
  --selection-mode fixed_total \
  --fixed-dataset-split test \
  --task-list "$(python3 -c "import json;print(','.join(map(str,json.load(open('$PROJECT_ROOT/apps/scienceworld/tasklist_63_nomem.json')))))")" \
  --loops 100 \
  --baseline \
  --parallel-tasks 6 \
  --experiment-name sw_glm52_63_nomem \
  > "$PROJECT_ROOT/nohup_sw_glm52_63_nomem.out" 2>&1 < /dev/null &

echo "Launched PID: $!"
echo "Monitor: tail -f nohup_sw_glm52_63_nomem.out"
