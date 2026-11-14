#!/usr/bin/env bash
# Run the tale_jericho iterative pipeline (play1 -> phase_m1 -> play2 -> ... -> playN).
set -euo pipefail
cd "$(dirname "$0")"

# tale-suite library lives here (microsoft/tale-suite clone). Auto-discovered
# by the runner as the repo's sibling dir, but set explicitly for robustness.
export TALE_SUITE_ROOT="${TALE_SUITE_ROOT:-~/tale-suite}"

# Silence harmless "Failed to import alfworld/textworld_express" UserWarnings
# from tales (only jericho is needed here).
export PYTHONWARNINGS="${PYTHONWARNINGS:-ignore::UserWarning}"

python apps/tale_jericho/run_all_tasks.py \
  --play-loops 200 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 16 \
  --experiment-name jericho_wiki_evolve_full
