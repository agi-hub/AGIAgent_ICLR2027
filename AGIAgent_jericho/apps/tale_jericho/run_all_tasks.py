#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch runner: one task -> one AGIAgent session -> one output_* directory.

Implements the iterative wiki memory pipeline (play_1 -> phase_m_1 -> play_2 -> ... -> play_N),
adapted for TALE-Suite Jericho games. Each game is a single episode (no variations).
Each play iteration is a single-attempt fresh game (no restart within a phase).
Phase M distills trajectory knowledge into the wiki between iterations.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

APP_NAME = "tale_jericho"
DATASET_NAME = "Jericho"
TOOL_PREFIX = APP_NAME
DEFAULT_PLAY_LOOPS = 200
# Optional static task list hyperparameter (1-based indices).
# Examples:
#   [1, 2, 3] -> run first 3 tasks
#   [7, 8, 30, 45] -> run tasks #7/#8/#30/#45
# Keep empty to disable and rely on CLI args.
TASK_INDEX_LIST: List[int] = [27, 31, 35, 21, 44, 3, 51]  # Ludicorp, Night, Planetfall, Inhumane, Temple, Advent, Zork1

APP_DIR = Path(__file__).resolve().parent
AGI_ROOT = APP_DIR.parent.parent.resolve()
WORKSPACE_ROOT = AGI_ROOT.parent.resolve()
DATA_ROOT = AGI_ROOT / "data"
BENCHMARK_RESULTS_ROOT = DATA_ROOT / "benchmark_results"
DEFAULT_GENERAL_ROOT = DATA_ROOT / "default" / "general"
EXPERIENCE_ROOT = DEFAULT_GENERAL_ROOT / "experience"


def _load_embedding_config() -> None:
    """Load embedding model API config from config.txt into environment.

    config.txt has lines like:
      embedding_model_api_key=sk-xxx
      embedding_model_api_base=https://api.siliconflow.cn/v1
    We map these to AGIA_WIKI_EMBEDDING_API_KEY for wiki_memory.py.
    """
    config_path = APP_DIR / "config.txt"
    if not config_path.is_file():
        return
    try:
        for line in config_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()
            if key == "embedding_model_api_key" and val and val != "your key":
                os.environ.setdefault("AGIA_WIKI_EMBEDDING_API_KEY", val)
            elif key == "embedding_model_api_base" and val:
                os.environ.setdefault("AGIA_WIKI_EMBEDDING_API_BASE", val)
    except Exception:
        pass


_load_embedding_config()
if str(AGI_ROOT) not in sys.path:
    sys.path.insert(0, str(AGI_ROOT))

from src.tools.tale_jericho_tools import TaleJerichoTools as ToolClass
from src.wiki_gc import run_wiki_gc


