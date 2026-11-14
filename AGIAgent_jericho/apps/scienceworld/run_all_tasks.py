#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch runner: iterative wiki memory pipeline (play_1 -> phase_m_1 -> play_2 -> ... -> play_N).
Each play iteration is a single-attempt fresh game (no restart within a phase).
Phase M distills trajectory knowledge into the wiki between iterations.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

APP_NAME = "scienceworld"
DATASET_NAME = "ScienceWorld"
TOOL_PREFIX = APP_NAME
DEFAULT_PLAY_LOOPS = 200
TASK_INDEX_LIST: List[int] = []
FIXED_DATASET_SPLIT_FILES: Sequence[str] = ("test_indices.json", "valid_indices.json")
FIXED_DATASET_SPLIT_PRESETS: Dict[str, Sequence[str]] = {
    "total": FIXED_DATASET_SPLIT_FILES,
    "test": ("test_indices.json",),
    "valid": ("valid_indices.json",),
}

APP_DIR = Path(__file__).resolve().parent
AGI_ROOT = APP_DIR.parent.parent.resolve()
WORKSPACE_ROOT = AGI_ROOT.parent.resolve()
DATA_ROOT = AGI_ROOT / "data"
BENCHMARK_RESULTS_ROOT = DATA_ROOT / "benchmark_results"
DEFAULT_GENERAL_ROOT = DATA_ROOT / "default" / "general"
EXPERIENCE_ROOT = DEFAULT_GENERAL_ROOT / "experience"
if str(AGI_ROOT) not in sys.path:
    sys.path.insert(0, str(AGI_ROOT))

from src.tools.scienceworld_tools import ScienceworldTools as ToolClass

MAX_TRANSIENT_PHASE_ATTEMPTS = max(
    1, int(os.environ.get("AGIA_TRANSIENT_PHASE_ATTEMPTS", "1") or 1)
)
TRANSIENT_PHASE_RETRY_BASE_SECONDS = max(
    0, int(os.environ.get("AGIA_TRANSIENT_PHASE_RETRY_BASE_SECONDS", "0") or 0)
)
TRANSIENT_PHASE_RETRY_JITTER_SECONDS = max(
    0, int(os.environ.get("AGIA_TRANSIENT_PHASE_RETRY_JITTER_SECONDS", "0") or 0)
)
PHASE_ZOMBIE_STALE_SECONDS = 1800
WRITE_PER_RUN_PHASE_LOGS = str(
    os.environ.get("AGIA_WRITE_PER_RUN_PHASE_LOGS", "false") or "false"
).strip().lower() in {"1", "true", "yes", "on"}
RECOVERABLE_PHASE_RETURN_CODES = {129, 130, 137, 143, -9, -15}
TRANSIENT_MODEL_ERROR_MARKERS = (
    "error executing subtask: connection error",
    "connection error",
    "temporary failure in name resolution",
    "name resolution",
    "apiconnectionerror",
    "api connection error",
    "connecterror",
    "remoteprotocolerror",
    "readtimeout",
    "timeout",
    "timed out",
    "rate limit",
    "too many requests",
    "too many concurrent",
    "concurrent requests",
    "parallel requests",
    "parallel request",
    "overloaded",
    "server overloaded",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "throttle",
    "retry later",
    "try again later",
    "error code: 429",
    "error code: 500",
    "error code: 502",
    "error code: 503",
    "error code: 504",
    "status code 429",
    "status code 500",
    "status code 502",
    "status code 503",
    "status code 504",
)
RECOVERABLE_PHASE_INTERRUPTION_MARKERS = (
    "keyboardinterrupt",
    "killed",
    "terminated",
    "sigterm",
    "sigkill",
    "hangup",
    "interrupted",
    "broken pipe",
    "exit code 129",
    "returncode 129",
)


