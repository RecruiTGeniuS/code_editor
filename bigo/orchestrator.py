from __future__ import annotations

import os
import threading

from PySide6.QtCore import QObject, Signal

from .ai_fallback import estimate_with_ai, needs_ai_fallback
from .block_utils import analyzable_blocks
from .cache import BlockComplexityCache
from .dependency_graph import block_graph_id, build_dependency_graph, topological_blocks
from .models import AnalysisResult, CodeBlock, ProjectAnalysis, is_ranked_complexity
from .ollama_client import OllamaBigOClient
from .project_index import build_index
from .review import build_project_review
from .static_analyzer import analyze_block_static


class BigOOrchestrator(QObject):
    progress = Signal(str, int)  # message, percent
    finished = Signal(object)  # ProjectAnalysis
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

    def _apply_analysis_to_block(
        self, block: CodeBlock, analysis: AnalysisResult, cache: BlockComplexityCache
    ) -> None:
        c = analysis.complexity
        reason = analysis.reason or analysis.reasoning_summary
        if c and (is_ranked_complexity(c) or c not in (None, "unknown")):
            block.complexity = c
            block.reason = reason
            block.source_kind = (
                "llm" if analysis.analyzer_kind == "llm" else "static"
            )
            cache.upsert(block)

    def _run(self, run_id: int, root_path: str) -> None:
        try:
            self.progress.emit("Запущен rule-based анализ", 3)
            if self._use_ai:
                self.progress.emit("AI fallback включён", 5)
            else:
                self.progress.emit("AI fallback выключен", 5)

            self.progress.emit("Сканирование проекта…", 8)
            files_scanned, by_file, all_blocks = build_index(root_path)
            dependency_graph = build_dependency_graph(all_blocks)
            if self._should_stop(run_id):
                return

            cache_path = os.path.join(root_path, ".bigo_cache.json")
            cache = BlockComplexityCache(cache_path)

            ollama_ai: OllamaBigOClient | None = None
            ollama_available: bool | None = None
            if self._use_ai:
                ollama_ai = OllamaBigOClient(
                    base_url=self._ollama_base_url,
                    model=self._ai_model,
                    timeout_s=self._ai_timeout,
                    max_workers=1,
                )
                ollama_available = ollama_ai.is_available()
                if not ollama_available:
                    self.progress.emit(
                        "Ollama недоступна — сложные блоки останутся без AI-оценки",
                        10,
                    )

            self.progress.emit("Статический анализ…", 15)

            unknown: list[CodeBlock] = []
            to_analyze = topological_blocks(all_blocks, dependency_graph)
            known_results: dict[str, AnalysisResult] = {}
            total = max(1, len(to_analyze))
            ai_queue = 0
            ai_llm_errors = 0

            for i, block in enumerate(to_analyze, start=1):
                if self._should_stop(run_id):
                    return
                bid = block_graph_id(block)
                if cache.try_apply(block):
                    known_results[bid] = AnalysisResult(
                        complexity=block.complexity,
                        reason=block.reason,
                        reasoning_summary=block.reason,
                        analyzer_kind="rule",
                        features=block.features,
                    )
                    continue

                analysis = analyze_block_static(
                    block, dependency_graph, known_results
                )

                if self._use_ai and ollama_ai is not None and needs_ai_fallback(analysis):
                    ai_queue += 1
                    self.progress.emit(
                        f"AI fallback ({ai_queue})…",
                        min(75, 60 + int(i * 15 / total)),
                    )
                    analysis = estimate_with_ai(
                        block,
                        analysis,
                        dependency_graph,
                        known_results,
                        model=self._ai_model,
                        client=ollama_ai,
                        timeout_s=self._ai_timeout,
                    )
                    if analysis.analyzer_kind == "llm_error":
                        ai_llm_errors += 1

                known_results[bid] = analysis

                if (
                    analysis.complexity is None
                    or analysis.complexity == "unknown"
                    or (needs_ai_fallback(analysis) and not self._use_ai)
                ):
                    unknown.append(block)
                else:
                    self._apply_analysis_to_block(block, analysis, cache)

                if i % 25 == 0:
                    pct = 15 + int(i * 45 / total)
                    self.progress.emit("Статический анализ…", min(60, pct))

            if self._should_stop(run_id):
                return

            if ai_queue > 0:
                self.progress.emit(f"Передано в AI: {ai_queue} блоков", 78)

            if unknown and not self._use_ai:
                for block in unknown:
                    block.complexity = "unknown"
                    block.reason = (
                        "Rule-based анализ не смог уверенно оценить блок; "
                        "AI fallback отключен."
                    )
                    block.source_kind = "static"
                    cache.upsert(block)

            if self._should_stop(run_id):
                return

            cache.prune_to(all_blocks)
            cache.save()

            ollama_review = (
                OllamaBigOClient(base_url=self._ollama_base_url, model=self._ai_model)
                if self._use_ai
                else None
            )
            self.progress.emit("Подготовка рецензии…", 88)
            review_text = build_project_review(
                all_blocks,
                ollama_review,
                dependency_graph,
            )

            if self._should_stop(run_id):
                return

            self.progress.emit("Готово", 100)
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
            )
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            if not self._should_stop(run_id):
                self.failed.emit(str(exc))
