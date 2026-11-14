#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Analyze jericho_wiki_evolve_full benchmark results.

Reads phase_records.json for all games, prints a per-game per-iteration score
table, and computes aggregate metrics:
  - Round-1 total score  (sum of best_score across all games at iteration 1)
  - Best total score     (sum of the highest best_score per game across all iterations)
  - Per-game and dataset-wide score rates

Usage:
    python analyze_jericho_results.py [EXPERIMENT_NAME] [--benchmark-dir DIR]

Defaults: experiment=jericho_wiki_evolve_full, benchmark-dir=data/benchmark_results/<experiment>
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_EXPERIMENT = "jericho_wiki_evolve_full"


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _trajectory_real_score(output_dir: Path) -> Optional[float]:
    """Read trajectory.jsonl and return the true best_score from environment observations.

    The trajectory contains per-step tool results with the real game score as
    reported by the Jericho environment. This is the ground truth, unaffected by
    the _summarize_score_history regex pollution bug in src/main.py.

    If output_dir doesn't exist (stale path from a prior run), search sibling
    directories for the same play{i} pattern to find the real trajectory.
    """
    tj_path = output_dir / "logs" / "trajectory.jsonl"
    if not tj_path.exists():
        # Fallback: search sibling dirs with same game + play iteration pattern
        tj_path = _find_trajectory_fallback(output_dir)
    if tj_path is None or not tj_path.exists():
        return None
    real_best = 0.0
    try:
        for line in tj_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            v = entry.get("best_score")
            if isinstance(v, (int, float)) and v > real_best:
                real_best = float(v)
    except Exception:
        return None
    return real_best


def _find_trajectory_fallback(output_dir: Path) -> Optional[Path]:
    """When the recorded play_output_dir doesn't exist, find a matching trajectory.

    output_dir like  output_tale_jericho_26_JerichoEnvLostpig_play2_20260703_102700
    → search for     output_tale_jericho_26_JerichoEnvLostpig_play2_*
    """
    name = output_dir.name
    # Strip the trailing _TIMESTAMP pattern (12 digits)
    m = re.match(r"^(.*_play\d+)_\d{8}_\d{6}$", name)
    if not m:
        return None
    prefix = m.group(1)
    parent = output_dir.parent
    candidates = sorted(parent.glob(f"{prefix}_*/logs/trajectory.jsonl"))
    return candidates[-1] if candidates else None


