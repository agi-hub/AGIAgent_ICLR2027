#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wiki garbage collector: compacts, prunes, and deduplicates wiki knowledge.

Called after each curation phase to keep the wiki lean:
  1. Experience consolidation: merge per-date experience files into one
     per-game summary, keeping only the best-score attempt and key warnings.
  2. World-model pruning: archive low-information location/object pages
     (stubs with < MIN_USEFUL_LINES of content) to an _archive/ directory.
  3. Knowledge dedup: if multiple knowledge files exist for the same game
     slug (non-standard names), merge their score-progression steps into
     the canonical score_recipe_<slug>.md.

Design principles:
  - NEVER delete score-progression knowledge (Verified steps).
  - Archived files are moved, not deleted — knowledge is recoverable.
  - All operations are logged to wiki_root/_gc_log.md for auditability.
"""

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

MIN_USEFUL_LINES = 4  # pages with fewer body lines (excl. YAML) are stubs
MIN_USEFUL_CHARS = 200  # pages with fewer total chars are stubs


def _read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _non_empty_lines(text: str) -> int:
    """Count non-empty, non-frontmatter lines."""
    lines = text.splitlines()
    # Skip YAML front-matter
    start = 0
    if text.strip().startswith("---"):
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                start = i + 1
                break
    return sum(1 for line in lines[start:] if line.strip())


def _extract_best_score(content: str) -> Optional[float]:
    """Try to find a best score number in experience/knowledge content."""
    # Patterns: "Best score: 70", "score 70/350", "Best: 70", "+70 points"
    patterns = [
        r"(?:best(?:\s+score)?|best_score)\s*[:=]?\s*(\d+)",
        r"score\s*(?:of\s+)?(\d+)\s*/",
        r"final\s+score\s*[:=]?\s*(\d+)",
        r"attempt\s+\d+\s+score\s*[:=]?\s*(\d+)",
    ]
    best = None
    for pat in patterns:
        for m in re.finditer(pat, content, re.IGNORECASE):
            try:
                val = float(m.group(1))
                if best is None or val > best:
                    best = val
            except (ValueError, IndexError):
                continue
    return best


def _extract_game_slug(rel_path: str, filename: str) -> str:
    """Extract game slug from filename like 'score_recipe_zork1.md' or 'zork1.md'."""
    name = filename.replace(".md", "")
    # Strip common prefixes
    for prefix in ("score_recipe_", "score_progression_", "score_progression_steps_",
                    "winning_strategy_", "scoring_actions_", "early_items_",
                    "initial_exploration_", "score_sequences_", "score_",
                    "lethal_commands_", "cure_headache_", "entering_bar_",
                    "boulder_puzzle_", "garbage_ticket_recovery_",
                    "chant_system_", "item_acquisition_recipes_",
                    "wireless_discovery_", "submarine_navigation_",
                    "candygram_delivery_recipe_"):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def consolidate_experiences(wiki_root: Path) -> Dict[str, int]:
    """Merge per-date experience files into one consolidated file per game.

    Returns stats: {files_merged, files_removed, games_updated}
    """
    exp_root = wiki_root / "experiences"
    if not exp_root.is_dir():
        return {"files_merged": 0, "files_removed": 0, "games_updated": 0}

    # Collect all experience files grouped by game slug
    # Structure: experiences/<date>/<game_slug>.md  OR  experiences/<descriptive>_<game_slug>.md
    game_experiences: Dict[str, List[Tuple[Path, str, float]]] = {}  # slug -> [(path, content, best_score)]

    # Date-organized files: experiences/YYYY-MM-DD/<slug>.md
    for entry in sorted(exp_root.iterdir()):
        if not entry.is_dir():
            # Top-level experience file like 'guard_death_ballyhoo.md'
            # Try to extract game slug from filename
            slug = _extract_game_slug("", entry.name)
            if slug and slug != entry.stem:
                content = _read_file(entry)
                if content.strip():
                    score = _extract_best_score(content) or 0.0
                    game_experiences.setdefault(slug, []).append((entry, content, score))
            continue

        # Date directory
        for f in entry.glob("*.md"):
            slug = f.stem
            content = _read_file(f)
            if content.strip():
                score = _extract_best_score(content) or 0.0
                game_experiences.setdefault(slug, []).append((f, content, score))

    stats = {"files_merged": 0, "files_removed": 0, "games_updated": 0}

    for slug, entries in game_experiences.items():
        if len(entries) <= 1:
            continue  # Nothing to merge

        # Sort by best score descending — keep best content first
        entries.sort(key=lambda x: x[2], reverse=True)

        # Build consolidated file: best attempt full + warnings from others
        best_path, best_content, best_score = entries[0]
        consolidated_lines = [
            f"# Experience Log: {slug} (consolidated {datetime.now().strftime('%Y-%m-%d')})",
            f"Best score across attempts: {best_score}",
            "",
            "## Best Attempt (Full Detail)",
            best_content.strip(),
            "",
        ]

        # Extract key warnings from other attempts (only if they add new info)
        for path, content, score in entries[1:]:
            warnings = _extract_warnings(content)
            if warnings:
                consolidated_lines.append(f"## Warnings from {path.parent.name}/{path.name}")
                consolidated_lines.append(warnings)
                consolidated_lines.append("")

        consolidated = "\n".join(consolidated_lines)

        # Write consolidated file to experiences/<slug>_consolidated.md
        consolidated_path = exp_root / f"{slug}_consolidated.md"
        _write_file(consolidated_path, consolidated)

        # Remove original per-date files
        for path, _, _ in entries:
            try:
                path.unlink()
                stats["files_removed"] += 1
            except Exception:
                pass

        stats["files_merged"] += len(entries)
        stats["games_updated"] += 1

    return stats


def _extract_warnings(content: str) -> str:
    """Extract key warnings/mistakes from an experience file."""
    lines = []
    in_warning = False
    for line in content.splitlines():
        lower = line.lower().strip()
        # Start capturing at warning/mistake/death sections
        if any(kw in lower for kw in ("## warning", "## mistake", "## key mistake",
                                       "## death", "## key lesson", "## what did not")):
            in_warning = True
            lines.append(line)
            continue
        if in_warning:
            if lower.startswith("## ") and not any(kw in lower for kw in ("warning", "mistake", "death", "lesson")):
                break  # Next section
            lines.append(line)
    return "\n".join(lines).strip() if lines else ""


def prune_world_model(wiki_root: Path) -> Dict[str, int]:
    """Archive low-information location/object pages to _archive/.

    Returns stats: {pages_archived, pages_kept}
    """
    stats = {"pages_archived": 0, "pages_kept": 0}

    for subdir in ("world_model/locations", "world_model/objects"):
        section_root = wiki_root / subdir
        if not section_root.is_dir():
            continue

        archive_root = wiki_root / subdir.replace("world_model/", "world_model/_archive_")
        archive_root.mkdir(parents=True, exist_ok=True)

        for f in sorted(section_root.glob("*.md")):
            content = _read_file(f)
            nel = _non_empty_lines(content)
            nchar = len(content.strip())

            if nel < MIN_USEFUL_LINES or nchar < MIN_USEFUL_CHARS:
                # Archive: move to _archive/
                try:
                    shutil.move(str(f), str(archive_root / f.name))
                    stats["pages_archived"] += 1
                except Exception:
                    pass
            else:
                stats["pages_kept"] += 1

    return stats


def deduplicate_knowledge(wiki_root: Path) -> Dict[str, int]:
    """Merge non-standard knowledge files into canonical score_recipe_<slug>.md.

    If files like 'score_progression_zork3.md' exist alongside 'score_recipe_zork3.md',
    merge the non-standard file's verified steps into the canonical one, then remove
    the non-standard file.

    Returns stats: {files_merged, files_removed}
    """
    stats = {"files_merged": 0, "files_removed": 0}
    knowledge_root = wiki_root / "knowledge"
    if not knowledge_root.is_dir():
        return stats

    # Group knowledge files by game slug
    files_by_slug: Dict[str, List[Path]] = {}
    for f in sorted(knowledge_root.glob("*.md")):
        if f.name.startswith("_"):
            continue
        slug = _extract_game_slug("", f.name)
        files_by_slug.setdefault(slug, []).append(f)

    for slug, files in files_by_slug.items():
        if len(files) <= 1:
            continue

        # Find canonical file: score_recipe_<slug>.md
        canonical = knowledge_root / f"score_recipe_{slug}.md"
        others = [f for f in files if f != canonical]

        if not canonical.exists():
            # If no canonical, pick the one with highest content as canonical
            others_sorted = sorted(files, key=lambda f: len(_read_file(f)), reverse=True)
            canonical = others_sorted[0]
            others = others_sorted[1:]

        if not others:
            continue

        canon_content = _read_file(canonical)

        for other in others:
            other_content = _read_file(other)
            # Extract score-progression data not already in canonical
            new_steps = _extract_new_score_steps(other_content, canon_content)
            if new_steps:
                appendix = f"\n\n## Additional Steps from {other.name}\n\n{new_steps}\n"
                _write_file(canonical, canon_content + appendix)
                canon_content += appendix  # update for next iteration
                stats["files_merged"] += 1
            try:
                other.unlink()
                stats["files_removed"] += 1
            except Exception:
                pass

    return stats


def _extract_new_score_steps(source: str, target: str) -> str:
    """Extract score-progression lines from source not present in target."""
    source_lines = []

    # Match any table row containing a +N pattern or score-like content
    score_row_re = re.compile(r'\+\s*\d+', re.IGNORECASE)
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        # Skip separator rows like |---|---|
        if re.match(r'^[\s|:-]+$', stripped):
            continue
        # Keep rows with score deltas (+N) that aren't already in target
        if score_row_re.search(stripped) and stripped not in target:
            source_lines.append(line)
        # Also keep header rows containing score/step/action/command
        elif any(kw in stripped.lower() for kw in ("score", "step", "action", "command", "points", "cumulative")):
            if stripped not in target:
                source_lines.append(line)

    # Also extract standalone "+N points" annotations outside tables
    for line in source.splitlines():
        stripped = line.strip()
        if re.search(r'\+\d+\s*(?:points?|pts?)', stripped, re.IGNORECASE):
            if stripped not in target and stripped not in [l.strip() for l in source_lines]:
                source_lines.append(line)

    return "\n".join(source_lines).strip()


def run_wiki_gc(wiki_root_str: str) -> Dict[str, any]:
    """Run full garbage collection cycle on a wiki root.

    Returns a summary dict with stats from each phase.
    """
    wiki_root = Path(wiki_root_str)
    if not wiki_root.is_dir():
        return {"error": f"wiki_root not found: {wiki_root}"}

    log_lines = [f"# Wiki GC Log — {datetime.now().isoformat()}", ""]

    exp_stats = consolidate_experiences(wiki_root)
    log_lines.append(f"## Experience Consolidation")
    log_lines.append(f"- Files merged: {exp_stats['files_merged']}")
    log_lines.append(f"- Files removed (per-date originals): {exp_stats['files_removed']}")
    log_lines.append(f"- Games updated: {exp_stats['games_updated']}")
    log_lines.append("")

    prune_stats = prune_world_model(wiki_root)
    log_lines.append(f"## World Model Pruning")
    log_lines.append(f"- Pages archived (low-info stubs): {prune_stats['pages_archived']}")
    log_lines.append(f"- Pages kept: {prune_stats['pages_kept']}")
    log_lines.append("")

    dedup_stats = deduplicate_knowledge(wiki_root)
    log_lines.append(f"## Knowledge Deduplication")
    log_lines.append(f"- Files merged into canonical: {dedup_stats['files_merged']}")
    log_lines.append(f"- Duplicate files removed: {dedup_stats['files_removed']}")
    log_lines.append("")

    # Remove stale embedding cache (force rebuild on next read)
    index_cache = wiki_root / ".wiki_index.npz"
    if index_cache.exists():
        try:
            index_cache.unlink()
            log_lines.append("Embedding index cache cleared (will rebuild on next query).")
        except Exception:
            pass

    # Write GC log
    log_path = wiki_root / "_gc_log.md"
    _write_file(log_path, "\n".join(log_lines))

    return {
        "experience_consolidation": exp_stats,
        "world_model_pruning": prune_stats,
        "knowledge_deduplication": dedup_stats,
        "log_path": str(log_path),
    }


if __name__ == "__main__":
    import sys
    root = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("AGIA_WIKI_ROOT", "")
    if not root:
        print("Usage: python wiki_gc.py <wiki_root>  or set AGIA_WIKI_ROOT")
        sys.exit(1)
    result = run_wiki_gc(root)
    print(f"Wiki GC complete: {result}")
