from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import asdict
from typing import Any

from .dependency_graph import DependencyGraph, block_graph_id
from .models import AnalysisResult, CodeBlock
from .static_analyzer import RULES_VERSION
from .llm_contract import PROMPT_VERSION

SCHEMA_VERSION = 1
ANALYZER_VERSION = "bigo-backend-v1"


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def _asdict_or_empty(value: Any) -> dict:
    if value is None:
        return {}
    try:
        return asdict(value)
    except TypeError:
        return dict(value) if isinstance(value, dict) else {}


def _relative_path(path: str, root_path: str) -> str:
    try:
        return os.path.relpath(path, root_path)
    except ValueError:
        return path


class BigoStorage:
    def __init__(self, root_path: str, db_path: str | None = None):
        self.root_path = os.path.abspath(root_path)
        self.db_path = db_path or os.path.join(self.root_path, ".bigo", "bigo.sqlite")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        try:
            self.conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.DatabaseError:
            pass
        self._create_schema()

    def close(self) -> None:
        self.conn.close()

    def _create_schema(self) -> None:
        cur = self.conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                relative_path TEXT NOT NULL UNIQUE,
                language TEXT,
                size INTEGER,
                mtime REAL,
                content_hash TEXT,
                has_parse_errors INTEGER DEFAULT 0,
                last_seen_run_id TEXT
            );

            CREATE TABLE IF NOT EXISTS blocks (
                id TEXT PRIMARY KEY,
                file_id INTEGER NOT NULL,
                parent_block_id TEXT,
                kind TEXT,
                name TEXT,
                qualified_name TEXT,
                signature TEXT,
                start_line INTEGER,
                end_line INTEGER,
                start_byte INTEGER,
                end_byte INTEGER,
                body_start_line INTEGER,
                body_end_line INTEGER,
                source_hash TEXT,
                normalized_hash TEXT,
                is_container INTEGER DEFAULT 0,
                error_state INTEGER DEFAULT 0,
                last_seen_run_id TEXT,
                FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS block_features (
                block_id TEXT PRIMARY KEY,
                loop_count INTEGER,
                max_loop_depth INTEGER,
                branch_count INTEGER,
                call_count INTEGER,
                project_call_count INTEGER,
                external_call_count INTEGER,
                has_recursion INTEGER,
                recursion_kind TEXT,
                has_sorting INTEGER,
                has_log_pattern INTEGER,
                loop_summaries_json TEXT,
                call_summaries_json TEXT,
                container_operations_json TEXT,
                uncertainty_flags_json TEXT,
                features_json TEXT,
                FOREIGN KEY(block_id) REFERENCES blocks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS edges (
                edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_block_id TEXT,
                target_block_id TEXT,
                edge_type TEXT,
                call_name TEXT,
                raw_expression TEXT,
                source_line INTEGER,
                inside_loop_depth INTEGER,
                resolved_state TEXT,
                confidence TEXT,
                metadata_json TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_block_id);
            CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_block_id);

            CREATE TABLE IF NOT EXISTS analysis_results (
                result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                block_id TEXT NOT NULL,
                cache_key TEXT NOT NULL UNIQUE,
                complexity TEXT,
                confidence TEXT,
                analyzer_kind TEXT,
                reason TEXT,
                reasoning_summary TEXT,
                assumptions_json TEXT,
                evidence_ranges_json TEXT,
                needs_human_review INTEGER,
                duration_ms INTEGER,
                model_id TEXT,
                prompt_version TEXT,
                rules_version TEXT,
                dependency_hash TEXT,
                payload_hash TEXT,
                created_at REAL,
                FOREIGN KEY(block_id) REFERENCES blocks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS reviews (
                review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                block_id TEXT NOT NULL,
                review_text TEXT,
                review_json TEXT,
                source_kind TEXT,
                model_id TEXT,
                prompt_version TEXT,
                payload_hash TEXT,
                created_at REAL,
                UNIQUE(block_id, payload_hash, prompt_version),
                FOREIGN KEY(block_id) REFERENCES blocks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS analysis_runs (
                run_id TEXT PRIMARY KEY,
                started_at REAL,
                finished_at REAL,
                root_path TEXT,
                status TEXT,
                analyzer_version TEXT,
                rules_version TEXT,
                prompt_version TEXT,
                model_id TEXT
            );
            """
        )
        cur.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.conn.commit()

    def begin_run(self, model_id: str | None = None) -> str:
        run_id = f"{int(time.time() * 1000)}-{os.getpid()}"
        self.conn.execute(
            """
            INSERT OR REPLACE INTO analysis_runs
            (run_id, started_at, root_path, status, analyzer_version, rules_version, prompt_version, model_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                time.time(),
                self.root_path,
                "running",
                ANALYZER_VERSION,
                RULES_VERSION,
                PROMPT_VERSION,
                model_id,
            ),
        )
        self.conn.commit()
        return run_id

    def finish_run(self, run_id: str, status: str = "ok") -> None:
        self.conn.execute(
            "UPDATE analysis_runs SET finished_at = ?, status = ? WHERE run_id = ?",
            (time.time(), status, run_id),
        )
        self.conn.commit()

    def upsert_index(self, files_scanned: list[str], blocks: list[CodeBlock], run_id: str) -> None:
        file_ids: dict[str, int] = {}
        language_by_file = {
            block.file_path: block.language_id
            for block in blocks
            if block.file_path and block.language_id
        }
        with self.conn:
            for path in files_scanned:
                rel = _relative_path(path, self.root_path)
                try:
                    st = os.stat(path)
                    size = st.st_size
                    mtime = st.st_mtime
                    with open(path, "rb") as fh:
                        content_hash = hashlib.sha1(fh.read()).hexdigest()
                except OSError:
                    size = 0
                    mtime = 0.0
                    content_hash = ""
                has_errors = any(b.file_path == path and b.error_state for b in blocks)
                self.conn.execute(
                    """
                    INSERT INTO files(relative_path, language, size, mtime, content_hash, has_parse_errors, last_seen_run_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(relative_path) DO UPDATE SET
                        language=excluded.language,
                        size=excluded.size,
                        mtime=excluded.mtime,
                        content_hash=excluded.content_hash,
                        has_parse_errors=excluded.has_parse_errors,
                        last_seen_run_id=excluded.last_seen_run_id
                    """,
                    (rel, language_by_file.get(path), size, mtime, content_hash, int(has_errors), run_id),
                )
                row = self.conn.execute(
                    "SELECT id FROM files WHERE relative_path = ?", (rel,)
                ).fetchone()
                if row:
                    file_ids[path] = int(row["id"])

            for block in blocks:
                bid = block_graph_id(block)
                file_id = file_ids.get(block.file_path)
                if file_id is None:
                    continue
                self.conn.execute(
                    """
                    INSERT INTO blocks(
                        id, file_id, parent_block_id, kind, name, qualified_name, signature,
                        start_line, end_line, start_byte, end_byte, body_start_line, body_end_line,
                        source_hash, normalized_hash, is_container, error_state, last_seen_run_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        file_id=excluded.file_id,
                        parent_block_id=excluded.parent_block_id,
                        kind=excluded.kind,
                        name=excluded.name,
                        qualified_name=excluded.qualified_name,
                        signature=excluded.signature,
                        start_line=excluded.start_line,
                        end_line=excluded.end_line,
                        start_byte=excluded.start_byte,
                        end_byte=excluded.end_byte,
                        body_start_line=excluded.body_start_line,
                        body_end_line=excluded.body_end_line,
                        source_hash=excluded.source_hash,
                        normalized_hash=excluded.normalized_hash,
                        is_container=excluded.is_container,
                        error_state=excluded.error_state,
                        last_seen_run_id=excluded.last_seen_run_id
                    """,
                    (
                        bid,
                        file_id,
                        block.parent_block_id,
                        block.kind,
                        block.name,
                        block.qualified_name,
                        block.signature,
                        block.start_line,
                        block.end_line,
                        block.start_byte,
                        block.end_byte,
                        block.body_start_line,
                        block.body_end_line,
                        block.source_hash,
                        block.normalized_hash,
                        int(block.is_container),
                        int(block.error_state),
                        run_id,
                    ),
                )
                features = block.features
                self.conn.execute(
                    """
                    INSERT INTO block_features(
                        block_id, loop_count, max_loop_depth, branch_count, call_count,
                        project_call_count, external_call_count, has_recursion, recursion_kind,
                        has_sorting, has_log_pattern, loop_summaries_json, call_summaries_json,
                        container_operations_json, uncertainty_flags_json, features_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(block_id) DO UPDATE SET
                        loop_count=excluded.loop_count,
                        max_loop_depth=excluded.max_loop_depth,
                        branch_count=excluded.branch_count,
                        call_count=excluded.call_count,
                        project_call_count=excluded.project_call_count,
                        external_call_count=excluded.external_call_count,
                        has_recursion=excluded.has_recursion,
                        recursion_kind=excluded.recursion_kind,
                        has_sorting=excluded.has_sorting,
                        has_log_pattern=excluded.has_log_pattern,
                        loop_summaries_json=excluded.loop_summaries_json,
                        call_summaries_json=excluded.call_summaries_json,
                        container_operations_json=excluded.container_operations_json,
                        uncertainty_flags_json=excluded.uncertainty_flags_json,
                        features_json=excluded.features_json
                    """,
                    (
                        bid,
                        features.loop_count,
                        features.max_loop_depth,
                        features.branch_count,
                        features.call_count,
                        features.project_call_count,
                        features.external_call_count,
                        int(features.has_recursion),
                        features.recursion_kind,
                        int(features.has_sorting or features.has_sort_call),
                        int(features.has_log_pattern),
                        _json(features.loop_summaries),
                        _json(features.call_summaries),
                        _json(features.container_operations),
                        _json(features.uncertainty_flags),
                        _json(_asdict_or_empty(features)),
                    ),
                )

    def replace_edges(self, graph: DependencyGraph) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM edges")
            for edge in graph.edges:
                self.conn.execute(
                    """
                    INSERT INTO edges(
                        source_block_id, target_block_id, edge_type, call_name, raw_expression,
                        source_line, inside_loop_depth, resolved_state, confidence, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        edge.source_block_id,
                        edge.target_block_id,
                        edge.edge_type,
                        edge.call_name,
                        edge.raw_expression,
                        edge.source_line,
                        edge.inside_loop_depth,
                        edge.resolved_state,
                        edge.confidence,
                        _json(edge.metadata),
                    ),
                )

    def dependency_hash(self, block: CodeBlock, graph: DependencyGraph | None = None) -> str:
        if graph is None:
            return _sha1_text("")
        bid = block_graph_id(block)
        parts: list[str] = []
        for edge in graph.get_callees(bid):
            if edge.resolved and edge.target_block_id:
                target = graph.blocks_by_id.get(edge.target_block_id)
                parts.append(f"{edge.call_name}:{edge.target_block_id}:{getattr(target, 'normalized_hash', '')}")
            else:
                parts.append(f"{edge.call_name}:{edge.resolved_state}:unresolved")
        return _sha1_text("|".join(sorted(parts)))

    def make_cache_key(
        self,
        block: CodeBlock,
        *,
        dependency_hash: str = "",
        model_id: str | None = None,
        prompt_version: str = PROMPT_VERSION,
        rules_version: str = RULES_VERSION,
    ) -> str:
        payload = {
            "language": block.language_id,
            "kind": block.kind,
            "qualified_name": block.qualified_name or block.name,
            "normalized_hash": block.normalized_hash or block.source_hash,
            "dependency_hash": dependency_hash,
            "analyzer_version": ANALYZER_VERSION,
            "rules_version": rules_version,
            "prompt_version": prompt_version,
            "model_id": model_id or "",
        }
        return _sha1_text(_json(payload))

    def load_analysis_result(self, block: CodeBlock, cache_key: str) -> AnalysisResult | None:
        row = self.conn.execute(
            """
            SELECT * FROM analysis_results
            WHERE block_id = ? AND cache_key = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (block_graph_id(block), cache_key),
        ).fetchone()
        if row is None:
            return None
        try:
            assumptions = json.loads(row["assumptions_json"] or "[]")
            evidence = json.loads(row["evidence_ranges_json"] or "[]")
        except json.JSONDecodeError:
            assumptions = []
            evidence = []
        return AnalysisResult(
            complexity=row["complexity"],
            reason=row["reason"] or "",
            reasoning_summary=row["reasoning_summary"] or row["reason"] or "",
            confidence=row["confidence"] or "medium",
            analyzer_kind=row["analyzer_kind"] or "cache",
            assumptions=assumptions,
            evidence_ranges=evidence,
            needs_human_review=bool(row["needs_human_review"]),
            duration_ms=row["duration_ms"],
            model_id=row["model_id"],
            prompt_version=row["prompt_version"],
            rules_version=row["rules_version"],
            cache_key=row["cache_key"],
            dependency_hash=row["dependency_hash"],
            payload_hash=row["payload_hash"],
        )

    def save_analysis_result(self, block: CodeBlock, analysis: AnalysisResult, cache_key: str) -> None:
        bid = block_graph_id(block)
        payload_hash = analysis.payload_hash or _sha1_text(
            _json(
                {
                    "block": bid,
                    "source_hash": block.source_hash,
                    "analysis": {
                        "complexity": analysis.complexity,
                        "confidence": analysis.confidence,
                        "kind": analysis.analyzer_kind,
                    },
                }
            )
        )
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO analysis_results(
                    block_id, cache_key, complexity, confidence, analyzer_kind, reason,
                    reasoning_summary, assumptions_json, evidence_ranges_json,
                    needs_human_review, duration_ms, model_id, prompt_version, rules_version,
                    dependency_hash, payload_hash, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    complexity=excluded.complexity,
                    confidence=excluded.confidence,
                    analyzer_kind=excluded.analyzer_kind,
                    reason=excluded.reason,
                    reasoning_summary=excluded.reasoning_summary,
                    assumptions_json=excluded.assumptions_json,
                    evidence_ranges_json=excluded.evidence_ranges_json,
                    needs_human_review=excluded.needs_human_review,
                    duration_ms=excluded.duration_ms,
                    model_id=excluded.model_id,
                    prompt_version=excluded.prompt_version,
                    rules_version=excluded.rules_version,
                    dependency_hash=excluded.dependency_hash,
                    payload_hash=excluded.payload_hash,
                    created_at=excluded.created_at
                """,
                (
                    bid,
                    cache_key,
                    analysis.complexity,
                    analysis.confidence,
                    analysis.analyzer_kind,
                    analysis.reason,
                    analysis.reasoning_summary,
                    _json(analysis.assumptions),
                    _json(analysis.evidence_ranges),
                    int(analysis.needs_human_review),
                    analysis.duration_ms,
                    analysis.model_id,
                    analysis.prompt_version,
                    analysis.rules_version,
                    analysis.dependency_hash,
                    payload_hash,
                    time.time(),
                ),
            )

    def save_block_review(
        self,
        block: CodeBlock,
        review_text: str,
        *,
        review_json: dict | None = None,
        source_kind: str = "local",
        model_id: str | None = None,
        prompt_version: str = PROMPT_VERSION,
        payload_hash: str | None = None,
    ) -> None:
        payload_hash = payload_hash or _sha1_text(
            _json(
                {
                    "block": block_graph_id(block),
                    "source_hash": block.source_hash,
                    "review_json": review_json or {},
                    "source_kind": source_kind,
                }
            )
        )
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO reviews(block_id, review_text, review_json, source_kind, model_id, prompt_version, payload_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(block_id, payload_hash, prompt_version) DO UPDATE SET
                    review_text=excluded.review_text,
                    review_json=excluded.review_json,
                    source_kind=excluded.source_kind,
                    model_id=excluded.model_id,
                    created_at=excluded.created_at
                """,
                (
                    block_graph_id(block),
                    review_text,
                    _json(review_json or {}),
                    source_kind,
                    model_id,
                    prompt_version,
                    payload_hash,
                    time.time(),
                ),
            )

    def delete_block_reviews(self, block_ids: list[str] | None = None) -> None:
        with self.conn:
            if block_ids:
                self.conn.executemany(
                    "DELETE FROM reviews WHERE block_id = ?",
                    [(bid,) for bid in block_ids],
                )
            else:
                self.conn.execute("DELETE FROM reviews")


class SQLiteBlockComplexityCache:
    """SQLite-backed cache with the old BlockComplexityCache shape."""

    def __init__(
        self,
        storage: BigoStorage,
        *,
        graph: DependencyGraph | None = None,
        model_id: str | None = None,
    ):
        self.storage = storage
        self.graph = graph
        self.model_id = model_id
        self._keys: dict[str, tuple[str, str]] = {}

    def _key_for(self, block: CodeBlock) -> tuple[str, str]:
        dep_hash = self.storage.dependency_hash(block, self.graph)
        key = self.storage.make_cache_key(
            block,
            dependency_hash=dep_hash,
            model_id=self.model_id,
        )
        self._keys[block_graph_id(block)] = (key, dep_hash)
        return key, dep_hash

    def try_apply(self, block: CodeBlock) -> bool:
        key, dep_hash = self._key_for(block)
        result = self.storage.load_analysis_result(block, key)
        if (
            result is None
            or not result.complexity
            or result.complexity == "unknown"
            or result.analyzer_kind == "llm_error"
        ):
            return False
        block.complexity = result.complexity
        block.reason = result.reason or result.reasoning_summary
        block.source_kind = "cache"
        result.analyzer_kind = "cache"
        result.dependency_hash = dep_hash
        return True

    def upsert(self, block: CodeBlock, analysis: AnalysisResult | None = None) -> None:
        if not block.complexity and (analysis is None or not analysis.complexity):
            return
        if (
            (analysis is not None and analysis.complexity == "unknown")
            or (analysis is None and block.complexity == "unknown")
        ):
            return
        key, dep_hash = self._key_for(block)
        if analysis is None:
            analysis = AnalysisResult(
                complexity=block.complexity,
                reason=block.reason,
                reasoning_summary=block.reason,
                analyzer_kind=block.source_kind or "rule",
                confidence="medium",
            )
        analysis.cache_key = key
        analysis.dependency_hash = dep_hash
        self.storage.save_analysis_result(block, analysis, key)

    def prune_to(self, blocks: list[CodeBlock]) -> None:
        # Historical rows are intentionally kept for run reproducibility.
        return None

    def save(self) -> None:
        self.storage.conn.commit()
