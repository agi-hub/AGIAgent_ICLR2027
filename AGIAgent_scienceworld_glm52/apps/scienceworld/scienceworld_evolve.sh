#!/usr/bin/env bash
# Run the scienceworld iterative pipeline (play1 -> phase_m1 -> play2 -> ... -> playN).
set -euo pipefail
cd "$(dirname "$0")"

# ScienceWorld server JAR (adjust if installed elsewhere).
export SCIENCEWORLD_SERVER_PATH="${SCIENCEWORLD_SERVER_PATH:-}"

# 5 diverse tasks with partial progress (3%–60%), spanning different task types:
#   idx=285  chemistry-mix                       var=21   eff=33%
#   idx=299  chemistry-mix-paint-secondary-color var=21   eff=30%
#   idx=33   freeze                              var=15   eff=43%
#   idx=59   melt                                var=25   eff=43%
#   idx=115  power-component-renewable-vs-non    var=15   eff=53%
python apps/scienceworld/run_all_tasks.py \
  --task-list "[285,299,33,59,115]" \
  --play-loops 100 --phase-m-loops 15 \
  --max-iterations 10 --parallel-tasks 5 \
  --env-step-limit 100 \
  --experiment-name scienceworld_evolve_v1
