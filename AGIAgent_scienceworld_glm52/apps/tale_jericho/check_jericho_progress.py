#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quick progress check for jericho_wiki_evolve_full.

Reads phase_records.json for all 54 games, cross-checks trajectory.jsonl for
real scores, and prints a concise progress table.

Usage:
    python check_jericho_progress.py
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

OUTPUTS_DIR = Path(__file__).resolve().parent / "data" / "benchmark_results" / "jericho_wiki_evolve_full" / "outputs"


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _traj_best(play_dir: str) -> Optional[float]:
    """Real best_score from trajectory.jsonl (ground truth)."""
    p = Path(play_dir) / "logs" / "trajectory.jsonl"
    if not p.exists():
        return None
    best = 0.0
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            v = entry.get("best_score")
            if isinstance(v, (int, float)) and v > best:
                best = float(v)
    except Exception:
        return None
    return best if best > 0 else None


def main() -> int:
    files = sorted(glob.glob(str(OUTPUTS_DIR / "output_tale_jericho_*_phase_records.json")))
    if not files:
        print("No phase_records.json found.", file=sys.stderr)
        return 1

    rows = []
    for fpath in files:
        m = re.match(r".*output_tale_jericho_(\d+)_(JerichoEnv\w+)_phase_records\.json$", fpath)
        if not m:
            continue
        idx = int(m.group(1))
        env = m.group(2).replace("JerichoEnv", "")
        try:
            records = json.loads(Path(fpath).read_text(encoding="utf-8"))
        except Exception:
            continue

        real_best_overall = 0.0
        full_score = 0.0
        done_iters = 0
        run_iters = 0  # iterations that actually have score data
        pending_iters = 0
        iter_scores = {}

        for r in records:
            i = r.get("iteration", 0)
            recorded = _safe_float(r.get("play_best_score"))
            full = _safe_float(r.get("play_full_score"))
            st = str(r.get("play_status") or "")
            play_dir = r.get("play_output_dir", "")

            if full and full > full_score:
                full_score = full

            if st in ("pending", "running"):
                pending_iters += 1
                iter_scores[i] = None
                continue

            # Get real score from trajectory
            real = _traj_best(play_dir) if play_dir else None
            score = real if real is not None else (recorded or 0.0)
            if real is not None and recorded is not None and abs(real - recorded) > 0.5:
                score = real  # use real score when polluted

            if score > real_best_overall:
                real_best_overall = score

            if recorded is not None or st in ("partial_success", "success"):
                run_iters += 1
                iter_scores[i] = score
            else:
                iter_scores[i] = None  # skipped without data (false termination)

            done_iters += 1

        rate = (real_best_overall / full_score * 100) if full_score > 0 else 0.0
        reached_full = full_score > 0 and real_best_overall >= full_score
        is_done = pending_iters == 0 or reached_full

        rows.append((idx, env, done_iters, run_iters, pending_iters,
                      real_best_overall, full_score, rate, reached_full, is_done, iter_scores))

    # Sort by index
    rows.sort(key=lambda x: x[0])

    # Print table
    print()
    print(f"{'#':>3}  {'Game':<14} {'Done':>5} {'Run':>4} {'Pend':>5}  {'Best':>6} {'Full':>6} {'Rate':>6}  {'Status':<8}")
    print("-" * 72)

    done_count = 0
    running_count = 0
    total_best = 0.0
    total_r1 = 0.0
    total_full = 0.0
    full_reached = 0

    for idx, env, done_iters, run_iters, pending, best, full, rate, reached, is_done, iter_scores in rows:
        total_best += best
        total_full += full
        r1 = iter_scores.get(1)
        total_r1 += (r1 if r1 else 0.0)
        if reached:
            full_reached += 1

        if is_done:
            status = "DONE"
            done_count += 1
        else:
            status = "RUN"
            running_count += 1

        best_str = f"{best:.0f}" if best else "0"
        full_str = f"{full:.0f}" if full else "?"
        flag = " *" if reached else ""
        print(f"{idx:>3}  {env:<14} {done_iters:>5} {run_iters:>4} {pending:>5}  {best_str:>6} {full_str:>6} {rate:>5.0f}%  {status:<8}{flag}")

    print("-" * 72)
    macro_rate = sum(r[7] for r in rows) / len(rows) if rows else 0
    micro_rate = (total_best / total_full * 100) if total_full > 0 else 0
    print(f"     {'TOTAL':<14} {'':>5} {'':>4} {'':>5}  {total_best:>6.0f} {total_full:>6.0f}")
    print()
    print(f"  Done:    {done_count}/54   Running: {running_count}/54")
    print(f"  Full score reached (trajectory-verified): {full_reached}/54")
    print(f"  Round-1 total:  {total_r1:>8.0f}")
    print(f"  Best total:     {total_best:>8.0f}   (real, trajectory-verified)")
    print(f"  Total full:     {total_full:>8.0f}")
    print(f"  Macro avg rate: {macro_rate:>7.1f}%")
    print(f"  Micro avg rate: {micro_rate:>7.1f}%")
    print()

    # Show running games detail
    running = [r for r in rows if not r[9]]
    if running:
        print("Running games:")
        for idx, env, done_iters, run_iters, pending, best, full, rate, reached, _, iter_scores in running:
            # find current iteration
            curr = max((i for i, s in iter_scores.items() if s is not None), default=0) + 1
            if curr > 10:
                curr = 10
            full_str = f"{full:.0f}" if full else "?"
            print(f"  {env:<14} iter {curr}/10  best={best:.0f}/{full_str} ({rate:.0f}%)")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
