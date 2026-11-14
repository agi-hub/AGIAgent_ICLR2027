#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Interactive Jericho game player with bilingual (EN/ZH) display and LLM translation.

Usage:
    python apps/tale_jericho/play.py
    python apps/tale_jericho/play.py --game JerichoEnvZork1
    python apps/tale_jericho/play.py --no-translate

You act as the agent: pick a game, read observations, type actions (or pick from
admissible commands), and the game responds. Observations are translated to
Chinese inline using the LLM API from config.txt. A trajectory.jsonl is written
to the output directory for later analysis (compatible with phase_m consumption).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Paths ────────────────────────────────────────────────────────────────────
APP_DIR = Path(__file__).resolve().parent
AGI_ROOT = APP_DIR.parent.parent.resolve()
WORKSPACE_ROOT = AGI_ROOT.parent.resolve()
CONFIG_FILE = APP_DIR / "config.txt"
GLOBAL_CONFIG_FILE = AGI_ROOT / "config" / "config.txt"

if str(AGI_ROOT) not in sys.path:
    sys.path.insert(0, str(AGI_ROOT))

# ── ANSI colors ──────────────────────────────────────────────────────────────
C_RESET = "\033[0m"
C_DIM = "\033[2m"
C_BOLD = "\033[1m"
C_CYAN = "\033[36m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_RED = "\033[31m"
C_MAGENTA = "\033[35m"
C_BLUE = "\033[34m"
C_BG_BLUE = "\033[44;30m"


def _term_width() -> int:
    try:
        return os.get_terminal_size().columns
    except Exception:
        return 80


def _hr(char: str = "─") -> str:
    return char * _term_width()


# ── Config loading ───────────────────────────────────────────────────────────
def _parse_config(path: Path) -> Dict[str, str]:
    """Parse active (non-commented) key=value pairs from a config file."""
    cfg: Dict[str, str] = {}
    if not path.exists():
        return cfg
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            k = k.strip().lower()
            v = v.strip()
            if k in ("api_key", "api_base", "model", "max_tokens"):
                cfg[k] = v
    return cfg


def load_llm_config() -> Dict[str, str]:
    """Load LLM config for translation from config/config.txt (global), falling
    back to apps/tale_jericho/config.txt.

    Translation uses the OpenAI-compatible coding-plan endpoint
    (open.bigmodel.cn/api/coding/paas/v4/chat/completions) with the api_key
    from config/config.txt, and the glm-4.5-flash model for speed.
    """
    # Prefer global config/config.txt (has the working coding-plan API key)
    cfg = _parse_config(GLOBAL_CONFIG_FILE)
    if not cfg.get("api_key"):
        cfg = _parse_config(CONFIG_FILE)

    # Override api_base and model for translation: use the fast coding-plan endpoint
    cfg["api_base"] = "https://open.bigmodel.cn/api/coding/paas/v4"
    cfg["model"] = "glm-4.5-flash"
    return cfg


# ── LLM translation ──────────────────────────────────────────────────────────
class Translator:
    """Translates English text to Chinese using the OpenAI-compatible chat API.

    Uses config/config.txt's api_key with the coding-plan endpoint
    (open.bigmodel.cn/api/coding/paas/v4) and glm-4.5-flash for speed.
    15s per-call timeout, one retry. Translation is non-blocking on failure.
    """

    # Override the config model for translation (faster than glm-4.7 which
    # times out on this router).
    TRANSLATE_MODEL = "glm-4.5-flash"
    CALL_TIMEOUT = 15  # seconds per API call
    MAX_RETRIES = 2    # total attempts

    def __init__(self, config: Dict[str, str]):
        self.config = config
        self.enabled = bool(config.get("api_key") and config.get("api_base"))
        self._cache: Dict[str, str] = {}

    def translate(self, text: str) -> str:
        if not self.enabled or not text or not text.strip():
            return ""
        cache_key = text[:500]
        if cache_key in self._cache:
            return self._cache[cache_key]
        result = ""
        for attempt in range(self.MAX_RETRIES):
            try:
                result = self._call_api(text)
                if result and result.strip():
                    break
            except Exception:
                result = ""
                continue
        self._cache[cache_key] = result
        return result

    def _call_api(self, text: str) -> str:
        import urllib.request

        api_base = self.config["api_base"].rstrip("/")
        url = f"{api_base}/chat/completions"
        payload = {
            "model": self.TRANSLATE_MODEL,
            "max_tokens": 1024,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a professional English-to-Chinese translator for text-adventure games. "
                        "Translate the user's text into natural, fluent Simplified Chinese. "
                        "Output ONLY the translation, nothing else."
                    ),
                },
                {"role": "user", "content": text[:2000]},
            ],
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config['api_key']}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.CALL_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"].strip()