def _safe_name(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", text).strip("_") or "task"


def _experiment_name(text: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", (text or "").strip()).strip("_")
    return safe or "tale_jericho_smoke_v1"


def _resolve_log_file(base_dir: Path, raw_value: str) -> Optional[Path]:
    value = (raw_value or "").strip()
    if not value:
        return None
    if value.lower() == "auto":
        return base_dir / "nohup.out"
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = (base_dir / candidate).resolve()
    return candidate


# ---------------------------------------------------------------------------
# Watchdog constants & helpers (ported from scienceworld run_all_tasks.py)
# ---------------------------------------------------------------------------
PHASE_ZOMBIE_STALE_SECONDS = 1800  # heartbeat stale threshold (30 min)


def _parse_iso_datetime(text: Any) -> Optional[datetime]:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _load_spawn_manager_status(output_dir: Path) -> Dict[str, Any]:
    status_path = output_dir / ".agia_spawn_manager_status.json"
    if not status_path.exists():
        return {"exists": False, "status_path": str(status_path.resolve())}
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"exists": True, "status_path": str(status_path.resolve()), "error": str(e)}
    if not isinstance(data, dict):
        return {"exists": True, "status_path": str(status_path.resolve()), "error": "invalid format"}
    data["exists"] = True
    data["status_path"] = str(status_path.resolve())
    return data


def _is_running_like_status(spawn_status: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(spawn_status, dict):
        return False
    return str(spawn_status.get("status") or "").strip().lower() in {"running", "pending"}


def _spawn_status_last_progress_time(spawn_status: Optional[Dict[str, Any]]) -> Optional[datetime]:
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


def _phase_stale_kill_enabled() -> bool:
    return str(os.environ.get("AGIA_ENABLE_PHASE_STALE_KILL", "true") or "true").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _is_spawn_status_stale(spawn_status: Optional[Dict[str, Any]]) -> bool:
    if not _phase_stale_kill_enabled():
        return False
    if not _is_running_like_status(spawn_status):
        return False
    if str(spawn_status.get("completion_time") or "").strip():
        return False
    stale_seconds = max(60, int(
        os.environ.get("AGIA_PHASE_ZOMBIE_STALE_SECONDS", str(PHASE_ZOMBIE_STALE_SECONDS))
        or PHASE_ZOMBIE_STALE_SECONDS
    ))
    last_update = _spawn_status_last_progress_time(spawn_status)
    if last_update is None:
        return True
    return (datetime.now() - last_update).total_seconds() >= stale_seconds


def _mark_spawn_status_terminal(
    output_dir: Path, *, terminal_status: str, error_message: str,
    returncode: Optional[int] = None, stale_killed: bool = False,
) -> None:
    existing = _load_spawn_manager_status(output_dir)
    now_iso = datetime.now().isoformat()
    payload: Dict[str, Any] = {}
    if existing.get("exists"):
        payload = {k: v for k, v in existing.items() if k not in {"exists", "status_path"}}
    payload["status"] = terminal_status
    payload["completion_time"] = now_iso
    payload["updated_at"] = now_iso
    payload["error"] = error_message
    payload["terminated_by_runner"] = True
    payload["stale_killed"] = bool(stale_killed)
    status_path = output_dir / ".agia_spawn_manager_status.json"
    status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class _ExperimentLogger:
    """Tee logger: prints to stdout and appends to one or more log files."""

    def __init__(self, file_paths: List[Path]) -> None:
        self._handles = []
        for path in file_paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._handles.append(open(path, "a", encoding="utf-8"))
        self._lock = __import__("threading").Lock()

    def println(self, message: str, error: bool = False) -> None:
        stream = sys.stderr if error else sys.stdout
        text = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        with self._lock:
            print(text, file=stream, flush=True)
            for handle in self._handles:
                try:
                    handle.write(text + "\n")
                    handle.flush()
                except Exception:
                    pass

    def run_process(
        self,
        cmd: List[str],
        cwd: str,
        env: Optional[Dict[str, str]] = None,
        per_run_log_path: Optional[Path] = None,
        output_dir: Optional[Path] = None,
        write_per_run_log: bool = False,
    ) -> int:
        with self._lock:
            print(" ".join(cmd), flush=True)
            for handle in self._handles:
                try:
                    handle.write(" ".join(cmd) + "\n")
                    handle.flush()
                except Exception:
                    pass

        if output_dir is None:
            output_dir = Path(cwd)

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
            start_new_session=True,  # independent process group for clean kill
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
        kill_grace = max(1.0, float(
            os.environ.get("AGIA_PHASE_TERMINATE_GRACE_SECONDS", "20") or 20
        ))

        # Watchdog throttle: evaluating spawn status hits the filesystem every
        # check; once per ~30s of wall time is enough (stale threshold is 1800s).
        _last_watchdog_check = 0.0

        while True:
            # Watchdog: check child heartbeat on EVERY iteration — a child
            # streaming garbage (degenerate repeat loops) keeps stdout lines
            # flowing, which previously starved the queue.Empty branch and the
            # stale check with it. Heartbeat (last_loop_update) is written by
            # the child itself, so flow of output is irrelevant to staleness.
            now = time.monotonic()
            if now - _last_watchdog_check >= 30.0:
                _last_watchdog_check = now
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
                        proc.wait(timeout=kill_grace)
                    except subprocess.TimeoutExpired:
                        self.println(
                            f"   child did not exit after {kill_grace:.0f}s, sending SIGKILL",
                            error=True,
                        )
                        proc.kill()
                        proc.wait()
                    terminated_for_stale = True
                    break

            try:
                line = stdout_queue.get(timeout=1.0)
            except queue.Empty:
                if proc.poll() is not None:
                    break
                continue


            if line is None:
                break
            with self._lock:
                print(line, end="", flush=True)
                for handle in self._handles:
                    try:
                        handle.write(line)
                        handle.flush()
                    except Exception:
                        pass

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
            self.println(
                f"   process terminated for stale progress: {terminate_reason}",
                error=True,
            )
        return returncode

    def close(self) -> None:
        for handle in self._handles:
            try:
                handle.close()
            except Exception:
                pass
        self._handles = []


def _slice(tasks: List[str], offset: int, count: int) -> List[str]:
    s = max(0, int(offset))
    if int(count) <= 0:
        return tasks[s:]
    return tasks[s:s + int(count)]


def _parse_task_list(raw: str) -> List[int]:
    text = (raw or "").strip()
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
        except Exception as e:
            raise ValueError(f"invalid --task-list JSON: {e}") from e
        if not isinstance(parsed, list):
            raise ValueError("--task-list JSON must be a list of 1-based indices")
        return [int(i) for i in parsed]
    parts = [p.strip() for p in text.split(",") if p.strip()]
    result: List[int] = []
    for part in parts:
        if not re.fullmatch(r"\d+", part):
            raise ValueError(f"invalid --task-list entry: {part!r}")
        result.append(int(part))
    return result


def _play_requirement(
    env_name: str,
    iteration: int,
    max_iterations: int,
    use_wiki: bool,
) -> str:
    """Dynamic per-iteration parameters for play. All static strategy is in system_prompt.txt."""
    lines: List[str] = [
        f"Run only one {DATASET_NAME} task: {env_name}.",
        f"Only {TOOL_PREFIX}_action is allowed for environment interaction.",
        (
            f"The first {TOOL_PREFIX}_action call must include env_name=\"{env_name}\". "
            "The first environment action should normally be `look` so you can read the "
            "returned observation, feedback, admissible_commands, and score fields."
        ),
        "",
        f"This is attempt {iteration} of {max_iterations}. Each attempt is a FRESH game — one single playthrough with no restart.",
        "Your goal is always to maximize score and WIN the game. Make your strongest effort.",
        f"Keep calling {TOOL_PREFIX}_action(action=...) each turn until done=true is returned.",
        "",
    ]

    _ablation = os.environ.get("AGIA_WIKI_ABLATION", "").strip().lower()
    _curator_style = str(os.environ.get("AGIA_CURATOR_STYLE", "")).strip().lower()
    if use_wiki and _curator_style == "autom":
        # AutoManual-style: inject the curated manual text directly into the play
        # prompt (no retrieval tool). Mirrors AutoManual's manual-as-context design;
        # keeps every other mechanism identical to the react baseline.
        manual_text = _load_manual_for_env(env_name)
        if manual_text:
            lines += [
                "This is attempt {} of {}. A MANUAL built from earlier attempts is embedded below.".format(iteration, max_iterations),
                "It records which actions scored where, which actions killed the agent where, and open questions. It may contain errors or gaps.",
                "Use it as your starting plan: replay the scoring path, avoid the death traps, and probe the listed open questions.",
                "Verify every suggestion against the current observation — rooms and seeds vary between attempts. A manual entry that fails twice is stale; skip it and explore.",
                "",
                "=" * 60,
                "MANUAL (from previous attempts):",
                "=" * 60,
                manual_text,
                "=" * 60,
            ]
        else:
            lines += [
                "This is attempt {} of {}. No manual exists yet — explore and solve from scratch.".format(iteration, max_iterations),
            ]
    elif use_wiki and _ablation == "no_knowledge":
        lines += [
            "This is attempt {} of {}. Prior playthrough EXPERIENCES from earlier attempts ARE available.".format(iteration, max_iterations),
            "STRATEGY: Query the wiki for past attempt records (section=\"experiences\"). They summarize what worked, what killed the agent, and what was discovered in each earlier attempt.",
            "Use experiences as REFERENCE — past deaths tell you what to avoid; past progress tells you which routes paid off. Verify each suggestion against the current observation.",
        ]
    elif use_wiki:
        lines += [
            "This is attempt {} of {}. Prior wiki knowledge from earlier attempts IS available.".format(iteration, max_iterations),
            "STRATEGY: Query the wiki for score-increasing actions (section=\"knowledge\"). Use them as REFERENCE — try the suggested actions, but verify each one against the current observation. If a wiki action does not work, skip it and explore alternatives.",
            "The wiki is a starting point, not a fixed path. It may contain errors, unnecessary steps, or miss better routes. Always keep exploring new actions and areas the wiki does not mention.",
            "CRITICAL SURVIVAL: Before EVERY action, check if it matches a [FATAL] entry in the wiki DON'T list. NEVER execute an action marked [FATAL] — a dead agent scores zero.",
        ]
    else:
        lines += [
            "This is your first attempt — no prior knowledge is available. Explore and solve from scratch.",
        ]

    lines += [
        "",
        "At the end, output TASK_COMPLETED: <brief summary> with your best_score/current_score/full_score/score_rate/moves.",
    ]
    return "\n".join(lines)


def _baseline_requirement(env_name: str) -> str:
    return "\n".join(
        [
            f"Run only one {DATASET_NAME} task: {env_name}.",
            f"Only {TOOL_PREFIX}_action is allowed for environment interaction.",
            (
                f"The first {TOOL_PREFIX}_action call must include env_name=\"{env_name}\". "
                "The first environment action should normally be `look`."
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
            "- Start with `look` to anchor the current state.",
            "- Reason directly from the observation to choose the next action.",
            "- If an action is invalid or returns an error, try a nearby admissible variant.",
            "",
            "Single-attempt rule: When done=true is returned, output TASK_COMPLETED with your final scores. No restart.",
            "",
            "At the end, output best_score/current_score/full_score/score_rate/moves.",
        ]
    )


def _jericho_game_slug(env_name: str) -> str:
    """Game slug for wiki naming: strip the 'JerichoEnv' prefix and lowercase.

    e.g. 'JerichoEnvZork1' -> 'zork1', 'JerichoEnv905' -> '905'.
    Every wiki asset filename must end with this slug so its source game is
    unambiguous.
    """
    raw = str(env_name or "").strip()
    prefix = "JerichoEnv"
    core = raw[len(prefix):] if raw.startswith(prefix) else raw
    return re.sub(r"[^a-zA-Z0-9]+", "_", core).strip("_").lower() or _safe_name(raw).lower()

def _load_manual_for_env(env_name: str) -> str:
    """Load the curated knowledge file (manual) for one game, for AutoManual-style
    direct prompt injection.

    Reads from the experiment's wiki root (AGIA_WIKI_ROOT). Returns empty string
    when no manual exists yet (first attempts).
    """
    game_slug = _jericho_game_slug(env_name)
    wiki_root = os.environ.get("AGIA_WIKI_ROOT", "").strip()
    if not wiki_root:
        return ""
    manual_path = os.path.join(wiki_root, "knowledge", f"score_recipe_{game_slug}.md")
    try:
        if not os.path.isfile(manual_path):
            return ""
        text = open(manual_path, encoding="utf-8").read().strip()
        if not text:
            return ""
        # Cap the manual to keep the play prompt within model context budget.
        cap = int(os.environ.get("AGIA_MANUAL_INJECT_CAP", "6000") or 6000)
        if len(text) > cap:
            text = text[:cap] + "\n... (manual truncated)"
        return text
    except (OSError, IOError):
        return ""

def _pre_extract_score_actions(trajectory_path: str) -> str:
    """Pre-parse trajectory.jsonl and extract score-progression actions.

    Returns a human-readable summary that is injected into the Curator prompt,
    so the Curator doesn't need to parse the raw trajectory itself.
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

    # Extract tale_jericho_action records with score data
    actions_with_score = []
    prev_best = 0.0
    for rec in records:
        if rec.get("tool") != "tale_jericho_action":
            continue
        best = rec.get("best_score")
        current = rec.get("current_score")
        action = rec.get("action", "")
        done = rec.get("done", False)
        won = rec.get("won", False)
        # Extract room name from observation (format: "<< Room Name >> ...")
        obs = str(rec.get("observation", "") or "")
        import re as _re
        room_match = _re.search(r"<<\s*(.+?)\s*>>", obs)
        room = room_match.group(1) if room_match else ""
        if best is None and current is None:
            continue
        try:
            best_f = float(best) if best is not None else 0.0
            current_f = float(current) if current is not None else 0.0
        except (TypeError, ValueError):
            continue

        # Detect score increase
        delta = current_f - prev_best if current_f > prev_best else 0.0
        actions_with_score.append({
            "action": action,
            "room": room,
            "best_score": best_f,
            "current_score": current_f,
            "delta": delta,
            "done": done,
            "won": won,
        })
        if best_f > prev_best:
            prev_best = best_f

    if not actions_with_score:
        return ""

    # Build summary
    final = actions_with_score[-1]
    score_actions = [a for a in actions_with_score if a["delta"] > 0]
    death_actions = [a for a in actions_with_score if a.get("done") and not a.get("won")]

    lines = [
        "## Pre-Extracted Trajectory Summary (auto-generated — do NOT re-parse the trajectory file)",
        f"- Total actions: {len(actions_with_score)}",
        f"- Final best_score: {final['best_score']}",
        f"- Score-increasing actions: {len(score_actions)}",
        "",
    ]

    if score_actions:
        lines.append("### Score-Progression Actions (VERIFIED — include room context in knowledge):")
        for i, sa in enumerate(score_actions, 1):
            room_str = f" at [{sa['room']}]" if sa.get("room") else ""
            lines.append(
                f"  {i}. {sa['action']}{room_str} -> +{sa['delta']:.0f} (score {sa['best_score']:.0f})"
            )
        lines.append("")

    if death_actions:
        lines.append("### Death/Failure Actions:")
        for da in death_actions:
            room_str = f" at [{da.get('room','')}]" if da.get("room") else ""
            lines.append(f"  - {da['action']}{room_str} -> died (score was {da['best_score']:.0f})")
        lines.append("")

    lines.append(
        "Use the above as your primary data source. Cross-reference with the trajectory only if you need "
        "room/object details. Focus your effort on SYNTHESIZING knowledge (connecting fragments), not parsing."
    )
    return "\n".join(lines)

def _phase_m_requirement(
    env_name: str,
    wiki_root: str,
    trajectory_log_path: str,
    iteration: int,
) -> str:
    """Build the phase_m user requirement: static format rules + dynamic per-iteration params."""
    game_slug = _jericho_game_slug(env_name)
    is_first = (iteration == 1)

    knowledge_path = os.path.join(wiki_root, "knowledge", f"score_recipe_{game_slug}.md")
    exp_path = os.path.join(wiki_root, "experiences", datetime.now().strftime("%Y-%m-%d"), f"{game_slug}.md")

    # Load static format instructions from phase_m_prompt.txt
    prompt_file = APP_DIR / "prompts" / "phase_m_prompt.txt"
    static_instructions = ""
    if prompt_file.is_file():
        static_instructions = prompt_file.read_text(encoding="utf-8").strip()

    # E6 ablation: pure episodic event log (no semanticization, no program pre-extract, no knowledge file)
    if str(os.environ.get("AGIA_CURATOR_PURE_EPISODIC", "")).strip().lower() in {"1", "true", "yes", "on"}:
        pe_file = APP_DIR / "prompts" / "phase_m_prompt_pure_episodic.txt"
        if pe_file.is_file():
            fmt = pe_file.read_text(encoding="utf-8")
            fmt = fmt.replace("{trajectory_log_path}", trajectory_log_path)
            fmt = fmt.replace("{exp_path}", exp_path)
            fmt = fmt.replace("{iteration}", str(iteration))
            fmt = fmt.replace("{env_name}", env_name)
            fmt = fmt.replace("{game_slug}", game_slug)
            fmt = fmt.replace("{wiki_root}", wiki_root)
            return fmt  # E6: event-log only; run with --ablation no_knowledge so retrieval is experiences-only

    # E1 ablation: scattered-triplet representation (replaces ordered narrative + knowledge file)
    if str(os.environ.get("AGIA_CURATOR_REPRESENTATION", "")).strip().lower() == "scatter":
        scatter_file = APP_DIR / "prompts" / "phase_m_prompt_scatter.txt"
        if scatter_file.is_file():
            fmt = scatter_file.read_text(encoding="utf-8")
            fmt = fmt.replace("{trajectory_log_path}", trajectory_log_path)
            fmt = fmt.replace("{exp_path}", exp_path)
            fmt = fmt.replace("{iteration}", str(iteration))
            fmt = fmt.replace("{env_name}", env_name)
            fmt = fmt.replace("{game_slug}", game_slug)
            fmt = fmt.replace("{wiki_root}", wiki_root)
            return fmt  # E1 bypasses the standard requirement entirely

    # E2 ablation: order-free curator prompt (content preserved, order stripped)
    if str(os.environ.get("AGIA_CURATOR_NO_TIME", "")).strip().lower() in {"1", "true", "yes", "on"}:
        notime_file = APP_DIR / "prompts" / "phase_m_prompt_notime.txt"
        if notime_file.is_file():
            fmt = notime_file.read_text(encoding="utf-8")
            fmt = fmt.replace("{trajectory_log_path}", trajectory_log_path)
            fmt = fmt.replace("{exp_path}", exp_path)
            fmt = fmt.replace("{iteration}", str(iteration))
            fmt = fmt.replace("{env_name}", env_name)
            fmt = fmt.replace("{game_slug}", game_slug)
            fmt = fmt.replace("{wiki_root}", wiki_root)
            return fmt  # E2 uses its own format rules (order-free)

    # Optional AutoManual-style curator discipline addon (env-gated, single-variable ablation)
    if str(os.environ.get("AGIA_CURATOR_STYLE", "")).strip().lower() == "autom":
        autom_file = APP_DIR / "prompts" / "phase_m_prompt_autom.txt"
        if autom_file.is_file():
            autom_addon = autom_file.read_text(encoding="utf-8").strip()
            if autom_addon:
                static_instructions = static_instructions + "\n\n" + autom_addon if static_instructions else autom_addon

    lines: List[str] = []
    if static_instructions:
        lines += [static_instructions, "", "=" * 60, ""]

    lines += [
        f"Attempt {iteration} has just completed. Update the wiki using the paths below.",
        "",
        f"Game ID (env_name): {env_name}",
        f"Game slug: {game_slug}",
        f"Wiki root: {wiki_root}",
        f"Latest trajectory (from attempt {iteration}): {trajectory_log_path}",
        "",
        f"Knowledge file (MUST use this exact path): {knowledge_path}",
        f"Experience file: {exp_path}",
        f"Experience relative path (for knowledge links): ../experiences/{datetime.now().strftime('%Y-%m-%d')}/{game_slug}.md",
    ]

# Ablation AGIA_CURATOR_NO_PREEXTRACT=1: do NOT inject the program-extracted summary.
    # Instead, describe the program's extraction method in the prompt so the curator
    # LLM must perform the extraction itself from the raw trajectory file.
    # (Contrast arm for the neuro-symbolic pre-extraction: tests whether program-side
    #  extraction is load-bearing vs. LLM-side extraction given the same recipe.)
    if str(os.environ.get("AGIA_CURATOR_NO_PREEXTRACT", "")).strip().lower() in {"1", "true", "yes", "on"}:
        lines += [
            "## Extraction Method Reference (the usual pipeline runs a DETERMINISTIC program first; this run does NOT)",
            "Normally a program pre-parses the trajectory and hands you a summary. This time YOU must do the",
            "extraction yourself, from the raw trajectory file, following the same method the program uses:",
            "1. Read trajectory.jsonl line by line; each line is a JSON record. Keep only records with",
            '   "tool": "tale_jericho_action" that carry best_score/current_score fields.',
            '2. Track a running best score. An action is SCORE-INCREASING when its current_score exceeds the',
            "   running best so far; record (action, room, delta, new best).",
            '3. Extract the room name from the observation text: the first "<< Room Name >>" marker.',
            '4. An action is a DEATH when done=true and won=false; record (action, room).',
            "5. Summarize: total actions, final best score, every score-increasing action with room context,",
            "   every death, in chronological order. Verify counts against the file; do not guess.",
            "",
            f"Then curate the wiki from YOUR OWN extraction of: {trajectory_log_path}",
            "",
        ]
    else:
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
        lines.append("This is the first curation — the wiki may be empty for this game. Create the files above.")
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
    data["score_summary_path"] = str(summary_path.resolve())
    return data


def _phase_status_from_returncode(returncode: int, score_summary: Dict[str, Any]) -> str:
    # returncode=0 means a clean exit (won or explicit completion).
    if int(returncode) == 0:
        if score_summary.get("has_metrics") and score_summary.get("won"):
            return "success"
        if score_summary.get("has_metrics"):
            return "partial_success"
        return "max_rounds_reached"
    # returncode=1 is the normal exit for max_rounds_reached (agia.py exits 1
    # when the agent runs out of loops without winning). Check score_summary
    # to distinguish "ran to completion" from a genuine crash.
    task_status = str((score_summary or {}).get("task_status") or "").strip().lower()
    if task_status in ("max_rounds_reached", "completed"):
        if score_summary.get("has_metrics") and score_summary.get("won"):
            return "success"
        if score_summary.get("has_metrics"):
            return "partial_success"
        return "max_rounds_reached"
    if isinstance(score_summary, dict) and score_summary.get("has_metrics"):
        return "partial_success"
    return "error"


def _phase_current_loop(score_summary: Optional[Dict[str, Any]]) -> int:
    if not isinstance(score_summary, dict):
        return 0
    max_loops = score_summary.get("max_loops")
    try:
        return int(max_loops) if max_loops is not None else 0
    except Exception:
        return 0


def _build_phase_skipped_result(
    phase_name: str,
    out_dir: Path,
    per_run_log_path: Path,
) -> Dict[str, Any]:
    return {
        "phase": phase_name,
        "output_dir": str(out_dir.resolve()),
        "per_run_log_path": str(per_run_log_path.resolve()),
        "command": None,
        "returncode": None,
        "status": "skipped",
        "score_summary": {"has_metrics": False, "reason": "phase skipped"},
        "score_summary_path": str((out_dir / "logs" / "score_summary.json").resolve()),
        "skipped": True,
    }


def _build_phase_error_result(
    phase_name: str,
    out_dir: Path,
    per_run_log_path: Path,
    cmd: Optional[List[str]],
    error_message: str,
) -> Dict[str, Any]:
    return {
        "phase": phase_name,
        "output_dir": str(out_dir.resolve()),
        "per_run_log_path": str(per_run_log_path.resolve()),
        "command": cmd,
        "returncode": None,
        "status": "error",
        "score_summary": {"has_metrics": False, "error": error_message},
        "score_summary_path": str((out_dir / "logs" / "score_summary.json").resolve()),
        "error": error_message,
    }


def _phase_needs_error_fallback(phase: Any) -> bool:
    if not isinstance(phase, dict):
        return False
    status = str(phase.get("status") or "").strip().lower()
    return status in {"", "pending", "running"}


def _flatten_phase_for_metrics(item: Dict[str, Any]) -> Dict[str, Any]:
    phase_mode = str(item.get("phase_mode") or "iterative").strip().lower()
    if phase_mode == "baseline":
        baseline_phase = item.get("baseline_phase") or {}
        summary = baseline_phase.get("score_summary") if isinstance(baseline_phase.get("score_summary"), dict) else {}
        return {
            "task_index_1based": item.get("task_index_1based"),
            "env_name": item.get("env_name"),
            "status": baseline_phase.get("status"),
            "score_summary": summary,
        }
    # Iterative: use the best play phase across iterations
    iterations = item.get("iterations") or []
    best_summary: Dict[str, Any] = {}
    best_score: Optional[float] = None
    best_status: Optional[str] = None
    for it in iterations:
        play = it.get("play_phase") or {}
        summary = play.get("score_summary") if isinstance(play.get("score_summary"), dict) else {}
        if summary.get("has_metrics"):
            s = _safe_float(summary.get("best_score"))
            if s is not None and (best_score is None or s > best_score):
                best_score = s
                best_summary = summary
                best_status = play.get("status")
    return {
        "task_index_1based": item.get("task_index_1based"),
        "env_name": item.get("env_name"),
        "status": best_status or item.get("status"),
        "score_summary": best_summary,
    }


def _compute_dataset_score_averages(manifest: Dict[str, Any]) -> None:
    runs = [_flatten_phase_for_metrics(run) for run in manifest.get("runs", [])]
    scored_summaries: List[Dict[str, Any]] = [
        run["score_summary"]
        for run in runs
        if isinstance(run.get("score_summary"), dict) and run["score_summary"].get("has_metrics")
    ]
    manifest["scored_runs"] = len(scored_summaries)
    manifest["dataset_average_score_rate"] = _avg([s.get("score_rate") for s in scored_summaries])


def _persist_manifest(batch_dir: Path, manifest: Dict[str, Any]) -> None:
    (batch_dir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _build_run_item(
    *,
    index: int,
    task_index_1based: int,
    env_name: str,
    safe_env_name: str,
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
        "status": "pending",
        "phase_mode": phase_mode,
    }

    if phase_mode == "baseline":
        baseline_output_dir = (
            outputs_dir / f"{output_prefix}_{APP_NAME}_{task_index_1based:02d}_{safe_env_name}_baseline_{ts}"
        ).resolve()
        item["baseline_phase"] = {
            "phase": "phase_baseline",
            "output_dir": str(baseline_output_dir),
            "per_run_log_path": str(
                (experience_logs_dir / f"{task_index_1based:02d}_{safe_env_name}_baseline_{ts}.log").resolve()
            ),
        }
    else:
        # Iterative mode: play_1, phase_m_1, play_2, phase_m_2, ..., play_N
        # Output dirs are generated lazily per-iteration inside _run_task_iterative,
        # but we pre-create the first batch so the manifest has concrete paths.
        item["iterations"] = []
        item["max_iterations"] = max_iterations
        for i in range(1, max_iterations + 1):
            play_dir = (
                outputs_dir / f"{output_prefix}_{APP_NAME}_{task_index_1based:02d}_{safe_env_name}_play{i}_{ts}"
            ).resolve()
            phase_m_dir = (
                outputs_dir / f"{output_prefix}_{APP_NAME}_{task_index_1based:02d}_{safe_env_name}_phasem{i}_{ts}"
            ).resolve()
            iteration_entry: Dict[str, Any] = {
                "iteration": i,
                "play_phase": {
                    "phase": f"play_{i}",
                    "output_dir": str(play_dir),
                    "per_run_log_path": str(
                        (experience_logs_dir / f"{task_index_1based:02d}_{safe_env_name}_play{i}_{ts}.log").resolve()
                    ),
                    "status": "pending",
                },
                "phase_m_phase": {
                    "phase": f"phase_m_{i}",
                    "output_dir": str(phase_m_dir),
                    "per_run_log_path": str(
                        (experience_logs_dir / f"{task_index_1based:02d}_{safe_env_name}_phasem{i}_{ts}.log").resolve()
                    ),
                    "status": "pending",
                },
            }
            item["iterations"].append(iteration_entry)

        # Per-task phase records file (score per iteration).
        item["phase_records_path"] = str(
            (outputs_dir / f"{output_prefix}_{APP_NAME}_{task_index_1based:02d}_{safe_env_name}_phase_records.json").resolve()
        )
    return item


def _finalize_run_item(item: Dict[str, Any]) -> Dict[str, Any]:
    phase_mode = str(item.get("phase_mode") or "iterative").strip().lower()

    if phase_mode == "baseline":
        baseline = item.get("baseline_phase") or {}
        status = str(baseline.get("status") or "").strip().lower()
        if status == "error":
            item["status"] = "error"
            item["error"] = "baseline phase failed"
        else:
            item["status"] = status or "error"
    else:
        # Iterative: status = best play phase status across all iterations
        iterations = item.get("iterations") or []
        best_status = "error"
        won_any = False
        for it in iterations:
            play = it.get("play_phase") or {}
            s = str(play.get("status") or "").strip().lower()
            if s == "success":
                won_any = True
            if play.get("score_summary", {}).get("has_metrics"):
                if s != "error" and best_status == "error":
                    best_status = s
        if won_any:
            item["status"] = "success"
        elif best_status != "error":
            item["status"] = best_status
        else:
            item["status"] = "error"
    return item


def _best_iteration_score(item: Dict[str, Any]) -> Optional[float]:
    """Return the highest best_score across all play iterations."""
    iterations = item.get("iterations") or []
    best: Optional[float] = None
    for it in iterations:
        play = it.get("play_phase") or {}
        summary = play.get("score_summary") or {}
        if summary.get("has_metrics"):
            s = _safe_float(summary.get("best_score"))
            if s is not None:
                if best is None or s > best:
                    best = s
    return best

def _run_phase(
    *,
    logger: _ExperimentLogger,
    phase_name: str,
    phase_requirement: str,
    env_name: str,
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
    child_env["JERICHO_ACTIVE_ENV"] = env_name
    child_env["AGIA_WIKI_ROOT"] = os.path.join(
        str(AGI_ROOT), "data", "default", "general", "wiki", experiment_name
    )

    logger.println(
        f"[{task_order_index}/{total_selected}] {phase_name} task#{task_index_1based} {env_name} -> {out_dir}"
    )
    returncode = logger.run_process(
        cmd=cmd,
        cwd=AGI_ROOT,
        env=child_env,
        per_run_log_path=per_run_log_path,
        output_dir=out_dir,
    )

    score_summary = _load_score_summary(out_dir)
    phase_result: Dict[str, Any] = {
        "phase": phase_name,
        "output_dir": str(out_dir.resolve()),
        "per_run_log_path": str(per_run_log_path.resolve()),
        "command": cmd,
        "returncode": returncode,
        "status": _phase_status_from_returncode(returncode, score_summary),
        "score_summary": score_summary,
        "score_summary_path": str((out_dir / "logs" / "score_summary.json").resolve()),
        "current_loop": _phase_current_loop(score_summary),
    }

    if score_summary.get("has_metrics"):
        phase_result["best_score"] = score_summary.get("best_score")
        phase_result["current_score"] = score_summary.get("current_score")
        phase_result["full_score"] = score_summary.get("full_score")
        phase_result["score_rate"] = score_summary.get("score_rate")
        logger.println(
            f"   {phase_name} score summary: "
            f"best={_fmt(phase_result.get('best_score'))}, "
            f"current={_fmt(phase_result.get('current_score'))}, "
            f"full={_fmt(phase_result.get('full_score'))}, "
            f"score_rate={_fmt(phase_result.get('score_rate'))}"
        )
    else:
        reason = score_summary.get("reason") or score_summary.get("error") or "no score metrics"
        logger.println(f"   {phase_name} score summary unavailable: {reason}")

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


def _trajectory_best_score(output_dir: str) -> Optional[float]:
    """Read trajectory.jsonl and return the true best_score from environment data.

    Cross-checks against the polluted score_summary which may contain inflated
    scores from the _summarize_score_history regex bug.
    """
    tj_path = os.path.join(output_dir, "logs", "trajectory.jsonl")
    if not os.path.exists(tj_path):
        return None
    real_best = 0.0
    try:
        for line in Path(tj_path).read_text(encoding="utf-8").splitlines():
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
    return real_best if real_best > 0 else None


def _load_prior_phase_records(item: Dict[str, Any]) -> int:
    """Load existing phase_records.json and mark completed iterations as skipped.

    Returns the number of iterations restored (skipped). Only iterations where
    play has a terminal status (success/skipped/partial_success with score) are
    considered completed.

    Early-exit (won/full score) is verified against trajectory.jsonl ground truth
    to avoid false positives from the score_summary pollution bug.
    """
    records_path = item.get("phase_records_path")
    if not records_path or not Path(records_path).exists():
        return 0

    try:
        prior = json.loads(Path(records_path).read_text(encoding="utf-8"))
    except Exception:
        return 0

    if not isinstance(prior, list) or not prior:
        return 0

    restored = 0
    max_iterations = item.get("max_iterations", 10)

    # Build a lookup: iteration -> record
    rec_by_iter = {}
    for rec in prior:
        i = rec.get("iteration")
        if isinstance(i, int):
            rec_by_iter[i] = rec

    # No early exit: all games run all iterations regardless of score.
    early_exit = False


    for iteration_idx in range(max_iterations):
        iteration = iteration_idx + 1
        rec = rec_by_iter.get(iteration)
        if rec is None:
            break

        play_status = rec.get("play_status")

        # An iteration is "completed" if it actually ran and produced score data.
        # A "skipped" status WITHOUT score data means it was skipped by a false
        # early-exit (polluted score triggered premature termination) — those
        # should be re-run, not skipped again.
        play_done = False
        if play_status == "skipped":
            # Only skip if it has real score data (restored from a genuine run)
            if rec.get("play_best_score") is not None:
                play_done = True
        elif play_status == "success":
            play_done = True
        elif play_status == "partial_success":
            if rec.get("play_best_score") is not None:
                play_done = True

        if play_done:
            iter_entry = item["iterations"][iteration_idx]
            iter_entry["play_phase"]["status"] = "skipped"
            iter_entry["play_phase"]["score_summary"] = {
                "has_metrics": rec.get("play_best_score") is not None,
                "best_score": rec.get("play_best_score"),
                "current_score": rec.get("play_current_score"),
                "full_score": rec.get("play_full_score"),
                "score_rate": rec.get("play_score_rate"),
                "won": rec.get("play_won"),
                "done": rec.get("play_done"),
            }
            iter_entry["play_phase"]["best_score"] = rec.get("play_best_score")
            iter_entry["play_phase"]["current_score"] = rec.get("play_current_score")
            iter_entry["play_phase"]["full_score"] = rec.get("play_full_score")
            iter_entry["play_phase"]["score_rate"] = rec.get("play_score_rate")
            iter_entry["phase_m_phase"]["status"] = "skipped"
            restored += 1
        else:
            # This iteration was falsely skipped (no score data) — stop restoring,
            # let it and all subsequent iterations run.
            break

    # If verified early exit (real won/full score), mark all remaining as skipped
    if early_exit:
        for iteration_idx in range(restored, max_iterations):
            item["iterations"][iteration_idx]["play_phase"]["status"] = "skipped"
            item["iterations"][iteration_idx]["phase_m_phase"]["status"] = "skipped"
        restored = max_iterations

    return restored

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
    resume: bool = False,
) -> Dict[str, Any]:
    env_name = str(item["env_name"])
    task_index_1based = int(item["task_index_1based"])
    task_order_index = int(item["index"])

    try:
        item["status"] = "running"

        # Wiki root shared across all iterations for this game.
        wiki_root = str(AGI_ROOT / "data" / "default" / "general" / "wiki" / experiment_name)
        os.makedirs(wiki_root, exist_ok=True)
        for subdir in ["knowledge", "experiences"]:
            os.makedirs(os.path.join(wiki_root, subdir), exist_ok=True)
        os.environ["AGIA_WIKI_ROOT"] = wiki_root

        global_best_score: Optional[float] = None

        if resume:
            restored = _load_prior_phase_records(item)
            if restored > 0:
                logger.println(
                    f"[{task_order_index}/{total_selected}] task#{task_index_1based} {env_name} "
                    f"resumed: skipping {restored} completed iteration(s)."
                )
                _persist_phase_records(item)

        for iteration_idx in range(max_iterations):
            iteration = iteration_idx + 1
            iter_entry = item["iterations"][iteration_idx]

            # ---- Skip already-completed iterations (resume mode) ----
            play_status = iter_entry["play_phase"].get("status", "pending")
            if play_status == "skipped":
                # This iteration was restored from a prior run — carry forward score
                play_summary = iter_entry["play_phase"].get("score_summary") or {}
                play_best = _safe_float(play_summary.get("best_score")) if play_summary.get("has_metrics") else None
                if play_best is not None:
                    if global_best_score is None or play_best > global_best_score:
                        global_best_score = play_best
                continue

            # ---- Play phase (with retry for incomplete runs) ----
            use_wiki = (iteration > 1) and (phase_m_loops > 0)
            play_phase = iter_entry["play_phase"]
            max_play_attempts = max(1, int(os.environ.get("AGIA_PLAY_RETRY_ATTEMPTS", "2") or 2))

            for play_attempt in range(1, max_play_attempts + 1):
                iter_entry["play_phase"] = _run_phase(
                    logger=logger,
                    phase_name=f"play_{iteration}",
                    phase_requirement=_play_requirement(
                        env_name=env_name,
                        iteration=iteration,
                        max_iterations=max_iterations,
                        use_wiki=use_wiki,
                    ),
                    env_name=env_name,
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
                play_rc = play_result.get("returncode")
                play_summary = play_result.get("score_summary") or {}

                # Decide: keep result or retry?
                # Keep if: completed normally (rc=0/1), or zombie with score_summary written (rc=143 but has data)
                # Retry if: killed by watchdog (rc=143) AND no score_summary (truly incomplete)
                has_summary = bool(play_summary.get("has_metrics") or play_summary.get("task_status"))

                if play_attempt >= max_play_attempts:
                    break  # out of retries

                if play_rc == 143 and not has_summary:
                    logger.println(
                        f"[{task_order_index}/{total_selected}] play_{iteration} attempt {play_attempt} "
                        f"was killed (rc=143) without completing — retrying...",
                        error=True,
                    )
                    continue  # retry

                break  # result is acceptable

            play_result = iter_entry["play_phase"]
            play_summary = play_result.get("score_summary") or {}
            play_best = _safe_float(play_summary.get("best_score")) if play_summary.get("has_metrics") else None
            play_full = _safe_float(play_summary.get("full_score")) if play_summary.get("has_metrics") else None
            play_won = bool(play_summary.get("won")) if play_summary.get("has_metrics") else False

            logger.println(
                f"[{task_order_index}/{total_selected}] iteration {iteration}/{max_iterations} "
                f"task#{task_index_1based} {env_name} play done: "
                f"best={_fmt(play_best)}, won={play_won}"
            )

            # Persist phase records after each play phase
            _persist_phase_records(item)

            # Track global best
            if play_best is not None:
                if global_best_score is None or play_best > global_best_score:
                    global_best_score = play_best

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
                        wiki_root=wiki_root,
                        trajectory_log_path=trajectory_log_path,
                        iteration=iteration,
                    ),
                    env_name=env_name,
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

            # Persist phase records after each phase_m
            _persist_phase_records(item)
            # Run wiki garbage collection after each curation phase.
            # DISABLED by default — enable with AGIA_ENABLE_WIKI_GC=1.
            if phase_m_loops > 0 and str(os.environ.get("AGIA_ENABLE_WIKI_GC", "")).strip().lower() in {"1", "true", "yes", "on"}:
                try:
                    gc_stats = run_wiki_gc(wiki_root)
                    if gc_stats.get("experience_consolidation", {}).get("files_removed", 0) > 0 or \
                       gc_stats.get("world_model_pruning", {}).get("pages_archived", 0) > 0:
                        logger.println(
                            f"   wiki_gc: merged {gc_stats['experience_consolidation']['files_merged']} exp files, "
                            f"archived {gc_stats['world_model_pruning']['pages_archived']} stubs"
                        )
                except Exception as gc_err:
                    logger.println(f"   wiki_gc warning: {gc_err}", error=True)

        if global_best_score is not None:
            item["best_score_across_iterations"] = global_best_score

        _persist_phase_records(item)
        return _finalize_run_item(item)
    except Exception as e:
        error_message = f"unexpected task failure: {type(e).__name__}: {e}"
        logger.println(
            f"[{task_order_index}/{total_selected}] task#{task_index_1based} {env_name} crashed: {error_message}",
            error=True,
        )
        # Mark any pending phases as error
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
        help="1-based task index list, e.g. \"[1,2,3]\" or \"7,8,30,45\". When provided, it overrides --task-offset/--task-count.",
    )
    p.add_argument("--loops", type=int, default=100)
    p.add_argument("--play-loops", type=int, default=0, help="Loops per play attempt. 0 falls back to --loops.")
    p.add_argument(
        "--phase-m-loops",
        type=int,
        default=30,
        help="Loops for phase_m (wiki memory curation). 0 disables phase_m.",
    )
    p.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="Maximum number of play+phase_m iterations per task (default: 10).",
    )
    p.add_argument("--output-prefix", type=str, default="output")
    p.add_argument("--python-exe", type=str, default=sys.executable)
    p.add_argument("--experiment-name", type=str, default="tale_jericho_smoke_v1")
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
        help="额外副本日志路径。传 `auto` 时写到 AGIAgent/nohup.out；无论是否设置，实验完整日志都会自动保存到 data/default/general/experience/<experiment>/logs/。",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip iterations already completed in prior runs (reads existing phase_records.json). Default enabled; use --no-resume to disable.",
    )
    p.add_argument(
        "--baseline",
        action="store_true",
        help="Run a single-phase baseline: solve each task from scratch without any long-term memory assets.",
    )
    p.add_argument(
        "--ablation",
        type=str,
        default="",
        choices=["", "no_wiki", "no_world_model", "no_experiences", "no_knowledge", "no_fatal_guard"],
        help="Wiki ablation mode: no_wiki (disable all), no_world_model, no_experiences, no_knowledge, or no_fatal_guard (keep knowledge retrieval, disable FATAL hard interception only).",
    )
    p.add_argument(
        "--game-seed",
        type=int,
        default=0,
        help="Fix the game seed for all runs (ensures identical environments across conditions). 0 = random.",
    )
    args = p.parse_args()

    # Propagate ablation mode to child processes via env
    if args.ablation:
        os.environ["AGIA_WIKI_ABLATION"] = args.ablation
        print(f"[ablation] wiki ablation mode: {args.ablation}")

    # Fix game seed for reproducibility across conditions/iterations
    if args.game_seed:
        os.environ["AGIA_GAME_SEED"] = str(args.game_seed)
        print(f"[game-seed] fixed seed: {args.game_seed}")

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
    ret: Dict[str, Any] = list_method()
    if ret.get("status") != "success":
        print(json.dumps(ret, ensure_ascii=False, indent=2))
        return 1

    tasks = ret.get("tasks", [])
    selected_items: List[Dict[str, Any]] = []

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
            selected_items.append(
                {
                    "task_index_1based": idx,
                    "env_name": tasks[idx - 1],
                }
            )
    else:
        selected = _slice(tasks, args.task_offset, args.task_count)
        if selected:
            start = max(0, int(args.task_offset))
            for i, env_name in enumerate(selected):
                selected_items.append(
                    {
                        "task_index_1based": start + i + 1,
                        "env_name": env_name,
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
        "task_total": len(tasks),
        "task_selected": len(selected_items),
        "task_list": effective_task_list if effective_task_list else None,
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
            task_index_1based = int(selected_item["task_index_1based"])
            run_items.append(
                _build_run_item(
                    index=i,
                    task_index_1based=task_index_1based,
                    env_name=env_name,
                    safe_env_name=_safe_name(env_name),
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
                        resume=args.resume,
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
                            resume=args.resume,
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
        if avg_score_rate is not None:
            logger.println(
                f"Dataset average score rate ({DATASET_NAME}): "
                f"{_fmt(avg_score_rate)} based on {manifest.get('scored_runs', 0)} scored runs"
            )
        else:
            logger.println(f"Dataset average score rate ({DATASET_NAME}): N/A (no scored runs)")

        _persist_manifest(batch_dir, manifest)
        logger.println(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0 if errs == 0 else 2
    finally:
        logger.close()


if __name__ == "__main__":
    raise SystemExit(main())
