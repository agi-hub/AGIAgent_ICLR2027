#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export wiki_memory_read query counts per game per iteration to CSV.

Usage:
    python3 export_wiki_queries.py --csv wiki_queries.csv

Output columns: TaskIdx, Game, q1, q2, ..., q10, Total
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import re
from pathlib import Path
from typing import Any

OUTPUTS_DIR = Path(__file__).resolve().parent / "data" / "benchmark_results" / "jericho_wiki_evolve_full" / "outputs"
MAX_ITERATIONS = 10


def _count_wiki_queries(traj_path: Path) -> int:
    """Count wiki_memory_read entries in a trajectory.jsonl."""
    if not traj_path.exists():
        return 0
    count = 0
    try:
        for line in traj_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if entry.get("tool") == "wiki_memory_read":
                count += 1
    except Exception:
        pass
    return count


def _find_trajectory(play_dir: str) -> Path | None:
    """Find trajectory.jsonl, with fallback for stale paths."""
    p = Path(play_dir) / "logs" / "trajectory.jsonl"
    if p.exists():
        return p
    # Fallback: search sibling dirs
    name = Path(play_dir).name
    m = re.match(r"^(.*_play\d+)_\d{8}_\d{6}$", name)
    if not m:
        return None
    prefix = m.group(1)
    parent = Path(play_dir).parent
    candidates = sorted(parent.glob(f"{prefix}_*/logs/trajectory.jsonl"))
    return candidates[-1] if candidates else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Export wiki query counts per game per iteration")
    parser.add_argument("--csv", type=str, default="wiki_queries.csv", help="CSV output path")
    parser.add_argument("--experiment", type=str, default="jericho_wiki_evolve_full")
    args = parser.parse_args()

    outputs_dir = OUTPUTS_DIR
    rows: list[list[Any]] = []

    pattern = str(outputs_dir / "output_tale_jericho_*_phase_records.json")
    for fpath in sorted(glob.glob(pattern)):
        m = re.match(r".*output_tale_jericho_(\d+)_(JerichoEnv\w+)_phase_records\.json$", fpath)
        if not m:
            continue
        task_idx = int(m.group(1))
        env_name = m.group(2).replace("JerichoEnv", "")

        try:
            records = json.loads(Path(fpath).read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(records, list):
            continue

        row: list[Any] = [task_idx, env_name]
        total = 0
        for i in range(1, MAX_ITERATIONS + 1):
            rec = next((r for r in records if r.get("iteration") == i), None)
            count = 0
            if rec:
                play_dir = rec.get("play_output_dir", "")
                if play_dir:
                    tj = _find_trajectory(play_dir)
                    if tj:
                        count = _count_wiki_queries(tj)
            row.append(count)
            total += count
        row.append(total)
        rows.append(row)

    rows.sort(key=lambda r: r[0])

    # Write CSV
    header = ["TaskIdx", "Game"]
    header += [f"q{i}" for i in range(1, MAX_ITERATIONS + 1)]
    header += ["Total"]

    csv_path = Path(args.csv)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)

        # Summary
        grand_total = sum(r[-1] for r in rows)
        writer.writerow([])
        writer.writerow(["Metric", "Value"])
        writer.writerow(["Total wiki queries", grand_total])
        writer.writerow(["Games", len(rows)])

    # Print summary to console
    print(f"CSV written to {csv_path}")
    print(f"Total wiki queries across all games: {grand_total}")
    print(f"Games: {len(rows)}")

    # Print table
    print()
    hdr = f"{'#':>3}  {'Game':<14}" + "".join(f"{'q'+str(i):>4}" for i in range(1, MAX_ITERATIONS + 1)) + f"  {'Total':>5}"
    print(hdr)
    print("-" * len(hdr))
    for row in rows:
        line = f"{row[0]:>3}  {row[1]:<14}"
        line += "".join(f"{row[2+i]:>4}" for i in range(MAX_ITERATIONS))
        line += f"  {row[-1]:>5}"
        print(line)
    print("-" * len(hdr))
    print(f"{'':>18}" + "".join(f"{sum(r[2+i] for r in rows):>4}" for i in range(MAX_ITERATIONS)) + f"  {grand_total:>5}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
