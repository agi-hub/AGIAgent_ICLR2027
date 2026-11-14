#!/bin/bash
# ============================================================
# Generate analysis reports for all 5 ablation conditions.
#
# Outputs (in project root):
#   abl_full.csv, abl_no_wiki.csv, abl_no_world_model.csv,
#   abl_no_experiences.csv, abl_no_knowledge.csv
#
# Usage:
#   bash apps/tale_jericho/analyze_ablations.sh
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ANALYZE="$SCRIPT_DIR/analyze_jericho_results.py"

cd "$PROJECT_ROOT"

CONDITIONS="full no_wiki no_world_model no_experiences no_knowledge"

echo "=== Ablation Analysis ==="
echo ""

for cond in $CONDITIONS; do
  exp_name="abl_${cond}"
  csv_file="abl_${cond}.csv"

  echo "--- $cond ---"

  if python3 "$ANALYZE" "$exp_name" --csv "$csv_file" --score ratio 2>&1; then
    echo "  CSV: $csv_file"
  else
    echo "  WARNING: analysis failed for $exp_name (experiment may still be running)"
  fi
  echo ""
done

# Print a quick comparison summary
echo "=== Score Comparison (avg score rate across games) ==="
printf "%-20s %s\n" "Condition" "Avg Score Rate"
printf "%-20s %s\n" "---------" "--------------"

for cond in $CONDITIONS; do
  csv_file="abl_${cond}.csv"
  if [[ -f "$csv_file" ]]; then
    # Extract Avg column from CSV (last column), skip header and Sum row
    avg=$(python3 -c "
import csv
scores = []
with open('$csv_file') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row.get('Game','') == 'Sum':
            continue
        try:
            scores.append(float(row.get('Avg', 0)))
        except:
            pass
if scores:
    print(f'{sum(scores)/len(scores):.4f}')
else:
    print('N/A')
" 2>/dev/null || echo "N/A")
    printf "%-20s %s\n" "$cond" "$avg"
  else
    printf "%-20s %s\n" "$cond" "(no data)"
  fi
done

echo ""
echo "Done. CSV files: abl_*.csv"
