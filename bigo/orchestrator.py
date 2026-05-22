from __future__ import annotations

import os
import threading
from collections import defaultdict

from PySide6.QtCore import QObject, Signal

from .cache import BlockComplexityCache
from .models import CodeBlock, ProjectAnalysis
from .ollama_client import OllamaBigOClient
from .project_index import build_index
from .review import build_project_review
from .static_analyzer import analyze_block_static


class BigOOrchestrator(QObject):
    progress = Signal(str, int)  # message, percent
    finished = Signal(object)  # ProjectAnalysis
    failed = Signal(str)

    def __init__(self, parent=None, use_ai: bool = False):
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._cancel_event = threading.Event()
        self._generation = 0
        self._use_ai = use_ai

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

    def _run(self, run_id: int, root_path: str) -> None:
        try:
            self.progress.emit("Сканирование проекта…", 2)
            files_scanned, by_file, all_blocks = build_index(root_path)
            if self._should_stop(run_id):
                return

            cache_path = os.path.join(root_path, ".bigo_cache.json")
            cache = BlockComplexityCache(cache_path)
            self.progress.emit("Статический анализ…", 15)

            unknown: list[CodeBlock] = []
            total = max(1, len(all_blocks))
            for i, block in enumerate(all_blocks, start=1):
                if self._should_stop(run_id):
                    return
                if cache.try_apply(block):
                    continue
                c, reason = analyze_block_static(block)
                if c is None:
                    unknown.append(block)
                else:
                    block.complexity = c
                    block.reason = reason
                    block.source_kind = "static"
                    cache.upsert(block)
                if i % 25 == 0:
                    pct = 15 + int(i * 45 / total)
                    self.progress.emit("Статический анализ…", min(60, pct))

            if self._should_stop(run_id):
                return

            ollama = OllamaBigOClient(max_workers=5) if self._use_ai else None
            if unknown:
                if self._use_ai and ollama is not None:
                    self.progress.emit("LLM fallback (Ollama)…", 65)
                    llm_rows = ollama.analyze_many(unknown)
                    for block in unknown:
                        comp, reason = llm_rows.get(
                            block.block_id, ("O(n)", "Fallback по умолчанию.")
                        )
                        block.complexity = comp
                        block.reason = reason
                        block.source_kind = "llm"
                        cache.upsert(block)
                else:
                    # Быстрый режим без ИИ: неизвестные случаи оцениваем
                    # консервативно как O(n), чтобы визуализация была мгновенной.
                    for block in unknown:
                        block.complexity = "O(n)"
                        block.reason = "Эвристика: случай вне правил, без ИИ fallback."
                        block.source_kind = "static"
                        cache.upsert(block)

            if self._should_stop(run_id):
                return

            cache.prune_to(all_blocks)
            cache.save()

            self.progress.emit("Подготовка рецензии…", 88)
            review_text = build_project_review(all_blocks, ollama if self._use_ai else None)

            if self._should_stop(run_id):
                return

            self.progress.emit("Готово", 100)
            result = ProjectAnalysis(
                root_path=root_path,
                files_scanned=files_scanned,
                blocks_by_file=by_file,
                all_blocks=all_blocks,
                review_text=review_text,
            )
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            if not self._should_stop(run_id):
                self.failed.emit(str(exc))

