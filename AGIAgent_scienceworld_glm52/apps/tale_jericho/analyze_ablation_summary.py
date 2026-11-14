#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate a single ablation comparison CSV.

Output: abl_summary.csv
  Rows: one per condition (full, no_wiki, no_world_model, no_experiences, no_knowledge)
  Columns: one per game (Balances, Detective, Zork1)
  Each cell: "best_score (completed_rounds/10)"

Usage:
  python3 apps/tale_jericho/analyze_ablation_summary.py
  python3 apps/tale_jericho/analyze_ablation_summary.py --output custom.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BENCHMARK_ROOT = PROJECT_ROOT / "data" / "benchmark_results"
MAX_ITERATIONS = 10

# Display order
CONDITIONS = ["full", "no_wiki", "no_world_model", "no_experiences", "no_knowledge"]
CONDITION_LABELS = {
    "full": "full (control)",
    "no_wiki": "no_wiki",
    "no_world_model": "no_world_model",
    "no_experiences": "no_experiences",
    "no_knowledge": "no_knowledge",
}
GAME_ORDER = []


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _load_phase_records(outputs_dir: Path) -> Dict[str, Dict[int, dict]]:
    """Load phase_records.json for each game.

    Returns: {game_name: {iteration: record_dict}}
    """
    games: Dict[str, Dict[int, dict]] = {}
    if not outputs_dir.is_dir():
        return games

    for f in sorted(outputs_dir.glob("*phase_records.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue

        # Extract game name from filename: output_tale_jericho_51_JerichoEnvZork1_phase_records.json
        game_name = None
        m = re.search(r"JerichoEnv(\w+?)(?=_phase_records|_play\d|_phasem\d)", f.name)
        if m:
            game_name = m.group(1)
        if not game_name:
            for record in data:
                env = record.get("play_output_dir", "") or ""
                m2 = re.search(r"JerichoEnv(\w+?)(?=_play|_phasem|_phase)", env)
                if m2:
                    game_name = m2.group(1)
                    break
        if not game_name:
            continue

        iters: Dict[int, dict] = {}
        for record in data:
            i = record.get("iteration")
            if isinstance(i, int):
                iters[i] = record
        games[game_name] = iters

    return games


def _extract_metrics(game_iters: Dict[int, dict]) -> tuple:
    """Return (avg_score, best_score, completed_rounds) from phase records.

    A round is 'completed' if play_status is anything other than pending/skipped/empty.
    """
    scores = []
    best_overall = 0.0
    completed = 0

    for i, record in game_iters.items():
        if i > MAX_ITERATIONS:
            continue
        play_status = str(record.get("play_status") or "")
        if play_status not in ("", "pending", "skipped"):
            completed += 1
        best = _safe_float(record.get("play_best_score"))
        if best is not None:
            scores.append(best)
            if best > best_overall:
                best_overall = best

    avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0
    return avg_score, best_overall, completed


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate ablation comparison CSV (best + average).")
    parser.add_argument("--prefix", default="abl", help="Experiment name prefix (abl or abl2)")
    parser.add_argument("--output-suffix", default="", help="Suffix for output CSV files (e.g. _r2)")
    args = parser.parse_args()
    prefix = args.prefix

    # Collect data: condition -> game -> (avg, best, rounds)
    results: Dict[str, Dict[str, tuple]] = {}
    all_games: set = set()

    for cond in CONDITIONS:
        exp_name = f"{prefix}_{cond}"
        outputs_dir = BENCHMARK_ROOT / exp_name / "outputs"
        games = _load_phase_records(outputs_dir)
        results[cond] = {}
        for game_name, iters in games.items():
            avg, best, rounds = _extract_metrics(iters)
            results[cond][game_name] = (avg, best, rounds)
            all_games.add(game_name)

    if not all_games:
        print("Error: no data found. Are experiments complete?", file=sys.stderr)
        return 1

    # Order games: known ones first, then alphabetical for any extras
    ordered_games = [g for g in GAME_ORDER if g in all_games]
    ordered_games += sorted(g for g in all_games if g not in GAME_ORDER)

    def _write_csv(path: Path, metric_idx: int, metric_name: str) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            header = ["Condition"] + ordered_games
            writer.writerow(header)
            for cond in CONDITIONS:
                row = [CONDITION_LABELS.get(cond, cond)]
                for game in ordered_games:
                    data = results[cond].get(game)
                    if data:
                        val = data[metric_idx]
                        rounds = data[2]
                        row.append(f"{val:g} ({rounds}/{MAX_ITERATIONS})")
                    else:
                        row.append("-")
                writer.writerow(row)
        print(f"Written: {path} ({metric_name})", file=sys.stderr)

    avg_path = PROJECT_ROOT / f"abl_summary_avg{args.output_suffix}.csv"
    best_path = PROJECT_ROOT / f"abl_summary_best{args.output_suffix}.csv"
    _write_csv(avg_path, 0, "average")
    _write_csv(best_path, 1, "best")

    print()
    print("=== AVERAGE SCORE ===")
    with open(avg_path, "r") as f:
        print(f.read())
    print("=== BEST SCORE ===")
    with open(best_path, "r") as f:
        print(f.read())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