def _safe_name(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", text).strip("_") or "task"


def _experiment_name(text: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", (text or "").strip()).strip("_")
    return safe or "scienceworld_smoke_v1"


def _resolve_log_file(base_dir: Path, raw_value: str) -> Optional[Path]:
    value = (raw_value or "").strip()
    if not value:
        return None
    if value.lower() == "auto":
        return base_dir / "nohup.out"

    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return base_dir / candidate


class _ExperimentLogger:
    def __init__(self, file_paths: Sequence[Path]) -> None:
        self.console_out = sys.stdout
        self.console_err = sys.stderr
        self.file_paths = [Path(p).resolve() for p in file_paths]
        self._write_lock = threading.Lock()
        self.file_handles = []
        for path in self.file_paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.file_handles.append(open(path, "a", buffering=1, encoding="utf-8"))

    def close(self) -> None:
        for handle in self.file_handles:
            try:
                handle.close()
            except Exception:
                pass

    def write(self, text: str, error: bool = False) -> None:
        if text is None:
            return
        with self._write_lock:
            stream = self.console_err if error else self.console_out
            stream.write(text)
            stream.flush()
            for handle in self.file_handles:
                handle.write(text)
                handle.flush()

    def println(self, text: str = "", error: bool = False) -> None:
        self.write(f"{text}\n", error=error)

    def run_process(
        self,
        cmd: Sequence[str],
        cwd: Path,
        env: Dict[str, str],
        per_run_log_path: Path,
        output_dir: Path,
        write_per_run_log: bool,
    ) -> int:
        per_run_log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(per_run_log_path, "a", buffering=1, encoding="utf-8") as per_run_fp:
            per_run_fp.write(f"$ {' '.join(cmd)}\n")
            if not write_per_run_log:
                manager_log_path = (output_dir / "logs" / "manager.log").resolve()
                per_run_fp.write(
                    "Per-phase stdout copy disabled to avoid duplicate logs. "
                    f"See manager log instead: {manager_log_path}\n"
                )
            per_run_fp.flush()
            proc = subprocess.Popen(
                list(cmd),
                cwd=str(cwd),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                start_new_session=True,
            )
            assert proc.stdout is not None
            stdout_queue: "queue.Queue[Optional[str]]" = queue.Queue()

            def _reader() -> None:
                try:
                    for line in proc.stdout:
                        stdout_queue.put(line)
                finally:
                    stdout_queue.put(None)

            reader_thread = threading.Thread(target=_reader, daemon=True)
            reader_thread.start()

            terminated_for_stale = False
            terminate_reason = ""
            kill_grace_seconds = max(
                1.0, float(os.environ.get("AGIA_PHASE_TERMINATE_GRACE_SECONDS", "20") or 20)
            )

            while True:
                try:
                    line = stdout_queue.get(timeout=1.0)
                except queue.Empty:
                    if proc.poll() is not None:
                        break
                    spawn_status = _load_spawn_manager_status(output_dir)
                    if _is_spawn_status_stale(spawn_status):
                        runtime_status = str(spawn_status.get("status") or "unknown").strip().lower()
                        last_update = (
                            spawn_status.get("last_loop_update")
                            or spawn_status.get("updated_at")
                            or spawn_status.get("start_time")
                            or "unknown"
                        )
                        terminate_reason = (
                            f"spawn manager status remained {runtime_status} and became stale "
                            f"(last_update={last_update})"
                        )
                        self.println(
                            f"   detected stalled child process, sending SIGTERM: {terminate_reason}",
                            error=True,
                        )
                        try:
                            proc.terminate()
                            proc.wait(timeout=kill_grace_seconds)
                        except subprocess.TimeoutExpired:
                            self.println(
                                f"   child did not exit after {kill_grace_seconds:.0f}s, sending SIGKILL",
                                error=True,
                            )
                            proc.kill()
                            proc.wait()
                        terminated_for_stale = True
                        break
                    continue

                if line is None:
                    break
                self.write(line)
                if write_per_run_log:
                    per_run_fp.write(line)
                    per_run_fp.flush()

            reader_thread.join(timeout=1.0)
            returncode = proc.wait()
            if terminated_for_stale and returncode == 0:
                returncode = 143
            if terminated_for_stale:
                _mark_spawn_status_terminal(
                    output_dir,
                    terminal_status="terminated_stale",
                    error_message=(
                        "Runner terminated child process after stale progress detection: "
                        f"{terminate_reason}"
                    ),
                    returncode=returncode,
                    stale_killed=True,
                )
                self.println(f"   process terminated for stale progress: {terminate_reason}", error=True)
            return returncode


def _slice(tasks: List[str], offset: int, count: int) -> List[str]:
    s = max(0, int(offset))
    if s >= len(tasks):
        return []
    if int(count) <= 0:
        return tasks[s:]
    return tasks[s:s + int(count)]


def _scienceworld_task_key_to_env_name(task_key: str) -> str:
    match = re.match(r"^task-[^-]+-(.+)$", str(task_key or "").strip())
    if not match:
        raise ValueError(f"invalid ScienceWorld task key: {task_key}")
    return match.group(1)


def _load_scienceworld_taskname2id() -> Dict[str, int]:
    path = APP_DIR / "taskname2id.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise ValueError(f"invalid taskname2id file: {path}")
    result: Dict[str, int] = {}
    for key, value in data.items():
        result[str(key)] = int(value)
    return result


def _load_fixed_total_dataset_items(split_name: str = "total") -> List[Dict[str, Any]]:
    normalized_split = str(split_name or "total").strip().lower()
    split_files = FIXED_DATASET_SPLIT_PRESETS.get(normalized_split)
    if not split_files:
        raise ValueError(
            f"unsupported fixed dataset split: {split_name}. "
            f"Expected one of {sorted(FIXED_DATASET_SPLIT_PRESETS)}"
        )

    taskname2id = _load_scienceworld_taskname2id()
    canonical_keys = [
        key for key, _ in sorted(taskname2id.items(), key=lambda item: (int(item[1]), str(item[0])))
    ]
    canonical_index = {key: idx + 1 for idx, key in enumerate(canonical_keys)}

    pair_to_split: Dict[tuple[str, int], str] = {}
    for split_file in split_files:
        split_path = APP_DIR / split_file
        raw_items = json.loads(split_path.read_text(encoding="utf-8"))
        if not isinstance(raw_items, list):
            raise ValueError(f"invalid fixed dataset split file: {split_path}")
        for row in raw_items:
            if not isinstance(row, list) or len(row) != 2:
                raise ValueError(f"invalid row in {split_path}: {row!r}")
            task_key = str(row[0])
            variation_num = int(row[1])
            if task_key not in taskname2id:
                raise ValueError(f"unknown task key in {split_path}: {task_key}")
            pair_to_split[(task_key, variation_num)] = split_file.replace("_indices.json", "")

    ordered_pairs = sorted(
        pair_to_split.keys(),
        key=lambda item: (taskname2id[item[0]], int(item[1])),
    )
    dataset_items: List[Dict[str, Any]] = []
    for dataset_item_index_1based, (task_key, variation_num) in enumerate(ordered_pairs, start=1):
        dataset_items.append(
            {
                "dataset_item_index_1based": dataset_item_index_1based,
                "task_index_1based": dataset_item_index_1based,
                "task_key": task_key,
                "canonical_task_index_1based": canonical_index[task_key],
                "env_name": _scienceworld_task_key_to_env_name(task_key),
                "variation_num": int(variation_num),
                "split_selection": normalized_split,
                "split": pair_to_split[(task_key, variation_num)],
            }
        )
    return dataset_items


def _select_fixed_dataset_items(
    dataset_items: Sequence[Dict[str, Any]],
    task_list_raw: str,
    task_offset: int,
    task_count: int,
) -> List[Dict[str, Any]]:
    if task_list_raw.strip():
        requested_indices = _parse_task_list(task_list_raw)
        out_of_range = [i for i in requested_indices if i > len(dataset_items)]
        if out_of_range:
            raise ValueError(
                f"dataset item index out of range: {out_of_range}; total fixed dataset items={len(dataset_items)}"
            )
        return [dict(dataset_items[idx - 1]) for idx in requested_indices]

    selected = _slice(list(dataset_items), task_offset, task_count)
    return [dict(item) for item in selected]


def _parse_task_list(raw: str) -> List[int]:
    text = (raw or "").strip()
    if not text:
        return []

    values: List[Any]
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            values = parsed
        elif isinstance(parsed, int):
            values = [parsed]
        else:
            raise ValueError("task list must be a JSON list or integer")
    except Exception:
        cleaned = text
        if cleaned.startswith("[") and cleaned.endswith("]"):
            cleaned = cleaned[1:-1]
        parts = [p.strip() for p in cleaned.split(",") if p.strip()]
        if not parts:
            raise ValueError("task list is empty")
        values = parts

    result: List[int] = []
    for v in values:
        if isinstance(v, bool):
            raise ValueError(f"invalid task index: {v}")
        try:
            idx = int(v)
        except Exception as e:
            raise ValueError(f"invalid task index: {v}") from e
        if idx <= 0:
            raise ValueError(f"task index must be >= 1, got {idx}")
        result.append(idx)

    if not result:
        raise ValueError("task list is empty")
    return result


def _slice_variations(variation_count: int, offset: int, count: int) -> List[int]:
    total = max(0, int(variation_count))
    start = max(0, int(offset))
    if start >= total:
        return []
    if int(count) <= 0:
        end = total
    else:
        end = min(total, start + int(count))
    return list(range(start, end))


def _quoted_or_empty(text: str) -> str:
    value = str(text or "")
    return f"\"{value}\""


def _play_requirement(
    env_name: str,
    variation_num: int,
    simplification_str: str,
    env_step_limit: int,
    iteration: int,
    max_iterations: int,
    use_wiki: bool,
) -> str:
    """Unified requirement for every play iteration (iterations 1..N)."""
    lines: List[str] = [
        f"Run only one {DATASET_NAME} task: {env_name}.",
        f"Variation: {variation_num}.",
        f"Only {TOOL_PREFIX}_action is allowed for environment interaction.",
        (
            "The first environment call must include "
            f"env_name=\"{env_name}\", variation_num={variation_num}, "
            f"simplification_str={_quoted_or_empty(simplification_str)}, "
            f"env_step_limit={int(env_step_limit)}."
        ),
        "",
        f"This is attempt {iteration} of {max_iterations}. Each attempt is a FRESH game — one single playthrough with no restart.",
        "Your goal is always to maximize score/progress and WIN the task. Make your strongest effort.",
        f"Keep calling {TOOL_PREFIX}_action(action=...) each turn until done=true is returned.",
        "",
        "Task reading (critical):",
        (
            "- The env_name above is only the task identifier (e.g. 'boil'), not the full task description. "
            f"After your first {TOOL_PREFIX}_action call initializes the environment, the tool result contains a "
            "`task_description` field with the real objective (e.g. 'Your task is to boil water. ...')."
        ),
        "- Read `task_description` on the very first tool result and use it as your authoritative goal for every subsequent action. Do not plan from the task name alone.",
        "- Also read the returned `observation`, `feedback`, `look`, `inventory`, `admissible_commands`, `score`, and `progress` to ground each decision.",
        "",
        "Solving priorities:",
        "- Treat completing the task and reaching a full win (done=true, won=true) as the primary objective. Maximize score and progress.",
        "- Derive a concrete plan from the task description and current observation, then execute it step by step with scienceworld_action.",
        "- Before an irreversible transformation, check for focus/connect/open/hold/container prerequisites and satisfy them first.",
        "",
        "FOCUS ON warning: `focus on X` is irreversible — wrong X instantly fails with -100. Focus on the exact substance name from task_description, never a container (cup/pot/jug) or state variant (liquid/gas). Check admissible_commands when unsure.",
        "",
        "Reflection on repeated failures:",
        "- If you find yourself stuck — repeating the same actions, hitting the same dead end, or failing to "
        "progress for many turns — STOP and reflect: What have you tried? What is blocking you? What "
        "fundamentally different approach could work?",
        "- Do NOT keep doing the same thing expecting different results.",
        "",
        "Single-attempt rule (critical):",
        "- When done=true is returned (task complete, won, or lost), the attempt is over. Do NOT attempt to restart.",
        "- Output TASK_COMPLETED: <brief summary> with your best_score/current_score/full_score/score_rate/progress/best_progress.",
        "- If the tool returns an error saying the task has ended, immediately output TASK_COMPLETED.",
        "",
        "Parser recovery and loop handling:",
        f"- If {TOOL_PREFIX}_action returns parser_feedback.is_parser_issue=true, use parser_feedback.category, local_repair_focus, and suggested_actions before any more high-level planning.",
        f"- If {TOOL_PREFIX}_action returns stuck_state.is_stuck=true, obey stuck_state.recommended_policy before more high-level planning: local_retry_only means try at most one nearby unblocked variant, and switch_local_goal means abandon the current command chain and pivot locally.",
        f"- If {TOOL_PREFIX}_action returns anti_loop_blocked=true or action_executed=false, do not retry that blocked action; immediately follow must_do_action if present, otherwise change branch.",
        "- When parser feedback indicates a local command failure, switch into parser recovery mode: stay on the same local goal, try at most 1-3 nearby command variants or prerequisite repairs.",
        "- If parser recovery fails 3 times for the same local goal, abandon that exact command chain and move to a nearby alternative.",
        "- When blocked_action_patterns is non-empty and the local state has not clearly changed, do not repeat those blocked patterns.",
    ]

    if use_wiki:
        lines += [
            "",
            "WIKI-GUIDED SOLVING:",
            "Prior wiki knowledge from earlier attempts IS available.",
            "STRATEGY: Query the wiki for score-increasing actions (section=\"knowledge\"). Use them as REFERENCE — try the suggested actions, but verify each one against the current observation. If a wiki action does not work, skip it and explore alternatives.",
            "The wiki is a starting point, not a fixed path. It may contain errors or miss better routes. Always keep exploring new actions and areas the wiki does not mention.",
            "CRITICAL SURVIVAL: Before EVERY action, check if it matches a [FATAL:...] entry in the wiki Death Traps. NEVER execute a marked action — it will cause failure.",
            "Do not spam wiki reads. Search once at startup, then only when stuck. Max 3 wiki_memory_read calls per attempt.",
        ]
    else:
        lines += [
            "",
            "This is your first attempt — no prior knowledge is available. Explore and solve from scratch.",
        ]

    lines += [
        "",
        "At the end, output best_score/current_score/full_score/score_rate/progress/best_progress.",
    ]
    return "\n".join(lines)


def _baseline_requirement(
    env_name: str,
    variation_num: int,
    simplification_str: str,
    env_step_limit: int,
) -> str:
    return "\n".join(
        [
            f"Run only one {DATASET_NAME} task: {env_name}.",
            f"Variation: {variation_num}.",
            f"Only {TOOL_PREFIX}_action is allowed for environment interaction.",
            (
                "The first environment call must include "
                f"env_name=\"{env_name}\", variation_num={variation_num}, "
                f"simplification_str={_quoted_or_empty(simplification_str)}, "
                f"env_step_limit={int(env_step_limit)}."
            ),
            "",
            "Phase: Baseline. Solve this task from scratch without any long-term memory or prior exploration.",
            f"Keep calling {TOOL_PREFIX}_action(action=...) each turn until done=true is returned.",
            "",
            "No-memory baseline rules (strict):",
            "- Do NOT call wiki_memory_read; this is a no-memory baseline run.",
            "- Rely only on the live environment observation each turn.",
            "",
            "Solving strategy:",
            "- Start with a harmless observation action such as 'look around' to anchor the current state.",
            "- Reason directly from the task description and current observation to choose the next action.",
            f"- If {TOOL_PREFIX}_action returns parser_feedback.is_parser_issue=true, use parser_feedback.category, local_repair_focus, and suggested_actions before more high-level planning.",
            f"- If {TOOL_PREFIX}_action returns stuck_state.is_stuck=true, obey stuck_state.recommended_policy.",
            f"- If {TOOL_PREFIX}_action returns anti_loop_blocked=true or action_executed=false, do not retry that blocked action; immediately change branch.",
            "",
            "Single-attempt rule: When done=true is returned, output TASK_COMPLETED with your final scores. No restart.",
            "",
            "At the end, output best_score/current_score/full_score/score_rate/progress/best_progress.",
        ]
    )



def _scienceworld_task_slug(env_name: str) -> str:
    """Task slug for wiki naming: ScienceWorld task names are already clean slugs."""
    raw = str(env_name or "").strip()
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", raw).strip("_").lower() or _safe_name(raw).lower()


def _pre_extract_score_actions(trajectory_path: str) -> str:
    """Pre-parse trajectory.jsonl and extract score/progress-progression actions.

    Returns a human-readable summary injected into the Curator prompt so the
    Curator does not need to parse the raw trajectory itself.
    """
    try:
        records = []
        with open(trajectory_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except (json.JSONDecodeError, ValueError):
                    continue
    except (IOError, OSError):
        return ""

    if not records:
        return ""

    actions_with_score = []
    prev_best = 0.0
    prev_best_progress = 0.0
    for rec in records:
        if rec.get("tool") != "scienceworld_action":
            continue
        best = rec.get("best_score")
        current = rec.get("current_score")
        action = rec.get("action", "")
        done = rec.get("done", False)
        won = rec.get("won", False)
        progress = rec.get("progress")
        best_progress = rec.get("best_progress")
        # Extract room name from observation
        obs = str(rec.get("observation", "") or "")
        room = ""
        for oline in obs.strip().split("\n"):
            oline_s = oline.strip().lower()
            if oline_s.startswith(("this is the ", "you are in")):
                import re as _re
                m = _re.match(r"^(?:this is the |you are in (?:the )?)(.+?)\.?\s*$", oline_s)
                if m:
                    room = m.group(1).strip()
                break
        if best is None and current is None and progress is None:
            continue
        try:
            best_f = float(best) if best is not None else 0.0
            current_f = float(current) if current is not None else 0.0
            progress_f = float(progress) if progress is not None else 0.0
            best_progress_f = float(best_progress) if best_progress is not None else 0.0
        except (TypeError, ValueError):
            continue
        delta = current_f - prev_best if current_f > prev_best else 0.0
        progress_delta = best_progress_f - prev_best_progress if best_progress_f > prev_best_progress else 0.0
        actions_with_score.append({
            "action": action,
            "room": room,
            "best_score": best_f,
            "current_score": current_f,
            "delta": delta,
            "progress": progress_f,
            "best_progress": best_progress_f,
            "progress_delta": progress_delta,
            "done": done,
            "won": won,
        })
        if best_f > prev_best:
            prev_best = best_f
        if best_progress_f > prev_best_progress:
            prev_best_progress = best_progress_f

    if not actions_with_score:
        return ""

    final = actions_with_score[-1]
    score_actions = [a for a in actions_with_score if a["delta"] > 0]
    progress_actions = [a for a in actions_with_score if a["progress_delta"] > 0]
    death_actions = [a for a in actions_with_score if a.get("done") and not a.get("won")]
    # Detect focus actions (critical for ScienceWorld — wrong focus = -100)
    focus_actions = [a for a in actions_with_score if "focus on" in a["action"].lower()]
    failed_focus = [a for a in focus_actions if a["best_score"] < 0 or a["done"]]

    lines = [
        "## Pre-Extracted Trajectory Summary (auto-generated — do NOT re-parse the trajectory file)",
        f"- Total actions: {len(actions_with_score)}",
        f"- Final best_score: {final['best_score']}",
        f"- Final best_progress: {final['best_progress']}",
        f"- Score-increasing actions: {len(score_actions)}",
        f"- Progress-increasing actions: {len(progress_actions)}",
        f"- Focus actions: {len(focus_actions)} (failed: {len(failed_focus)})",
        "",
    ]

    if score_actions:
        lines.append("### Score-Progression Actions (VERIFIED — include room context):")
        for i, sa in enumerate(score_actions, 1):
            room_str = f" at [{sa['room']}]" if sa.get("room") else ""
            lines.append(f"  {i}. {sa['action']}{room_str} -> +{sa['delta']:.0f} (score {sa['best_score']:.0f})")
        lines.append("")

    if progress_actions:
        lines.append("### Progress-Progression Actions (VERIFIED — include room context):")
        for i, pa in enumerate(progress_actions, 1):
            room_str = f" at [{pa['room']}]" if pa.get("room") else ""
            lines.append(f"  {i}. {pa['action']}{room_str} -> +{pa['progress_delta']:.1f}% progress")
        lines.append("")

    if focus_actions:
        lines.append("### Focus Actions (CRITICAL — record correct focus targets):")
        for fa in focus_actions:
            status = "FAILED" if fa in failed_focus else "OK"
            room_str = f" at [{fa['room']}]" if fa.get("room") else ""
            lines.append(f"  - [{status}] {fa['action']}{room_str} (score {fa['best_score']:.0f}, progress {fa['best_progress']:.1f}%)")
        lines.append("")

    if death_actions:
        lines.append("### Death/Failure Actions:")
        for da in death_actions:
            room_str = f" at [{da.get('room','')}]" if da.get("room") else ""
            lines.append(f"  - {da['action']}{room_str} -> failed (score was {da['best_score']:.0f})")
        lines.append("")

    lines.append(
        "Use the above as your primary data source. Cross-reference with the trajectory only if you need "
        "room/object details. Focus your effort on SYNTHESIZING knowledge (connecting fragments), not parsing."
    )
    return "\n".join(lines)


def _phase_m_requirement(
    env_name: str,
    variation_num: int,
    wiki_root: str,
    trajectory_log_path: str,
    iteration: int,
) -> str:
    """Build the phase_m user requirement: static format rules + dynamic per-iteration params."""
    task_slug = _scienceworld_task_slug(env_name)
    is_first = (iteration == 1)

    knowledge_path = os.path.join(wiki_root, "knowledge", f"score_recipe_{task_slug}.md")
    exp_path = os.path.join(wiki_root, "experiences", datetime.now().strftime("%Y-%m-%d"), f"{task_slug}-var{variation_num}.md")

    # Load static format instructions from phase_m_prompt.txt
    prompt_file = APP_DIR / "prompts" / "phase_m_prompt.txt"
    static_instructions = ""
    if prompt_file.is_file():
        static_instructions = prompt_file.read_text(encoding="utf-8").strip()

    lines: List[str] = []
    if static_instructions:
        lines += [static_instructions, "", "=" * 60, ""]

    lines += [
        f"Attempt {iteration} has just completed. Update the wiki using the paths below.",
        "",
        f"Task: {env_name} (variation {variation_num}).",
        f"Task slug: {task_slug}",
        f"Wiki root: {wiki_root}",
        f"Latest trajectory (from attempt {iteration}): {trajectory_log_path}",
        "",
        f"Knowledge file (MUST use this exact path): {knowledge_path}",
        f"Experience file: {exp_path}",
        f"Experience relative path (for knowledge links): ../experiences/{datetime.now().strftime('%Y-%m-%d')}/{task_slug}-var{variation_num}.md",
    ]

    # Inject pre-extracted score actions so the Curator doesn't need to parse raw trajectory
    pre_extracted = _pre_extract_score_actions(trajectory_log_path)
    if pre_extracted:
        lines += [
            pre_extracted,
            "",
            "The summary above is auto-extracted from the trajectory. Use it as your PRIMARY data source.",
            "Only read the raw trajectory file if you need room/object details not in the summary.",
            "",
        ]

    if is_first:
        lines.append("This is the first curation — the wiki may be empty for this task. Create the files above.")
    else:
        lines.append(f"This is NOT the first curation. Use 'cat {knowledge_path}' to read the existing knowledge, then REWRITE the knowledge file completely with merged old+new. For the experience file, READ it and APPEND your new entry — do NOT overwrite previous entries.")

    return "\n".join(lines)


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _fmt(value: Any, digits: int = 4) -> str:
    v = _safe_float(value)
    if v is None:
        return "N/A"
    return f"{v:.{digits}f}"


def _avg(values: List[Any]) -> Optional[float]:
    nums: List[float] = []
    for value in values:
        v = _safe_float(value)
        if v is not None:
            nums.append(v)
    if not nums:
        return None
    return sum(nums) / len(nums)


def _effective_progress(summary: Optional[Dict[str, Any]]) -> Optional[float]:
    if not isinstance(summary, dict):
        return None
    best_progress = _safe_float(summary.get("best_progress"))
    if best_progress is not None:
        return best_progress
    return _safe_float(summary.get("progress"))


def _load_score_summary(output_dir: Path) -> Dict[str, Any]:
    summary_path = output_dir / "logs" / "score_summary.json"
    if not summary_path.exists():
        return {
            "has_metrics": False,
            "reason": f"score summary file not found: {summary_path}",
        }

    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {
            "has_metrics": False,
            "error": f"failed to parse {summary_path}: {e}",
        }

    if not isinstance(data, dict):
        return {
            "has_metrics": False,
            "error": f"invalid score summary format in {summary_path}",
        }

    if "has_metrics" not in data:
        data["has_metrics"] = False
    if data.get("has_metrics") and data.get("effective_progress") is None:
        data["effective_progress"] = _effective_progress(data)
        data["progress_source"] = "best_progress" if data.get("best_progress") is not None else "progress"

    data["score_summary_path"] = str(summary_path.resolve())
    return data


def _load_spawn_manager_status(output_dir: Path) -> Dict[str, Any]:
    status_path = output_dir / ".agia_spawn_manager_status.json"
    if not status_path.exists():
        return {
            "exists": False,
            "status_path": str(status_path.resolve()),
        }

    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {
            "exists": True,
            "status_path": str(status_path.resolve()),
            "error": f"failed to parse {status_path}: {e}",
        }

    if not isinstance(data, dict):
        return {
            "exists": True,
            "status_path": str(status_path.resolve()),
            "error": f"invalid spawn manager status format in {status_path}",
        }

    data["exists"] = True
    data["status_path"] = str(status_path.resolve())
    return data


def _write_spawn_manager_status(output_dir: Path, payload: Dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / ".agia_spawn_manager_status.json"
    status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return status_path


def _mark_spawn_status_terminal(
    output_dir: Path,
    *,
    terminal_status: str,
    error_message: str,
    returncode: Optional[int] = None,
    stale_killed: bool = False,
) -> Dict[str, Any]:
    existing = _load_spawn_manager_status(output_dir)
    now_iso = datetime.now().isoformat()
    previous_status = str(existing.get("status") or "").strip()
    payload: Dict[str, Any] = {}
    if existing.get("exists"):
        payload = {
            k: v
            for k, v in existing.items()
            if k not in {"exists", "status_path"}
        }

    payload["status"] = terminal_status
    payload["completion_time"] = now_iso
    payload["updated_at"] = now_iso
    payload["error"] = error_message
    payload["terminated_by_runner"] = True
    payload["stale_killed"] = bool(stale_killed)
    if previous_status and previous_status != terminal_status:
        payload["previous_status"] = previous_status
    if not str(payload.get("last_loop_update") or "").strip():
        payload["last_loop_update"] = now_iso
    if returncode is not None:
        payload["returncode"] = int(returncode)

    _write_spawn_manager_status(output_dir, payload)
    return _load_spawn_manager_status(output_dir)


def _extract_phase_task_status(
    score_summary: Optional[Dict[str, Any]],
    spawn_status: Optional[Dict[str, Any]] = None,
) -> str:
    if isinstance(score_summary, dict):
        task_status = str(score_summary.get("task_status") or "").strip().lower()
        if task_status:
            return task_status

    if isinstance(spawn_status, dict):
        runtime_status = str(spawn_status.get("status") or "").strip().lower()
        if runtime_status:
            return runtime_status

    return ""


def _phase_status_from_returncode(
    returncode: int,
    score_summary: Dict[str, Any],
    spawn_status: Optional[Dict[str, Any]] = None,
) -> str:
    if int(returncode) == 0:
        return "success"

    task_status = _extract_phase_task_status(score_summary, spawn_status)
    if task_status == "skipped":
        return "skipped"
    if task_status == "max_rounds_reached":
        return "max_rounds_reached"
    if isinstance(score_summary, dict) and score_summary.get("has_metrics"):
        return "partial_success"

    return "error"


def _read_log_tail(path: Path, max_chars: int = 16000) -> str:
    try:
        if not path.exists():
            return ""
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _read_phase_diagnostic_tail(output_dir: Path, per_run_log_path: Path, max_chars: int = 16000) -> str:
    parts: List[str] = []
    seen = set()
    candidates = [
        per_run_log_path,
        output_dir / "logs" / "manager.log",
        output_dir / "logs" / "manager.out",
    ]
    for path in candidates:
        resolved = str(path.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        text = _read_log_tail(path, max_chars=max_chars)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _parse_iso_datetime(text: Any) -> Optional[datetime]:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _spawn_status_last_progress_time(spawn_status: Optional[Dict[str, Any]]) -> Optional[datetime]:
    """Use the newest timestamp among main-loop updates and asset-update heartbeats.

    Without this, long graph/world_model LLM calls can freeze `last_loop_update` while
    `tool_executor` still refreshes `asset_update_in_progress.updated_at`, and the batch
    runner mis-classifies the child as stale (false positive).
    """
    if not isinstance(spawn_status, dict):
        return None
    candidates: List[datetime] = []
    for key in ("last_loop_update", "updated_at", "start_time"):
        t = _parse_iso_datetime(spawn_status.get(key))
        if t is not None:
            candidates.append(t)
    aid = spawn_status.get("asset_update_in_progress")
    if isinstance(aid, dict):
        t = _parse_iso_datetime(aid.get("updated_at"))
        if t is not None:
            candidates.append(t)
    return max(candidates) if candidates else None


def _is_running_like_status(spawn_status: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(spawn_status, dict):
        return False
    return str(spawn_status.get("status") or "").strip().lower() in {"running", "pending"}


def _phase_stale_kill_enabled() -> bool:
    """Batch runner may SIGTERM children when status looks stale; disable via AGIA_ENABLE_PHASE_STALE_KILL=false."""
    return str(os.environ.get("AGIA_ENABLE_PHASE_STALE_KILL", "true") or "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _is_spawn_status_stale(spawn_status: Optional[Dict[str, Any]]) -> bool:
    if not _phase_stale_kill_enabled():
        return False
    if not _is_running_like_status(spawn_status):
        return False
    if str(spawn_status.get("completion_time") or "").strip():
        return False

    stale_seconds = max(60, int(os.environ.get("AGIA_PHASE_ZOMBIE_STALE_SECONDS", str(PHASE_ZOMBIE_STALE_SECONDS)) or PHASE_ZOMBIE_STALE_SECONDS))
    last_update = _spawn_status_last_progress_time(spawn_status)
    if last_update is None:
        return True
    return (datetime.now() - last_update).total_seconds() >= stale_seconds


def _detect_transient_model_error(
    *,
    returncode: int,
    score_summary: Dict[str, Any],
    spawn_status: Optional[Dict[str, Any]],
    per_run_log_path: Path,
    output_dir: Path,
) -> str:
    if int(returncode) == 0:
        return ""

    if _phase_status_from_returncode(returncode, score_summary, spawn_status) == "max_rounds_reached":
        return ""

    texts: List[str] = []
    if isinstance(score_summary, dict):
        reason = score_summary.get("reason")
        error = score_summary.get("error")
        task_status = score_summary.get("task_status")
        if reason:
            texts.append(str(reason))
        if error:
            texts.append(str(error))
        if task_status:
            texts.append(str(task_status))
    log_tail = _read_phase_diagnostic_tail(output_dir, per_run_log_path)
    if log_tail:
        texts.append(log_tail)

    merged = "\n".join(texts).strip()
    if not merged:
        return ""

    lowered = merged.lower()
    for marker in TRANSIENT_MODEL_ERROR_MARKERS:
        if marker in lowered:
            return marker

    if "error code: 400" in lowered and any(
        token in lowered for token in ("concurrent", "parallel", "busy", "overload", "retry later")
    ):
        return "error code: 400 with transient concurrency marker"

    return ""


def _detect_recoverable_phase_interruption(
    *,
    returncode: int,
    score_summary: Dict[str, Any],
    spawn_status: Optional[Dict[str, Any]],
    per_run_log_path: Path,
    output_dir: Path,
) -> str:
    if int(returncode) == 0:
        return ""
    if _phase_status_from_returncode(returncode, score_summary, spawn_status) in {"success", "partial_success", "max_rounds_reached"}:
        return ""

    has_metrics = bool(isinstance(score_summary, dict) and score_summary.get("has_metrics"))
    runtime_status = str((spawn_status or {}).get("status") or "").strip().lower()
    if _is_running_like_status(spawn_status) and not has_metrics:
        if _is_spawn_status_stale(spawn_status):
            return f"spawn manager status remained {runtime_status} and became stale"
        return f"spawn manager status remained {runtime_status} after process exit"

    if int(returncode) in RECOVERABLE_PHASE_RETURN_CODES and not has_metrics:
        return f"recoverable interruption returncode={returncode}"

    log_tail = _read_phase_diagnostic_tail(output_dir, per_run_log_path)
    lowered = log_tail.lower()
    for marker in RECOVERABLE_PHASE_INTERRUPTION_MARKERS:
        if marker in lowered:
            return f"log marker: {marker}"

    return ""


def _transient_retry_delay_seconds(attempt_index: int, task_index_1based: int) -> int:
    base = TRANSIENT_PHASE_RETRY_BASE_SECONDS * (2 ** max(0, attempt_index))
    jitter = ((max(1, task_index_1based) - 1) % 3) * TRANSIENT_PHASE_RETRY_JITTER_SECONDS
    return int(base + jitter)


def _archive_phase_workspace_for_retry(out_dir: Path, attempt: int) -> str:
    resolved_dir = out_dir.resolve()
    if not resolved_dir.exists():
        return ""

    suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    archived_dir = resolved_dir.parent / f"{resolved_dir.name}__stale_retry{attempt}_{suffix}"
    counter = 1
    while archived_dir.exists():
        archived_dir = resolved_dir.parent / f"{resolved_dir.name}__stale_retry{attempt}_{suffix}_{counter}"
        counter += 1
    shutil.move(str(resolved_dir), str(archived_dir))
    return str(archived_dir.resolve())


def _build_phase_error_result(
    *,
    phase_name: str,
    out_dir: Path,
    per_run_log_path: Path,
    cmd: Optional[Sequence[str]],
    error_message: str,
) -> Dict[str, Any]:
    return {
        "phase": phase_name,
        "output_dir": str(out_dir.resolve()),
        "per_run_log_path": str(per_run_log_path.resolve()),
        "command": list(cmd) if cmd is not None else [],
        "returncode": -1,
        "status": "error",
        "score_summary": {
            "has_metrics": False,
            "error": error_message,
        },
        "score_summary_path": str((out_dir / "logs" / "score_summary.json").resolve()),
    }


def _build_phase_skipped_result(
    *,
    phase_name: str,
    out_dir: Path,
    per_run_log_path: Path,
    cmd: Optional[Sequence[str]],
    reason: str,
) -> Dict[str, Any]:
    return {
        "phase": phase_name,
        "output_dir": str(out_dir.resolve()),
        "per_run_log_path": str(per_run_log_path.resolve()),
        "command": list(cmd) if cmd is not None else [],
        "returncode": None,
        "status": "skipped",
        "score_summary": {
            "has_metrics": False,
            "task_status": "skipped",
            "reason": reason,
        },
        "score_summary_path": str((out_dir / "logs" / "score_summary.json").resolve()),
    }


def _phase_current_loop(phase: Optional[Dict[str, Any]]) -> int:
    if not isinstance(phase, dict):
        return 0
    spawn_status = phase.get("spawn_manager_status")
    if isinstance(spawn_status, dict):
        try:
            return max(0, int(spawn_status.get("current_loop", 0) or 0))
        except Exception:
            return 0
    return 0


def _phase_needs_error_fallback(phase: Any) -> bool:
    if not isinstance(phase, dict):
        return True
    status = str(phase.get("status") or "").strip().lower()
    return status in {"", "pending", "running"}


def _repair_phase_result(phase: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(phase, dict):
        return phase

    repaired = dict(phase)
    output_dir = Path(str(repaired.get("output_dir") or "")).resolve()
    if not str(output_dir):
        return repaired
    current_status = str(repaired.get("status") or "").strip().lower()
    if current_status in {"", "pending"} and not output_dir.exists():
        repaired["status"] = current_status or "pending"
        return repaired

    score_summary = _load_score_summary(output_dir)
    spawn_status = _load_spawn_manager_status(output_dir)
    returncode = int(repaired.get("returncode", -1) or -1)
    recoverable_reason = _detect_recoverable_phase_interruption(
        returncode=returncode,
        score_summary=score_summary,
        spawn_status=spawn_status,
        per_run_log_path=Path(str(repaired.get("per_run_log_path") or "")),
        output_dir=output_dir,
    )

    repaired["score_summary"] = score_summary
    repaired["score_summary_path"] = str((output_dir / "logs" / "score_summary.json").resolve())
    repaired["spawn_manager_status"] = spawn_status
    repaired["spawn_manager_status_path"] = str((output_dir / ".agia_spawn_manager_status.json").resolve())
    repaired["current_loop"] = _phase_current_loop(repaired)
    repaired["status"] = _phase_status_from_returncode(returncode, score_summary, spawn_status)
    if recoverable_reason:
        repaired["recoverable_interruption_reason"] = recoverable_reason
    else:
        repaired.pop("recoverable_interruption_reason", None)

    if score_summary.get("has_metrics"):
        repaired.pop("score_rate", None)
        repaired.pop("progress", None)
        repaired.pop("best_progress", None)
        repaired.pop("effective_progress", None)
        repaired.pop("progress_source", None)

    return repaired


def _repair_manifest_runs(manifest: Dict[str, Any]) -> Dict[str, Any]:
    runs = manifest.get("runs", [])
    if not isinstance(runs, list):
        return manifest

    repaired_runs: List[Dict[str, Any]] = []
    for item in runs:
        if not isinstance(item, dict):
            repaired_runs.append(item)
            continue

        repaired_item = dict(item)
        if isinstance(repaired_item.get("baseline_phase"), dict):
            repaired_item["baseline_phase"] = _repair_phase_result(repaired_item["baseline_phase"])
            repaired_item = _finalize_run_item(repaired_item)
        elif isinstance(repaired_item.get("iterations"), list):
            for it in repaired_item["iterations"]:
                if isinstance(it.get("play_phase"), dict):
                    it["play_phase"] = _repair_phase_result(it["play_phase"])
                if isinstance(it.get("phase_m_phase"), dict):
                    it["phase_m_phase"] = _repair_phase_result(it["phase_m_phase"])
            repaired_item = _finalize_run_item(repaired_item)
        repaired_runs.append(repaired_item)

    manifest["runs"] = repaired_runs
    errs = sum(1 for r in repaired_runs if isinstance(r, dict) and r.get("status") == "error")
    non_success = sum(1 for r in repaired_runs if isinstance(r, dict) and r.get("status") != "success")
    manifest["status"] = "success" if non_success == 0 else "partial_success"
    manifest["error_count"] = errs
    _compute_dataset_score_averages(manifest)
    return manifest


def _flatten_phase_for_metrics(item: Dict[str, Any]) -> Dict[str, Any]:
    phase_mode = str(item.get("phase_mode") or "iterative").strip().lower()
    flattened = dict(item)
    if phase_mode == "baseline":
        bp = item.get("baseline_phase") if isinstance(item.get("baseline_phase"), dict) else {}
        flattened["score_summary"] = bp.get("score_summary")
        flattened["score_summary_path"] = bp.get("score_summary_path")
        flattened["best_score"] = bp.get("best_score")
        flattened["current_score"] = bp.get("current_score")
        flattened["full_score"] = bp.get("full_score")
        flattened["score_rate"] = bp.get("score_rate")
        flattened["progress"] = bp.get("progress")
        flattened["best_progress"] = bp.get("best_progress")
        flattened["effective_progress"] = bp.get("effective_progress")
        flattened["progress_source"] = bp.get("progress_source")
        flattened["status"] = bp.get("status", item.get("status"))
        flattened["returncode"] = bp.get("returncode", item.get("returncode"))
        return flattened
    # Iterative: use the best play phase across iterations
    iterations = item.get("iterations") or []
    best_summary: Dict[str, Any] = {}
    best_play: Dict[str, Any] = {}
    best_progress_val: Optional[float] = None
    for it in iterations:
        play = it.get("play_phase") or {}
        summary = play.get("score_summary") if isinstance(play.get("score_summary"), dict) else {}
        if summary.get("has_metrics"):
            prog = _effective_progress(summary)
            if prog is not None and (best_progress_val is None or prog > best_progress_val):
                best_progress_val = prog
                best_summary = summary
                best_play = play
    flattened["score_summary"] = best_summary
    flattened["score_summary_path"] = best_play.get("score_summary_path")
    flattened["best_score"] = best_play.get("best_score")
    flattened["current_score"] = best_play.get("current_score")
    flattened["full_score"] = best_play.get("full_score")
    flattened["score_rate"] = best_play.get("score_rate")
    flattened["progress"] = best_play.get("progress")
    flattened["best_progress"] = best_play.get("best_progress")
    flattened["effective_progress"] = best_play.get("effective_progress")
    flattened["progress_source"] = best_play.get("progress_source")
    flattened["status"] = best_play.get("status", item.get("status"))
    flattened["returncode"] = best_play.get("returncode", item.get("returncode"))
    return flattened


def _compute_dataset_score_averages(manifest: Dict[str, Any]) -> None:
    runs = [_flatten_phase_for_metrics(run) for run in manifest.get("runs", [])]
    scored_summaries: List[Dict[str, Any]] = []

    for run in runs:
        summary = run.get("score_summary")
        if isinstance(summary, dict) and summary.get("has_metrics"):
            scored_summaries.append(summary)

    manifest["scored_runs"] = len(scored_summaries)
    manifest["dataset_average_score_rate"] = _avg([s.get("score_rate") for s in scored_summaries])
    manifest["dataset_average_progress"] = _avg([_effective_progress(s) for s in scored_summaries])


def _is_won_score_summary(summary: Dict[str, Any]) -> bool:
    if not isinstance(summary, dict) or not summary.get("has_metrics"):
        return False

    if summary.get("won") is True:
        return True
    if summary.get("lost") is True:
        return False

    task_status = str(summary.get("task_status") or "").strip().lower()
    if task_status in {"won", "game_won"}:
        return True

    best_progress = _safe_float(summary.get("best_progress"))
    progress = _safe_float(summary.get("progress"))
    if (best_progress is not None and best_progress >= 100.0) or (progress is not None and progress >= 100.0):
        return True

    best_score = _safe_float(summary.get("best_score"))
    current_score = _safe_float(summary.get("current_score"))
    full_score = _safe_float(summary.get("full_score"))
    if full_score is None or full_score <= 0:
        return False
    return (best_score is not None and best_score >= full_score) or (
        current_score is not None and current_score >= full_score
    )


def _build_benchmark_summary(manifest: Dict[str, Any]) -> Dict[str, Any]:
    runs = [_flatten_phase_for_metrics(run) for run in manifest.get("runs", [])]
    scored_runs = [
        run for run in runs
        if isinstance(run.get("score_summary"), dict) and run["score_summary"].get("has_metrics")
    ]

    won_count = sum(1 for run in scored_runs if _is_won_score_summary(run.get("score_summary", {})))
    max_rounds_count = sum(
        1
        for run in scored_runs
        if str(run.get("score_summary", {}).get("task_status") or "").strip().lower() == "max_rounds_reached"
    )

    summary: Dict[str, Any] = {
        "tag": APP_NAME,
        "experiment_name": manifest.get("experiment_name"),
        "dataset": DATASET_NAME,
        "phase_mode": manifest.get("phase_mode"),
        "task_total": len(runs),
        "won_count": won_count,
        "win_rate": (won_count / len(runs) * 100.0) if runs else 0.0,
        "avg_score_rate": _avg([
            run.get("score_summary", {}).get("score_rate")
            for run in scored_runs
        ]),
        "avg_progress": _avg([
            _effective_progress(run.get("score_summary", {}))
            for run in scored_runs
        ]),
        "avg_progress_source": "best_progress_if_available_else_progress",
        "metrics_count": len(scored_runs),
        "max_rounds_reached_count": max_rounds_count,
        "error_count": int(manifest.get("error_count") or 0),
        "results_json": str((Path(manifest["benchmark_dir"]) / "run_manifest.json").resolve()),
        "run_root": manifest.get("benchmark_dir"),
    }
    return summary


def _write_benchmark_summary(manifest: Dict[str, Any]) -> Path:
    batch_dir = Path(manifest["benchmark_dir"]).resolve()
    summary_path = batch_dir / "benchmark_summary.json"
    benchmark_summary = _build_benchmark_summary(manifest)
    summary_path.write_text(json.dumps(benchmark_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary_path


def _persist_manifest(batch_dir: Path, manifest: Dict[str, Any]) -> None:
    (batch_dir / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_run_item(
    *,
    index: int,
    task_index_1based: int,
    env_name: str,
    safe_env_name: str,
    variation_num: int,
    ts: str,
    output_prefix: str,
    outputs_dir: Path,
    experience_logs_dir: Path,
    phase_mode: str = "iterative",
    max_iterations: int = 10,
) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "index": index,
        "task_index_1based": task_index_1based,
        "env_name": env_name,
        "variation_num": int(variation_num),
        "status": "pending",
        "phase_mode": phase_mode,
    }

    if phase_mode == "baseline":
        baseline_output_dir = (
            outputs_dir / f"{output_prefix}_{APP_NAME}_{task_index_1based:02d}_{safe_env_name}_var{variation_num:03d}_baseline_{ts}"
        ).resolve()
        item["baseline_phase"] = {
            "phase": "phase_baseline",
            "output_dir": str(baseline_output_dir),
            "per_run_log_path": str((experience_logs_dir / f"{task_index_1based:02d}_{safe_env_name}_var{variation_num:03d}_baseline_{ts}.log").resolve()),
        }
    else:
        item["iterations"] = []
        item["max_iterations"] = max_iterations
        for i in range(1, max_iterations + 1):
            play_dir = (
                outputs_dir / f"{output_prefix}_{APP_NAME}_{task_index_1based:02d}_{safe_env_name}_var{variation_num:03d}_play{i}_{ts}"
            ).resolve()
            phase_m_dir = (
                outputs_dir / f"{output_prefix}_{APP_NAME}_{task_index_1based:02d}_{safe_env_name}_var{variation_num:03d}_phasem{i}_{ts}"
            ).resolve()
            iteration_entry: Dict[str, Any] = {
                "iteration": i,
                "play_phase": {
                    "phase": f"play_{i}",
                    "output_dir": str(play_dir),
                    "per_run_log_path": str(
                        (experience_logs_dir / f"{task_index_1based:02d}_{safe_env_name}_var{variation_num:03d}_play{i}_{ts}.log").resolve()
                    ),
                    "status": "pending",
                },
                "phase_m_phase": {
                    "phase": f"phase_m_{i}",
                    "output_dir": str(phase_m_dir),
                    "per_run_log_path": str(
                        (experience_logs_dir / f"{task_index_1based:02d}_{safe_env_name}_var{variation_num:03d}_phasem{i}_{ts}.log").resolve()
                    ),
                    "status": "pending",
                },
            }
            item["iterations"].append(iteration_entry)

        item["phase_records_path"] = str(
            (outputs_dir / f"{output_prefix}_{APP_NAME}_{task_index_1based:02d}_{safe_env_name}_var{variation_num:03d}_phase_records.json").resolve()
        )
    return item


def _finalize_run_item(item: Dict[str, Any]) -> Dict[str, Any]:
    phase_mode = str(item.get("phase_mode") or "iterative").strip().lower()

    if phase_mode == "baseline":
        bp = item.get("baseline_phase") if isinstance(item.get("baseline_phase"), dict) else {}
        item["status"] = bp.get("status", item.get("status"))
        item["returncode"] = bp.get("returncode")
        item["output_dir"] = bp.get("output_dir")
        item["score_summary"] = bp.get("score_summary")
        item["score_summary_path"] = bp.get("score_summary_path")
        item["best_score"] = bp.get("best_score")
        item["current_score"] = bp.get("current_score")
        item["full_score"] = bp.get("full_score")
        item["score_rate"] = bp.get("score_rate")
        item["progress"] = bp.get("progress")
        item["best_progress"] = bp.get("best_progress")
        item["effective_progress"] = bp.get("effective_progress")
        item["progress_source"] = bp.get("progress_source")
        return item

    # Iterative: pick best play phase across all iterations
    iterations = item.get("iterations") or []
    best_play: Dict[str, Any] = {}
    best_progress_val: Optional[float] = None
    won_any = False
    for it in iterations:
        play = it.get("play_phase") or {}
        summary = play.get("score_summary") if isinstance(play.get("score_summary"), dict) else {}
        if summary.get("has_metrics"):
            if _is_won_score_summary(summary):
                won_any = True
            prog = _effective_progress(summary)
            if prog is not None and (best_progress_val is None or prog > best_progress_val):
                best_progress_val = prog
                best_play = play

    if won_any:
        item["status"] = "success"
    elif best_play:
        item["status"] = best_play.get("status", item.get("status"))
    else:
        item["status"] = "error"

    item["output_dir"] = best_play.get("output_dir")
    item["score_summary"] = best_play.get("score_summary")
    item["score_summary_path"] = best_play.get("score_summary_path")
    item["best_score"] = best_play.get("best_score")
    item["current_score"] = best_play.get("current_score")
    item["full_score"] = best_play.get("full_score")
    item["score_rate"] = best_play.get("score_rate")
    item["progress"] = best_play.get("progress")
    item["best_progress"] = best_play.get("best_progress")
    item["effective_progress"] = best_play.get("effective_progress")
    item["progress_source"] = best_play.get("progress_source")
    return item


def _run_phase(
    *,
    logger: _ExperimentLogger,
    phase_name: str,
    phase_requirement: str,
    env_name: str,
    variation_num: int,
    task_index_1based: int,
    task_order_index: int,
    total_selected: int,
    phase_loops: int,
    out_dir: Path,
    per_run_log_path: Path,
    python_exe: str,
    experiment_name: str,
) -> Dict[str, Any]:
    cmd = [
        python_exe,
        "agia.py",
        "--app", APP_NAME,
        "--dir", str(out_dir.resolve()),
        "--loops", str(int(phase_loops)),
        phase_requirement,
    ]

    child_env = os.environ.copy()
    child_env["AGIA_EXPERIMENT_NAMESPACE"] = experiment_name
    child_env["AGIA_EXPERIMENT_PHASE"] = phase_name
    child_env["AGIA_EXPECTED_ENV_NAME"] = env_name
    # Set both SCIENCEWORLD_ACTIVE_ENV and JERICHO_ACTIVE_ENV.
    # SCIENCEWORLD_ACTIVE_ENV is the primary identifier for the scienceworld tool.
    # JERICHO_ACTIVE_ENV is used by wiki_memory.py for cross-game filtering —
    # we set it to the same value so wiki_memory_read works without changes.
    child_env["SCIENCEWORLD_ACTIVE_ENV"] = env_name
    child_env["JERICHO_ACTIVE_ENV"] = env_name
    child_env["AGIA_WIKI_ROOT"] = os.path.join(
        str(AGI_ROOT), "data", "default", "general", "wiki", experiment_name
    )
    logger.println(
        f"[{task_order_index}/{total_selected}] {phase_name} task#{task_index_1based} "
        f"{env_name} var={variation_num} -> {out_dir}"
    )
    phase_result: Dict[str, Any] = {}
    retry_reasons: List[str] = []
    retry_workspace_archives: List[str] = []
    for attempt in range(1, MAX_TRANSIENT_PHASE_ATTEMPTS + 1):
        if attempt > 1:
            logger.println(
                f"   {phase_name} retry attempt {attempt}/{MAX_TRANSIENT_PHASE_ATTEMPTS} "
                f"for task#{task_index_1based} {env_name}"
            )

        returncode = logger.run_process(
            cmd=cmd,
            cwd=AGI_ROOT,
            env=child_env,
            per_run_log_path=per_run_log_path,
            output_dir=out_dir,
            write_per_run_log=WRITE_PER_RUN_PHASE_LOGS,
        )

        score_summary = _load_score_summary(out_dir)
        spawn_status = _load_spawn_manager_status(out_dir)
        phase_result = {
            "phase": phase_name,
            "output_dir": str(out_dir.resolve()),
            "per_run_log_path": str(per_run_log_path.resolve()),
            "command": cmd,
            "returncode": returncode,
            "status": _phase_status_from_returncode(returncode, score_summary, spawn_status),
            "score_summary": score_summary,
            "score_summary_path": str((out_dir / "logs" / "score_summary.json").resolve()),
            "spawn_manager_status": spawn_status,
            "spawn_manager_status_path": str((out_dir / ".agia_spawn_manager_status.json").resolve()),
            "attempt_count": attempt,
            "current_loop": _phase_current_loop({"spawn_manager_status": spawn_status}),
        }

        if score_summary.get("has_metrics"):
            phase_result["best_score"] = score_summary.get("best_score")
            phase_result["current_score"] = score_summary.get("current_score")
            phase_result["full_score"] = score_summary.get("full_score")
            phase_result["score_rate"] = score_summary.get("score_rate")
            phase_result["progress"] = score_summary.get("progress")
            phase_result["best_progress"] = score_summary.get("best_progress")
            phase_result["effective_progress"] = _effective_progress(score_summary)
            phase_result["progress_source"] = score_summary.get("progress_source") or (
                "best_progress" if score_summary.get("best_progress") is not None else "progress"
            )
            logger.println(
                f"   {phase_name} score summary: "
                f"best={_fmt(phase_result.get('best_score'))}, "
                f"current={_fmt(phase_result.get('current_score'))}, "
                f"full={_fmt(phase_result.get('full_score'))}, "
                f"score_rate={_fmt(phase_result.get('score_rate'))}, "
                f"progress={_fmt(phase_result.get('progress'))}, "
                f"best_progress={_fmt(phase_result.get('best_progress'))}, "
                f"effective_progress={_fmt(phase_result.get('effective_progress'))}"
            )
        else:
            reason = score_summary.get("reason") or score_summary.get("error") or "no score metrics"
            logger.println(f"   {phase_name} score summary unavailable: {reason}")

        transient_reason = _detect_transient_model_error(
            returncode=returncode,
            score_summary=score_summary,
            spawn_status=spawn_status,
            per_run_log_path=per_run_log_path,
            output_dir=out_dir,
        )
        recoverable_reason = _detect_recoverable_phase_interruption(
            returncode=returncode,
            score_summary=score_summary,
            spawn_status=spawn_status,
            per_run_log_path=per_run_log_path,
            output_dir=out_dir,
        )
        if recoverable_reason:
            phase_result["recoverable_interruption_reason"] = recoverable_reason

        retry_kind = ""
        retry_reason = ""
        if recoverable_reason:
            retry_kind = "recoverable_interruption"
            retry_reason = recoverable_reason
        elif transient_reason:
            retry_kind = "transient_model_error"
            retry_reason = transient_reason

        if not retry_reason or attempt >= MAX_TRANSIENT_PHASE_ATTEMPTS:
            if retry_reasons:
                phase_result["retry_reasons"] = retry_reasons
                phase_result["retried_after_failure"] = True
                phase_result["recovered_after_retry"] = phase_result["status"] in {"success", "partial_success", "max_rounds_reached"}
            if retry_workspace_archives:
                phase_result["retry_workspace_archives"] = retry_workspace_archives
            return phase_result

        retry_reasons.append(f"{retry_kind}: {retry_reason}")
        phase_result["retried_after_failure"] = True
        if retry_kind == "recoverable_interruption":
            archived_dir = _archive_phase_workspace_for_retry(out_dir, attempt)
            if archived_dir:
                retry_workspace_archives.append(archived_dir)
                logger.println(
                    f"   {phase_name} archived stale workspace before retry: {archived_dir}"
                )
            delay = min(12, _transient_retry_delay_seconds(attempt - 1, task_index_1based))
            logger.println(
                f"   {phase_name} detected recoverable interruption/zombie state "
                f"({retry_reason}); retrying in {delay}s"
            )
        else:
            delay = _transient_retry_delay_seconds(attempt - 1, task_index_1based)
            logger.println(
                f"   {phase_name} detected transient model/provider failure "
                f"({retry_reason}); retrying in {delay}s"
            )
        time.sleep(delay)

    return phase_result


def _persist_phase_records(item: Dict[str, Any]) -> None:
    """Write/overwrite the per-task phase_records.json tracking scores per iteration."""
    records_path = item.get("phase_records_path")
    if not records_path:
        return
    records: List[Dict[str, Any]] = []
    for it in item.get("iterations") or []:
        iteration_num = it.get("iteration")
        play = it.get("play_phase") or {}
        phase_m = it.get("phase_m_phase") or {}
        play_summary = play.get("score_summary") or {}
        entry: Dict[str, Any] = {
            "iteration": iteration_num,
            "play_status": play.get("status"),
            "play_best_score": play_summary.get("best_score") if play_summary.get("has_metrics") else None,
            "play_current_score": play_summary.get("current_score") if play_summary.get("has_metrics") else None,
            "play_full_score": play_summary.get("full_score") if play_summary.get("has_metrics") else None,
            "play_score_rate": play_summary.get("score_rate") if play_summary.get("has_metrics") else None,
            "play_progress": play_summary.get("progress") if play_summary.get("has_metrics") else None,
            "play_best_progress": play_summary.get("best_progress") if play_summary.get("has_metrics") else None,
            "play_won": play_summary.get("won") if play_summary.get("has_metrics") else None,
            "play_done": play_summary.get("done") if play_summary.get("has_metrics") else None,
            "play_output_dir": play.get("output_dir"),
            "phase_m_status": phase_m.get("status"),
            "phase_m_output_dir": phase_m.get("output_dir"),
        }
        records.append(entry)
    Path(records_path).write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _run_task_baseline(
    *,
    logger: _ExperimentLogger,
    item: Dict[str, Any],
    total_selected: int,
    loops: int,
    python_exe: str,
    experiment_name: str,
    simplification_str: str,
    env_step_limit: int,
) -> Dict[str, Any]:
    env_name = str(item["env_name"])
    variation_num = int(item["variation_num"])
    task_index_1based = int(item["task_index_1based"])
    task_order_index = int(item["index"])
    baseline_cmd = [
        python_exe,
        "agia.py",
        "--app", APP_NAME,
        "--dir", str(Path(item["baseline_phase"]["output_dir"]).resolve()),
        "--loops", str(int(loops)),
        _baseline_requirement(
            env_name=env_name,
            variation_num=variation_num,
            simplification_str=simplification_str,
            env_step_limit=env_step_limit,
        ),
    ]

    try:
        item["status"] = "running"
        item["baseline_phase"] = _run_phase(
            logger=logger,
            phase_name="phase_baseline",
            phase_requirement=_baseline_requirement(
                env_name=env_name,
                variation_num=variation_num,
                simplification_str=simplification_str,
                env_step_limit=env_step_limit,
            ),
            env_name=env_name,
            variation_num=variation_num,
            task_index_1based=task_index_1based,
            task_order_index=task_order_index,
            total_selected=total_selected,
            phase_loops=loops,
            out_dir=Path(item["baseline_phase"]["output_dir"]),
            per_run_log_path=Path(item["baseline_phase"]["per_run_log_path"]),
            python_exe=python_exe,
            experiment_name=experiment_name,
        )
        return _finalize_run_item(item)
    except Exception as e:
        error_message = f"unexpected baseline task failure: {type(e).__name__}: {e}"
        logger.println(
            f"[{task_order_index}/{total_selected}] task#{task_index_1based} {env_name} crashed: {error_message}",
            error=True,
        )
        if _phase_needs_error_fallback(item.get("baseline_phase")):
            item["baseline_phase"] = _build_phase_error_result(
                phase_name="phase_baseline",
                out_dir=Path(item["baseline_phase"]["output_dir"]),
                per_run_log_path=Path(item["baseline_phase"]["per_run_log_path"]),
                cmd=baseline_cmd,
                error_message=error_message,
            )
        item["error"] = error_message
        return _finalize_run_item(item)

def _run_task_iterative(
    *,
    logger: _ExperimentLogger,
    item: Dict[str, Any],
    total_selected: int,
    play_loops: int,
    phase_m_loops: int,
    max_iterations: int,
    python_exe: str,
    experiment_name: str,
    simplification_str: str,
    env_step_limit: int,
) -> Dict[str, Any]:
    env_name = str(item["env_name"])
    variation_num = int(item["variation_num"])
    task_index_1based = int(item["task_index_1based"])
    task_order_index = int(item["index"])

    try:
        item["status"] = "running"

        # Wiki root shared across all iterations for this game.
        wiki_root = str(AGI_ROOT / "data" / "default" / "general" / "wiki" / experiment_name)
        os.makedirs(wiki_root, exist_ok=True)
        for subdir in ["knowledge", "experiences", "world_model/locations", "world_model/objects"]:
            os.makedirs(os.path.join(wiki_root, subdir), exist_ok=True)
        os.environ["AGIA_WIKI_ROOT"] = wiki_root

        for iteration_idx in range(max_iterations):
            iteration = iteration_idx + 1
            iter_entry = item["iterations"][iteration_idx]

            # ---- Play phase ----
            use_wiki = (iteration > 1) and (phase_m_loops > 0)
            play_phase = iter_entry["play_phase"]
            iter_entry["play_phase"] = _run_phase(
                logger=logger,
                phase_name=f"play_{iteration}",
                phase_requirement=_play_requirement(
                    env_name=env_name,
                    variation_num=variation_num,
                    simplification_str=simplification_str,
                    env_step_limit=env_step_limit,
                    iteration=iteration,
                    max_iterations=max_iterations,
                    use_wiki=use_wiki,
                ),
                env_name=env_name,
                variation_num=variation_num,
                task_index_1based=task_index_1based,
                task_order_index=task_order_index,
                total_selected=total_selected,
                phase_loops=play_loops,
                out_dir=Path(play_phase["output_dir"]),
                per_run_log_path=Path(play_phase["per_run_log_path"]),
                python_exe=python_exe,
                experiment_name=experiment_name,
            )

            play_result = iter_entry["play_phase"]
            play_summary = play_result.get("score_summary") or {}

            logger.println(
                f"[{task_order_index}/{total_selected}] iteration {iteration}/{max_iterations} "
                f"task#{task_index_1based} {env_name} var={variation_num} play done: "
                f"progress={_fmt(play_summary.get('progress'))}, "
                f"best_progress={_fmt(play_summary.get('best_progress'))}"
            )

            _persist_phase_records(item)

            # Early exit: won the task → no need for further iterations
            if play_summary.get("has_metrics") and _is_won_score_summary(play_summary):
                logger.println(
                    f"[{task_order_index}/{total_selected}] task#{task_index_1based} {env_name} "
                    f"var={variation_num} WON at iteration {iteration} — skipping remaining iterations.",
                )
                for remaining_idx in range(iteration_idx + 1, max_iterations):
                    item["iterations"][remaining_idx]["play_phase"]["status"] = "skipped"
                    item["iterations"][remaining_idx]["phase_m_phase"]["status"] = "skipped"
                break

            # ---- Phase M: wiki curation ----
            play_output_dir = str(play_result.get("output_dir") or "")
            trajectory_log_path = os.path.join(play_output_dir, "logs", "trajectory.jsonl")
            phase_m_phase = iter_entry["phase_m_phase"]

            if phase_m_loops > 0 and os.path.exists(trajectory_log_path):
                iter_entry["phase_m_phase"] = _run_phase(
                    logger=logger,
                    phase_name=f"phase_m_{iteration}",
                    phase_requirement=_phase_m_requirement(
                        env_name=env_name,
                        variation_num=variation_num,
                        wiki_root=wiki_root,
                        trajectory_log_path=trajectory_log_path,
                        iteration=iteration,
                    ),
                    env_name=env_name,
                    variation_num=variation_num,
                    task_index_1based=task_index_1based,
                    task_order_index=task_order_index,
                    total_selected=total_selected,
                    phase_loops=phase_m_loops,
                    out_dir=Path(phase_m_phase["output_dir"]),
                    per_run_log_path=Path(phase_m_phase["per_run_log_path"]),
                    python_exe=python_exe,
                    experiment_name=experiment_name,
                )
            else:
                iter_entry["phase_m_phase"] = _build_phase_skipped_result(
                    phase_name=f"phase_m_{iteration}",
                    out_dir=Path(phase_m_phase["output_dir"]),
                    per_run_log_path=Path(phase_m_phase["per_run_log_path"]),
                )

            _persist_phase_records(item)

        _persist_phase_records(item)
        return _finalize_run_item(item)
    except Exception as e:
        error_message = f"unexpected task failure: {type(e).__name__}: {e}"
        logger.println(
            f"[{task_order_index}/{total_selected}] task#{task_index_1based} {env_name} crashed: {error_message}",
            error=True,
        )
        for it in item.get("iterations") or []:
            if _phase_needs_error_fallback(it.get("play_phase")):
                pp = it["play_phase"]
                it["play_phase"] = _build_phase_error_result(
                    phase_name=pp.get("phase", "play"),
                    out_dir=Path(pp["output_dir"]),
                    per_run_log_path=Path(pp["per_run_log_path"]),
                    cmd=None,
                    error_message=error_message,
                )
        item["error"] = error_message
        _persist_phase_records(item)
        return _finalize_run_item(item)


def main() -> int:
    p = argparse.ArgumentParser(description=f"Run all {DATASET_NAME} tasks with isolated sessions")
    p.add_argument("--task-count", type=int, default=0)
    p.add_argument("--task-offset", type=int, default=0)
    p.add_argument(
        "--task-list",
        type=str,
        default="",
        help="1-based task index list, e.g. \"[1,2,3]\" or \"7,8,20\".",
    )
    p.add_argument("--loops", type=int, default=100)
    p.add_argument("--play-loops", type=int, default=0, help="Loops per play attempt. 0 falls back to --loops.")
    p.add_argument("--phase-m-loops", type=int, default=15, help="Loops for phase_m (wiki memory curation). 0 disables phase_m.")
    p.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="Maximum number of play+phase_m iterations per task (default: 10).",
    )
    p.add_argument("--variation-offset", type=int, default=0)
    p.add_argument("--variation-count", type=int, default=0)
    p.add_argument(
        "--selection-mode",
        type=str,
        default="fixed_total",
        choices=["fixed_total", "runtime"],
        help=(
            "`fixed_total` deterministically slices the canonical ScienceWorld total dataset pairs "
            "from apps/scienceworld/test_indices.json + valid_indices.json. "
            "`runtime` keeps the old live-environment task slicing behavior."
        ),
    )
    p.add_argument(
        "--fixed-dataset-split",
        type=str,
        default="total",
        choices=sorted(FIXED_DATASET_SPLIT_PRESETS),
        help=(
            "When --selection-mode=fixed_total, choose which canonical fixed split to slice: "
            "`total` (test+valid), `test`, or `valid`."
        ),
    )
    p.add_argument("--output-prefix", type=str, default="output")
    p.add_argument("--python-exe", type=str, default=sys.executable)
    p.add_argument("--experiment-name", type=str, default="scienceworld_smoke_v1")
    p.add_argument("--simplification-str", type=str, default="")
    p.add_argument("--env-step-limit", type=int, default=100)
    p.add_argument(
        "--parallel-tasks",
        type=int,
        default=1,
        help="Number of tasks to run in parallel. Each task runs its full iteration chain (play1->m1->...->playN) before moving to the next.",
    )
    p.add_argument(
        "--log-file",
        type=str,
        default="",
        help="额外副本日志路径。传 `auto` 时写到 AGIAgent_v3/nohup.out；无论是否设置，实验完整日志都会自动保存到 data/default/general/experience/<experiment>/logs/",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--baseline",
        action="store_true",
        help=(
            "Run a single-phase baseline: solve each task from scratch without any long-term memory assets."
        ),
    )
    args = p.parse_args()
    experiment_name = _experiment_name(args.experiment_name)
    batch_dir = BENCHMARK_RESULTS_ROOT / experiment_name
    outputs_dir = batch_dir / "outputs"
    experience_dir = EXPERIENCE_ROOT / experiment_name
    experience_logs_dir = experience_dir / "logs"
    experience_logs_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    main_log_path = experience_logs_dir / f"run_all_tasks_{ts}.log"
    extra_log_path = _resolve_log_file(AGI_ROOT, args.log_file)
    log_paths = [main_log_path]
    if extra_log_path is not None and extra_log_path.resolve() != main_log_path.resolve():
        log_paths.append(extra_log_path)
    logger = _ExperimentLogger(log_paths)

    effective_task_list = args.task_list.strip()
    if (
        not effective_task_list
        and TASK_INDEX_LIST
        and int(args.task_count) <= 0
        and int(args.task_offset) == 0
    ):
        effective_task_list = json.dumps(TASK_INDEX_LIST, ensure_ascii=False)

    tool = ToolClass(workspace_root=str(WORKSPACE_ROOT))
    list_method = getattr(tool, f"{TOOL_PREFIX}_list_tasks")
    ret: Dict[str, Any] = list_method(env_step_limit=int(args.env_step_limit))
    if ret.get("status") != "success":
        print(json.dumps(ret, ensure_ascii=False, indent=2))
        return 1

    tasks = ret.get("tasks", [])
    variation_counts = {
        str(k): max(1, int(v))
        for k, v in (ret.get("task_variation_counts") or {}).items()
    }
    selected_items: List[Dict[str, Any]] = []
    selection_mode = str(args.selection_mode or "fixed_total").strip().lower()
    fixed_dataset_split = str(args.fixed_dataset_split or "total").strip().lower()
    fixed_dataset_items: List[Dict[str, Any]] = []

    if selection_mode == "fixed_total":
        try:
            fixed_dataset_items = _load_fixed_total_dataset_items(fixed_dataset_split)
            selected_items = _select_fixed_dataset_items(
                fixed_dataset_items,
                effective_task_list,
                args.task_offset,
                args.task_count,
            )
        except ValueError as e:
            print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False, indent=2))
            return 1

        runtime_tasks = {str(name) for name in tasks}
        invalid_envs = sorted({item["env_name"] for item in selected_items if item["env_name"] not in runtime_tasks})
        if invalid_envs:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "message": "fixed dataset contains env names unavailable in current runtime",
                        "invalid_env_names": invalid_envs,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1

        invalid_variations: List[Dict[str, Any]] = []
        for item in selected_items:
            max_variations = variation_counts.get(str(item["env_name"]), 1)
            variation_num = int(item["variation_num"])
            if variation_num < 0 or variation_num >= max_variations:
                invalid_variations.append(
                    {
                        "task_key": item["task_key"],
                        "env_name": item["env_name"],
                        "variation_num": variation_num,
                        "variation_count": max_variations,
                    }
                )
        if invalid_variations:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "message": "fixed dataset contains variation indices unavailable in current runtime",
                        "invalid_variations": invalid_variations[:20],
                        "invalid_variation_count": len(invalid_variations),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1

        if int(args.variation_offset) != 0 or int(args.variation_count) != 0:
            logger.println(
                "selection_mode=fixed_total uses exact task-variation pairs from the canonical dataset; "
                "ignoring --variation-offset/--variation-count."
            )
    else:
        if effective_task_list:
            try:
                requested_indices = _parse_task_list(effective_task_list)
            except ValueError as e:
                print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False, indent=2))
                return 1

            out_of_range = [i for i in requested_indices if i > len(tasks)]
            if out_of_range:
                print(
                    json.dumps(
                        {
                            "status": "error",
                            "message": f"task index out of range: {out_of_range}",
                            "task_count": len(tasks),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 1

            for idx in requested_indices:
                env_name = tasks[idx - 1]
                variations = _slice_variations(
                    variation_counts.get(env_name, 1),
                    args.variation_offset,
                    args.variation_count,
                )
                for variation_num in variations:
                    selected_items.append(
                        {
                            "task_index_1based": idx,
                            "env_name": env_name,
                            "variation_num": variation_num,
                        }
                    )
        else:
            selected = _slice(tasks, args.task_offset, args.task_count)
            if selected:
                start = max(0, int(args.task_offset))
                for i, env_name in enumerate(selected):
                    variations = _slice_variations(
                        variation_counts.get(env_name, 1),
                        args.variation_offset,
                        args.variation_count,
                    )
                    for variation_num in variations:
                        selected_items.append(
                            {
                                "task_index_1based": start + i + 1,
                                "env_name": env_name,
                                "variation_num": variation_num,
                            }
                        )

    if not selected_items:
        print(json.dumps({"status": "error", "message": "No tasks selected."}, ensure_ascii=False, indent=2))
        return 1

    batch_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    play_loops = int(args.play_loops) if int(args.play_loops) > 0 else int(args.loops)
    phase_m_loops = int(args.phase_m_loops)
    baseline_loops = int(args.loops)
    max_iterations = max(1, int(args.max_iterations))
    parallel_tasks = max(1, int(args.parallel_tasks))
    phase_mode = "baseline" if args.baseline else "iterative"

    manifest: Dict[str, Any] = {
        "status": "running",
        "app": APP_NAME,
        "dataset": DATASET_NAME,
        "experiment_name": experiment_name,
        "timestamp": ts,
        "phase_mode": phase_mode,
        "play_loops": play_loops if phase_mode != "baseline" else None,
        "phase_m_loops": phase_m_loops if phase_mode != "baseline" else None,
        "max_iterations": max_iterations if phase_mode != "baseline" else None,
        "baseline_loops": baseline_loops if phase_mode == "baseline" else None,
        "parallel_tasks": parallel_tasks,
        "task_total": len(fixed_dataset_items) if selection_mode == "fixed_total" else len(tasks),
        "task_selected": len(selected_items),
        "task_list": effective_task_list if effective_task_list else None,
        "selection_mode": selection_mode,
        "fixed_dataset_split": fixed_dataset_split if selection_mode == "fixed_total" else None,
        "variation_offset": int(args.variation_offset),
        "variation_count": int(args.variation_count),
        "simplification_str": args.simplification_str,
        "env_step_limit": int(args.env_step_limit),
        "task_variation_counts": variation_counts,
        "fixed_dataset_split_files": (
            list(FIXED_DATASET_SPLIT_PRESETS.get(fixed_dataset_split, FIXED_DATASET_SPLIT_FILES))
            if selection_mode == "fixed_total" else None
        ),
        "benchmark_dir": str(batch_dir.resolve()),
        "outputs_dir": str(outputs_dir.resolve()),
        "experience_dir": str(experience_dir.resolve()),
        "experience_log_dir": str(experience_logs_dir.resolve()),
        "experiment_log_path": str(main_log_path.resolve()),
        "log_file": str(extra_log_path.resolve()) if extra_log_path is not None else None,
        "runs": [],
    }
    _persist_manifest(batch_dir, manifest)

    try:
        run_items: List[Dict[str, Any]] = []
        for i, selected_item in enumerate(selected_items, 1):
            env_name = str(selected_item["env_name"])
            variation_num = int(selected_item["variation_num"])
            task_index_1based = int(selected_item["task_index_1based"])
            run_items.append(
                _build_run_item(
                    index=i,
                    task_index_1based=task_index_1based,
                    env_name=env_name,
                    safe_env_name=_safe_name(env_name),
                    variation_num=variation_num,
                    ts=ts,
                    output_prefix=args.output_prefix,
                    outputs_dir=outputs_dir,
                    experience_logs_dir=experience_logs_dir,
                    phase_mode=phase_mode,
                    max_iterations=max_iterations,
                )
            )

        manifest["runs"] = run_items
        _persist_manifest(batch_dir, manifest)

        if args.dry_run:
            for item in run_items:
                item["status"] = "dry_run"
                env_name = str(item["env_name"])
                if phase_mode == "baseline":
                    logger.println(
                        f"DRY RUN baseline: task#{item['task_index_1based']} {env_name} "
                        f"loops={baseline_loops}"
                    )
                else:
                    logger.println(
                        f"DRY RUN iterative: task#{item['task_index_1based']} {env_name} "
                        f"max_iterations={max_iterations} play_loops={play_loops} phase_m_loops={phase_m_loops}"
                    )
            _compute_dataset_score_averages(manifest)
            _persist_manifest(batch_dir, manifest)
        elif parallel_tasks == 1:
            for idx, item in enumerate(run_items):
                if phase_mode == "baseline":
                    run_items[idx] = _run_task_baseline(
                        logger=logger,
                        item=item,
                        total_selected=len(selected_items),
                        loops=baseline_loops,
                        python_exe=args.python_exe,
                        experiment_name=experiment_name,
                        simplification_str=args.simplification_str,
                        env_step_limit=int(args.env_step_limit),
                    )
                else:
                    run_items[idx] = _run_task_iterative(
                        logger=logger,
                        item=item,
                        total_selected=len(selected_items),
                        play_loops=play_loops,
                        phase_m_loops=phase_m_loops,
                        max_iterations=max_iterations,
                        python_exe=args.python_exe,
                        experiment_name=experiment_name,
                        simplification_str=args.simplification_str,
                        env_step_limit=int(args.env_step_limit),
                    )
                manifest["runs"] = run_items
                _compute_dataset_score_averages(manifest)
                _persist_manifest(batch_dir, manifest)
        else:
            with ThreadPoolExecutor(max_workers=min(parallel_tasks, len(run_items))) as executor:
                if phase_mode == "baseline":
                    future_to_index = {
                        executor.submit(
                            _run_task_baseline,
                            logger=logger,
                            item=item,
                            total_selected=len(selected_items),
                            loops=baseline_loops,
                            python_exe=args.python_exe,
                            experiment_name=experiment_name,
                            simplification_str=args.simplification_str,
                            env_step_limit=int(args.env_step_limit),
                        ): idx
                        for idx, item in enumerate(run_items)
                    }
                else:
                    future_to_index = {
                        executor.submit(
                            _run_task_iterative,
                            logger=logger,
                            item=item,
                            total_selected=len(selected_items),
                            play_loops=play_loops,
                            phase_m_loops=phase_m_loops,
                            max_iterations=max_iterations,
                            python_exe=args.python_exe,
                            experiment_name=experiment_name,
                            simplification_str=args.simplification_str,
                            env_step_limit=int(args.env_step_limit),
                        ): idx
                        for idx, item in enumerate(run_items)
                    }
                for future in as_completed(future_to_index):
                    idx = future_to_index[future]
                    try:
                        run_items[idx] = future.result()
                    except Exception as e:
                        item = run_items[idx]
                        error_message = f"worker future crashed: {type(e).__name__}: {e}"
                        logger.println(
                            f"[{item['index']}/{len(selected_items)}] task#{item['task_index_1based']} "
                            f"{item['env_name']} future failed: {error_message}",
                            error=True,
                        )
                        if phase_mode == "baseline":
                            if _phase_needs_error_fallback(item.get("baseline_phase")):
                                item["baseline_phase"] = _build_phase_error_result(
                                    phase_name="phase_baseline",
                                    out_dir=Path(item["baseline_phase"]["output_dir"]),
                                    per_run_log_path=Path(item["baseline_phase"]["per_run_log_path"]),
                                    cmd=None,
                                    error_message=error_message,
                                )
                        else:
                            for it in item.get("iterations") or []:
                                if _phase_needs_error_fallback(it.get("play_phase")):
                                    pp = it["play_phase"]
                                    it["play_phase"] = _build_phase_error_result(
                                        phase_name=pp.get("phase", "play"),
                                        out_dir=Path(pp["output_dir"]),
                                        per_run_log_path=Path(pp["per_run_log_path"]),
                                        cmd=None,
                                        error_message=error_message,
                                    )
                        item["error"] = error_message
                        run_items[idx] = _finalize_run_item(item)
                    manifest["runs"] = run_items
                    _compute_dataset_score_averages(manifest)
                    _persist_manifest(batch_dir, manifest)

        errs = sum(1 for r in manifest["runs"] if r["status"] == "error")
        non_success = sum(1 for r in manifest["runs"] if r["status"] != "success")
        manifest["status"] = "success" if non_success == 0 else "partial_success"
        manifest["error_count"] = errs
        _compute_dataset_score_averages(manifest)

        avg_score_rate = manifest.get("dataset_average_score_rate")
        avg_progress = manifest.get("dataset_average_progress")
        if avg_score_rate is not None:
            logger.println(
                f"Dataset average score rate ({DATASET_NAME}): "
                f"{_fmt(avg_score_rate)} based on {manifest.get('scored_runs', 0)} scored runs"
            )
        else:
            logger.println(f"Dataset average score rate ({DATASET_NAME}): N/A (no scored runs)")

        if avg_progress is not None:
            logger.println(f"Dataset average progress ({DATASET_NAME}): {_fmt(avg_progress)}")
        else:
            logger.println(f"Dataset average progress ({DATASET_NAME}): N/A (no scored runs)")

        summary_path = _write_benchmark_summary(manifest)
        manifest["benchmark_summary_path"] = str(summary_path.resolve())
        manifest = _repair_manifest_runs(manifest)
        summary_path = _write_benchmark_summary(manifest)
        manifest["benchmark_summary_path"] = str(summary_path.resolve())
        _persist_manifest(batch_dir, manifest)
        logger.println(json.dumps(manifest, ensure_ascii=False, indent=2))
        final_errs = int(manifest.get("error_count") or 0)
        return 0 if final_errs == 0 else 2
    finally:
        logger.close()


if __name__ == "__main__":
    raise SystemExit(main())