# ── Trajectory writer ────────────────────────────────────────────────────────
class TrajectoryWriter:
    """Writes trajectory.jsonl compatible with phase_m consumption."""

    def __init__(self, path: Path):
        self.path = path
        self.round = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, action: str, result: Dict[str, Any], params: Optional[Dict] = None):
        self.round += 1
        record: Dict[str, Any] = {
            "round": self.round,
            "tool": "tale_jericho_action",
            "params": params or {"action": action},
        }
        for field in (
            "action", "observation", "observation_before", "feedback",
            "best_score", "current_score", "full_score", "score_rate",
            "moves", "done", "won", "lost", "steps_taken", "env_name",
        ):
            val = result.get(field)
            if val is not None and val != "":
                record[field] = val
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ── Display helpers ──────────────────────────────────────────────────────────
def display_result(result: Dict[str, Any], translator: Translator, translate: bool):
    """Render the game's response in a clean bilingual format."""
    obs = result.get("observation") or ""
    feedback = result.get("feedback") or ""
    adm = result.get("admissible_commands") or []

    # Score line
    best = result.get("best_score", 0)
    full = result.get("full_score", 0)
    cur = result.get("current_score", 0)
    moves = result.get("moves", 0)
    won = result.get("won", False)
    done = result.get("done", False)
    lost = result.get("lost", False)

    score_line = f"{C_BOLD}Score: {cur}/{full}  (best={best})  moves={moves}{C_RESET}"
    if won:
        score_line += f"  {C_GREEN}{C_BOLD}★ WON!{C_RESET}"
    if lost:
        score_line += f"  {C_RED}{C_BOLD}LOST{C_RESET}"
    if done and not won:
        score_line += f"  {C_YELLOW}DONE{C_RESET}"

    print()
    print(_hr("═"))
    print(score_line)
    print(_hr("─"))

    # Observation (English)
    if obs:
        print(f"{C_CYAN}{obs}{C_RESET}")

    # Translation (Chinese)
    if translate and translator.enabled and obs:
        print()
        zh = translator.translate(obs)
        if zh and not zh.startswith("[翻译失败"):
            print(f"{C_DIM}{zh}{C_RESET}")

    # Feedback if different from observation
    if feedback and feedback != obs and feedback.strip():
        print()
        print(f"{C_YELLOW}[Feedback] {feedback}{C_RESET}")
        if translate and translator.enabled:
            zh_fb = translator.translate(feedback)
            if zh_fb and not zh_fb.startswith("[翻译失败"):
                print(f"{C_DIM}{zh_fb}{C_RESET}")

    # Admissible commands (numbered for quick selection)
    adm_list: List[str] = []
    if adm and isinstance(adm, list) and len(adm) > 0:
        adm_list = [str(c) for c in adm if c][:20]
        print()
        print(f"{C_DIM}可执行命令 / Admissible commands:{C_RESET}")
        cols = max(1, _term_width() // 38)
        for i in range(0, len(adm_list), cols):
            row = adm_list[i : i + cols]
            parts = []
            for j, cmd in enumerate(row):
                idx = i + j + 1
                parts.append(f"{C_BOLD}[{idx}]{C_RESET}{C_GREEN} {cmd}{C_RESET}")
            print("  " + "  ".join(parts))

    print(_hr("═"))
    return adm_list

# ── Game selection ───────────────────────────────────────────────────────────
def select_game(tool, args_game: Optional[str]) -> str:
    """Show game list and let user pick."""
    ret = tool.tale_jericho_list_tasks()
    if ret.get("status") != "success":
        print(f"{C_RED}Failed to list tasks: {ret}{C_RESET}")
        sys.exit(1)
    tasks: List[str] = ret.get("tasks", [])
    if not tasks:
        print(f"{C_RED}No tasks available.{C_RESET}")
        sys.exit(1)

    if args_game:
        # match by full name or slug
        for t in tasks:
            if t.lower() == args_game.lower() or t.lower() == f"jerichoenv{args_game.lower()}":
                return t
        print(f"{C_RED}Game '{args_game}' not found.{C_RESET}")

    print(f"\n{C_BG_BLUE} TALE-Suite Jericho — 选择游戏 / Select Game {C_RESET}\n")
    for i, t in enumerate(tasks, 1):
        slug = t.replace("JerichoEnv", "")
        print(f"  {C_BOLD}{i:>3}.{C_RESET} {t:<30} {C_DIM}({slug}){C_RESET}")
    print()
    while True:
        choice = input(f"{C_BOLD}选择编号或游戏名 (1-{len(tasks)}): {C_RESET}").strip()
        if not choice:
            continue
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(tasks):
                return tasks[idx - 1]
        # try name match
        for t in tasks:
            if choice.lower() in t.lower():
                return t
        print(f"{C_RED}无效选择，请重试。{C_RESET}")


# ── Main game loop ───────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Interactive Jericho player with bilingual display")
    parser.add_argument("--game", type=str, default="", help="Game name or slug (skip menu)")
    parser.add_argument("--no-translate", action="store_true", help="Disable LLM translation")
    parser.add_argument("--output-dir", type=str, default="", help="Trajectory output dir (default: auto)")
    parser.add_argument("--tale-suite-root", type=str, default=os.environ.get("TALE_SUITE_ROOT", ""))
    args = parser.parse_args()

    os.environ.setdefault("TALE_SUITE_ROOT", "/home/agiagent/tale-suite")
    os.environ.setdefault("PYTHONWARNINGS", "ignore::UserWarning")

    # Load tool
    from src.tools.tale_jericho_tools import TaleJerichoTools

    tool = TaleJerichoTools(workspace_root=str(WORKSPACE_ROOT))

    # Load translator
    cfg = load_llm_config()
    translator = Translator(cfg)
    do_translate = not args.no_translate
    if do_translate and not translator.enabled:
        print(f"{C_YELLOW}⚠ LLM API not configured in config.txt, translation disabled.{C_RESET}")
        do_translate = False

    # Select game
    game = select_game(tool, args.game)

    # Setup output
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.output_dir:
        out_dir = Path(args.output_dir)
    else:
        out_dir = AGI_ROOT / "data" / "benchmark_results" / "jericho_play" / f"play_{ts}"
    traj_path = out_dir / "logs" / "trajectory.jsonl"
    traj = TrajectoryWriter(traj_path)

    print(f"\n{C_BG_BLUE} ▶ Playing: {game} {C_RESET}")
    print(f"{C_DIM}Trajectory: {traj_path}{C_RESET}")
    print(f"{C_DIM}Translation: {'ON' if do_translate else 'OFF'}{C_RESET}")
    print(f"{C_DIM}输入编号选动作，或直接键入命令 | Enter number to pick, or type command{C_RESET}")
    print(f"{C_DIM}'r'=restart  't'=toggle翻译  'q'=quit{C_RESET}\n")

    # Start game with 'look'
    result = tool.tale_jericho_action(action="look", env_name=game)
    traj.append("look", result, {"action": "look", "env_name": game})
    adm_list = display_result(result, translator, do_translate)

    # Game loop
    while True:
        if result.get("done"):
            print(f"\n{C_MAGENTA}{C_BOLD}游戏结束。Game over.{C_RESET}")
            break

        try:
            user_input = input(f"\n{C_BOLD}{C_BLUE}> {C_RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{C_YELLOW}退出。{C_RESET}")
            break

        if not user_input:
            continue

        cmd = user_input.lower()
        if cmd in ("q", "quit", "exit"):
            print(f"{C_YELLOW}退出。Trajectory saved to {traj_path}{C_RESET}")
            break
        if cmd in ("h", "help"):
            if adm_list:
                for i, c in enumerate(adm_list, 1):
                    print(f"  {C_BOLD}[{i}]{C_RESET} {C_GREEN}{c}{C_RESET}")
            else:
                print(f"{C_DIM}No admissible commands available.{C_RESET}")
            continue
        if cmd in ("r", "restart"):
            result = tool.tale_jericho_action(action="look", env_name=game, restart=True)
            traj.append("look", result, {"action": "look", "env_name": game, "restart": True})
            adm_list = display_result(result, translator, do_translate)
            continue
        if cmd in ("t", "translate"):
            do_translate = not do_translate
            print(f"{C_DIM}Translation: {'ON' if do_translate else 'OFF'}{C_RESET}")
            continue

        # Number input → pick from admissible commands
        action = user_input
        if user_input.isdigit():
            idx = int(user_input)
            if adm_list and 1 <= idx <= len(adm_list):
                action = adm_list[idx - 1]
            else:
                print(f"{C_RED}编号无效 (1-{len(adm_list)}){C_RESET}")
                continue

        # Execute action
        result = tool.tale_jericho_action(action=action)
        if result.get("status") != "success":
            err = result.get("message", "unknown error")
            print(f"{C_RED}✗ {err}{C_RESET}")
            continue
        traj.append(action, result, {"action": action})
        adm_list = display_result(result, translator, do_translate)

    print(f"\n{C_DIM}Trajectory saved: {traj_path}{C_RESET}")


if __name__ == "__main__":
    main()
