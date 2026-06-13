from __future__ import annotations

import os
import threading

from PySide6.QtCore import QObject, Signal

from .ai_fallback import ai_error_result, needs_ai_fallback
from .ai_service import OllamaAiAdapter
from .cache import BlockComplexityCache
from .dependency_graph import block_graph_id, build_dependency_graph, topological_blocks
from .models import AnalysisResult, CodeBlock, ProjectAnalysis
from .project_index import build_index
from .project_recommendations import build_ai_project_recommendations
from .review import build_project_review
from .static_analyzer import analyze_block_static
from .storage import BigoStorage, SQLiteBlockComplexityCache

PROJECT_AI_MAX_BLOCKS = int(os.environ.get("BIGO_AI_MAX_BLOCKS", "32"))
PROJECT_AI_TIMEOUT_S = float(os.environ.get("BIGO_AI_TIMEOUT_S", "12"))
PROJECT_AI_MAX_WORKERS = int(os.environ.get("BIGO_AI_MAX_WORKERS", "4"))


class BigOOrchestrator(QObject):
    progress = Signal(str, int)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        parent=None,
        use_ai: bool = False,
        ai_model: str = "qwen2.5-coder:7b",
        ai_timeout: int = 60,
        ollama_base_url: str = "http://127.0.0.1:11434",
    ):
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._cancel_event = threading.Event()
        self._generation = 0
        # Kept for constructor compatibility. Project scans stay fast by
        # default; when enabled, AI fallback has a small hard budget.
        self._use_ai = use_ai
        self._ai_model = ai_model
        self._ai_timeout = float(ai_timeout)
        self._ollama_base_url = ollama_base_url.rstrip("/")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def cancel(self) -> None:
        self._cancel_event.set()
        self._generation += 1

    def start(self, root_path: str) -> None:
        if self.is_running():
            return
        self._cancel_event.clear()
        self._generation += 1
        run_id = self._generation
        self._thread = threading.Thread(
            target=self._run, args=(run_id, root_path), daemon=True
        )
        self._thread.start()

    def _should_stop(self, run_id: int) -> bool:
        return self._cancel_event.is_set() or run_id != self._generation

    def _apply_analysis_to_block(self, block: CodeBlock, analysis: AnalysisResult, cache) -> None:
        block.complexity = analysis.complexity or "unknown"
        block.reason = analysis.reason or analysis.reasoning_summary
        if analysis.analyzer_kind in {"llm", "llm_error"}:
            block.source_kind = "llm"
        elif analysis.analyzer_kind == "cache":
            block.source_kind = "cache"
        else:
            block.source_kind = "static"
        try:
            cache.upsert(block, analysis)
        except TypeError:
            cache.upsert(block)

    def _open_storage(self, root_path: str, files_scanned, all_blocks, graph):
        storage = BigoStorage(root_path)
        run_id = storage.begin_run(self._ai_model)
        storage.upsert_index(files_scanned, all_blocks, run_id)
        storage.replace_edges(graph)
        return storage, run_id

    def _fallback_cache(self, root_path: str) -> BlockComplexityCache:
        return BlockComplexityCache(os.path.join(root_path, ".bigo_cache.json"))

    def _run(self, run_id: int, root_path: str) -> None:
        storage: BigoStorage | None = None
        storage_run_id: str | None = None
        try:
            self.progress.emit("Rule-based analysis started", 3)
            self.progress.emit("Fast project scan", 5)

            self.progress.emit("Scanning project...", 8)
            files_scanned, by_file, all_blocks = build_index(root_path)
            if self._should_stop(run_id):
                return

            dependency_graph = build_dependency_graph(all_blocks)
            if self._should_stop(run_id):
                return

            try:
                storage, storage_run_id = self._open_storage(
                    root_path, files_scanned, all_blocks, dependency_graph
                )
                cache = SQLiteBlockComplexityCache(
                    storage,
                    graph=dependency_graph,
                    model_id=self._ai_model,
                )
            except Exception:
                storage = None
                storage_run_id = None
                cache = self._fallback_cache(root_path)

            ai_adapter: OllamaAiAdapter | None = None
            ollama_available: bool | None = None
            if PROJECT_AI_MAX_BLOCKS > 0:
                ai_adapter = OllamaAiAdapter(
                    base_url=self._ollama_base_url,
                    model=self._ai_model,
                    timeout_s=min(self._ai_timeout, PROJECT_AI_TIMEOUT_S),
                    max_workers=PROJECT_AI_MAX_WORKERS,
                )
                ollama_available = ai_adapter.is_available()
                if not ollama_available:
                    self.progress.emit(
                        "Ollama is unavailable; uncertain blocks will stay unknown",
                        10,
                    )

            self.progress.emit("Static analysis...", 15)

            unknown: list[CodeBlock] = []
            to_analyze = topological_blocks(all_blocks, dependency_graph)
            known_results: dict[str, AnalysisResult] = {}
            total = max(1, len(to_analyze))
            ai_queue = 0
            ai_llm_errors = 0
            ai_candidates: list[tuple[CodeBlock, AnalysisResult]] = []

            for i, block in enumerate(to_analyze, start=1):
                if self._should_stop(run_id):
                    return
                bid = block_graph_id(block)

                if cache.try_apply(block):
                    cached_result = None
                    applied_result_for = getattr(cache, "applied_result_for", None)
                    if callable(applied_result_for):
                        cached_result = applied_result_for(block)
                    if cached_result is None:
                        cached_result = AnalysisResult(
                            complexity=block.complexity,
                            reason=block.reason,
                            reasoning_summary=block.reason,
                            analyzer_kind=block.source_kind or "cache",
                            features=block.features,
                        )
                    else:
                        cached_result.features = cached_result.features or block.features
                    known_results[bid] = cached_result
                    continue

                analysis = analyze_block_static(block, dependency_graph, known_results)

                if needs_ai_fallback(analysis):
                    analysis.needs_human_review = True
                    if (
                        ai_adapter is not None
                        and ollama_available
                        and len(ai_candidates) < PROJECT_AI_MAX_BLOCKS
                    ):
                        ai_candidates.append((block, analysis))
                    else:
                        analysis = ai_error_result(
                            analysis,
                            "Ollama unavailable or AI budget exhausted; used local conservative fallback.",
                        )

                known_results[bid] = analysis
                if analysis.complexity in (None, "unknown"):
                    unknown.append(block)
                self._apply_analysis_to_block(block, analysis, cache)

                pct = 15 + int(i * 50 / total)
                self.progress.emit(
                    f"Static analysis: {i}/{total} blocks",
                    min(65, pct),
                )

            if self._should_stop(run_id):
                return

            if ai_candidates and ai_adapter is not None and ollama_available:
                ai_queue = len(ai_candidates)
                self.progress.emit(
                    f"AI fallback: {ai_queue} compact requests...",
                    72,
                )
                def on_ai_progress(done: int, ai_total: int) -> None:
                    pct = 72 + int(done * 12 / max(1, ai_total))
                    self.progress.emit(
                        f"AI fallback: {done}/{ai_total} blocks",
                        min(84, pct),
                    )

                ai_results = ai_adapter.estimate_many(
                    ai_candidates,
                    dependency_graph,
                    known_results,
                    progress_callback=on_ai_progress,
                )
                for block, _rule_result in ai_candidates:
                    if self._should_stop(run_id):
                        return
                    bid = block_graph_id(block)
                    ai_result = ai_results.get(bid)
                    if ai_result is None:
                        continue
                    if ai_result.analyzer_kind == "llm_error":
                        ai_llm_errors += 1
                    known_results[bid] = ai_result
                    self._apply_analysis_to_block(block, ai_result, cache)

                self.progress.emit(f"AI fallback done: {ai_queue} blocks", 84)

            cache.prune_to(all_blocks)
            cache.save()

            if self._should_stop(run_id):
                return

            self.progress.emit("Preparing recommendations...", 88)
            project_recommendations = {}
            if ai_adapter is not None and ollama_available:
                old_timeout = ai_adapter.client.timeout_s
                try:
                    ai_adapter.client.timeout_s = max(old_timeout, min(self._ai_timeout, 30.0))
                    project_recommendations = build_ai_project_recommendations(
                        all_blocks,
                        known_results,
                        ai_adapter.client,
                        check_available=False,
                    )
                finally:
                    ai_adapter.client.timeout_s = old_timeout

            self.progress.emit("Saving results and preparing review...", 92)
            review_text = build_project_review(all_blocks, None, dependency_graph)

            if self._should_stop(run_id):
                return

            if storage is not None and storage_run_id is not None:
                storage.finish_run(storage_run_id, "ok")

            result = ProjectAnalysis(
                root_path=root_path,
                files_scanned=files_scanned,
                blocks_by_file=by_file,
                all_blocks=all_blocks,
                review_text=review_text,
                dependency_graph=dependency_graph,
                ai_blocks_sent=ai_queue,
                ai_llm_errors=ai_llm_errors,
                ollama_available=ollama_available,
                block_results=known_results,
                storage_path=storage.db_path if storage is not None else None,
                project_recommendations=project_recommendations,
            )
            self.progress.emit("Done", 100)
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            if not self._should_stop(run_id):
                self.failed.emit(str(exc))
        finally:
            if storage is not None:
                try:
                    if storage_run_id is not None:
                        row = storage.conn.execute(
                            "SELECT status FROM analysis_runs WHERE run_id = ?",
                            (storage_run_id,),
                        ).fetchone()
                        if row is not None and row["status"] == "running":
                            storage.finish_run(storage_run_id, "cancelled")
                    storage.close()
                except Exception:
                    pass