def _load_all_games(outputs_dir: Path) -> List[Dict[str, Any]]:
    """Load every *_phase_records.json, cross-check with trajectory.jsonl for real scores."""
    games: List[Dict[str, Any]] = []
    pattern = str(outputs_dir / "output_tale_jericho_*_phase_records.json")
    for fpath in sorted(glob.glob(pattern)):
        m = re.match(
            r".*output_tale_jericho_(\d+)_(JerichoEnv\w+)_phase_records\.json$",
            fpath,
        )
        if not m:
            continue
        task_idx = int(m.group(1))
        env_name = m.group(2)
        try:
            records = json.loads(Path(fpath).read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(records, list):
            continue

        # Cross-check each iteration's score against trajectory ground truth
        for r in records:
            play_dir = r.get("play_output_dir")
            if not play_dir:
                continue
            traj_best = _trajectory_real_score(Path(play_dir))
            if traj_best is not None:
                recorded = _safe_float(r.get("play_best_score"))
                if recorded is not None and abs(recorded - traj_best) > 0.5:
                    # Polluted: recorded score differs from trajectory
                    r["_score_corrected"] = traj_best
                    r["_score_polluted"] = recorded

        games.append(
            {
                "task_idx": task_idx,
                "env_name": env_name,
                "records": records,
            }
        )
    games.sort(key=lambda g: g["task_idx"])
    return games


def _extract_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract per-iteration metrics from phase records, using trajectory-corrected scores."""
    iters: Dict[int, Dict[str, Any]] = {}
    overall_best = 0.0
    overall_full: Optional[float] = None
    won_any = False
    corrected_count = 0

    for r in records:
        i = r.get("iteration")
        if not isinstance(i, int):
            continue

        # Use trajectory-corrected score if available, otherwise recorded score
        if "_score_corrected" in r:
            best = _safe_float(r["_score_corrected"])
            corrected_count += 1
        else:
            best = _safe_float(r.get("play_best_score"))
        full = _safe_float(r.get("play_full_score"))
        won = bool(r.get("play_won"))
        play_status = str(r.get("play_status") or "")
        phm_status = str(r.get("phase_m_status") or "")

        # Fix won flag: if corrected best < full, it can't be a real win
        if best is not None and full is not None and full > 0 and best < full:
            won = False

        iters[i] = {
            "best": best,
            "full": full,
            "won": won,
            "play_status": play_status,
            "phase_m_status": phm_status,
            "corrected": "_score_corrected" in r,
        }

        if best is not None and best > overall_best:
            overall_best = best
        if full is not None and (overall_full is None or full > overall_full):
            overall_full = full
        if won:
            won_any = True

    return {
        "iters": iters,
        "overall_best": overall_best,
        "overall_full": overall_full,
        "won_any": won_any,
        "corrected_count": corrected_count,
    }


def _fmt_score(best: Optional[float], full: Optional[float], won: bool) -> str:
    """Format a score cell like '82/350', '82/350*', or '  -  '."""
    if best is None and full is None:
        # Distinguish between 'skipped with prior data' vs 'pending/not run'
        return "    -    "
    b = f"{best:.0f}" if best is not None else "?"
    f = f"{full:.0f}" if full is not None else "?"
    star = "*" if won else " "
    # Pad for alignment
    return f"{b:>5}/{f:<5}{star}"


def _fmt_status(play_status: str) -> str:
    """Short status tag."""
    if play_status == "skipped":
        return "skip"
    if play_status == "pending":
        return "pend"
    if play_status == "running":
        return "run "
    if play_status == "success":
        return "done"
    if play_status == "partial_success":
        return "part"
    if play_status == "error":
        return "err "
    return play_status[:4]


import csv


def write_csv(
    games: List[Dict[str, Any]],
    max_iterations: int,
    csv_path: Path,
) -> None:
    """Write per-game per-iteration score ratios to CSV.

    Columns: TaskIdx, Game, i1, i2, ..., i10, Best, Full, AvgRatio
    Each iteration cell is best_score / full_score (0-1).
    AvgRatio is the mean of all iteration ratios for that game.
    A final row "Average" shows the column-wise mean of each iteration ratio.
    """
    all_col_ratios: list[list[float]] = [[] for _ in range(max_iterations)]

    rows: List[List[Any]] = []
    for g in games:
        metrics = _extract_metrics(g["records"])
        iters = metrics["iters"]
        full = metrics["overall_full"] or 0.0

        row: List[Any] = [g["task_idx"], g["env_name"].replace("JerichoEnv", "")]
        iter_ratios: list[float] = []
        for i in range(1, max_iterations + 1):
            it = iters.get(i)
            best = it["best"] if it and it["best"] is not None else None
            if best is not None and full and full > 0:
                ratio = best / full
                row.append(round(ratio, 4))
                iter_ratios.append(ratio)
                all_col_ratios[i - 1].append(ratio)
            else:
                row.append("")
        avg_ratio = round(sum(iter_ratios) / len(iter_ratios), 4) if iter_ratios else ""
        row.extend([metrics["overall_best"], full or "", avg_ratio])
        rows.append(row)

    # Header
    header = ["TaskIdx", "Game"]
    header += [f"i{i}" for i in range(1, max_iterations + 1)]
    header += ["Best", "Full", "AvgRatio"]

    # Column averages row
    avg_row: List[Any] = ["", "Average"]
    for i in range(max_iterations):
        col = all_col_ratios[i]
        avg_row.append(round(sum(col) / len(col), 4) if col else "")
    avg_row.extend(["", "", ""])

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)

def write_csv_absolute(
    games: List[Dict[str, Any]],
    max_iterations: int,
    csv_path: Path,
) -> None:
    """Write per-game per-iteration absolute scores to CSV.

    Columns: TaskIdx, Game, i1, i2, ..., i10, Best, Full, Avg
    Each iteration cell is the raw best_score. Missing iterations use full_score.
    Avg is the mean of all iteration scores for that game.
    A final row "Average" shows the column-wise mean of each iteration score.
    """
    all_cols: list[list[float]] = [[] for _ in range(max_iterations)]

    rows: List[List[Any]] = []
    for g in games:
        metrics = _extract_metrics(g["records"])
        iters = metrics["iters"]
        full = metrics["overall_full"] or 0.0

        row: List[Any] = [g["task_idx"], g["env_name"].replace("JerichoEnv", "")]
        iter_vals: list[float] = []
        for i in range(1, max_iterations + 1):
            it = iters.get(i)
            best = it["best"] if it and it["best"] is not None else None
            if best is not None:
                val = best
                row.append(round(val, 1))
                iter_vals.append(val)
                all_cols[i - 1].append(val)
            else:
                row.append("")
        avg_val = round(sum(iter_vals) / len(iter_vals), 1) if iter_vals else ""
        row.extend([metrics["overall_best"], full or "", avg_val])
        rows.append(row)

    header = ["TaskIdx", "Game"]
    header += [f"i{i}" for i in range(1, max_iterations + 1)]
    header += ["Best", "Full", "Avg"]

    sum_row: List[Any] = ["", "Sum"]
    for i in range(max_iterations):
        col = all_cols[i]
        sum_row.append(round(sum(col), 1) if col else "")
    sum_row.extend([
        round(sum(r[12] for r in rows if r[12] != "" and r[12] is not None), 1),
        round(sum(r[13] for r in rows if r[13] != "" and r[13] is not None), 1),
        "",
    ])

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
        writer.writerow(sum_row)



def print_results(
    games: List[Dict[str, Any]],
    max_iterations: int,
    *,
    file=sys.stdout,
) -> None:
    """Print the full results table and aggregate metrics."""

    # ---- Per-game per-iteration table ----
    n_games = len(games)

    # Header
    print(file=file)
    header_game = f"{'#':>3}  {'Game':<16}"
    header_iters = ""
    for i in range(1, max_iterations + 1):
        header_iters += f" i{i:>1}        "
    header_summary = f"  {'Best':>7}  {'Full':>6}  {'Rate':>6}  {'Won':>3}"
    print(header_game + header_iters + header_summary, file=file)
    print("-" * (len(header_game + header_iters + header_summary)), file=file)

    round1_scores: List[float] = []  # iter1 best per game (0 if no data)
    best_scores: List[float] = []  # overall best per game
    full_scores: List[float] = []  # full score per game
    full_known_games: List[str] = []  # games where full > 0

    for g in games:
        metrics = _extract_metrics(g["records"])
        env_name = g["env_name"].replace("JerichoEnv", "")
        task_idx = g["task_idx"]
        iters = metrics["iters"]

        print(f"{task_idx:>3}  {env_name:<16}", file=file, end="")

        for i in range(1, max_iterations + 1):
            it = iters.get(i)
            if it is None:
                cell = "    -    "
            else:
                cell = _fmt_score(it["best"], it["full"], it["won"])
                if it.get("corrected"):
                    cell += "~"  # ~ marks trajectory-corrected scores
            print(f" {cell}", file=file, end="")

        # Summary columns
        ob = metrics["overall_best"]
        of = metrics["overall_full"]
        won = metrics["won_any"]
        rate = (ob / of * 100) if (of and of > 0) else 0.0

        ob_str = f"{ob:.0f}" if ob else "0"
        of_str = f"{of:.0f}" if of else "?"
        won_str = "Y" if won else "-"
        print(f"  {ob_str:>7}  {of_str:>6}  {rate:>5.1f}%  {won_str:>3}", file=file)

        # Collect for aggregation
        r1 = iters.get(1)
        r1_best = r1["best"] if r1 and r1["best"] is not None else 0.0
        round1_scores.append(r1_best)
        best_scores.append(ob)
        if of is not None and of > 0:
            full_scores.append(of)
            full_known_games.append(env_name)

    # ---- Separator ----
    print("=" * 60, file=file)

    # ---- Aggregate metrics ----
    total_round1 = sum(round1_scores)
    total_best = sum(best_scores)
    total_full = sum(full_scores)

    # Score rates
    # Method 1: simple average of per-game rates (macro average)
    game_rates = []
    for g in games:
        m = _extract_metrics(g["records"])
        ob = m["overall_best"]
        of = m["overall_full"]
        if of and of > 0:
            game_rates.append(ob / of)
    macro_rate = (sum(game_rates) / len(game_rates) * 100) if game_rates else 0.0

    # Method 2: total best / total full (micro average)
    micro_rate = (total_best / total_full * 100) if total_full > 0 else 0.0

    print(file=file)
    print("Aggregate Metrics", file=file)
    print("-" * 40, file=file)
    print(f"  Games analyzed:           {n_games}", file=file)
    print(f"  Games with known full:    {len(full_scores)}", file=file)
    print(f"  Games won (won=true):     {sum(1 for g in games if _extract_metrics(g['records'])['won_any'])}", file=file)
    print(file=file)
    print(f"  Round-1 total score:      {total_round1:>10.0f}", file=file)
    print(f"  Best total score:         {total_best:>10.0f}", file=file)
    print(f"  Total full score:         {total_full:>10.0f}", file=file)
    print(file=file)
    print(f"  Macro avg score rate:     {macro_rate:>9.1f}%   (mean of per-game rates)", file=file)
    print(f"  Micro avg score rate:     {micro_rate:>9.1f}%   (total_best / total_full)", file=file)
    print(file=file)

    # ---- Improvement from round 1 to best ----
    improvement = total_best - total_round1
    pct_improve = (improvement / total_round1 * 100) if total_round1 > 0 else 0.0
    print(f"  Improvement (best - r1):  {improvement:>10.0f}", file=file)
    if total_round1 > 0:
        print(f"  Improvement %:            {pct_improve:>9.1f}%", file=file)
    print(file=file)

    # ---- Pollution report ----
    total_corrected = sum(_extract_metrics(g["records"]).get("corrected_count", 0) for g in games)
    if total_corrected > 0:
        print(f"Score corrections (trajectory-verified): {total_corrected}", file=file)
        print("  Scores marked with ~ were corrected from polluted phase_records values", file=file)
        print("  Root cause: _summarize_score_history regex re-parses system print lines", file=file)
        print(file=file)

    # ---- Per-game rate breakdown (sorted by rate desc) ----
    print("Per-Game Score Rate (sorted)", file=file)
    print("-" * 40, file=file)
    rate_list = []
    for g in games:
        m = _extract_metrics(g["records"])
        ob = m["overall_best"]
        of = m["overall_full"]
        rate = (ob / of * 100) if (of and of > 0) else 0.0
        r1 = m["iters"].get(1)
        r1_best = r1["best"] if r1 and r1["best"] is not None else 0.0
        rate_list.append((g["env_name"].replace("JerichoEnv", ""), ob, of or 0, rate, r1_best))
    rate_list.sort(key=lambda x: x[3], reverse=True)
    print(f"  {'Game':<16} {'Best':>6} {'Full':>6} {'Rate':>6}  {'R1':>6}", file=file)
    for name, ob, of, rate, r1 in rate_list:
        print(f"  {name:<16} {ob:>6.0f} {of:>6.0f} {rate:>5.1f}%  {r1:>6.0f}", file=file)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze jericho benchmark results (per-iteration scores + aggregates)."
    )
    parser.add_argument(
        "experiment",
        nargs="?",
        default=DEFAULT_EXPERIMENT,
        help=f"Experiment name (default: {DEFAULT_EXPERIMENT}).",
    )
    parser.add_argument(
        "--benchmark-dir",
        type=str,
        default="",
        help="Override benchmark dir (default: data/benchmark_results/<experiment>).",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="Max iterations to display (default: 10).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Write text results to this file instead of stdout.",
    )
    parser.add_argument(
        "--csv",
        type=str,
        default="",
        help="Write structured per-game per-iteration results to this CSV file.",
    )
    parser.add_argument(
        "--score",
        type=str,
        default="ratio",
        choices=["ratio", "absolute"],
        help="CSV score format: 'ratio' (score/full, default) or 'absolute' (raw scores).",
    )
    args = parser.parse_args()

    # Resolve relative to project root (two levels up from apps/tale_jericho/)
    project_root = Path(__file__).resolve().parent.parent.parent
    if args.benchmark_dir:
        benchmark_dir = Path(args.benchmark_dir)
    else:
        benchmark_dir = project_root / "data" / "benchmark_results" / args.experiment
    outputs_dir = benchmark_dir / "outputs"

    if not outputs_dir.exists():
        print(f"Error: outputs dir not found: {outputs_dir}", file=sys.stderr)
        return 1

    games = _load_all_games(outputs_dir)
    if not games:
        print(f"Error: no phase_records.json found in {outputs_dir}", file=sys.stderr)
        return 1

    out_file = None
    if args.output:
        out_file = open(args.output, "w", encoding="utf-8")

    print(
        f"Experiment: {args.experiment}",
        file=out_file or sys.stdout,
    )

    if args.csv:
        csv_path = Path(args.csv)
        if args.score == "absolute":
            write_csv_absolute(games, args.max_iterations, csv_path)
        else:
            write_csv(games, args.max_iterations, csv_path)
        print(f"CSV written to {csv_path} (score={args.score})", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
