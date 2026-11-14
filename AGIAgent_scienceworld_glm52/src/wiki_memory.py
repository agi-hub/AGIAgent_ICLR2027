#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Wiki memory reader with embedding-based semantic search.

Embedding backend (priority):
  1. API (SiliconFlow bge-m3) — if AGIA_WIKI_EMBEDDING_API_KEY is set
  2. Local sentence-transformers (all-MiniLM-L6-v2) — fallback

The wiki is a flat directory of Markdown files organized into three sections:
  - knowledge/      (skills, recipes, tactics)
  - experiences/    (key lessons learned per task, organized by date)
  - world_model/    (locations and objects)

Index is cached as .npz next to the wiki root. It auto-rebuilds when pages
are added/modified (detected via file mtime hash).
"""

import hashlib
import json
import os
import re
import threading
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

import numpy as np

# Lazy-loaded local model (used only when API is unavailable)
_MODEL = None
_MODEL_LOCK = threading.Lock()

_LOCAL_FALLBACK_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# --- API configuration (SiliconFlow bge-m3) ---
_API_BASE = os.environ.get("AGIA_WIKI_EMBEDDING_API_BASE", "https://api.siliconflow.cn/v1").rstrip("/") + "/embeddings"
_API_MODEL = "BAAI/bge-m3"


def _api_configured() -> bool:
    """Check if API embedding is configured (key present)."""
    return bool(os.environ.get("AGIA_WIKI_EMBEDDING_API_KEY", "").strip())


def _api_embed_batch(texts: List[str], batch_size: int = 32) -> Optional[np.ndarray]:
    """Embed a list of texts via SiliconFlow bge-m3 API.

    Returns normalized embeddings array of shape (len(texts), 1024), or None on failure.
    """
    api_key = os.environ.get("AGIA_WIKI_EMBEDDING_API_KEY", "").strip()
    if not api_key:
        return None

    all_embeddings: List[List[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        payload = json.dumps({"model": _API_MODEL, "input": batch}).encode("utf-8")
        req = urllib.request.Request(
            _API_BASE,
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            data_list = result.get("data") or []
            # Sort by index to preserve order
            data_list.sort(key=lambda d: d.get("index", 0))
            for d in data_list:
                all_embeddings.append(d["embedding"])
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError,
                KeyError, TypeError, OSError) as e:
            # API failed — caller will fall back to local model
            import sys
            print(f"[wiki_memory] API embedding failed (batch {i}): {e}", file=sys.stderr)
            return None

    if not all_embeddings:
        return None
    emb = np.array(all_embeddings, dtype=np.float32)
    # L2 normalize
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return emb / norms


def _get_local_model():
    """Get or lazily initialize the local sentence-transformers model."""
    global _MODEL
    if _MODEL is None:
        with _MODEL_LOCK:
            if _MODEL is None:
                from sentence_transformers import SentenceTransformer
                model_name = os.environ.get("AGIA_WIKI_EMBEDDING_MODEL", _LOCAL_FALLBACK_MODEL)
                _MODEL = SentenceTransformer(model_name)
    return _MODEL


def _local_embed_batch(texts: List[str]) -> np.ndarray:
    """Embed texts using local sentence-transformers model."""
    model = _get_local_model()
    return model.encode(texts, show_progress_bar=False, normalize_embeddings=True)


def embed_texts(texts: List[str]) -> np.ndarray:
    """Embed a list of texts using API (bge-m3) if configured, else local model.

    Returns normalized embeddings array of shape (len(texts), dim).
    """
    if not texts:
        return np.array([], dtype=np.float32)

    # Try API first
    if _api_configured():
        result = _api_embed_batch(texts)
        if result is not None:
            return result
        # Fall through to local on failure

    # Fallback: local model
    return _local_embed_batch(texts)


def _resolve_wiki_root() -> str:
    explicit = os.environ.get("AGIA_WIKI_ROOT", "").strip()
    if explicit and os.path.isdir(explicit):
        return os.path.abspath(explicit)
    project_root = os.getcwd()
    for _ in range(5):
        if os.path.exists(os.path.join(project_root, "agia.py")):
            break
        parent = os.path.dirname(project_root)
        if parent == project_root:
            break
        project_root = parent
    namespace = os.environ.get("AGIA_EXPERIMENT_NAMESPACE", "").strip()
    return os.path.join(project_root, "data", "default", "general", "wiki", namespace or "shared")


def _normalize_section(section: str) -> str:
    s = str(section or "").strip().lower()
    aliases = {
        "": "",
        "all": "",
        "knowledge": "knowledge",
        "skill": "knowledge",
        "skills": "knowledge",
        "experience": "experiences",
        "experiences": "experiences",
        "world": "world_model",
        "world_model": "world_model",
        "location": "world_model/locations",
        "locations": "world_model/locations",
        "object": "world_model/objects",
        "objects": "world_model/objects",
    }
    return aliases.get(s, s)


def _parse_confidence(content: str) -> float:
    """Estimate knowledge confidence from content signals.

    Returns a multiplier in [0.5, 1.0]:
    - Files with 'Confirmed In' entries (verified by multiple attempts) → 1.0
    - Files with score-progression data → 0.9
    - Files with 'Unverified' or 'Risky' markers but no confirmation → 0.7
    - Files with 'honesty' failure notes (score 0, explored) → 0.6
    - World model / experience files → 0.8 (neutral, useful for navigation)
    """
    lower = content.lower()

    # Count confirmed-in occurrences (proxy for verification count)
    confirmed_count = lower.count("confirmed in")
    if confirmed_count >= 3:
        return 1.0
    if confirmed_count >= 1:
        return 0.95

    # Has verified score-progression but no explicit confirmed-in
    if "verified" in lower and "score" in lower:
        return 0.9

    # Explicitly unverified / risky
    if "unverified" in lower or "risky" in lower:
        return 0.7

    # Honesty-rule failure: explored but scored 0
    if "scored 0" in lower or "score 0" in lower or "no score" in lower:
        return 0.6

    # Default: neutral (world_model, experiences with useful navigation data)
    return 0.8


def _extract_relevant_snippet(content: str, max_chars: int = 200, query: str = "") -> str:
    """Extract the most relevant snippet from a wiki page.

    Query-aware: if the query mentions death/fatal/avoid/danger, prefer DON'T.
    Otherwise prefer DO (the score path). Falls back to the highest-scoring
    section by simple keyword overlap with the query.
    """
    if not content:
        return ""

    # Parse sections by ## headers
    sections: List[tuple] = []  # (header, body)
    parts = re.split(r"(?=^## )", content, flags=re.MULTILINE)
    for part in parts:
        part = part.strip()
        if part.startswith("## "):
            header = part.split("\n", 1)[0]
            body = part[len(header):].strip()
            sections.append((header, body))
        elif part and not sections:
            # Content before first ## (e.g. front-matter, title)
            sections.append(("", part))

    if not sections:
        return content[:max_chars]

    query_lower = query.lower()
    danger_words = ("fatal", "death", "die", "kill", "avoid", "danger", "don't", "dont", "trap", "deadly", "warning", "stuck", "loop", "block")
    is_danger_query = any(w in query_lower for w in danger_words)

    # Build a quick lookup by header keyword
    def _header_key(header: str) -> str:
        h = header.lower()
        if "don't" in h or "dont" in h:
            return "dont"
        if "do " in h or h.endswith(" do"):
            return "do"
        if "need" in h:
            return "need"
        if "seed" in h:
            return "seed"
        return "other"

    section_map = {}
    for header, body in sections:
        section_map[_header_key(header)] = (header, body)

    # Choose the best section
    if is_danger_query and "dont" in section_map:
        header, body = section_map["dont"]
    elif "do" in section_map and not is_danger_query:
        header, body = section_map["do"]
    else:
        # Score by keyword overlap between query and section body
        query_words = set(re.findall(r"\w+", query_lower)) - {"the", "a", "an", "in", "on", "at", "to", "of", "for", "and", "or", "is", "are", "how", "what", "where", "game", "walkthrough", "solution", "sequence", "score", "progress"}
        best_section = None
        best_overlap = -1
        for header, body in sections:
            body_lower = body.lower()
            overlap = sum(1 for w in query_words if len(w) > 2 and w in body_lower)
            if overlap > best_overlap:
                best_overlap = overlap
                best_section = (header, body)
        if best_section:
            header, body = best_section
        else:
            header, body = sections[0]

    snippet = f"{header}\n{body}".strip()
    if len(snippet) > max_chars:
        snippet = snippet[:max_chars]
    return snippet


def _parse_applies_to(content: str) -> List[str]:
    """Extract the applies_to list from YAML front-matter."""
    if not content.startswith("---"):
        return []
    end = content.find("---", 3)
    if end < 0:
        return []
    front = content[3:end]
    for line in front.splitlines():
        line = line.strip()
        if line.lower().startswith("applies_to:"):
            val = line.split(":", 1)[1].strip()
            # Parse [Item1, Item2] or [Item1] format
            val = val.strip("[]")
            items = [x.strip().strip("'\"") for x in val.split(",") if x.strip()]
            return items
    return []


def _collect_wiki_pages(wiki_root: str, subdirectory: str = "") -> List[Dict[str, str]]:
    """Walk the wiki directory and return [{path, rel_path, title, content}] for all .md files."""
    search_path = os.path.join(wiki_root, subdirectory) if subdirectory else wiki_root
    if not os.path.isdir(search_path):
        return []
    pages = []
    for dirpath, dirs, files in os.walk(search_path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for fname in sorted(files):
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as fp:
                    content = fp.read()
            except Exception:
                continue
            rel_path = os.path.relpath(fpath, wiki_root)
            title = os.path.splitext(fname)[0].replace("_", " ").replace("-", " ")
            # Extract title from first markdown heading if present
            for line in content.split("\n"):
                stripped = line.strip()
                if stripped.startswith("# "):
                    title = stripped[2:].strip()
                    break
                if stripped and not stripped.startswith("---"):
                    break
            pages.append({"path": fpath, "rel_path": rel_path, "title": title, "content": content})
    return pages


def _load_or_build_index(wiki_root: str, pages: List[Dict[str, str]]):
    """Load or incrementally update the embedding index.

    Only embeds pages that are new or modified since last cache write.
    Deleted pages are removed from the index automatically.

    Cache format (.wiki_index.npz):
      embeddings: (N, dim) float32 array
      page_meta:  list of {path, rel_path, title}
      rel_paths:  array of rel_path strings (aligns with embeddings rows)
      mtimes:     array of mtime floats (aligns with embeddings rows)

    Returns (embeddings: np.ndarray, page_meta: list, file_hash: str).
    """
    if not pages:
        return None, [], ""

    index_path = os.path.join(wiki_root, ".wiki_index.npz")

    # Current file state: rel_path -> (mtime, page_dict)
    current: Dict[str, tuple] = {}
    for p in pages:
        try:
            mtime = os.path.getmtime(p["path"])
        except OSError:
            mtime = 0
        current[p["rel_path"]] = (mtime, p)

    # Reusable embeddings from cache: rel_path -> (embedding_vector, meta_dict)
    reused: Dict[str, tuple] = {}

    if os.path.exists(index_path):
        try:
            cached = np.load(index_path, allow_pickle=True)
            cached_pm = list(cached["page_meta"])
            cached_emb = cached["embeddings"]
            cached_mtimes = list(cached["mtimes"])
            # Build rel_path -> row index lookup
            cached_lookup = {pm["rel_path"]: i for i, pm in enumerate(cached_pm)}
            for rel_path, (mtime, _) in current.items():
                i = cached_lookup.get(rel_path)
                if i is not None and cached_mtimes[i] == mtime:
                    reused[rel_path] = (cached_emb[i], cached_pm[i])
        except Exception:
            pass  # cache corrupted or old format — rebuild from scratch

    # Determine pages needing (re)embedding
    to_embed: List[tuple] = []  # (rel_path, text)
    for rel_path, (mtime, p) in current.items():
        if rel_path not in reused:
            text = f"{p['title']}\n{p['content'][:500]}"
            to_embed.append((rel_path, text))

    if to_embed:
        texts = [t for _, t in to_embed]
        new_emb = embed_texts(texts)
        for i, (rel_path, _) in enumerate(to_embed):
            p = current[rel_path][1]
            reused[rel_path] = (new_emb[i], {"path": p["path"], "rel_path": rel_path, "title": p["title"]})

    # Assemble final arrays in stable order (sorted by rel_path for determinism)
    ordered_paths = sorted(current.keys())
    embeddings = np.array([reused[rp][0] for rp in ordered_paths], dtype=np.float32)
    page_meta = [reused[rp][1] for rp in ordered_paths]
    mtimes = [current[rp][0] for rp in ordered_paths]

    # Save cache
    try:
        np.savez(
            index_path,
            embeddings=embeddings,
            page_meta=np.array(page_meta, dtype=object),
            rel_paths=np.array(ordered_paths),
            mtimes=np.array(mtimes, dtype=np.float64),
        )
    except Exception:
        pass

    n_new = len(to_embed)
    n_reused = len(ordered_paths) - n_new
    if n_new > 0:
        import sys
        print(f"[wiki_memory] index: {n_reused} reused, {n_new} embedded ({len(ordered_paths)} total)", file=sys.stderr)

    return embeddings, page_meta, ""


class WikiMemoryReader:
    """Agent-facing wiki search tool using embedding-based semantic retrieval."""

    def __init__(self, workspace_root: str = ""):
        self.workspace_root = workspace_root or os.getcwd()
        self._query_count = 0
        self._max_queries = int(os.environ.get("AGIA_WIKI_MAX_QUERIES", "3"))

    def wiki_memory_read(
        self,
        query: str,
        section: str = "all",
        max_results: int = 3,
        _bypass_count: bool = False,
        **_: Any,
    ) -> Dict[str, Any]:
        """Search the wiki using embedding similarity.

        Cross-game filtering: if env variable JERICHO_ACTIVE_ENV is set,
        pages are filtered by their YAML front-matter 'applies_to' field.
        Pages matching the current game or tagged [all] get full score;
        pages from other games get score × 0.3 (deprioritized, not removed).

        Args:
            query: Natural-language search string.
            section: 'knowledge', 'experiences', 'world_model', 'locations', 'objects', or 'all'.
            max_results: Max number of pages to return.

        Returns:
            Dict with status, wiki_root, total_matches, and ranked page matches with content snippets.
        """

        if not _bypass_count:
            self._query_count += 1
        if not _bypass_count and self._query_count > self._max_queries:
            return {
                "status": "success",
                "message": f"Wiki query limit reached ({self._max_queries} per session). Rely on wiki_hint in action results.",
                "wiki_root": _resolve_wiki_root(),
                "total_matches": 0,
                "matches": [],
            }
        query_clean = str(query or "").strip()
        if not query_clean:
            return {
                "status": "error",
                "message": "query is required for wiki_memory_read",
                "wiki_root": _resolve_wiki_root(),
                "matches": [],
            }

        wiki_root = _resolve_wiki_root()
        if not os.path.isdir(wiki_root):
            return {
                "status": "success",
                "message": f"Wiki does not exist yet at {wiki_root}. No results.",
                "wiki_root": wiki_root,
                "total_matches": 0,
                "matches": [],
            }

        # Ablation mode: filter out disabled sections
        # AGIA_WIKI_ABLATION can be: "no_wiki", "no_world_model", "no_experiences", "no_knowledge"
        ablation = os.environ.get("AGIA_WIKI_ABLATION", "").strip().lower()
        if ablation == "no_wiki":
            return {
                "status": "success",
                "message": "Wiki disabled by ablation (no_wiki).",
                "wiki_root": wiki_root,
                "total_matches": 0,
                "matches": [],
            }
        requested = str(section or "").strip().lower()
        ablation_subdir = None  # if set, overrides normal normalize
        if ablation == "no_world_model" and requested in ("", "all", "world", "world_model", "location", "locations", "object", "objects"):
            if requested in ("", "all"):
                ablation_subdir = "knowledge"  # search remaining sections
            else:
                return {
                    "status": "success",
                    "message": "world_model disabled by ablation.",
                    "wiki_root": wiki_root,
                    "total_matches": 0,
                    "matches": [],
                }
        elif ablation == "no_experiences" and requested in ("", "all", "experience", "experiences"):
            if requested in ("", "all"):
                ablation_subdir = "knowledge"
            else:
                return {
                    "status": "success",
                    "message": "experiences disabled by ablation.",
                    "wiki_root": wiki_root,
                    "total_matches": 0,
                    "matches": [],
                }
        elif ablation == "no_knowledge" and requested in ("", "all", "knowledge", "skill", "skills"):
            if requested in ("", "all"):
                ablation_subdir = "experiences"
            else:
                return {
                    "status": "success",
                    "message": "knowledge disabled by ablation.",
                    "wiki_root": wiki_root,
                    "total_matches": 0,
                    "matches": [],
                }

        subdirectory = ablation_subdir if ablation_subdir is not None else _normalize_section(section)
        pages = _collect_wiki_pages(wiki_root, subdirectory)
        if not pages:
            return {
                "status": "success",
                "message": f"No wiki pages found in {section or 'all'}.",
                "wiki_root": wiki_root,
                "total_matches": 0,
                "matches": [],
            }

        # Build/load index
        embeddings, page_meta, file_hash = _load_or_build_index(wiki_root, pages)
        if embeddings is None or len(page_meta) == 0:
            return {
                "status": "success",
                "message": "Wiki index is empty.",
                "wiki_root": wiki_root,
                "total_matches": 0,
                "matches": [],
            }

        # Determine current game for filtering
        active_env = os.environ.get("JERICHO_ACTIVE_ENV", "").strip()

        # Embed query and compute similarity
        query_emb = embed_texts([query_clean])

        # Dimension mismatch guard: if index was built with a different embedding
        # model (e.g. API 1024-dim bge-m3 but query fell back to local 384-dim),
        # delete the stale index and rebuild so dimensions are consistent.
        if embeddings.shape[1] != query_emb.shape[1]:
            index_path = os.path.join(wiki_root, ".wiki_index.npz")
            import sys
            print(
                f"[wiki_memory] dim mismatch: index={embeddings.shape[1]} query={query_emb.shape[1]} "
                f"— rebuilding index from scratch",
                file=sys.stderr,
            )
            try:
                os.remove(index_path)
            except OSError:
                pass
            embeddings, page_meta, file_hash = _load_or_build_index(wiki_root, pages)
            if embeddings is None or len(page_meta) == 0:
                return {
                    "status": "success",
                    "message": "Wiki index is empty after rebuild.",
                    "wiki_root": wiki_root,
                    "total_matches": 0,
                    "matches": [],
                }
            query_emb = embed_texts([query_clean])

        scores = np.dot(embeddings, query_emb[0])

        # Rank and select top-k
        ranked_indices = np.argsort(scores)[::-1][:max(1, int(max_results)) * 3]

        # Section-aware similarity threshold:
        #   knowledge  → 0.30 (need precise matches for action sequences)
        #   experiences → 0.20 (analogous lessons, broader recall)
        #   world_model → 0.25 (navigation, moderately precise)
        #   all         → 0.25 (balanced default)
        section_lower = str(section or "").strip().lower()
        if section_lower in ("knowledge", "skill", "skills"):
            threshold = 0.30
        elif section_lower in ("experience", "experiences"):
            threshold = 0.20
        elif section_lower in ("world", "world_model", "location", "locations", "object", "objects"):
            threshold = 0.25
        else:
            threshold = 0.25

        matches = []
        lines = [f"Wiki search '{query_clean}' in {section or 'all'}:", ""]
        for idx in ranked_indices:
            raw_score = float(scores[idx])
            meta = page_meta[idx]

            # Look up full content for confidence + snippet extraction
            page = next((p for p in pages if p["rel_path"] == meta["rel_path"]), None)
            content = page["content"] if page else ""

            # Cross-game filtering: parse applies_to and/or use filename slug
            applies_to = _parse_applies_to(content)
            is_same_game = True
            if active_env:
                is_same_game = active_env in applies_to or "all" in applies_to
                if not is_same_game and not applies_to:
                    active_slug = active_env.replace("JerichoEnv", "").lower()
                    if active_slug and active_slug in meta["rel_path"].lower():
                        is_same_game = True

            # Confidence-weighted final score:
            # final = embedding_sim × confidence × cross_game_penalty
            confidence = _parse_confidence(content)
            score = raw_score * confidence
            if active_env and not is_same_game:
                score *= 0.3

            if score < threshold:
                continue

            game_tag = " ✓" if (active_env and is_same_game) else ""
            conf_tag = f" conf={confidence:.2f}" if confidence < 1.0 else ""
            full_content = content.strip()
            matches.append({
                "page": meta["rel_path"],
                "title": meta["title"],
                "similarity": round(score, 4),
                "raw_similarity": round(raw_score, 4),
                "confidence": round(confidence, 2),
                "content": full_content,
            })
            lines.append(f"[sim={score:.3f}] {meta['title']} ({meta['rel_path']}){game_tag}{conf_tag}")
            lines.append(full_content)
            lines.append("")

            if len(matches) >= min(int(max_results), 3):
                break

        if not matches:
            lines.append("No pages above similarity threshold. Try different keywords.")

        return {
            "status": "success",
            "message": "\n".join(lines).strip(),
            "wiki_root": wiki_root,
            "query": query_clean,
            "section": section or "all",
            "total_matches": len(matches),
            "matches": matches,
        }
