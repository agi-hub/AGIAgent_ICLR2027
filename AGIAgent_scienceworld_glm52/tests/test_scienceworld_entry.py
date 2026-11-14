#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Tests for the ScienceWorld wiki memory system and basic tool infrastructure."""

import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from src.tools.scienceworld_tools import ScienceworldTools
from src.wiki_memory import WikiMemoryReader

class ScienceworldActionTest(unittest.TestCase):
    def test_scienceworld_action_starts_session_and_returns_task_description(self):
        """Verify scienceworld_action initializes env and returns task_description."""
        tool = ScienceworldTools(workspace_root=tempfile.gettempdir())
        result = tool.scienceworld_action(
            action="look around",
            env_name="boil",
            variation_num=0,
            simplification_str="",
            env_step_limit=100,
        )
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["session_started"])
        self.assertIn("boil", result["task_description"].lower())
        self.assertEqual(result["env_name"], "boil")
        self.assertIn("observation", result)
        self.assertIn("admissible_commands", result)

    def test_scienceworld_action_executes_step(self):
        """Verify a follow-up action executes and updates score."""
        tool = ScienceworldTools(workspace_root=tempfile.gettempdir())
        tool.scienceworld_action(
            action="look around",
            env_name="boil",
            variation_num=0,
        )
        result = tool.scienceworld_action(action="look around")
        self.assertEqual(result["status"], "success")
        self.assertFalse(result["session_started"])  # already started


class WikiMemoryReadTest(unittest.TestCase):
    def test_wiki_memory_read_returns_empty_when_no_wiki(self):
        """wiki_memory_read returns success with 0 matches when wiki dir doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["AGIA_WIKI_ROOT"] = os.path.join(tmpdir, "nonexistent_wiki")
            try:
                reader = WikiMemoryReader(workspace_root=tmpdir)
                result = reader.wiki_memory_read(query="kitchen")
                self.assertEqual(result["status"], "success")
                self.assertEqual(result["total_matches"], 0)
            finally:
                os.environ.pop("AGIA_WIKI_ROOT", None)

    def test_wiki_memory_read_finds_matches(self):
        """wiki_memory_read finds pages containing the query string."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wiki_root = os.path.join(tmpdir, "test_wiki")
            os.makedirs(os.path.join(wiki_root, "world_model", "locations"))
            # Create a test page
            with open(os.path.join(wiki_root, "world_model", "locations", "kitchen.md"), "w") as f:
                f.write("# Kitchen\n\nThe kitchen has a stove and oven.\n")

            os.environ["AGIA_WIKI_ROOT"] = wiki_root
            try:
                reader = WikiMemoryReader(workspace_root=tmpdir)
                result = reader.wiki_memory_read(query="stove")
                self.assertEqual(result["status"], "success")
                self.assertGreaterEqual(result["total_matches"], 1)
                # Verify the match references kitchen.md
                found_kitchen = any("kitchen" in m.get("page", "") for m in result["matches"])
                self.assertTrue(found_kitchen)
            finally:
                os.environ.pop("AGIA_WIKI_ROOT", None)

    def test_wiki_memory_read_section_filter(self):
        """wiki_memory_read respects the section parameter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wiki_root = os.path.join(tmpdir, "test_wiki")
            os.makedirs(os.path.join(wiki_root, "knowledge"))
            os.makedirs(os.path.join(wiki_root, "world_model", "locations"))
            # Knowledge page
            with open(os.path.join(wiki_root, "knowledge", "boil-recipe.md"), "w") as f:
                f.write("# Boil Recipe\n\nUse stove to heat water.\n")
            # Location page
            with open(os.path.join(wiki_root, "world_model", "locations", "kitchen.md"), "w") as f:
                f.write("# Kitchen\n\nHas a stove.\n")

            os.environ["AGIA_WIKI_ROOT"] = wiki_root
            try:
                reader = WikiMemoryReader(workspace_root=tmpdir)
                # Search only in knowledge
                result = reader.wiki_memory_read(query="stove", section="knowledge")
                self.assertEqual(result["status"], "success")
                # Should find boil-recipe but not kitchen
                pages = [m.get("page", "") for m in result["matches"]]
                self.assertTrue(any("boil-recipe" in p for p in pages))
                self.assertFalse(any("kitchen" in p for p in pages))
            finally:
                os.environ.pop("AGIA_WIKI_ROOT", None)

    def test_wiki_memory_read_empty_query_returns_error(self):
        """wiki_memory_read rejects empty query."""
        reader = WikiMemoryReader()
        result = reader.wiki_memory_read(query="")
        self.assertEqual(result["status"], "error")


class RunnerHelpersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        module_path = Path(__file__).resolve().parents[1] / "apps" / "scienceworld" / "run_all_tasks.py"
        spec = importlib.util.spec_from_file_location("run_all_tasks_test", module_path)
        cls.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runner)

    def test_explore_requirement_has_no_curiosity_refs(self):
        """Phase 1 requirement must not reference trigger_curiosity or FLAG_CURIOSITY."""
        req = self.runner._explore_requirement(
            env_name="boil",
            variation_num=0,
            simplification_str="",
            env_step_limit=100,
        )
        self.assertNotIn("trigger_curiosity", req)
        self.assertNotIn("FLAG_CURIOSITY", req)
        self.assertNotIn("query_skill", req)
        self.assertIn("task_description", req)

    def test_solve_requirement_has_wiki_memory_read(self):
        """Phase 2 requirement must reference wiki_memory_read."""
        req = self.runner._solve_requirement(
            env_name="boil",
            variation_num=0,
            simplification_str="",
            env_step_limit=100,
        )
        self.assertIn("wiki_memory_read", req)
        self.assertNotIn("query_skill", req)
        self.assertNotIn("query_world_model", req)

    def test_baseline_requirement_has_no_memory_tools(self):
        """Baseline must not reference any memory tools."""
        req = self.runner._baseline_requirement(
            env_name="boil",
            variation_num=0,
            simplification_str="",
            env_step_limit=100,
        )
        self.assertNotIn("trigger_curiosity", req)
        self.assertNotIn("query_skill", req)

    def test_phase_m_requirement_has_wiki_root_and_log_path(self):
        """Phase M requirement must include wiki root and trajectory log path."""
        req = self.runner._phase_m_requirement(
            env_name="boil",
            variation_num=0,
            wiki_root="/tmp/test_wiki",
            trajectory_log_path="/tmp/test.log",
        )
        self.assertIn("/tmp/test_wiki", req)
        self.assertIn("/tmp/test.log", req)
        self.assertIn("wiki_memory_read", req)
        self.assertIn("knowledge", req)
        self.assertIn("world_model", req)


if __name__ == "__main__":
    unittest.main()
