#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Single-action TALE-Suite tool implementation for dataset: jericho
"""

from __future__ import annotations

import os
import re
import sys
import time
from typing import Any, Dict, List, Optional



_jericho_dict_patch_applied = False


def _patch_jericho_dictionary_bug() -> None:
    """Patch upstream jericho bug: ztools_cleanup() corrupts Frotz's internal
    dictionary iterator, causing subsequent C-level operations to spin forever.

    Root cause: jericho.FrotzEnv.get_dictionary() calls frotz_lib.ztools_cleanup()
    which corrupts a C-level global. This causes subsequent get_dictionary() and
    the ctypes filter_candidate_actions() to enter infinite C-level loops.

    Critical: _load_frotz_lib() creates a NEW CDLL instance per FrotzEnv.
    There is no module-level frotz_lib to patch — we must patch each
    instance's self.frotz_lib AFTER construction.

    Fix: wrap FrotzEnv.__init__ to neutralize ztools_cleanup on every new
    instance's CDLL object, plus cache get_dictionary and force serial mode
    as defense in depth.
    """
    global _jericho_dict_patch_applied
    if _jericho_dict_patch_applied:
        return

    try:
        import jericho as jc

        def _noop(*args, **kwargs):
            pass

        # Layer 0: wrap __init__ to neutralize ztools_cleanup on each instance.
        # This runs AFTER _load_frotz_lib creates the CDLL, so we patch the
        # actual instance's frotz_lib — the only place the C function pointer
        # can be intercepted.
        if not getattr(jc.FrotzEnv.__init__, "_ztools_neutered", False):
            original_init = jc.FrotzEnv.__init__

            def patched_init(self, *args, **kwargs):
                original_init(self, *args, **kwargs)
                # Neutralize ztools_cleanup on this instance's CDLL.
                # Skipping cleanup leaks a few hundred bytes of dictionary
                # node structs per step — irrelevant for short-lived workers.
                try:
                    self.frotz_lib.ztools_cleanup = _noop
                except Exception:
                    pass

            patched_init._ztools_neutered = True
            jc.FrotzEnv.__init__ = patched_init

        # Layer 1: cache get_dictionary per instance (defense in depth)
        if not getattr(jc.FrotzEnv.get_dictionary, "_jericho_dict_cached", False):
            original_get_dictionary = jc.FrotzEnv.get_dictionary

            def cached_get_dictionary(self):
                cache = getattr(self, "_dict_cache", None)
                if cache is None:
                    cache = original_get_dictionary(self)
                    self._dict_cache = cache
                return cache

            cached_get_dictionary._jericho_dict_cached = True
            jc.FrotzEnv.get_dictionary = cached_get_dictionary

        # Layer 2: force serial mode (defense in depth)
        if not getattr(jc.FrotzEnv.get_valid_actions, "_force_serial", False):
            original_get_valid_actions = jc.FrotzEnv.get_valid_actions

            def serial_get_valid_actions(self, *args, **kwargs):
                kwargs["use_parallel"] = False
                return original_get_valid_actions(self, *args, **kwargs)

            serial_get_valid_actions._force_serial = True
            jc.FrotzEnv.get_valid_actions = serial_get_valid_actions

    except Exception:
        pass

    _jericho_dict_patch_applied = True


class TaleJerichoTools:
    DATASET_KEY = "jericho"
    TOOL_PREFIX = "tale_jericho"

    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = os.path.abspath(workspace_root or os.getcwd())
        self._runtime_cache: Dict[str, Any] = {}
        self._active_session: Optional[Dict[str, Any]] = None
        self._hint_already_injected = False
        self._fatal_cache: list = []
        self._fatal_cache_slug: str = ""
        self._fatal_cache_mtime: float = 0.0
        # World model graph (in-memory, per-session, not persisted across episodes)
        # Nodes: room/area names. Edges: (from_node, action, to_node, result, score_delta)
        self._wm_graph: Dict[str, Dict[str, Any]] = {}

    def tale_jericho_list_tasks(self, tale_suite_root: Optional[str] = None) -> Dict[str, Any]:
        runtime = self._ensure_runtime(tale_suite_root)
        if runtime["status"] != "success":
            return runtime
        return {
            "status": "success",
            "dataset": self.DATASET_KEY,
            "tasks": runtime["tasks"],
            "count": len(runtime["tasks"]),
            "tale_suite_root": runtime["tale_suite_root"],
        }

    @staticmethod
    def _extract_room(obs_text: str) -> str:
        """Extract room/location name from observation text.

        Jericho observations start with the room name when the agent enters or
        looks around. Short responses like 'Taken.' or 'You can't go that way.'
        are not room names — fall back to the previous room.
        """
        if not obs_text:
            return "unknown"
        text = obs_text.strip()
        first_line = text.split("\n")[0].strip()
        # Remove common prefixes
        for prefix in ("You are in ", "You are at ", "You're in ", "You're at ", "You see "):
            if first_line.lower().startswith(prefix.lower()):
                first_line = first_line[len(prefix):].strip()
        # Heuristic: room names are short, don't end with period, and aren't
        # common non-location responses
        _NON_ROOMS = {
            "taken.", "you can't go that way.", "you can't see that here.",
            "you can't do that.", "i don't know that verb.", "what?",
            "you already have that.", "you can't take that.",
        }
        lower = first_line.lower().strip()
        if lower in _NON_ROOMS or len(first_line) > 60 or first_line.endswith("."):
            return "_unknown"  # signal non-room response; caller can use prev room
        return first_line[:60] if first_line else "unknown"

    def _update_wm_graph(
        self,
        from_room: str,
        action: str,
        to_room: str,
        score_delta: float,
        result: str,
        admissible: Optional[List[str]] = None,
    ) -> None:
        """Update the in-memory world model graph with a new transition.

        Graph structure: dict of room nodes, each containing:
          - tried_actions: set of (action, result) pairs
          - edges: list of (action, to_room, result, score_delta)
          - admissible_seen: set of all admissible commands ever seen here
          - visits: count of times agent was in this room
          - best_score_here: highest score when leaving this room
        """
        # Ensure both nodes exist
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

        # Record the action
        action_lower = action.lower().strip()
        tried_entry = (action_lower, result)
        if tried_entry not in node["tried_actions"]:
            node["tried_actions"].append(tried_entry)

        # Record the edge
        edge = {
            "action": action_lower,
            "to": to_room,
            "result": result,  # "moved" / "scored" / "died" / "blocked" / "nochange"
            "score_delta": score_delta,
        }
        # Deduplicate edges: same action from same room -> same destination
        edge_key = (action_lower, to_room, result)
        existing_keys = [(e["action"], e["to"], e["result"]) for e in node["edges"]]
        if edge_key not in existing_keys:
            node["edges"].append(edge)

        # Update admissible commands seen
        if admissible:
            node["admissible_seen"].update(c.lower().strip() for c in admissible)

        # Compute untried (frontier)
        tried_set = {t[0] for t in node["tried_actions"]}
        node["untried"] = sorted(node["admissible_seen"] - tried_set)
        node["frontier"] = len(node["untried"]) > 0

    def query_wm(self, **_: Any) -> Dict[str, Any]:
        """Return the current world model graph as formatted text.

        Shows the explored map: rooms visited, actions tried, connections
        discovered, score changes, and untried actions (frontier) per room.
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

        # Sort rooms by visits descending
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

            # Show edges (connections)
            if data["edges"]:
                lines.append("  Exits:")
                for e in data["edges"]:
                    score_tag = f" +{e['score_delta']:.0f}" if e["score_delta"] != 0 else ""
                    result_tag = f" ({e['result']})" if e["result"] != "moved" else ""
                    lines.append(f"    {e['action']} -> {e['to']}{score_tag}{result_tag}")

            # Show untried actions
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


    def tale_jericho_action(
        self,
        action: str,
        env_name: str = "",
        task_index: int = 0,
        game_seed: Optional[int] = None,
        admissible_commands: bool = True,
        tale_suite_root: Optional[str] = None,
    ) -> Dict[str, Any]:
        runtime = self._ensure_runtime(tale_suite_root)
        if runtime["status"] != "success":
            return runtime

        if isinstance(action, (int, float)):
            action_text = str(action).strip()
        else:
            action_text = (action or "").strip()
        if not action_text:
            return {"status": "error", "message": "action must be non-empty."}

        # The game is single-attempt per phase: no restart. If the session is
        # already done (game over), block further actions so the agent wraps up.
        if self._active_session is not None and self._active_session.get("done"):
            session = self._active_session
            return {
                "status": "error",
                "message": (
                    "The game has already ended (done=true). Restarting within a "
                    "phase is not supported. Please output TASK_COMPLETED to end "
                    "this attempt so the pipeline can start a fresh phase."
                ),
                "dataset": self.DATASET_KEY,
                "env_name": session["env_name"],
                "done": True,
                "won": bool((session.get("last_info") or {}).get("won", False)),
                "best_score": self._safe_number(session.get("best_score"), 0),
                "current_score": self._safe_number(session.get("current_score"), 0),
                "full_score": self._safe_number(session.get("full_score"), 0),
            }

        session_started = False
        if self._active_session is None:
            start_res = self._start_session(
                runtime=runtime,
                env_name=env_name,
                task_index=task_index,
                game_seed=game_seed,
                admissible_commands=admissible_commands,
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

        # Tool-level FATAL interception: check if action matches a known fatal entry
        obs_before = session["last_observation"]
        current_room = ""
        try:
            room_match = re.search(r"<<\s*(.+?)\s*>>", str(obs_before or ""))
            if room_match:
                current_room = room_match.group(1)
        except Exception:
            pass
        fatal_warning = self._check_fatal_action(action_text, current_room)
        if fatal_warning:
            return {
                "status": "success",
                "dataset": self.DATASET_KEY,
                "env_name": session["env_name"],
                "action": action_text,
                "message": fatal_warning,
                "steps_taken": session["steps_taken"],
                "done": False,
                "won": False,
                "lost": False,
                "best_score": self._safe_number(session.get("best_score"), 0),
                "current_score": self._safe_number(session.get("current_score"), 0),
                "full_score": self._safe_number(session.get("full_score"), 0),
                "score_rate": float(session.get("best_score", 0)) / float(session.get("full_score", 1)) if session.get("full_score", 0) > 0 else 0.0,
                "moves": session.get("steps_taken", 0),
                "observation": str(obs_before or ""),
                "feedback": f"WIKI GUARD: {fatal_warning}",
                "admissible_commands": None,
            }

        try:
            step_out = session["env"].step(action_text)
        except Exception as e:
            return {
                "status": "error",
                "message": f"env.step failed: {e}",
                "env_name": session["env_name"],
                "action": action_text,
            }

        info: Dict[str, Any]
        if isinstance(step_out, tuple) and len(step_out) == 5:
            obs_after, _reward, terminated, truncated, info = step_out
            done = bool(terminated or truncated)
        elif isinstance(step_out, tuple) and len(step_out) == 4:
            obs_after, _reward, done, info = step_out
            done = bool(done)
        else:
            return {
                "status": "error",
                "message": f"Unexpected env.step return: {type(step_out).__name__}",
            }

        info = info or {}
        session["steps_taken"] += 1

        session["done"] = done
        session["last_action"] = action_text
        session["last_observation"] = obs_after
        session["last_info"] = info

        prev_current_score = self._safe_number(session.get("current_score"), 0)
        prev_full_score = self._safe_number(session.get("full_score"), 0)
        prev_best_score = self._safe_number(session.get("best_score"), 0)

        raw_current_score = self._safe_number(info.get("score"), prev_current_score)
        raw_full_score = self._safe_number(info.get("max_score"), prev_full_score)
        current_score = self._sanitize_score(raw_current_score, raw_full_score, prev_current_score)
        full_score = max(prev_full_score, raw_full_score)
        moves = self._safe_number(info.get("moves"), 0)

        session["current_score"] = current_score
        session["full_score"] = full_score
        session["best_score"] = max(prev_best_score, current_score)
        if full_score > 0:
            # Guard against transient invalid scores (e.g., restart confirmation screens).
            session["best_score"] = min(session["best_score"], full_score)

        score_rate = (
            float(session["best_score"]) / float(session["full_score"])
            if float(session["full_score"]) > 0
            else 0.0
        )

        session_closed = False
        close_note = ""
        if done:
            close_note = self._close_active_session()
            session_closed = True

        obs_text = self._as_text(obs_after)
        score_changed = current_score > prev_best_score

        # ── World model graph update ──
        if True:
            from_room = self._extract_room(self._as_text(obs_before))
            to_room = self._extract_room(obs_text)
            # If to_room is "_unknown" (non-room response), agent stayed in from_room
            if to_room == "_unknown":
                to_room = from_room
            if from_room == "_unknown":
                from_room = to_room
            score_delta = current_score - prev_current_score
            # Determine transition result
            if done and bool(info.get("lost", False)):
                wm_result = "died"
            elif score_delta > 0:
                wm_result = "scored"
            elif from_room != to_room:
                wm_result = "moved"
            elif obs_text.strip() == self._as_text(obs_before).strip():
                wm_result = "nochange"
            else:
                wm_result = "interact"
            self._update_wm_graph(
                from_room, action_text, to_room, score_delta, wm_result,
                admissible=info.get("admissible_commands"),
            )
        # Loop detection: track (action, room) pairs and warn if stuck.
        # Same action in DIFFERENT rooms is normal exploration, not a loop.
        loop_warning = ""
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
                # Collect untried commands from admissible_actions for actionable hint
                tried = {p.split("@", 1)[0] for p in recent}
                adm = info.get("admissible_commands") or []
                untried = [c for c in adm if c.lower().strip() not in tried]
                hint_extra = ""
                if untried:
                    hint_extra = f" Try one of these instead: {', '.join(untried[:5])}."
                else:
                    hint_extra = " You have exhausted known actions here. Go to a DIFFERENT room or examine objects you haven't checked."
                loop_warning = (
                    f"\n⚠ LOOP DETECTED: '{top_action}' repeated {top_count}x in {_room_sig} with no score gain."
                    f" This action is NOT working.{hint_extra}"
                )

        # Auto-inject wiki knowledge hint (opt-in via AGIA_ENABLE_AUTO_WIKI_HINT=1)
        wiki_hint = ""
        if str(os.environ.get("AGIA_ENABLE_AUTO_WIKI_HINT", "")).strip().lower() in {"1", "true", "yes", "on"}:
            wiki_hint = self._auto_wiki_hint(obs_text, score_changed, session["steps_taken"])

        result = {
            "status": "success",
            "dataset": self.DATASET_KEY,
            "env_name": session["env_name"],
            "action": action_text,
            "session_started": session_started,
            "session_closed": session_closed,
            "message": "Action executed." + (f" {close_note}" if close_note else ""),
            "steps_taken": session["steps_taken"],
            "done": done,
            "won": bool(info.get("won", False)),
            "lost": bool(info.get("lost", False)),
            "best_score": self._safe_number(session.get("best_score"), current_score),
            "current_score": current_score,
            "full_score": self._safe_number(session.get("full_score"), full_score),
            "score_rate": score_rate,
            "moves": moves,
            "observation_before": self._as_text(obs_before),
            "observation": obs_text,
            "feedback": self._as_text(info.get("feedback", obs_after)) + loop_warning,
            "admissible_commands": info.get("admissible_commands"),
        }
        if wiki_hint:
            result["wiki_hint"] = wiki_hint
        return result

    def _auto_wiki_hint(self, observation: str, score_changed: bool, steps_taken: int) -> str:
        """Auto-inject the full knowledge recipe ONCE per play session.

        Fires on the first score increase, then never again for this session.
        Returns the complete knowledge file (DO + DON'T + NEED + SEED) so the
        agent has the full picture without repeated fragment injections.
        """
        if not observation or len(observation.strip()) < 10:
            return ""
        if not score_changed:
            return ""
        if getattr(self, "_hint_already_injected", False):
            return ""

        try:
            from src.wiki_memory import WikiMemoryReader
            reader = WikiMemoryReader(workspace_root=self.workspace_root)

            # Use the env_name to build a targeted query for the right game
            env = os.environ.get("JERICHO_ACTIVE_ENV", "")
            query = env.replace("JerichoEnv", "") if env else observation[:100]

            result = reader.wiki_memory_read(query=query[:200], section="knowledge", max_results=1, _bypass_count=True)
            matches = result.get("matches") or []
            if not matches:
                return ""

            # Load the FULL knowledge file content (not just a snippet)
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

    def _start_session(
        self,
        runtime: Dict[str, Any],
        env_name: str,
        task_index: int,
        game_seed: Optional[int],
        admissible_commands: bool,
    ) -> Dict[str, Any]:
        tasks = runtime["tasks"]
        if not tasks:
            return {"status": "error", "message": f"No tasks for dataset {self.DATASET_KEY}."}

        # Env-var seed override: if AGIA_GAME_SEED is set, force it (overrides agent-supplied seed)
        env_seed = os.environ.get("AGIA_GAME_SEED", "").strip()
        if env_seed:
            try:
                game_seed = int(env_seed)
            except ValueError:
                pass

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

        gym = runtime["gym"]
        try:
            env = gym.make(
                f"tales/{selected}-v0",
                disable_env_checker=True,
                admissible_commands=bool(admissible_commands),
            )
            obs, info = env.reset(seed=game_seed)
        except Exception as e:
            return {"status": "error", "message": f"Failed to start env {selected}: {e}"}

        raw_init_score = self._safe_number((info or {}).get("score"), 0)
        raw_init_full_score = self._safe_number((info or {}).get("max_score"), 0)
        init_score = self._sanitize_score(raw_init_score, raw_init_full_score, 0)

        self._active_session = {
            "created_at": time.time(),
            "dataset": self.DATASET_KEY,
            "env_name": selected,
            "env": env,
            "steps_taken": 0,
            "done": False,
            "last_action": None,
            "last_observation": obs,
            "last_info": info or {},
            "current_score": init_score,
            "best_score": min(init_score, raw_init_full_score) if raw_init_full_score > 0 else init_score,
            "full_score": raw_init_full_score,
            "_recent_actions": [],
        }
        return {"status": "success"}

    def _check_fatal_action(self, action: str, current_room: str) -> str:
        """Check if the action+room matches a known FATAL entry in the knowledge file.
        Returns a warning message if matched, empty string otherwise.
        """
        if not action:
            return ""
        try:
            wiki_root = os.environ.get("AGIA_WIKI_ROOT", "").strip()
            if not wiki_root or not os.path.isdir(wiki_root):
                return ""
            ablation = os.environ.get("AGIA_WIKI_ABLATION", "").strip().lower()
            if ablation in ("no_wiki", "no_knowledge"):
                return ""

            env = os.environ.get("JERICHO_ACTIVE_ENV", "")
            game_slug = env.replace("JerichoEnv", "").lower()
            if not game_slug:
                return ""

            kf_path = os.path.join(wiki_root, "knowledge", f"score_recipe_{game_slug}.md")
            if not os.path.isfile(kf_path):
                return ""

            mtime = os.path.getmtime(kf_path)
            if self._fatal_cache_slug != game_slug or self._fatal_cache_mtime != mtime:
                content = open(kf_path, encoding="utf-8").read().lower()

                # Collect all scoring actions: lines containing "-> +" (score gain).
                # A FATAL action that also scores is conditional, not guaranteed death.
                # Only hard-block actions that NEVER appear in any scoring line.
                scoring_text = "\n".join(
                    ln for ln in content.split("\n") if "->" in ln and "+" in ln
                )

                fatal_entries = []  # list of (command, room_or_empty)
                in_death_section = False

                for line in content.split("\n"):
                    line_s = line.strip()

                    # Primary format: [FATAL:action words] (Room) description
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
                        _NAV_WORDS = {"east", "west", "north", "south", "up", "down",
                                      "northeast", "northwest", "southeast", "southwest",
                                      "ne", "nw", "se", "sw"}
                        if not room and core_cmd in _NAV_WORDS:
                            continue
                        # Skip if this action also scores (not a guaranteed death)
                        if core_cmd in scoring_text:
                            continue
                        fatal_entries.append((core_cmd, room))
                        continue

                    # Track section for fallback parser
                    if line_s.startswith("## "):
                        in_death_section = "death" in line_s or "don't" in line_s or "dont" in line_s
                        continue

                    # Fallback: old [FATAL] tag without explicit keywords
                    if "[fatal]" in line_s:
                        after = line_s.split("[fatal]", 1)[1].strip()
                    elif in_death_section and (line_s.startswith("- ") or line_s.startswith("* ")):
                        after = line_s.lstrip("-* ").strip()
                    else:
                        continue

                    # Parse room and command
                    desc_split = re.split(r"[-—–]\s*", after, maxsplit=1)
                    cmd_and_room = desc_split[0].strip()
                    full_desc = after
                    room = ""
                    cmd = cmd_and_room
                    paren_match = re.match(r"\((.+?)\)\s*(.+)", cmd_and_room)
                    if paren_match:
                        room = paren_match.group(1).strip()
                        cmd = paren_match.group(2).strip()
                    cmd_words = [w for w in cmd.split() if w not in ("the", "a", "an", "go")]
                    if not cmd_words:
                        continue
                    core_cmd = " ".join(cmd_words[:3])
                    if "anywhere" in full_desc or "any room" in full_desc or "regardless" in full_desc:
                        room = ""
                    # Skip if this action also scores (not a guaranteed death)
                    if core_cmd in scoring_text:
                        continue
                    fatal_entries.append((core_cmd, room))

                self._fatal_cache = fatal_entries
                self._fatal_cache_slug = game_slug
                self._fatal_cache_mtime = mtime

            action_lower = action.lower().strip()
            room_lower = (current_room or "").lower().strip()

            _NAV_WORDS = {"east", "west", "north", "south", "up", "down",
                          "northeast", "northwest", "southeast", "southwest",
                          "ne", "nw", "se", "sw", "n", "e", "s", "w", "u", "d"}
            for core_cmd, fatal_room in self._fatal_cache:
                keywords = [k.strip() for k in core_cmd.split(",") if k.strip()]
                if not any(k in action_lower for k in keywords):
                    continue
                if fatal_room and room_lower:
                    # Room known: filter by room match
                    room_words = [w for w in re.split(r"[\s,()]+", fatal_room) if len(w) >= 3]
                    if room_words and not any(rw in room_lower for rw in room_words):
                        continue
                elif fatal_room and not room_lower:
                    # Room unknown: trust FATAL for non-nav actions (say manaz, fwoosh),
                    # but skip nav directions (north/south/etc) to avoid over-blocking
                    if any(k.strip() in _NAV_WORDS for k in keywords):
                        continue
                return f"BLOCKED: '{action}' is marked [FATAL] in knowledge. Choose a different action."
        except Exception:
            pass
        return ""
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

    def _ensure_runtime(self, tale_suite_root: Optional[str]) -> Dict[str, Any]:
        root_res = self._resolve_tale_suite_root(tale_suite_root)
        if root_res["status"] != "success":
            return root_res

        tale_root = root_res["tale_suite_root"]
        cached = self._runtime_cache.get(tale_root)
        if cached is not None:
            return cached

        if tale_root not in sys.path:
            sys.path.insert(0, tale_root)

        try:
            import gymnasium as gym
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to import gymnasium: {e}",
            }

        try:
            import tales
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to import tales: {e}",
                "tale_suite_root": tale_root,
            }

        _patch_jericho_dictionary_bug()

        tasks = sorted(list(tales.envs_per_task.get(self.DATASET_KEY, [])))
        runtime = {
            "status": "success",
            "tale_suite_root": tale_root,
            "gym": gym,
            "tasks": tasks,
        }
        self._runtime_cache[tale_root] = runtime
        return runtime

    def _resolve_tale_suite_root(self, tale_suite_root: Optional[str]) -> Dict[str, Any]:
        candidates: List[str] = []
        if tale_suite_root:
            candidates.append(tale_suite_root)

        env_root = os.environ.get("TALE_SUITE_ROOT")
        if env_root:
            candidates.append(env_root)

        file_based = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "tale-suite")
        )
        candidates.append(file_based)
        candidates.append(os.path.abspath(os.path.join(self.workspace_root, "tale-suite")))
        candidates.append(os.path.abspath(os.path.join(self.workspace_root, "..", "tale-suite")))

        checked: List[str] = []
        for raw in candidates:
            if not raw:
                continue
            p = os.path.abspath(raw)
            if p in checked:
                continue
            checked.append(p)
            if os.path.isfile(os.path.join(p, "benchmark.py")) and os.path.isdir(os.path.join(p, "tales")):
                return {"status": "success", "tale_suite_root": p}

        return {
            "status": "error",
            "message": "Unable to locate tale-suite root.",
            "checked_paths": checked,
        }

    @staticmethod
    def _safe_number(value: Any, default: float) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _sanitize_score(current_score: float, full_score: float, fallback_score: float) -> float:
        """
        Jericho can occasionally return transient invalid scores on menu/restart screens.
        Keep score monotonic and bounded by max score when max score is known.
        """
        if full_score > 0 and current_score > full_score:
            if fallback_score <= full_score:
                return fallback_score
            return full_score
        return current_score

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
