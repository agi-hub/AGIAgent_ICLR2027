#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Single-action TextQuests tool implementation.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional


class TextQuestsTools:
    DATASET_KEY = "textquests"
    TOOL_PREFIX = "textquests"

    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = os.path.abspath(workspace_root or os.getcwd())
        self._runtime_cache: Dict[str, Any] = {}
        self._active_session: Optional[Dict[str, Any]] = None

    def textquests_list_tasks(self, textquests_root: Optional[str] = None) -> Dict[str, Any]:
        runtime = self._ensure_runtime(textquests_root)
        if runtime["status"] != "success":
            return runtime
        return {
            "status": "success",
            "dataset": self.DATASET_KEY,
            "tasks": runtime["tasks"],
            "count": len(runtime["tasks"]),
            "textquests_root": runtime["textquests_root"],
        }

    def textquests_action(
        self,
        action: str,
        env_name: str = "",
        task_index: int = 0,
        game_seed: Optional[int] = None,
        with_clues: bool = False,
        restart: bool = False,
        textquests_root: Optional[str] = None,
    ) -> Dict[str, Any]:
        runtime = self._ensure_runtime(textquests_root)
        if runtime["status"] != "success":
            return runtime

        action_text = (action or "").strip()
        if not action_text:
            return {"status": "error", "message": "action must be non-empty."}

        restart_best_state = None
        if restart and self._active_session is not None:
            active = self._active_session
            restart_best_state = {
                "env_name": active.get("env_name"),
                "best_score": self._safe_number(active.get("best_score"), 0),
                "best_progress": self._safe_number(active.get("best_progress"), active.get("progress", 0)),
                "best_progress_step": active.get("best_progress_step"),
                "best_progress_action": active.get("best_progress_action"),
            }
            if not env_name.strip():
                env_name = str(active.get("env_name") or "")
                with_clues = bool(active.get("with_clues", with_clues))
            self._close_active_session()

        session_started = False
        if self._active_session is None:
            start_res = self._start_session(
                runtime=runtime,
                env_name=env_name,
                task_index=task_index,
                game_seed=game_seed,
                with_clues=with_clues,
            )
            if start_res.get("status") != "success":
                return start_res
            session_started = True

        session = self._active_session
        assert session is not None
        if restart_best_state and restart_best_state.get("env_name") == session.get("env_name"):
            session["best_score"] = max(
                self._safe_number(session.get("best_score"), 0),
                self._safe_number(restart_best_state.get("best_score"), 0),
            )
            session["best_progress"] = max(
                self._safe_number(session.get("best_progress"), session.get("progress", 0)),
                self._safe_number(restart_best_state.get("best_progress"), 0),
            )
            if restart_best_state.get("best_progress_step") is not None:
                session["best_progress_step"] = restart_best_state.get("best_progress_step")
                session["best_progress_action"] = restart_best_state.get("best_progress_action")

        if env_name.strip() and env_name.strip() != session["env_name"]:
            return {
                "status": "error",
                "message": (
                    f"Active session env is {session['env_name']}, but received env_name={env_name}. "
                    "Use restart=true to start another task."
                ),
                "active_env_name": session["env_name"],
            }

        env = session["env"]
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

        # Mirror the original TextQuests evaluation loop: save checkpoint before every normal action.
        action_lower = action_text.lower()
        if not action_lower.startswith("restore ") and action_lower != "restart":
            try:
                env.save_checkpoint(obs_before, info_before)
            except Exception:
                pass

        try:
            obs_after, reward, done, info = env.step(action_text)
        except Exception as e:
            return {
                "status": "error",
                "message": f"env.step failed: {e}",
                "env_name": session["env_name"],
                "action": action_text,
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
        prev_progress = self._safe_number(session.get("progress"), 0)
        current_score = self._safe_number(info.get("score"), session.get("current_score", 0))
        full_score = self._safe_number(session.get("full_score"), 0)
        if full_score <= 0:
            try:
                full_score = self._safe_number(env.get_max_score(), 0)
            except Exception:
                full_score = 0
        best_score = max(prev_best_score, current_score)
        progress = self._safe_number(info.get("game_progress"), session.get("progress", 0))
        best_progress = max(prev_best_progress, progress)
        if progress > prev_best_progress:
            session["best_progress_step"] = session["steps_taken"]
            session["best_progress_action"] = action_text
        moves = self._safe_number(info.get("moves"), session["steps_taken"])
        checkpoint_count = self._safe_int(self._call_if_exists(env, "get_checkpoint_count"), 0)
        total_restores = self._safe_int(self._call_if_exists(env, "get_total_restores"), 0)
        suggested_restore_steps = self._suggest_restore_steps(checkpoint_count)

        session["current_score"] = current_score
        session["best_score"] = best_score
        session["full_score"] = full_score
        session["progress"] = progress
        session["best_progress"] = best_progress

        score_rate = (best_score / full_score) if full_score > 0 else 0.0
        won = bool(progress >= 100 or (full_score > 0 and current_score >= full_score))

        session_closed = False
        close_note = ""
        if done:
            close_note = self._close_active_session()
            session_closed = True

        parser_feedback = self._classify_parser_feedback(
            action_text=action_text,
            observation_before=obs_before,
            observation_after=obs_after,
            info=info,
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
            suggested_restore_steps=suggested_restore_steps,
        )
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
            moves=moves,
            reward=reward,
            done=bool(done),
            won=won,
        )

        return {
            "status": "success",
            "dataset": self.DATASET_KEY,
            "env_name": session["env_name"],
            "action": action_text,
            "session_started": session_started,
            "session_closed": session_closed,
            "message": "Action executed." + (f" {close_note}" if close_note else ""),
            "steps_taken": session["steps_taken"],
            "done": bool(done),
            "won": won,
            "lost": bool(done and not won),
            "reward": reward,
            "best_score": best_score,
            "current_score": current_score,
            "full_score": full_score,
            "score_rate": score_rate,
            "progress": progress,
            "best_progress": best_progress,
            "best_progress_step": session.get("best_progress_step"),
            "best_progress_action": session.get("best_progress_action"),
            "moves": moves,
            "checkpoint_count": checkpoint_count,
            "total_restores": total_restores,
            "suggested_restore_steps": suggested_restore_steps,
            "restore_guidance": (
                "If you need to backtrack, prefer restore <step_id> using one of suggested_restore_steps "
                "instead of restarting the whole run. Do not restore to a branch with lower progress than best_progress "
                "unless the current branch is dead, lost, or clearly irrecoverable."
                if suggested_restore_steps else
                "No restore checkpoints are available yet."
            ),
            "with_clues": bool(session.get("with_clues", False)),
            "observation_before": self._as_text(obs_before),
            "observation": self._as_text(obs_after),
            "feedback": self._as_text(obs_after),
            "markers": info.get("markers"),
            "label_vectors": self._normalize_label_vectors(info.get("label_vectors")),
            "feelies": session.get("feelies", "") if session_started else "",
            "parser_feedback": parser_feedback,
            "stuck_state": stuck_state,
            "blocked_action_patterns": stuck_state.get("blocked_action_patterns", []),
            "anti_loop_guidance": stuck_state.get("guidance", ""),
            "trusted_state_snapshot": trusted_state_snapshot,
            "trusted_state_json": json.dumps(trusted_state_snapshot, ensure_ascii=False, sort_keys=True),
        }

    def _start_session(
        self,
        runtime: Dict[str, Any],
        env_name: str,
        task_index: int,
        game_seed: Optional[int],
        with_clues: bool,
    ) -> Dict[str, Any]:
        tasks = runtime["tasks"]
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

        env_class = runtime.get("TextQuestsEnv")
        if env_class is None:
            return {
                "status": "error",
                "message": (
                    "TextQuests runtime is missing environment dependencies. "
                    + str(runtime.get("env_load_error") or "Unknown env load error")
                ),
                "textquests_root": runtime.get("textquests_root"),
            }
        game_folder_path = os.path.join(runtime["data_root"], selected)
        try:
            env = env_class(game_folder_path=game_folder_path, with_clues=bool(with_clues))
            if game_seed is not None and hasattr(env, "seed"):
                env.seed(int(game_seed))
                obs, info = env.reset()
            else:
                obs, info = env.reset()
        except Exception as e:
            return {"status": "error", "message": f"Failed to start env {selected}: {e}"}

        full_score = self._safe_number(runtime["game_info"].get(selected, {}).get("max_score"), 0)
        if full_score <= 0:
            full_score = self._safe_number(self._call_if_exists(env, "get_max_score"), 0)
        current_score = self._safe_number((info or {}).get("score"), 0)

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
            "current_score": current_score,
            "best_score": current_score,
            "full_score": full_score,
            "progress": self._safe_number((info or {}).get("game_progress"), 0),
            "best_progress": self._safe_number((info or {}).get("game_progress"), 0),
            "best_progress_step": 0,
            "best_progress_action": None,
            "with_clues": bool(with_clues),
            "feelies": self._as_text(getattr(env, "feelies", "")),
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
        }
        return {"status": "success"}

    def _close_active_session(self) -> str:
        if self._active_session is None:
            return ""
        msg = "Episode closed."
        try:
            self._active_session["env"].env.close()
        except Exception:
            try:
                self._active_session["env"].close()
            except Exception as e:
                msg = f"Episode closed with env.close error: {e}"
        self._active_session = None
        return msg

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
        moves: float,
        reward: Any,
        done: bool,
        won: bool,
    ) -> Dict[str, Any]:
        observation_before_text = self._as_text(observation_before)
        observation_after_text = self._as_text(observation_after)
        return {
            "snapshot_type": "textquests_runtime_state",
            "snapshot_scope": "single_verified_tool_result",
            "env_name": str(session.get("env_name") or ""),
            "action": str(action_text or ""),
            "steps_taken": self._safe_int(session.get("steps_taken"), 0),
            "moves": self._safe_number(moves, 0),
            "current_score": self._safe_number(current_score, 0),
            "best_score": self._safe_number(best_score, 0),
            "full_score": self._safe_number(full_score, 0),
            "score_rate": round(float(score_rate or 0.0), 6),
            "progress": self._safe_number(progress, 0),
            "best_progress": self._safe_number(best_progress, progress),
            "best_progress_step": session.get("best_progress_step"),
            "best_progress_action": session.get("best_progress_action"),
            "reward": self._safe_number(reward, 0),
            "done": bool(done),
            "won": bool(won),
            "with_clues": bool(session.get("with_clues", False)),
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
    ) -> Dict[str, Any]:
        del info
        before_text = self._as_text(observation_before)
        after_text = self._as_text(observation_after)
        after_lower = after_text.lower()
        before_norm = self._normalize_feedback_text(before_text)
        after_norm = self._normalize_feedback_text(after_text)

        category = "not_detected"
        confidence = 0.0
        matched_text = ""
        repair_focus = ""
        suggested_actions: List[str] = []
        is_parser_issue = False

        patterns = [
            (
                "missing_precondition",
                0.98,
                [
                    "you'll have to get out of",
                    "you'll have to stand up first",
                    "you'll have to get up first",
                    "you have to get out of",
                    "you have to stand up first",
                    "you have to open",
                    "the door is closed",
                    "you're still sitting",
                    "you are still sitting",
                ],
                "Fix the immediate prerequisite before retrying the same local goal.",
                self._precondition_repair_actions(action_text),
            ),
            (
                "need_specificity",
                0.97,
                [
                    "be specific",
                    "you'll have to be more specific",
                    "which do you mean",
                    "what do you want to",
                    "please be more specific",
                ],
                "Keep the same local goal, but make the command more explicit and mention the exact object or amount.",
                self._specificity_repair_actions(action_text),
            ),
            (
                "syntax_rejected",
                0.95,
                [
                    "i don't know the word",
                    "i dont know the word",
                    "i don't know that word",
                    "i don't understand that sentence",
                    "that sentence isn't one i recognize",
                    "you can't use multiple direct objects",
                    "i only understood you as far as",
                    "there was no verb in that sentence",
                    "that's not a verb i recognize",
                ],
                "Stay on the same local goal and try 1-3 simpler command variants.",
                self._syntax_repair_actions(action_text),
            ),
            (
                "unknown_object",
                0.94,
                [
                    "you can't see any such thing",
                    "you see no",
                    "there is no",
                    "you don't have that",
                    "you aren't holding that",
                ],
                "Re-anchor on visible objects or inventory before retrying.",
                self._unknown_object_repair_actions(action_text),
            ),
            (
                "movement_blocked",
                0.9,
                [
                    "you can't go that way",
                    "you can't see how to get there from here",
                    "there is no exit",
                ],
                "Do not keep forcing the same direction; inspect exits and try one nearby alternative.",
                self._movement_repair_actions(action_text),
            ),
        ]

        for detected_category, detected_confidence, phrases, detected_focus, detected_actions in patterns:
            phrase = self._first_matching_phrase(after_lower, phrases)
            if phrase:
                category = detected_category
                confidence = detected_confidence
                matched_text = phrase
                repair_focus = detected_focus
                suggested_actions = detected_actions
                is_parser_issue = True
                break

        observation_unchanged = bool(before_norm and after_norm and before_norm == after_norm)
        if not is_parser_issue and observation_unchanged:
            category = "no_effect_or_repeat"
            confidence = 0.6
            matched_text = "observation_unchanged"
            repair_focus = "The action produced no visible state change. Try at most a few local variants before abandoning this branch."
            suggested_actions = self._syntax_repair_actions(action_text)

        return {
            "is_parser_issue": is_parser_issue,
            "category": category,
            "confidence": confidence,
            "matched_text": matched_text,
            "observation_unchanged": observation_unchanged,
            "local_repair_focus": repair_focus,
            "suggested_actions": suggested_actions[:3],
            "retry_policy": (
                "If this category repeats for the same local goal, stay local and try at most 3 nearby variants. "
                "If all fail, stop forcing the same command chain and switch to another local path."
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
        suggested_restore_steps: List[int],
    ) -> Dict[str, Any]:
        anti_loop = session.setdefault("anti_loop", {})
        action_key = self._normalize_feedback_text(action_text)
        action_family = self._action_family(action_text)
        state_key = self._build_state_key(observation_after, current_score, progress)
        last_state_key = str(anti_loop.get("last_state_key") or "")
        same_state = bool(state_key and state_key == last_state_key)
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

        progress_improved = (
            current_score > prev_current_score
            or best_score > prev_best_score
            or progress > prev_progress
        )
        no_progress_count = 0 if progress_improved else int(anti_loop.get("no_progress_count", 0)) + 1
        is_low_information_action = self._is_low_information_action(action_text)
        low_information_action_count = (
            int(anti_loop.get("low_information_action_count", 0)) + 1
            if same_state and is_low_information_action
            else (1 if is_low_information_action else 0)
        )

        if action_key.startswith("restore ") or action_key == "restart":
            same_state_count = 1
            same_action_count = 1
            same_action_family_count = 1
            no_progress_count = 0
            low_information_action_count = 0

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
        if same_action_family_count >= 3 and action_family in {"movement", "look", "inventory", "examine", "search"}:
            blocked_action_patterns.append(action_family)
        if low_information_action_count >= 2 and action_family in {"look", "inventory", "examine", "search"}:
            blocked_action_patterns.append(action_family)
        blocked_action_patterns = list(dict.fromkeys(blocked_action_patterns))

        severity = "none"
        recommended_policy = "continue"
        reason_parts: List[str] = []
        if low_information_action_count >= 2 and same_state_count >= 3:
            severity = "warning"
            recommended_policy = "local_retry_only"
            reason_parts.append("Repeated low-information actions in the same unchanged state")
        if parser_feedback.get("observation_unchanged") and same_action_count >= 2:
            severity = "warning"
            recommended_policy = "local_retry_only"
            reason_parts.append("The same action was repeated without visible state change")
        if same_action_family_count >= 3 and parser_feedback.get("category") in {"movement_blocked", "no_effect_or_repeat"}:
            severity = "branch"
            recommended_policy = "force_restore" if suggested_restore_steps else "switch_local_goal"
            reason_parts.append("Nearby retries are exhausted for the current local branch")
        if same_state_count >= 4 and no_progress_count >= 5:
            severity = "branch"
            recommended_policy = "force_restore" if suggested_restore_steps else "switch_local_goal"
            reason_parts.append("The agent has stayed in the same local state for several rounds without score/progress gain")
        if same_state_count >= 6 and no_progress_count >= 8:
            severity = "critical"
            recommended_policy = "force_restore" if suggested_restore_steps else "restart_if_no_checkpoint"
            reason_parts.append("The current branch appears fully stalled and should be abandoned")

        recommended_restore_step = suggested_restore_steps[0] if suggested_restore_steps and recommended_policy == "force_restore" else None
        if severity == "none":
            guidance = "No strong loop signal detected. Continue, but avoid repeating low-information actions in the same unchanged state."
        elif recommended_policy == "local_retry_only":
            guidance = (
                "Loop warning detected. Try at most one nearby variant or prerequisite repair, "
                "and do not repeat blocked actions while the state remains unchanged."
            )
        elif recommended_policy == "force_restore":
            guidance = (
                f"Local branch is stalled. Do not keep probing the same puzzle branch; "
                f"use restore {recommended_restore_step} next unless a clearly better nearby checkpoint exists."
            )
        elif recommended_policy == "switch_local_goal":
            guidance = (
                "Local branch is stalled and no checkpoint is available. Leave this branch, stop repeating blocked actions, "
                "and switch to a different nearby goal or region."
            )
        else:
            guidance = (
                "The current branch appears irrecoverable without a checkpoint. Restart only if no useful restore point exists."
            )

        result = {
            "is_stuck": severity != "none",
            "severity": severity,
            "same_state_count": same_state_count,
            "same_action_count": same_action_count,
            "same_action_family_count": same_action_family_count,
            "no_progress_count": no_progress_count,
            "low_information_action_count": low_information_action_count,
            "blocked_action_patterns": blocked_action_patterns,
            "recommended_policy": recommended_policy,
            "recommended_restore_step": recommended_restore_step,
            "reason": "; ".join(reason_parts) if reason_parts else "No strong loop pattern detected",
            "guidance": guidance,
        }
        anti_loop["last_stuck_state"] = result
        return result

    def _precheck_action_guard(self, session: Dict[str, Any], action_text: str) -> Dict[str, Any]:
        anti_loop = session.setdefault("anti_loop", {})
        action_key = self._normalize_feedback_text(action_text)
        action_family = self._action_family(action_text)
        if not action_key:
            return {"blocked": False}
        if action_key.startswith("restore "):
            restore_step = self._parse_restore_step(action_key)
            checkpoint_count = self._safe_int(self._call_if_exists(session["env"], "get_checkpoint_count"), 0)
            if restore_step is None:
                anti_loop["guard_block_count"] = int(anti_loop.get("guard_block_count", 0)) + 1
                return {
                    "blocked": True,
                    "reason": "Invalid restore command format. Use restore <checkpoint_step_id>.",
                    "guidance": "The restore command was not executed. Choose a checkpoint from suggested_restore_steps.",
                    "blocked_action_patterns": [action_text.strip()],
                    "must_do_action": "",
                    "recommended_policy": "switch_local_goal",
                    "recommended_restore_step": None,
                    "guard_block_count": int(anti_loop.get("guard_block_count", 0)),
                    "same_state_count": int(anti_loop.get("same_state_count", 0)),
                    "same_action_count": int(anti_loop.get("same_action_count", 0)),
                    "same_action_family_count": int(anti_loop.get("same_action_family_count", 0)),
                    "no_progress_count": int(anti_loop.get("no_progress_count", 0)),
                    "low_information_action_count": int(anti_loop.get("low_information_action_count", 0)),
                    "parser_category": "invalid_restore_checkpoint",
                }
            if restore_step < 0 or restore_step >= checkpoint_count:
                anti_loop["guard_block_count"] = int(anti_loop.get("guard_block_count", 0)) + 1
                suggested_restore_steps = self._suggest_restore_steps(checkpoint_count)
                return {
                    "blocked": True,
                    "reason": (
                        f"Restore checkpoint {restore_step} is unavailable; "
                        f"valid checkpoint ids are 0..{checkpoint_count - 1}."
                        if checkpoint_count > 0 else
                        "No restore checkpoints are available yet."
                    ),
                    "guidance": (
                        "The invalid restore was not executed, so current_score/progress/best_progress are preserved. "
                        f"Use one of suggested_restore_steps={suggested_restore_steps} or switch local goal."
                    ),
                    "blocked_action_patterns": [action_text.strip()],
                    "must_do_action": f"restore {suggested_restore_steps[0]}" if suggested_restore_steps else "",
                    "recommended_policy": "force_restore" if suggested_restore_steps else "switch_local_goal",
                    "recommended_restore_step": suggested_restore_steps[0] if suggested_restore_steps else None,
                    "guard_block_count": int(anti_loop.get("guard_block_count", 0)),
                    "same_state_count": int(anti_loop.get("same_state_count", 0)),
                    "same_action_count": int(anti_loop.get("same_action_count", 0)),
                    "same_action_family_count": int(anti_loop.get("same_action_family_count", 0)),
                    "no_progress_count": int(anti_loop.get("no_progress_count", 0)),
                    "low_information_action_count": int(anti_loop.get("low_information_action_count", 0)),
                    "parser_category": "invalid_restore_checkpoint",
                }
            return {"blocked": False}
        if action_key == "restart":
            return {"blocked": False}

        current_state_key = self._build_state_key(
            session.get("last_observation"),
            self._safe_number(session.get("current_score"), 0),
            self._safe_number(session.get("progress"), 0),
        )
        same_state = bool(current_state_key and current_state_key == anti_loop.get("last_state_key"))
        if not same_state:
            return {"blocked": False}

        last_stuck_state = anti_loop.get("last_stuck_state") or {}
        blocked_patterns = list(last_stuck_state.get("blocked_action_patterns") or [])
        must_do_action = ""
        reason = ""

        if (
            last_stuck_state.get("is_stuck")
            and last_stuck_state.get("recommended_policy") == "force_restore"
            and last_stuck_state.get("recommended_restore_step") is not None
            and str(last_stuck_state.get("severity")) in {"branch", "critical"}
        ):
            must_do_action = f"restore {int(last_stuck_state['recommended_restore_step'])}"
            reason = "The current local branch was already marked as stalled and now requires restore before more probing."
        elif self._matches_blocked_pattern(action_text, blocked_patterns):
            reason = "This action matches blocked_action_patterns in the same unchanged state."
        elif self._is_low_information_action(action_text) and int(anti_loop.get("low_information_action_count", 0)) >= 2:
            blocked_patterns = list(dict.fromkeys(blocked_patterns + [action_family]))
            reason = "Low-information actions are rate limited in the same unchanged state."
        elif action_key == str(anti_loop.get("last_action_key") or "") and int(anti_loop.get("same_action_count", 0)) >= 2:
            blocked_patterns = list(dict.fromkeys(blocked_patterns + [action_text.strip()]))
            reason = "The exact same action was already repeated in the same unchanged state."
        elif (
            action_family
            and action_family == str(anti_loop.get("last_action_family") or "")
            and int(anti_loop.get("same_action_family_count", 0)) >= 3
            and action_family in {"movement", "look", "inventory", "examine", "search"}
        ):
            blocked_patterns = list(dict.fromkeys(blocked_patterns + [action_family]))
            reason = "This action family has already been exhausted in the same unchanged state."

        if not reason:
            return {"blocked": False}

        anti_loop["guard_block_count"] = int(anti_loop.get("guard_block_count", 0)) + 1
        guidance = (
            f"Anti-loop guard blocked this action before execution. Do not retry it in the same unchanged state. "
            f"{('Next action should be ' + must_do_action + '. ') if must_do_action else ''}"
            "Switch to a different local goal, or use a nearby restore point if available."
        )
        return {
            "blocked": True,
            "reason": reason,
            "guidance": guidance,
            "blocked_action_patterns": blocked_patterns,
            "must_do_action": must_do_action,
            "recommended_policy": "force_restore" if must_do_action else "switch_local_goal",
            "recommended_restore_step": (
                int(last_stuck_state["recommended_restore_step"])
                if must_do_action and last_stuck_state.get("recommended_restore_step") is not None
                else None
            ),
            "guard_block_count": int(anti_loop.get("guard_block_count", 0)),
            "same_state_count": int(anti_loop.get("same_state_count", 0)),
            "same_action_count": int(anti_loop.get("same_action_count", 0)),
            "same_action_family_count": int(anti_loop.get("same_action_family_count", 0)),
            "no_progress_count": int(anti_loop.get("no_progress_count", 0)),
            "low_information_action_count": int(anti_loop.get("low_information_action_count", 0)),
        }

    def _build_guard_block_response(
        self,
        session: Dict[str, Any],
        action_text: str,
        observation: Any,
        guard_res: Dict[str, Any],
    ) -> Dict[str, Any]:
        env = session["env"]
        current_score = self._safe_number(session.get("current_score"), 0)
        best_score = self._safe_number(session.get("best_score"), 0)
        full_score = self._safe_number(session.get("full_score"), 0)
        progress = self._safe_number(session.get("progress"), 0)
        best_progress = self._safe_number(session.get("best_progress"), progress)
        moves = self._safe_number((session.get("last_info") or {}).get("moves"), session.get("steps_taken", 0))
        checkpoint_count = self._safe_int(self._call_if_exists(env, "get_checkpoint_count"), 0)
        total_restores = self._safe_int(self._call_if_exists(env, "get_total_restores"), 0)
        suggested_restore_steps = self._suggest_restore_steps(checkpoint_count)
        parser_feedback = {
            "is_parser_issue": False,
            "category": str(guard_res.get("parser_category") or "anti_loop_blocked"),
            "confidence": 1.0,
            "matched_text": str(guard_res.get("parser_category") or "anti_loop_guard"),
            "observation_unchanged": True,
            "local_repair_focus": guard_res.get("reason", ""),
            "suggested_actions": [guard_res["must_do_action"]] if guard_res.get("must_do_action") else [],
            "retry_policy": "Do not retry the blocked action in the same unchanged state. Change branch immediately.",
        }
        stuck_state = {
            "is_stuck": True,
            "severity": "critical" if guard_res.get("must_do_action") else "branch",
            "same_state_count": guard_res.get("same_state_count", 0),
            "same_action_count": guard_res.get("same_action_count", 0),
            "same_action_family_count": guard_res.get("same_action_family_count", 0),
            "no_progress_count": guard_res.get("no_progress_count", 0),
            "low_information_action_count": guard_res.get("low_information_action_count", 0),
            "blocked_action_patterns": guard_res.get("blocked_action_patterns", []),
            "recommended_policy": guard_res.get("recommended_policy", "switch_local_goal"),
            "recommended_restore_step": guard_res.get("recommended_restore_step"),
            "reason": guard_res.get("reason", ""),
            "guidance": guard_res.get("guidance", ""),
            "anti_loop_blocked": True,
            "must_do_action": guard_res.get("must_do_action", ""),
        }
        session.setdefault("anti_loop", {})["last_stuck_state"] = stuck_state
        trusted_state_snapshot = self._build_trusted_state_snapshot(
            session=session,
            action_text=action_text,
            observation_before=observation,
            observation_after=observation,
            current_score=current_score,
            best_score=best_score,
            full_score=full_score,
            score_rate=(best_score / full_score) if full_score > 0 else 0.0,
            progress=progress,
            best_progress=best_progress,
            moves=moves,
            reward=0.0,
            done=bool(session.get("done")),
            won=bool(progress >= 100 or (full_score > 0 and current_score >= full_score)),
        )
        trusted_state_snapshot["action_executed"] = False
        trusted_state_snapshot["anti_loop_blocked"] = True
        return {
            "status": "success",
            "dataset": self.DATASET_KEY,
            "env_name": session["env_name"],
            "action": action_text,
            "action_executed": False,
            "anti_loop_blocked": True,
            "session_started": False,
            "session_closed": False,
            "message": guard_res.get("message") or "Guard blocked action before execution.",
            "steps_taken": session["steps_taken"],
            "done": bool(session.get("done")),
            "won": bool(progress >= 100 or (full_score > 0 and current_score >= full_score)),
            "lost": False,
            "reward": 0.0,
            "best_score": best_score,
            "current_score": current_score,
            "full_score": full_score,
            "score_rate": (best_score / full_score) if full_score > 0 else 0.0,
            "progress": progress,
            "best_progress": best_progress,
            "best_progress_step": session.get("best_progress_step"),
            "best_progress_action": session.get("best_progress_action"),
            "moves": moves,
            "checkpoint_count": checkpoint_count,
            "total_restores": total_restores,
            "suggested_restore_steps": suggested_restore_steps,
            "restore_guidance": (
                "If you need to backtrack, prefer restore <step_id> using one of suggested_restore_steps "
                "instead of restarting the whole run. Do not restore to a branch with lower progress than best_progress "
                "unless the current branch is dead, lost, or clearly irrecoverable."
                if suggested_restore_steps else
                "No restore checkpoints are available yet."
            ),
            "with_clues": bool(session.get("with_clues", False)),
            "observation_before": self._as_text(observation),
            "observation": self._as_text(observation),
            "feedback": self._as_text(observation),
            "markers": (session.get("last_info") or {}).get("markers"),
            "label_vectors": self._normalize_label_vectors((session.get("last_info") or {}).get("label_vectors")),
            "feelies": "",
            "parser_feedback": parser_feedback,
            "stuck_state": stuck_state,
            "blocked_action_patterns": stuck_state.get("blocked_action_patterns", []),
            "anti_loop_guidance": stuck_state.get("guidance", ""),
            "must_do_action": guard_res.get("must_do_action", ""),
            "guard_block_count": guard_res.get("guard_block_count", 0),
            "trusted_state_snapshot": trusted_state_snapshot,
            "trusted_state_json": json.dumps(trusted_state_snapshot, ensure_ascii=False, sort_keys=True),
        }

    def _ensure_runtime(self, textquests_root: Optional[str]) -> Dict[str, Any]:
        root_res = self._resolve_textquests_root(textquests_root)
        if root_res["status"] != "success":
            return root_res

        root = root_res["textquests_root"]
        cached = self._runtime_cache.get(root)
        if cached is not None:
            return cached

        try:
            game_info_mod = self._load_module_from_path(
                "textquests_runtime_game_info",
                os.path.join(root, "src", "game_info.py"),
            )
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to load TextQuests game metadata: {e}",
                "textquests_root": root,
            }

        tasks = sorted(
            [
                name
                for name in getattr(game_info_mod, "game_info", {}).keys()
                if os.path.isdir(os.path.join(root, "data", "jiminy-cricket", name))
            ]
        )
        runtime = {
            "status": "success",
            "textquests_root": root,
            "data_root": os.path.join(root, "data", "jiminy-cricket"),
            "game_info": getattr(game_info_mod, "game_info"),
            "tasks": tasks,
            "TextQuestsEnv": None,
            "env_load_error": None,
        }

        try:
            previous_game_info_mod = sys.modules.get("src.game_info")
            sys.modules["src.game_info"] = game_info_mod
            try:
                env_mod = self._load_module_from_path(
                    "textquests_runtime_env",
                    os.path.join(root, "src", "textquests_env.py"),
                )
                runtime["TextQuestsEnv"] = getattr(env_mod, "TextQuestsEnv")
            finally:
                if previous_game_info_mod is not None:
                    sys.modules["src.game_info"] = previous_game_info_mod
                else:
                    sys.modules.pop("src.game_info", None)
        except Exception as e:
            runtime["env_load_error"] = str(e)

        self._runtime_cache[root] = runtime
        return runtime

    def _resolve_textquests_root(self, textquests_root: Optional[str]) -> Dict[str, Any]:
        candidates: List[str] = []
        if textquests_root:
            candidates.append(textquests_root)

        env_root = os.environ.get("TEXTQUESTS_ROOT")
        if env_root:
            candidates.append(env_root)

        file_based = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "textquests")
        )
        candidates.append(file_based)
        candidates.append(os.path.abspath(os.path.join(self.workspace_root, "textquests")))
        candidates.append(os.path.abspath(os.path.join(self.workspace_root, "..", "textquests")))
        candidates.append(os.path.abspath(os.path.join(self.workspace_root, "..", "..", "textquests")))

        checked: List[str] = []
        for raw in candidates:
            if not raw:
                continue
            p = os.path.abspath(raw)
            if p in checked:
                continue
            checked.append(p)
            if (
                os.path.isfile(os.path.join(p, "play_textquests.py"))
                and os.path.isfile(os.path.join(p, "src", "textquests_env.py"))
                and os.path.isdir(os.path.join(p, "data", "jiminy-cricket"))
            ):
                return {"status": "success", "textquests_root": p}

        return {
            "status": "error",
            "message": "Unable to locate textquests root.",
            "checked_paths": checked,
        }

    @staticmethod
    def _load_module_from_path(module_name: str, file_path: str):
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create module spec for {file_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _call_if_exists(obj: Any, method_name: str):
        if obj is None or not hasattr(obj, method_name):
            return None
        try:
            return getattr(obj, method_name)()
        except Exception:
            return None

    @staticmethod
    def _normalize_label_vectors(value: Any) -> List[Any]:
        if not isinstance(value, list):
            return []
        normalized: List[Any] = []
        for item in value:
            if hasattr(item, "tolist"):
                try:
                    normalized.append(item.tolist())
                    continue
                except Exception:
                    pass
            normalized.append(item)
        return normalized

    @staticmethod
    def _safe_number(value: Any, default: float) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        try:
            if value is None:
                return default
            return int(value)
        except Exception:
            return default

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
    def _extract_observation_title(observation: str) -> str:
        for line in (observation or "").splitlines():
            text = line.strip()
            if text:
                return text[:120]
        return ""

    @staticmethod
    def _truncate_text(text: str, limit: int) -> str:
        normalized = " ".join((text or "").split())
        if len(normalized) <= limit:
            return normalized
        return normalized[: max(limit - 3, 0)] + "..."

    def _build_state_key(self, observation: Any, current_score: float, progress: float) -> str:
        observation_text = self._as_text(observation)
        observation_title = self._extract_observation_title(observation_text)
        normalized_observation = self._normalize_feedback_text(observation_text)
        return "|".join(
            [
                observation_title[:80],
                normalized_observation[:220],
                f"score:{self._safe_number(current_score, 0):.4f}",
                f"progress:{self._safe_number(progress, 0):.4f}",
            ]
        )

    @staticmethod
    def _normalize_feedback_text(text: str) -> str:
        return " ".join((text or "").lower().split())

    @staticmethod
    def _action_family(action_text: str) -> str:
        action = " ".join((action_text or "").lower().split())
        if action in {"north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest", "up", "down", "in", "out", "go north", "go south", "go east", "go west"}:
            return "movement"
        if action in {"look", "l"}:
            return "look"
        if action in {"inventory", "i"}:
            return "inventory"
        if action.startswith("examine ") or action.startswith("x "):
            return "examine"
        if action.startswith("search "):
            return "search"
        if action.startswith("restore "):
            return "restore"
        if action == "restart":
            return "restart"
        if action.startswith("take "):
            return "take"
        if action.startswith("drop "):
            return "drop"
        return action.split(" ", 1)[0] if action else ""

    @staticmethod
    def _parse_restore_step(action_text: str) -> Optional[int]:
        action = " ".join((action_text or "").strip().lower().split())
        match = re.fullmatch(r"restore\s+(-?\d+)", action)
        if not match:
            return None
        try:
            return int(match.group(1))
        except Exception:
            return None

    @staticmethod
    def _matches_blocked_pattern(action_text: str, blocked_patterns: List[str]) -> bool:
        action = " ".join((action_text or "").strip().lower().split())
        family = TextQuestsTools._action_family(action_text)
        for pattern in blocked_patterns or []:
            normalized = " ".join((pattern or "").strip().lower().split())
            if not normalized:
                continue
            if normalized == action or normalized == family:
                return True
        return False

    @staticmethod
    def _is_low_information_action(action_text: str) -> bool:
        family = TextQuestsTools._action_family(action_text)
        return family in {"look", "inventory", "examine", "search"}

    @staticmethod
    def _first_matching_phrase(text: str, phrases: List[str]) -> str:
        for phrase in phrases:
            if phrase in text:
                return phrase
        return ""

    @staticmethod
    def _precondition_repair_actions(action_text: str) -> List[str]:
        action_lower = (action_text or "").lower()
        if action_lower in {"north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest", "up", "down", "in", "out"}:
            return ["stand", "open door", action_text]
        return ["stand", "get up", action_text]

    @staticmethod
    def _specificity_repair_actions(action_text: str) -> List[str]:
        action = (action_text or "").strip()
        if action == "withdraw 500":
            return ["withdraw 500 dollars", "withdraw $500", "withdraw 500 from passbook"]
        return [action, f"{action} carefully", f"{action} with exact object"]

    @staticmethod
    def _syntax_repair_actions(action_text: str) -> List[str]:
        action = (action_text or "").strip()
        if action == "say yes":
            return ["yes", "accept", "agree"]
        if action == "withdraw 500":
            return ["withdraw 500 dollars", "withdraw $500", "show passbook to teller"]
        if "," in action:
            first_part = action.split(",", 1)[0].strip()
            second_part = action.split(",", 1)[1].strip()
            return [first_part, second_part, action.replace(",", " and ")]
        words = action.split()
        if len(words) > 2:
            return [" ".join(words[:2]), words[0], action]
        return [action, words[0] if words else action, action]

    @staticmethod
    def _unknown_object_repair_actions(action_text: str) -> List[str]:
        return ["look", "inventory", action_text]

    @staticmethod
    def _movement_repair_actions(action_text: str) -> List[str]:
        action_lower = (action_text or "").lower()
        nearby_map = {
            "north": ["look", "east", "west"],
            "south": ["look", "east", "west"],
            "east": ["look", "north", "south"],
            "west": ["look", "north", "south"],
            "northeast": ["look", "north", "east"],
            "northwest": ["look", "north", "west"],
            "southeast": ["look", "south", "east"],
            "southwest": ["look", "south", "west"],
        }
        return nearby_map.get(action_lower, ["look", "examine surroundings", action_text])

    @staticmethod
    def _suggest_restore_steps(checkpoint_count: int) -> List[int]:
        if checkpoint_count <= 0:
            return []
        last_step = checkpoint_count - 1
        start_step = max(0, last_step - 2)
        return list(range(last_step, start_step - 1, -1))
