#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Single-action native ScienceWorld tool implementation.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence



class ScienceworldTools:
    DATASET_KEY = "scienceworld"
    TOOL_PREFIX = "scienceworld"
    DEFAULT_ENV_STEP_LIMIT = 100
    DEFAULT_FULL_SCORE = 100.0

    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = os.path.abspath(workspace_root or os.getcwd())
        self._runtime_cache: Dict[str, Any] = {}
        self._active_session: Optional[Dict[str, Any]] = None
        self._fatal_cache: list = []
        self._fatal_cache_slug: str = ""
        self._fatal_cache_mtime: float = 0.0
        self._focus_cache: list = []
        self._focus_cache_slug: str = ""
        self._focus_cache_mtime: float = 0.0
        self._hint_already_injected = False
        self._wm_graph: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _extract_room(obs_text: str) -> str:
        """Extract the current room/location from a ScienceWorld observation.

        ScienceWorld observations typically begin with 'This is the <room>.' or
        contain 'You are in the <room>.' The room name appears on the first
        content line.
        """
        if not obs_text:
            return "unknown"
        for line in obs_text.strip().split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            lower = stripped.lower()
            # Common ScienceWorld room openers
            for pat in (
                r"^this is the (.+?)\.?\s*$",
                r"^you are in (?:the )?(.+?)\.?\s*$",
                r"^you are at (?:the )?(.+?)\.?\s*$",
            ):
                m = re.match(pat, lower)
                if m:
                    room = m.group(1).strip()
                    # Known room names
                    _ROOMS = {
                        "kitchen", "living room", "bedroom", "bathroom",
                        "workshop", "greenhouse", "art studio", "hallway",
                        "outside", "foundry",
                    }
                    if room in _ROOMS:
                        return room
                    # Fallback: return the match (may be "a room with...")
                    return room[:40]
            # ScienceWorld look-around output: first non-empty line IS the room
            if lower.startswith(("this is the ", "you are")):
                continue
            # Heuristic: if the line is short and looks like a place name
            if len(stripped) < 50 and not stripped.endswith(".") and " " not in stripped:
                return stripped.lower()
            break
        return "unknown"

    def _update_wm_graph(
        self,
        from_room: str,
        action: str,
        to_room: str,
        score_delta: float,
        result: str,
        admissible: Optional[List[str]] = None,
    ) -> None:
        """Update the in-memory world model graph with a new transition."""
        for room in (from_room, to_room):
            if room not in self._wm_graph:
                self._wm_graph[room] = {
                    "tried_actions": [],
                    "edges": [],
                    "admissible_seen": set(),
                    "visits": 0,
                    "best_score_here": 0.0,
                    "frontier": True,
                }
        node = self._wm_graph[from_room]
        node["visits"] += 1
        node["best_score_here"] = max(node["best_score_here"], score_delta + node.get("best_score_here", 0))
        action_lower = action.lower().strip()
        tried_entry = (action_lower, result)
        if tried_entry not in node["tried_actions"]:
            node["tried_actions"].append(tried_entry)
        edge = {
            "action": action_lower,
            "to": to_room,
            "result": result,
            "score_delta": score_delta,
        }
        edge_key = (action_lower, to_room, result)
        existing_keys = [(e["action"], e["to"], e["result"]) for e in node["edges"]]
        if edge_key not in existing_keys:
            node["edges"].append(edge)
        if admissible:
            node["admissible_seen"].update(c.lower().strip() for c in admissible)
        tried_set = {t[0] for t in node["tried_actions"]}
        node["untried"] = sorted(node["admissible_seen"] - tried_set)
        node["frontier"] = len(node["untried"]) > 0

    def query_wm(self, **_: Any) -> Dict[str, Any]:
        """Return the current world model graph as formatted text.

        Shows explored rooms, connections, score changes, and untried actions
        (frontier) per room.
        """
        if not self._wm_graph:
            return {
                "status": "success",
                "message": "World model graph is empty. No rooms explored yet.",
                "total_nodes": 0,
                "total_edges": 0,
            }
        lines = ["World Model Graph:", "=" * 50, ""]
        total_edges = 0
        sorted_rooms = sorted(
            self._wm_graph.items(),
            key=lambda x: x[1]["visits"],
            reverse=True,
        )
        frontier_rooms = []
        for room, data in sorted_rooms:
            total_edges += len(data["edges"])
            untried = data.get("untried", [])
            is_frontier = len(untried) > 0
            if is_frontier:
                frontier_rooms.append(room)
            frontier_tag = " [FRONTIER]" if is_frontier else ""
            lines.append(f"[{room}] (visits: {data['visits']}){frontier_tag}")
            if data["edges"]:
                lines.append("  Exits:")
                for e in data["edges"]:
                    score_tag = f" +{e['score_delta']:.0f}" if e["score_delta"] != 0 else ""
                    result_tag = f" ({e['result']})" if e["result"] != "moved" else ""
                    lines.append(f"    {e['action']} -> {e['to']}{score_tag}{result_tag}")
            if untried:
                lines.append(f"  Untried actions ({len(untried)}): {', '.join(untried[:10])}")
                if len(untried) > 10:
                    lines.append(f"    ... and {len(untried) - 10} more")
            else:
                lines.append("  Untried actions: none (fully explored)")
            lines.append("")
        return {
            "status": "success",
            "message": "\n".join(lines),
            "total_nodes": len(self._wm_graph),
            "total_edges": total_edges,
            "frontier_count": len(frontier_rooms),
        }

    def scienceworld_list_tasks(
        self,
        server_path: Optional[str] = None,
        env_step_limit: int = DEFAULT_ENV_STEP_LIMIT,
    ) -> Dict[str, Any]:
        runtime = self._ensure_runtime(server_path=server_path, env_step_limit=env_step_limit)
        if runtime["status"] != "success":
            return runtime

        tasks = list(runtime.get("tasks") or [])
        variation_counts = dict(runtime.get("variation_counts") or {})
        task_variations = [
            {
                "env_name": env_name,
                "variation_count": int(variation_counts.get(env_name, 1) or 1),
            }
            for env_name in tasks
        ]
        return {
            "status": "success",
            "dataset": self.DATASET_KEY,
            "tasks": tasks,
            "count": len(tasks),
            "task_variation_counts": variation_counts,
            "task_variations": task_variations,
            "server_path": runtime.get("server_path", ""),
        }

    def scienceworld_action(
        self,
        action: str,
        env_name: str = "",
        variation_num: int = 0,
        task_index: int = 0,
        simplification_str: str = "",
        env_step_limit: int = DEFAULT_ENV_STEP_LIMIT,
        generate_gold_path: bool = False,
        server_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        runtime = self._ensure_runtime(server_path=server_path, env_step_limit=env_step_limit)
        if runtime["status"] != "success":
            return runtime

        action_text = str(action).strip() if action is not None else ""
        if not action_text:
            return {"status": "error", "message": "action must be non-empty."}

        # Single-attempt per phase: if the session is already done, block further
        # actions so the agent wraps up with TASK_COMPLETED.
        if self._active_session is not None and self._active_session.get("done"):
            session = self._active_session
            return {
                "status": "error",
                "message": (
                    "The task has already ended (done=true). Restarting within a "
                    "phase is not supported. Please output TASK_COMPLETED to end "
                    "this attempt so the pipeline can start a fresh phase."
                ),
                "env_name": session["env_name"],
                "variation_num": session["variation_num"],
                "done": True,
                "won": bool((session.get("last_info") or {}).get("won", False)),
                "best_score": self._safe_number(session.get("best_score"), 0),
                "current_score": self._safe_number(session.get("current_score"), 0),
                "full_score": self._safe_number(session.get("full_score"), 0),
                "progress": self._safe_number(session.get("progress"), 0),
                "best_progress": self._safe_number(session.get("best_progress"), 0),
            }

        session_started = False
        if self._active_session is None:
            start_res = self._start_session(
                runtime=runtime,
                env_name=env_name,
                variation_num=variation_num,
                task_index=task_index,
                simplification_str=simplification_str,
                env_step_limit=env_step_limit,
                generate_gold_path=generate_gold_path,
            )
            if start_res.get("status") != "success":
                return start_res
            session_started = True
            self._hint_already_injected = False
            self._wm_graph = {}  # fresh graph per session

        session = self._active_session
        assert session is not None

        if env_name.strip() and env_name.strip() != session["env_name"]:
            return {
                "status": "error",
                "message": (
                    f"Active session env is {session['env_name']}, but received env_name={env_name}. "
                    "The game does not support restarting within a phase. Each phase is a single attempt."
                ),
                "active_env_name": session["env_name"],
            }
        if int(variation_num or 0) != int(session["variation_num"]):
            return {
                "status": "error",
                "message": (
                    f"Active session variation is {session['variation_num']}, but received "
                    f"variation_num={variation_num}. Each phase is a single attempt — no restart."
                ),
                "active_env_name": session["env_name"],
                "active_variation_num": session["variation_num"],
            }
        # Tool-level hard protection: FATAL interception + focus guard.
        # In ScienceWorld the dominant failure mode is `focus on X` where X is
        # wrong → instant -100 score. The guard checks `focus on` actions
        # against the known-correct focus target recorded in the knowledge file.
        # It also blocks confirmed-fatal actions tagged [FATAL:...].
        obs_before_fatal = session["last_observation"]
        current_room = self._extract_room(self._as_text(obs_before_fatal))
        guard_warning = self._check_focus_or_fatal_action(action_text, session)
        if guard_warning:
            return {
                "status": "success",
                "dataset": self.DATASET_KEY,
                "env_name": session["env_name"],
                "variation_num": session["variation_num"],
                "action": action_text,
                "message": guard_warning,
                "steps_taken": session["steps_taken"],
                "done": False,
                "won": False,
                "lost": False,
                "best_score": self._safe_number(session.get("best_score"), 0),
                "current_score": self._safe_number(session.get("current_score"), 0),
                "full_score": self._safe_number(session.get("full_score"), 0),
                "score_rate": 0.0,
                "progress": self._safe_number(session.get("progress"), 0),
                "best_progress": self._safe_number(session.get("best_progress"), 0),
                "observation_before": self._as_text(obs_before_fatal),
                "observation": self._as_text(obs_before_fatal),
                "feedback": f"WIKI GUARD: {guard_warning}",
                "look": "",
                "inventory": "",
                "valid_actions_count": 0,
                "admissible_commands": [],
                "parser_feedback": {},
                "stuck_state": {},
                "action_executed": False,
                "anti_loop_blocked": True,
            }
        obs_before = session["last_observation"]
        info_before = session.get("last_info") or {}
        guard_res = self._precheck_action_guard(session=session, action_text=action_text)
        if guard_res.get("blocked"):
            return self._build_guard_block_response(
                session=session,
                action_text=action_text,
                observation=obs_before,
                guard_res=guard_res,
            )

        try:
            step_out = session["env"].step(action_text)
        except Exception as e:
            return {
                "status": "error",
                "message": f"env.step failed: {e}",
                "env_name": session["env_name"],
                "variation_num": session["variation_num"],
                "memory_scope_key": session.get("memory_scope_key", ""),
                "action": action_text,
            }

        info: Dict[str, Any]
        if isinstance(step_out, tuple) and len(step_out) == 5:
            obs_after, reward, terminated, truncated, info = step_out
            done = bool(terminated or truncated)
        elif isinstance(step_out, tuple) and len(step_out) == 4:
            obs_after, reward, done, info = step_out
            done = bool(done)
        else:
            return {
                "status": "error",
                "message": f"Unexpected env.step return: {type(step_out).__name__}",
            }

        info = info or {}
        session["steps_taken"] += 1
        session["done"] = bool(done)
        session["last_action"] = action_text
        session["last_observation"] = obs_after
        session["last_info"] = info

        prev_best_score = self._safe_number(session.get("best_score"), 0)
        prev_best_progress = self._safe_number(session.get("best_progress"), session.get("progress", 0))
        prev_current_score = self._safe_number(session.get("current_score"), 0)
        prev_progress = self._safe_number(session.get("progress"), prev_current_score)

        current_score = self._safe_number(info.get("score"), prev_current_score)
        raw_full_score = self._safe_number(info.get("max_score"), session.get("full_score", self.DEFAULT_FULL_SCORE))
        full_score = max(self.DEFAULT_FULL_SCORE, raw_full_score, self._safe_number(session.get("full_score"), 0))
        progress = self._current_progress(
            env=session["env"],
            info=info,
            fallback=prev_progress,
            current_score=current_score,
            full_score=full_score,
        )
        best_score = max(prev_best_score, current_score)
        best_progress = max(prev_best_progress, progress)
        if progress > prev_best_progress:
            session["best_progress_step"] = session["steps_taken"]
            session["best_progress_action"] = action_text

        session["current_score"] = current_score
        session["best_score"] = best_score
        session["full_score"] = full_score
        session["progress"] = progress
        session["best_progress"] = best_progress

        valid_actions = self._extract_valid_actions(info)
        parser_feedback = self._classify_parser_feedback(
            action_text=action_text,
            observation_before=obs_before,
            observation_after=obs_after,
            info=info,
            current_score=current_score,
            prev_current_score=prev_current_score,
            valid_actions=valid_actions,
        )
        stuck_state = self._update_stuck_state(
            session=session,
            action_text=action_text,
            observation_after=obs_after,
            parser_feedback=parser_feedback,
            current_score=current_score,
            best_score=best_score,
            progress=progress,
            prev_current_score=prev_current_score,
            prev_best_score=prev_best_score,
            prev_progress=prev_progress,
        )
        score_rate = (best_score / full_score) if full_score > 0 else 0.0
        obs_text = self._as_text(obs_after)

        won = bool(
            info.get("won", False)
            or info.get("completed", False)
            or info.get("isCompleted", False)
            or progress >= 100.0
            or (full_score > 0 and current_score >= full_score)
        )

        # ── World model graph update ──
        from_room = self._extract_room(self._as_text(obs_before))
        to_room = self._extract_room(obs_text)
        if to_room == "unknown":
            to_room = from_room
        if from_room == "unknown":
            from_room = to_room
        score_delta = current_score - prev_current_score
        progress_delta = progress - prev_progress
        if done and not won:
            wm_result = "failed"
        elif score_delta > 0 or progress_delta > 0:
            wm_result = "progress"
        elif from_room != to_room:
            wm_result = "moved"
        elif obs_text.strip() == self._as_text(obs_before).strip():
            wm_result = "nochange"
        else:
            wm_result = "interact"
        self._update_wm_graph(
            from_room, action_text, to_room, score_delta, wm_result,
            admissible=valid_actions,
        )

        # Auto-inject wiki knowledge hint once per play session (first score gain)
        wiki_hint = ""
        if (score_delta > 0 or progress_delta > 0) and \
           str(os.environ.get("AGIA_ENABLE_AUTO_WIKI_HINT", "1")).strip().lower() in {"1", "true", "yes", "on"}:
            wiki_hint = self._auto_wiki_hint(obs_text, session)

        lost = bool(done and not won)
        trusted_state_snapshot = self._build_trusted_state_snapshot(
            session=session,
            action_text=action_text,
            observation_before=obs_before,
            observation_after=obs_after,
            current_score=current_score,
            best_score=best_score,
            full_score=full_score,
            score_rate=score_rate,
            progress=progress,
            best_progress=best_progress,
            reward=reward,
            done=bool(done),
            won=won,
        )

        session_closed = False
        close_note = ""
        if done:
            close_note = self._close_active_session()
            session_closed = True

        result = {
            "status": "success",
            "dataset": self.DATASET_KEY,
            "env_name": session["env_name"],
            "variation_num": session["variation_num"],
            "memory_scope_key": session.get("memory_scope_key", ""),
            "action": action_text,
            "session_started": session_started,
            "session_closed": session_closed,
            "message": "Action executed." + (f" {close_note}" if close_note else ""),
            "steps_taken": session["steps_taken"],
            "done": bool(done),
            "won": won,
            "lost": lost,
            "reward": reward,
            "best_score": best_score,
            "current_score": current_score,
            "full_score": full_score,
            "score_rate": score_rate,
            "progress": progress,
            "best_progress": best_progress,
            "best_progress_step": session.get("best_progress_step"),
            "best_progress_action": session.get("best_progress_action"),
            "task_description": session.get("task_description", ""),
            "memory_scope_key": session.get("memory_scope_key", ""),
            "simplification_str": session.get("simplification_str", ""),
            "env_step_limit": self._safe_int(
                session.get("env_step_limit"),
                self.DEFAULT_ENV_STEP_LIMIT,
            ),
            "generate_gold_path": bool(session.get("generate_gold_path", False)),
            "observation_before": self._as_text(obs_before),
            "observation": self._as_text(obs_after),
            "feedback": self._as_text(info.get("feedback", obs_after)) + self._loop_warning(session, action_text, self._as_text(obs_after)),
            "look": self._as_text(info.get("look", "")),
            "inventory": self._as_text(info.get("inv", "")),
            "valid_actions_count": len(valid_actions),
            "admissible_commands": valid_actions,
            "parser_feedback": parser_feedback,
            "stuck_state": stuck_state,
            "blocked_action_patterns": stuck_state.get("blocked_action_patterns", []),
            "anti_loop_guidance": stuck_state.get("guidance", ""),
            "action_executed": True,
            "anti_loop_blocked": False,
            "must_do_action": "",
            "trusted_state_snapshot": trusted_state_snapshot,
            "trusted_state_json": json.dumps(
                trusted_state_snapshot,
                ensure_ascii=False,
                sort_keys=True,
            ),
        }
        if wiki_hint:
            result["wiki_hint"] = wiki_hint
        return result

    def _start_session(
        self,
        runtime: Dict[str, Any],
        env_name: str,
        variation_num: int,
        task_index: int,
        simplification_str: str,
        env_step_limit: int,
        generate_gold_path: bool,
    ) -> Dict[str, Any]:
        tasks = list(runtime.get("tasks") or [])
        if not tasks:
            return {"status": "error", "message": f"No tasks for dataset {self.DATASET_KEY}."}

        selected = (env_name or "").strip()
        if selected:
            if selected not in tasks:
                return {
                    "status": "error",
                    "message": f"Unknown env_name: {selected}",
                    "available_tasks": tasks,
                }
        else:
            idx = int(task_index)
            if idx < 0 or idx >= len(tasks):
                return {
                    "status": "error",
                    "message": f"task_index out of range: {idx}",
                    "task_count": len(tasks),
                }
            selected = tasks[idx]

        variation_counts = dict(runtime.get("variation_counts") or {})
        max_variations = max(1, self._safe_int(variation_counts.get(selected), 1))
        if int(variation_num) < 0 or int(variation_num) >= max_variations:
            return {
                "status": "error",
                "message": (
                    f"variation_num out of range for {selected}: {variation_num}. "
                    f"Expected 0 <= variation_num < {max_variations}."
                ),
                "env_name": selected,
                "variation_count": max_variations,
            }

        env_step_limit = max(1, self._safe_int(env_step_limit, self.DEFAULT_ENV_STEP_LIMIT))
        scienceworld_env = runtime["ScienceWorldEnv"]
        try:
            env = scienceworld_env(
                taskName=selected,
                serverPath=runtime.get("server_path") or None,
                envStepLimit=env_step_limit,
            )
        except TypeError:
            try:
                env = scienceworld_env(
                    serverPath=runtime.get("server_path") or None,
                    envStepLimit=env_step_limit,
                )
            except Exception as e:
                return {"status": "error", "message": f"Failed to initialize ScienceWorldEnv: {e}"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to initialize ScienceWorldEnv: {e}"}

        try:
            self._call_method(
                env,
                ["load", "Load", "loadTask"],
                selected,
                int(variation_num),
                str(simplification_str or ""),
                bool(generate_gold_path),
            )
            reset_out = self._call_method(env, ["reset", "Reset"], default=None)
            if isinstance(reset_out, tuple) and len(reset_out) == 2:
                obs, info = reset_out
            else:
                obs, info = reset_out, {}
        except Exception as e:
            try:
                env.close()
            except Exception:
                pass
            return {
                "status": "error",
                "message": (
                    f"Failed to start env {selected} variation {variation_num}: {e}"
                ),
            }

        info = info or {}
        current_score = self._safe_number(info.get("score"), 0)
        full_score = max(
            self.DEFAULT_FULL_SCORE,
            self._safe_number(info.get("max_score"), self.DEFAULT_FULL_SCORE),
        )
        progress = self._current_progress(
            env=env,
            info=info,
            fallback=0.0,
            current_score=current_score,
            full_score=full_score,
        )
        task_description = self._as_text(
            info.get("taskDesc")
            or self._call_method(
                env,
                ["get_task_description", "getTaskDescription", "taskdescription"],
                default="",
            )
        )

        self._active_session = {
            "created_at": time.time(),
            "dataset": self.DATASET_KEY,
            "env_name": selected,
            "variation_num": int(variation_num),
            "memory_scope_key": selected,
            "env": env,
            "steps_taken": 0,
            "done": False,
            "last_action": None,
            "last_observation": obs,
            "last_info": info,
            "current_score": current_score,
            "best_score": current_score,
            "full_score": full_score,
            "progress": progress,
            "best_progress": progress,
            "best_progress_step": 0,
            "best_progress_action": None,
            "task_description": task_description,
            "simplification_str": str(simplification_str or ""),
            "env_step_limit": env_step_limit,
            "generate_gold_path": bool(generate_gold_path),
            "anti_loop": {
                "last_state_key": "",
                "last_action_key": "",
                "last_action_family": "",
                "same_state_count": 0,
                "same_action_count": 0,
                "same_action_family_count": 0,
                "no_progress_count": 0,
                "low_information_action_count": 0,
                "guard_block_count": 0,
                "last_stuck_state": {},
            },
            "_recent_actions": [],
        }
        return {"status": "success"}

    def _close_active_session(self) -> str:
        if self._active_session is None:
            return ""
        msg = "Episode closed."
        try:
            self._active_session["env"].close()
        except Exception as e:
            msg = f"Episode closed with env.close error: {e}"
        self._active_session = None
        return msg

    def _check_focus_or_fatal_action(self, action: str, session: Dict[str, Any]) -> str:
        """Hard protection for ScienceWorld.

        Two interception modes:

        1. FOCUS GUARD (primary): ScienceWorld's dominant failure mode is
           `focus on X` where X is wrong → instant -100 score. The knowledge
           file records the verified-correct focus target with
           [FOCUS:correct_target] tags. When the agent issues `focus on Y`:
             - If Y matches a known-correct target → allow.
             - If Y does NOT match any known-correct target AND at least one
               correct target exists → BLOCK, because wrong focus is -100.

        2. FATAL INTERCEPTION (secondary): blocks actions tagged [FATAL:...]
           in the knowledge file (e.g. drinking mercury, connecting to power
           without protection). Same logic as Jericho but adapted for
           ScienceWorld room extraction.

        Returns a warning message if blocked, empty string otherwise.
        """
        if not action:
            return ""
        action_lower = action.lower().strip()

        try:
            wiki_root = os.environ.get("AGIA_WIKI_ROOT", "").strip()
            if not wiki_root or not os.path.isdir(wiki_root):
                return ""
            ablation = os.environ.get("AGIA_WIKI_ABLATION", "").strip().lower()
            if ablation in ("no_wiki", "no_knowledge"):
                return ""

            task_slug = self._active_task_slug()
            if not task_slug:
                return ""

            kf_path = os.path.join(wiki_root, "knowledge", f"score_recipe_{task_slug}.md")
            if not os.path.isfile(kf_path):
                return ""

            mtime = os.path.getmtime(kf_path)
            cache_stale = (
                self._fatal_cache_slug != task_slug
                or self._focus_cache_slug != task_slug
                or self._fatal_cache_mtime != mtime
                or self._focus_cache_mtime != mtime
            )
            if cache_stale:
                content = open(kf_path, encoding="utf-8").read().lower()
                self._parse_knowledge_tags(content, task_slug, mtime)

            # ── 1. FOCUS GUARD ──
            # Only intercept `focus on X` actions
            focus_match = re.match(r"^focus on\s+(.+)$", action_lower)
            if focus_match and self._focus_cache:
                focus_target = focus_match.group(1).strip()
                # Check if the focus target matches any known-correct target
                for correct_target in self._focus_cache:
                    # Exact or substring match (both directions)
                    if (correct_target in focus_target
                            or focus_target in correct_target
                            or correct_target == focus_target):
                        return ""  # Allowed — matches a known-correct target

                # No match found — this focus target is NOT verified
                # Extract the task description for a helpful warning
                task_desc = str((session.get("task_description") or "")).strip()
                correct_str = ", ".join(self._focus_cache[:3])
                # Check admissible_commands for valid focus options
                adm = session.get("last_info", {}).get("admissible_commands") or []
                focus_options = [c for c in adm if c.lower().startswith("focus on ")]
                hint = ""
                if focus_options:
                    hint = f" Valid focus options from admissible_commands: {', '.join(focus_options[:5])}."
                return (
                    f"BLOCKED FOCUS: '{action}' — the target '{focus_target}' is NOT a verified "
                    f"correct focus target. Known-correct focus targets: [{correct_str}]."
                    f"{hint} Focus on the EXACT target substance from the task description, "
                    f"not a container (cup/pot/jug) or state variant. Wrong focus causes -100."
                )

            # ── 2. FATAL INTERCEPTION ──
            current_room = self._extract_room(self._as_text(session.get("last_observation", "")))
            room_lower = (current_room or "").lower().strip()
            _NAV_WORDS = {"go to", "go", "move", "walk", "north", "south", "east",
                          "west", "up", "down", "teleport"}
            for core_cmd, fatal_room in self._fatal_cache:
                keywords = [k.strip() for k in core_cmd.split(",") if k.strip()]
                if not any(k in action_lower for k in keywords):
                    continue
                if fatal_room and room_lower:
                    room_words = [w for w in re.split(r"[\s,()]+", fatal_room) if len(w) > 3]
                    if room_words and not any(rw in room_lower for rw in room_words):
                        continue
                elif fatal_room and not room_lower:
                    if any(k.strip() in _NAV_WORDS for k in keywords):
                        continue
                return f"BLOCKED: '{action}' is marked [FATAL] in knowledge. Choose a different action."
        except Exception:
            pass
        return ""

    def _parse_knowledge_tags(self, content: str, task_slug: str, mtime: float) -> None:
        """Parse [FOCUS:...] and [FATAL:...] tags from the knowledge file content.

        Populates self._focus_cache and self._fatal_cache.
        """
        fatal_entries: list = []
        focus_entries: list = []
        in_focus_section = False
        in_death_section = False

        for line in content.split("\n"):
            line_s = line.strip()

            # FOCUS target: [FOCUS:target_name]
            focus_match = re.search(r"\[focus:(.+?)\]", line_s)
            if focus_match:
                target = focus_match.group(1).strip()
                if target and target not in focus_entries:
                    focus_entries.append(target)

            # Track sections for fallback parsing
            if line_s.startswith("## "):
                section_lower = line_s.lower()
                in_focus_section = "focus" in section_lower
                in_death_section = "death" in section_lower or "fatal" in section_lower
                continue

            # FATAL: [FATAL:command words] (Room) description
            tag_match = re.search(r"\[fatal:(.+?)\]", line_s)
            if tag_match:
                core_cmd = tag_match.group(1).strip()
                room = ""
                room_match = re.search(r"\(([^)]+)\)", line_s)
                if room_match:
                    room = room_match.group(1).strip()
                if (not room or "anywhere" in room or room.startswith("any")
                        or "unknown" in room or "unspecified" in room):
                    room = ""
                fatal_entries.append((core_cmd, room))
                continue

            # Fallback: focus target in focus section
            if in_focus_section and (line_s.startswith("- ") or line_s.startswith("* ")):
                target_text = line_s.lstrip("-* ").strip()
                # Extract the substance name (may have extra description after dash)
                target = re.split(r"\s*[-—–]\s*", target_text, maxsplit=1)[0].strip()
                # Remove parenthetical notes
                target = re.sub(r"\([^)]*\)", "", target).strip()
                if target and target not in focus_entries and len(target) < 60:
                    focus_entries.append(target.lower())

            # Fallback: fatal in death section without explicit tag
            if "[fatal]" in line_s:
                after = line_s.split("[fatal]", 1)[1].strip()
            elif in_death_section and (line_s.startswith("- ") or line_s.startswith("* ")):
                after = line_s.lstrip("-* ").strip()
            else:
                continue
            if after:
                desc_split = re.split(r"[-—–]\s*", after, maxsplit=1)
                cmd_and_room = desc_split[0].strip()
                room = ""
                cmd = cmd_and_room
                paren_match = re.match(r"\((.+?)\)\s*(.+)", cmd_and_room)
                if paren_match:
                    room = paren_match.group(1).strip()
                    cmd = paren_match.group(2).strip()
                cmd_words = [w for w in cmd.split() if w not in ("the", "a", "an", "go")]
                if cmd_words:
                    core_cmd = " ".join(cmd_words[:3])
                    if "anywhere" in after.lower():
                        room = ""
                    fatal_entries.append((core_cmd, room))

        self._fatal_cache = fatal_entries
        self._fatal_cache_slug = task_slug
        self._fatal_cache_mtime = mtime
        self._focus_cache = focus_entries
        self._focus_cache_slug = task_slug
        self._focus_cache_mtime = mtime

    def _active_task_slug(self) -> str:
        """Derive the task slug for wiki file naming.

        ScienceWorld task names are already clean slugs (e.g. 'boil', 'melt').
        We read from SCIENCEWORLD_ACTIVE_ENV first, then fall back to
        JERICHO_ACTIVE_ENV (set by the runner for wiki_memory.py compatibility).
        """
        env = os.environ.get("SCIENCEWORLD_ACTIVE_ENV", "").strip()
        if not env:
            env = os.environ.get("JERICHO_ACTIVE_ENV", "").strip()
        if not env:
            return ""
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", env).strip("_").lower()
        # Strip common prefixes
        for prefix in ("jerichoenv", "scienceworld_"):
            if slug.startswith(prefix):
                slug = slug[len(prefix):]
        return slug or re.sub(r"[^a-zA-Z0-9]+", "_", env).strip("_").lower()

    def _auto_wiki_hint(self, observation: str, session: Dict[str, Any]) -> str:
        """Auto-inject the full knowledge recipe ONCE per play session.

        Fires on the first score/progress increase, then never again.
        Returns the complete knowledge file so the agent has the full picture
        without repeated fragment injections.
        """
        if not observation or len(observation.strip()) < 10:
            return ""
        if getattr(self, "_hint_already_injected", False):
            return ""

        try:
            from src.wiki_memory import WikiMemoryReader
            reader = WikiMemoryReader(workspace_root=self.workspace_root)

            task_slug = self._active_task_slug()
            query = task_slug or observation[:100]

            result = reader.wiki_memory_read(query=query[:200], section="knowledge", max_results=1, _bypass_count=True)
            matches = result.get("matches") or []
            if not matches:
                return ""

            page_path = matches[0].get("page", "")
            wiki_root = result.get("wiki_root") or os.environ.get("AGIA_WIKI_ROOT", "")
            full_path = os.path.join(wiki_root, page_path)
            try:
                content = open(full_path, encoding="utf-8").read().strip()
            except (OSError, IOError):
                content = matches[0].get("content", "")

            if not content:
                return ""

            self._hint_already_injected = True
            return f"[Wiki Knowledge Recipe]\n{content}"
        except Exception:
            pass
        return ""

    def _loop_warning(self, session: Dict[str, Any], action_text: str, obs_text: str = "") -> str:
        recent = session.setdefault("_recent_actions", [])
        _obs_lines = obs_text.strip().split("\n") if obs_text else []
        _room_sig = (_obs_lines[0].strip()[:50] if _obs_lines else "") or "unknown"
        recent.append(f"{action_text.lower().strip()}@{_room_sig}")
        if len(recent) > 10:
            recent.pop(0)
        if len(recent) >= 5:
            from collections import Counter
            pair_counts = Counter(recent)
            top_pair, top_count = pair_counts.most_common(1)[0]
            if top_count >= 5:
                top_action = top_pair.split("@", 1)[0]
                tried = {p.split("@", 1)[0] for p in recent}
                adm = (session.get("last_info") or {}).get("admissible_commands") or []
                untried = [c for c in adm if c.lower().strip() not in tried]
                hint_extra = ""
                if untried:
                    hint_extra = f" Try one of these instead: {', '.join(untried[:5])}."
                else:
                    hint_extra = " You have exhausted known actions here. Go to a DIFFERENT room or examine objects you haven't checked."
                return (
                    f"\n⚠ LOOP DETECTED: '{top_action}' repeated {top_count}x in {_room_sig} with no score gain."
                    f" This action is NOT working.{hint_extra}"
                )
        return ""

    def _ensure_runtime(self, server_path: Optional[str], env_step_limit: int) -> Dict[str, Any]:
        cache_key = os.path.abspath(server_path) if server_path else "__default__"
        cached = self._runtime_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            from scienceworld import ScienceWorldEnv
        except Exception as e:
            return {
                "status": "error",
                "message": (
                    "Failed to import native ScienceWorld runtime. "
                    "Install the official `scienceworld` package and ensure Java is available. "
                    f"Import error: {e}"
                ),
            }

        probe_env = None
        try:
            probe_env = ScienceWorldEnv(
                serverPath=server_path or None,
                envStepLimit=max(1, self._safe_int(env_step_limit, self.DEFAULT_ENV_STEP_LIMIT)),
            )
            tasks = list(
                self._call_method(
                    probe_env,
                    ["get_task_names", "getTaskNames"],
                    default=[],
                )
                or []
            )
            tasks = sorted(str(item).strip() for item in tasks if str(item).strip())
            variation_counts: Dict[str, int] = {}
            for task_name in tasks:
                count = self._safe_int(
                    self._call_method(
                        probe_env,
                        ["get_max_variations", "getMaxVariations"],
                        task_name,
                        default=1,
                    ),
                    1,
                )
                variation_counts[task_name] = max(1, count)
        except Exception as e:
            if probe_env is not None:
                try:
                    probe_env.close()
                except Exception:
                    pass
            return {
                "status": "error",
                "message": f"Failed to initialize ScienceWorld runtime: {e}",
                "server_path": server_path or "",
            }
        finally:
            if probe_env is not None:
                try:
                    probe_env.close()
                except Exception:
                    pass

        runtime = {
            "status": "success",
            "ScienceWorldEnv": ScienceWorldEnv,
            "tasks": tasks,
            "variation_counts": variation_counts,
            "server_path": server_path or "",
        }
        self._runtime_cache[cache_key] = runtime
        return runtime

    def _build_trusted_state_snapshot(
        self,
        session: Dict[str, Any],
        action_text: str,
        observation_before: Any,
        observation_after: Any,
        current_score: float,
        best_score: float,
        full_score: float,
        score_rate: float,
        progress: float,
        best_progress: float,
        reward: Any,
        done: bool,
        won: bool,
    ) -> Dict[str, Any]:
        observation_before_text = self._as_text(observation_before)
        observation_after_text = self._as_text(observation_after)
        return {
            "snapshot_type": "scienceworld_runtime_state",
            "snapshot_scope": "single_verified_tool_result",
            "env_name": str(session.get("env_name") or ""),
            "variation_num": self._safe_int(session.get("variation_num"), 0),
            "memory_scope_key": str(session.get("memory_scope_key") or ""),
            "action": str(action_text or ""),
            "steps_taken": self._safe_int(session.get("steps_taken"), 0),
            "current_score": self._safe_number(current_score, 0),
            "best_score": self._safe_number(best_score, 0),
            "full_score": self._safe_number(full_score, self.DEFAULT_FULL_SCORE),
            "score_rate": round(float(score_rate or 0.0), 6),
            "progress": self._safe_number(progress, 0),
            "best_progress": self._safe_number(best_progress, progress),
            "best_progress_step": session.get("best_progress_step"),
            "best_progress_action": session.get("best_progress_action"),
            "reward": self._safe_number(reward, 0),
            "done": bool(done),
            "won": bool(won),
            "simplification_str": str(session.get("simplification_str") or ""),
            "observation_title": self._extract_observation_title(observation_after_text),
            "observation_excerpt": self._truncate_text(observation_after_text, 280),
            "observation_before_excerpt": self._truncate_text(observation_before_text, 180),
        }

    def _classify_parser_feedback(
        self,
        action_text: str,
        observation_before: Any,
        observation_after: Any,
        info: Dict[str, Any],
        current_score: float,
        prev_current_score: float,
        valid_actions: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        before_text = self._as_text(observation_before)
        after_text = self._as_text(info.get("feedback", observation_after))
        lowered = after_text.lower()
        same_state = self._state_key(before_text) == self._state_key(after_text)

        category = "not_detected"
        confidence = 0.0
        matched_text = ""
        local_repair_focus = ""
        suggested_actions: List[str] = list(valid_actions or [])[:3]

        patterns = [
            (
                "syntax_rejected",
                0.95,
                [
                    "i don't understand",
                    "i dont understand",
                    "not a valid action",
                    "unknown action",
                    "no known action matches that input",
                    "not sure what you mean",
                ],
                "Stay on the same local goal and try 1-3 simpler command variants.",
            ),
            (
                "precondition_blocked",
                0.85,
                [
                    "you can't",
                    "you cannot",
                    "can't do that",
                    "cannot do that",
                    "can't reach",
                    "cannot reach",
                    "there is no",
                    "you do not see",
                    "not carrying",
                    "isn't open",
                    "is not open",
                    "is closed",
                ],
                "Stay local, inspect prerequisites, and try a nearby repair action.",
            ),
            (
                "no_effect_or_repeat",
                0.75,
                [
                    "nothing happens",
                    "already",
                    "no effect",
                    "doesn't change anything",
                    "does not change anything",
                ],
                "State appears unchanged. Stop repeating the same action chain and switch to a nearby alternative.",
            ),
        ]
        for detected_category, detected_confidence, phrases, detected_focus in patterns:
            for phrase in phrases:
                if phrase in lowered:
                    category = detected_category
                    confidence = detected_confidence
                    matched_text = phrase
                    local_repair_focus = detected_focus
                    break
            if category != "not_detected":
                break

        if category == "not_detected" and same_state and abs(current_score - prev_current_score) < 1e-6:
            category = "no_effect_or_repeat"
            confidence = 0.6
            matched_text = "unchanged_state"
            local_repair_focus = (
                "Observation and score did not change. Do not force the same exact action chain repeatedly."
            )

        if not suggested_actions and action_text.strip():
            action_family = self._action_family(action_text)
            if action_family == "movement":
                suggested_actions = ["look around", "examine surroundings", "help"]
            elif action_family in {"look", "inventory", "examine"}:
                suggested_actions = ["help"]

        if category == "syntax_rejected":
            open_candidates = [action for action in (valid_actions or []) if str(action).strip().lower().startswith("open ")]
            if open_candidates:
                suggested_actions = open_candidates[:3]
        elif category == "precondition_blocked" and ("isn't open" in lowered or "is not open" in lowered or "is closed" in lowered):
            open_candidates = [action for action in (valid_actions or []) if str(action).strip().lower().startswith("open ")]
            if open_candidates:
                suggested_actions = open_candidates[:3]
            local_repair_focus = (
                "A prerequisite door/container/apparatus is closed. Stay local, open the relevant object first, "
                "then retry the blocked manipulation."
            )

        return {
            "is_parser_issue": category != "not_detected",
            "category": category,
            "confidence": confidence,
            "matched_text": matched_text,
            "observation_unchanged": same_state,
            "local_repair_focus": local_repair_focus,
            "suggested_actions": suggested_actions[:3],
            "retry_policy": (
                "If this category repeats for the same local goal, stay local and try at most 3 nearby "
                "variants or prerequisite repairs. If all fail, stop forcing the same command chain and "
                "switch to another local path."
            ),
        }

    def _update_stuck_state(
        self,
        session: Dict[str, Any],
        action_text: str,
        observation_after: Any,
        parser_feedback: Dict[str, Any],
        current_score: float,
        best_score: float,
        progress: float,
        prev_current_score: float,
        prev_best_score: float,
        prev_progress: float,
    ) -> Dict[str, Any]:
        anti_loop = session.setdefault("anti_loop", {})
        state_key = self._state_key(observation_after)
        action_key = self._normalize_action(action_text)
        action_family = self._action_family(action_text)
        same_state = bool(state_key and state_key == anti_loop.get("last_state_key"))
        same_state_count = int(anti_loop.get("same_state_count", 0)) + 1 if same_state else 1
        same_action_count = (
            int(anti_loop.get("same_action_count", 0)) + 1
            if same_state and action_key and action_key == anti_loop.get("last_action_key")
            else 1
        )
        same_action_family_count = (
            int(anti_loop.get("same_action_family_count", 0)) + 1
            if same_state and action_family and action_family == anti_loop.get("last_action_family")
            else 1
        )
        no_progress = (
            abs(current_score - prev_current_score) < 1e-6
            and abs(best_score - prev_best_score) < 1e-6
            and abs(progress - prev_progress) < 1e-6
        )
        no_progress_count = int(anti_loop.get("no_progress_count", 0)) + 1 if no_progress else 0
        is_low_information_action = self._is_low_information_action(action_text)
        low_information_action_count = (
            int(anti_loop.get("low_information_action_count", 0)) + 1
            if same_state and is_low_information_action
            else (1 if is_low_information_action else 0)
        )

        anti_loop.update(
            {
                "last_state_key": state_key,
                "last_action_key": action_key,
                "last_action_family": action_family,
                "same_state_count": same_state_count,
                "same_action_count": same_action_count,
                "same_action_family_count": same_action_family_count,
                "no_progress_count": no_progress_count,
                "low_information_action_count": low_information_action_count,
            }
        )

        blocked_action_patterns: List[str] = []
        if same_action_count >= 2 and action_text.strip():
            blocked_action_patterns.append(action_text.strip())
        if same_action_family_count >= 3 and action_family in {"movement", "look", "inventory", "examine", "help"}:
            blocked_action_patterns.append(action_family)
        if low_information_action_count >= 2 and action_family in {"look", "inventory", "examine", "help"}:
            blocked_action_patterns.append(action_family)
        blocked_action_patterns = list(dict.fromkeys(item for item in blocked_action_patterns if item))

        recommended_policy = "continue"
        reason = "No strong loop pattern detected"
        guidance = "No strong loop signal detected. Continue, but avoid repeating low-information actions in the same unchanged state."
        is_stuck = False
        severity = "none"

        if parser_feedback.get("is_parser_issue") and same_action_count >= 2:
            is_stuck = True
            severity = "medium"
            recommended_policy = "switch_local_goal"
            reason = "Repeated parser/precondition issue for the same action in the same state"
            guidance = (
                "The same action is repeatedly failing in the same state. Stop retrying it and change to a nearby "
                "alternative local goal or prerequisite."
            )
        elif same_action_family_count >= 3 and same_state_count >= 3:
            is_stuck = True
            severity = "medium"
            recommended_policy = "switch_local_goal"
            reason = "Repeated local action family without state change"
            guidance = (
                "Several nearby actions from the same family were attempted without changing state. Switch branch "
                "or inspect a different local object."
            )
        elif no_progress_count >= 4 and same_state_count >= 3:
            is_stuck = True
            severity = "high"
            recommended_policy = "switch_local_goal"
            reason = "No score or progress change across repeated unchanged states"
            guidance = (
                "Local play has stalled. Re-anchor on the current observation, avoid blocked patterns, and pursue "
                "a different local hypothesis."
            )
        elif parser_feedback.get("is_parser_issue"):
            recommended_policy = "local_retry_only"
            reason = "Parser or precondition issue detected"
            guidance = (
                "Stay on the same local goal and try at most 1-3 nearby repairs before abandoning this command chain."
            )

        stuck_state = {
            "is_stuck": is_stuck,
            "severity": severity,
            "same_state_count": same_state_count,
            "same_action_count": same_action_count,
            "same_action_family_count": same_action_family_count,
            "no_progress_count": no_progress_count,
            "low_information_action_count": low_information_action_count,
            "blocked_action_patterns": blocked_action_patterns,
            "recommended_policy": recommended_policy,
            "recommended_restore_step": None,
            "reason": reason,
            "guidance": guidance,
        }
        anti_loop["last_stuck_state"] = stuck_state
        return stuck_state

    def _precheck_action_guard(self, session: Dict[str, Any], action_text: str) -> Dict[str, Any]:
        anti_loop = session.get("anti_loop") or {}
        last_stuck_state = anti_loop.get("last_stuck_state") or {}
        blocked_patterns = list(last_stuck_state.get("blocked_action_patterns") or [])
        action_family = self._action_family(action_text)
        action_norm = self._normalize_action(action_text)
        for pattern in blocked_patterns:
            if not pattern:
                continue
            if action_text.strip() == pattern or action_norm == self._normalize_action(pattern) or action_family == pattern:
                return {
                    "blocked": True,
                    "reason": "This action matches blocked_action_patterns in the same unchanged state.",
                    "blocked_action_patterns": blocked_patterns,
                    "must_do_action": "",
                    "same_action_count": int(anti_loop.get("same_action_count", 0)),
                    "same_action_family_count": int(anti_loop.get("same_action_family_count", 0)),
                    "low_information_action_count": int(anti_loop.get("low_information_action_count", 0)),
                    "parser_category": "anti_loop_blocked",
                    "recommended_policy": str(last_stuck_state.get("recommended_policy") or "switch_local_goal"),
                }
        return {"blocked": False}

    def _build_guard_block_response(
        self,
        session: Dict[str, Any],
        action_text: str,
        observation: Any,
        guard_res: Dict[str, Any],
    ) -> Dict[str, Any]:
        progress = self._safe_number(session.get("progress"), session.get("current_score", 0))
        best_progress = self._safe_number(session.get("best_progress"), progress)
        current_score = self._safe_number(session.get("current_score"), 0)
        best_score = self._safe_number(session.get("best_score"), current_score)
        full_score = self._safe_number(session.get("full_score"), self.DEFAULT_FULL_SCORE)
        score_rate = (best_score / full_score) if full_score > 0 else 0.0
        stuck_state = dict(session.get("anti_loop", {}).get("last_stuck_state") or {})
        if not stuck_state:
            stuck_state = {
                "is_stuck": True,
                "severity": "medium",
                "same_state_count": 0,
                "same_action_count": self._safe_int(guard_res.get("same_action_count"), 0),
                "same_action_family_count": self._safe_int(guard_res.get("same_action_family_count"), 0),
                "no_progress_count": 0,
                "low_information_action_count": self._safe_int(guard_res.get("low_information_action_count"), 0),
                "blocked_action_patterns": guard_res.get("blocked_action_patterns", []),
                "recommended_policy": guard_res.get("recommended_policy", "switch_local_goal"),
                "recommended_restore_step": None,
                "reason": guard_res.get("reason", "Blocked by anti-loop guard."),
                "guidance": (
                    "Do not repeat the blocked action in the same unchanged state. Choose a different nearby "
                    "local action or inspect another object."
                ),
            }
        trusted_state_snapshot = self._build_trusted_state_snapshot(
            session=session,
            action_text=action_text,
            observation_before=observation,
            observation_after=observation,
            current_score=current_score,
            best_score=best_score,
            full_score=full_score,
            score_rate=score_rate,
            progress=progress,
            best_progress=best_progress,
            reward=0,
            done=bool(session.get("done", False)),
            won=False,
        )
        trusted_state_snapshot["anti_loop_blocked"] = True
        parser_feedback = {
            "is_parser_issue": True,
            "category": str(guard_res.get("parser_category") or "anti_loop_blocked"),
            "confidence": 1.0,
            "matched_text": "",
            "observation_unchanged": True,
            "local_repair_focus": guard_res.get("reason", ""),
            "suggested_actions": [],
            "retry_policy": (
                "The blocked action was not executed. Change branch instead of retrying the same action in the same state."
            ),
        }
        return {
            "status": "success",
            "dataset": self.DATASET_KEY,
            "env_name": session["env_name"],
            "variation_num": session["variation_num"],
            "memory_scope_key": session.get("memory_scope_key", ""),
            "action": action_text,
            "session_started": False,
            "session_closed": False,
            "message": guard_res.get("reason", "Action blocked by anti-loop guard."),
            "steps_taken": session["steps_taken"],
            "done": bool(session.get("done", False)),
            "won": False,
            "lost": False,
            "reward": 0,
            "best_score": best_score,
            "current_score": current_score,
            "full_score": full_score,
            "score_rate": score_rate,
            "progress": progress,
            "best_progress": best_progress,
            "best_progress_step": session.get("best_progress_step"),
            "best_progress_action": session.get("best_progress_action"),
            "task_description": session.get("task_description", ""),
            "memory_scope_key": session.get("memory_scope_key", ""),
            "simplification_str": session.get("simplification_str", ""),
            "env_step_limit": self._safe_int(session.get("env_step_limit"), self.DEFAULT_ENV_STEP_LIMIT),
            "generate_gold_path": bool(session.get("generate_gold_path", False)),
            "observation_before": self._as_text(observation),
            "observation": self._as_text(observation),
            "feedback": self._as_text(observation),
            "look": self._as_text((session.get("last_info") or {}).get("look", "")),
            "inventory": self._as_text((session.get("last_info") or {}).get("inv", "")),
            "valid_actions_count": len(self._extract_valid_actions(session.get("last_info") or {})),
            "admissible_commands": self._extract_valid_actions(session.get("last_info") or {}),
            "parser_feedback": parser_feedback,
            "stuck_state": stuck_state,
            "blocked_action_patterns": stuck_state.get("blocked_action_patterns", []),
            "anti_loop_guidance": stuck_state.get("guidance", ""),
            "action_executed": False,
            "anti_loop_blocked": True,
            "must_do_action": str(guard_res.get("must_do_action") or ""),
            "trusted_state_snapshot": trusted_state_snapshot,
            "trusted_state_json": json.dumps(
                trusted_state_snapshot,
                ensure_ascii=False,
                sort_keys=True,
            ),
        }

    def _score_based_progress(self, current_score: float, full_score: float) -> float:
        current = max(0.0, self._safe_number(current_score, 0.0))
        full = max(0.0, self._safe_number(full_score, self.DEFAULT_FULL_SCORE))
        if full <= 0:
            return current
        return round(min(100.0, (current / full) * 100.0), 4)

    def _current_progress(
        self,
        env: Any,
        info: Dict[str, Any],
        fallback: float,
        current_score: float = 0.0,
        full_score: float = DEFAULT_FULL_SCORE,
    ) -> float:
        direct_candidates = [
            info.get("progress"),
            info.get("goal_progress"),
            info.get("goalProgress"),
            info.get("completion"),
            info.get("completion_pct"),
            info.get("completionPercent"),
        ]
        score_progress = self._score_based_progress(current_score=current_score, full_score=full_score)
        fallback_progress = max(self._safe_number(fallback, 0.0), score_progress)
        for candidate in direct_candidates:
            numeric = self._extract_progress_value(candidate)
            if numeric is not None:
                return max(numeric, fallback_progress)
        env_candidate = self._call_method(env, ["get_goal_progress", "getGoalProgress"], default=None)
        numeric = self._extract_progress_value(env_candidate)
        if numeric is not None:
            return max(numeric, fallback_progress)
        return fallback_progress

    def _extract_progress_value(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, bool):
            return 100.0 if value else 0.0
        if isinstance(value, (int, float)):
            numeric = float(value)
            if 0.0 <= numeric <= 1.0:
                return round(numeric * 100.0, 4)
            return round(numeric, 4)
        if isinstance(value, dict):
            for key in (
                "progress",
                "completion",
                "score",
                "percent",
                "percentage",
                "normalized_score",
                "normalizedScore",
            ):
                if key in value:
                    numeric = self._extract_progress_value(value.get(key))
                    if numeric is not None:
                        return numeric
            if value:
                candidates: List[float] = []
                for item in value.values():
                    numeric = self._extract_progress_value(item)
                    if numeric is not None:
                        candidates.append(numeric)
                if candidates:
                    return max(candidates)
            return None
        if isinstance(value, (list, tuple)):
            if not value:
                return None
            if all(isinstance(item, bool) for item in value):
                return round(sum(1 for item in value if item) / len(value) * 100.0, 4)
            candidates = [
                numeric
                for numeric in (self._extract_progress_value(item) for item in value)
                if numeric is not None
            ]
            if candidates:
                return max(candidates)
            return None
        text = str(value).strip()
        if not text:
            return None
        percent_match = re.search(r"(-?\d+(?:\.\d+)?)\s*%", text)
        if percent_match:
            return round(float(percent_match.group(1)), 4)
        number_matches = re.findall(r"-?\d+(?:\.\d+)?", text)
        for raw in number_matches:
            try:
                numeric = float(raw)
            except Exception:
                continue
            if 0.0 <= numeric <= 100.0:
                return round(numeric, 4)
            if 0.0 <= numeric <= 1.0:
                return round(numeric * 100.0, 4)
        return None

    def _extract_valid_actions(self, info: Dict[str, Any]) -> List[str]:
        raw = info.get("admissible_commands")
        if raw is None:
            raw = info.get("valid")
        actions: List[str] = []
        if isinstance(raw, str):
            parts = re.split(r"[\n;,]+", raw)
            actions.extend(part.strip() for part in parts if part.strip())
        elif isinstance(raw, dict):
            for key, value in raw.items():
                if isinstance(value, (list, tuple)):
                    for item in value:
                        text = self._normalize_valid_action_item(item)
                        if text:
                            actions.append(text)
                else:
                    text = self._normalize_valid_action_item(value)
                    if text:
                        actions.append(text)
                if key and not isinstance(key, int):
                    key_text = str(key).strip()
                    if key_text:
                        actions.append(key_text)
        elif isinstance(raw, (list, tuple, set)):
            for item in raw:
                text = self._normalize_valid_action_item(item)
                if text:
                    actions.append(text)
        deduped: List[str] = []
        seen = set()
        for action in actions:
            normalized = self._normalize_action(action)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(action.strip())
            if len(deduped) >= 50:
                break
        return deduped

    def _normalize_valid_action_item(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            parts = [str(item).strip() for item in value if str(item).strip()]
            return " ".join(parts).strip()
        return str(value).strip()

    def _state_key(self, value: Any) -> str:
        text = self._as_text(value).lower()
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"[^a-z0-9% ]+", " ", text)
        return text.strip()[:240]

    def _normalize_action(self, action_text: str) -> str:
        text = str(action_text or "").strip().lower()
        return re.sub(r"\s+", " ", text)

    def _action_family(self, action_text: str) -> str:
        action_norm = self._normalize_action(action_text)
        if action_norm in {"look", "look around"}:
            return "look"
        if action_norm in {"inventory", "inv"}:
            return "inventory"
        if action_norm == "help":
            return "help"
        if action_norm.startswith(("examine ", "inspect ", "look at ")):
            return "examine"
        if action_norm in {"north", "south", "east", "west", "up", "down"} or action_norm.startswith(
            ("go ", "move ", "teleport ")
        ):
            return "movement"
        if action_norm.startswith(("take ", "pick up ", "get ")):
            return "take"
        if action_norm.startswith(("put ", "place ", "drop ", "insert ")):
            return "place"
        if action_norm.startswith(("open ", "close ", "activate ", "switch ", "turn on ", "turn off ")):
            return "manipulate"
        return "other"

    def _is_low_information_action(self, action_text: str) -> bool:
        return self._action_family(action_text) in {"look", "inventory", "help", "examine"}

    @staticmethod
    def _call_method(obj: Any, method_names: Iterable[str], *args, default: Any = None, **kwargs) -> Any:
        for method_name in method_names:
            if not hasattr(obj, method_name):
                continue
            method = getattr(obj, method_name)
            try:
                return method(*args, **kwargs)
            except TypeError:
                continue
        return default

    @staticmethod
    def _safe_number(value: Any, default: float) -> float:
        try:
            if value is None:
                return float(default)
            return float(value)
        except Exception:
            return float(default)

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        try:
            if value is None:
                return int(default)
            return int(value)
        except Exception:
            return int(default)

    @staticmethod
    def _as_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        try:
            return str(value)
        except Exception:
            return ""

    @staticmethod
    def _truncate_text(text: str, limit: int) -> str:
        value = str(text or "").strip()
        if len(value) <= int(limit):
            return value
        return value[: max(0, int(limit) - 3)] + "..."

    @staticmethod
    def _extract_observation_title(text: str) -> str:
        for line in str(text or "").splitlines():
            stripped = line.strip()
            if stripped:
                return stripped[:200]
        return ""
