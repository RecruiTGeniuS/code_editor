"""Слой связи между GUI (MainWindow) и подсистемой bigo.

Контроллер владеет режимом Big-O: запуск/остановка анализа, кэш overlay-строк
по файлам, подсветка активной вкладки и обновление правой AI-панели.

Также обрабатывает клик по кнопке "рецензия блока" внутри Monaco editor:
сигнал из JS (через QWebChannel + BigOBridge) приходит как
`editor.block_review_requested(block_id)` и вызывает review_block(block_id).
"""

from __future__ import annotations

import base64
import json
import os
from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox, QPushButton, QTextEdit, QWidget

from bigo.block_review import build_block_review
from bigo.models import AnalysisResult, CodeBlock
from bigo.orchestrator import BigOOrchestrator
from bigo.overlay_model import to_monaco_decorations
from monaco_widget import CustomMonaco
from tab_manager import TabManager


def _load_review_icon_data_uri() -> str:
    """Прочитать icons/ai_ricense_block.png и вернуть data URI; "" если файла нет."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "icons", "ai_ricense_block.png"),
        os.path.join(here, "icons", "ai_review_block.png"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                with open(path, "rb") as fh:
                    data = fh.read()
                if not data:
                    return ""
                b64 = base64.b64encode(data).decode("ascii")
                return f"data:image/png;base64,{b64}"
            except OSError:
                return ""
    return ""


class BigOController:
    """Управление Big-O режимом без знания о полной структуре MainWindow."""

    def __init__(
        self,
        parent: QWidget,
        *,
        editor: CustomMonaco,
        tab_manager: TabManager,
        get_project_root: Callable[[], str | None],
        big_o_button: QPushButton,
        ai_sidebar_text: QTextEdit,
        show_ai_sidebar: Callable[[], None],
        set_ai_status: Callable[[str], None],
        read_ai_settings: Callable[[], None] | None = None,
        use_ai: bool = False,
        ai_model: str = "qwen2.5-coder:7b",
        ai_timeout: int = 60,
    ) -> None:
        self._parent = parent
        self._editor = editor
        self._tab_manager = tab_manager
        self._get_project_root = get_project_root
        self._big_o_button = big_o_button
        self._ai_sidebar_text = ai_sidebar_text
        self._show_ai_sidebar = show_ai_sidebar
        self._set_ai_status = set_ai_status
        self._read_ai_settings = read_ai_settings

        self.use_ai = use_ai
        self.ai_model = ai_model
        self.ai_timeout = int(ai_timeout)

        self._enabled = False
        self._analysis_running = False
        self._rows_by_file: dict[str, list[dict]] = {}
        self._blocks_by_id: dict[str, CodeBlock] = {}
        self._results_by_id: dict[str, AnalysisResult] = {}
        self._ollama_available_last: bool | None = None
        self._project_review_text: str = ""
        self._spinner_step = 0
        self._last_status_message = ""

        self._spinner_timer = QTimer(parent)
        self._spinner_timer.setInterval(350)
        self._spinner_timer.timeout.connect(self._tick_spinner)

        self._orchestrator: BigOOrchestrator | None = None
        self._rebuild_orchestrator()

        try:
            self._editor.block_review_requested.connect(self.review_block)
        except Exception:
            pass
        self._review_icon_uri = _load_review_icon_data_uri()
        if self._review_icon_uri:
            # Иконка ставится после initialized, чтобы JS-слой кнопок уже
            # успел смонтироваться в DOM. Повторный вызов set_big_o_review_icon
            # безопасен — он только подменяет содержимое существующего widget.
            try:
                self._editor.initialized.connect(self._apply_review_icon)
            except Exception:
                pass
            QTimer.singleShot(500, self._apply_review_icon)

    def _apply_review_icon(self) -> None:
        if self._review_icon_uri:
            self._editor.set_big_o_review_icon(self._review_icon_uri)

    def sync_ai_settings(
        self,
        *,
        use_ai: bool,
        ai_model: str,
        ai_timeout: int,
    ) -> None:
        self.use_ai = use_ai
        self.ai_model = ai_model.strip() or "qwen2.5-coder:7b"
        self.ai_timeout = max(5, int(ai_timeout))

    def _rebuild_orchestrator(self) -> None:
        old = self._orchestrator
        if old is not None:
            for signal, slot in (
                (old.progress, self._on_progress),
                (old.finished, self._on_finished),
                (old.failed, self._on_failed),
            ):
                try:
                    signal.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
            if old.is_running():
                old.cancel()

        self._orchestrator = BigOOrchestrator(
            self._parent,
            use_ai=self.use_ai,
            ai_model=self.ai_model,
            ai_timeout=self.ai_timeout,
        )
        self._orchestrator.progress.connect(self._on_progress)
        self._orchestrator.finished.connect(self._on_finished)
        self._orchestrator.failed.connect(self._on_failed)

    def toggle_mode(self) -> None:
        if self._enabled or self._analysis_running:
            self.disable_mode()
            return
        self.start_mode()

    def start_mode(self) -> None:
        root = self._get_project_root()
        if not root:
            QMessageBox.information(
                self._parent,
                "Big-O анализ",
                "Сначала откройте папку проекта (Файл → Открыть папку).",
            )
            self._big_o_button.setChecked(False)
            return
        if self._read_ai_settings:
            self._read_ai_settings()
        self._rebuild_orchestrator()

        self._enabled = True
        self._analysis_running = True
        self._rows_by_file.clear()
        self._blocks_by_id.clear()
        self._results_by_id.clear()
        self._ai_sidebar_text.clear()
        self._show_ai_sidebar()
        self._last_status_message = "Анализ проекта"
        self._set_ai_status(self._last_status_message)
        self._spinner_timer.start()
        self._editor.clear_big_o_overlays()
        self._big_o_button.setChecked(True)
        assert self._orchestrator is not None
        self._orchestrator.start(root)

    def disable_mode(self) -> None:
        self._enabled = False
        self._analysis_running = False
        self._spinner_timer.stop()
        self._set_ai_status("")
        self._big_o_button.setChecked(False)
        self._rows_by_file.clear()
        self._blocks_by_id.clear()
        self._results_by_id.clear()
        if self._orchestrator is not None:
            self._orchestrator.cancel()
        self._editor.clear_big_o_overlays()

    def on_active_tab_changed(self) -> None:
        if not self._enabled:
            return
        self.apply_for_active_tab()

    def apply_for_active_tab(self) -> None:
        if self._tab_manager.active_kind != "text":
            self._editor.clear_big_o_overlays()
            return
        path = self._tab_manager.file_path
        if not path:
            self._editor.clear_big_o_overlays()
            return
        norm_path = os.path.normcase(os.path.abspath(path))
        rows = self._rows_by_file.get(norm_path)
        if not rows:
            self._editor.clear_big_o_overlays()
            self._set_ai_status("Для текущего файла блоки Big-O не найдены")
            return
        self._editor.apply_big_o_overlays(rows, self._on_overlay_applied)

    def _tick_spinner(self) -> None:
        if not self._analysis_running:
            return
        self._spinner_step = (self._spinner_step + 1) % 4
        dots = "." * self._spinner_step
        base = self._last_status_message or "Анализ проекта"
        self._set_ai_status(f"{base}{dots}")

    def _on_progress(self, message: str, percent: int) -> None:
        self._show_ai_sidebar()
        self._last_status_message = message
        self._spinner_timer.stop()
        self._set_ai_status(f"{message} ({percent}%)")

    @staticmethod
    def _format_source_summary(result) -> str:
        counts = result.source_kind_counts()
        lines = ["", "--- Источники оценок ---"]
        label_map = {"static": "rule", "llm": "llm", "cache": "cache"}
        for key in ("cache", "static", "llm"):
            n = counts.get(key, 0)
            if n:
                lines.append(f"{label_map[key]}: {n}")
        unknown_n = result.unknown_block_count()
        if unknown_n:
            lines.append(f"unknown / needs review: {unknown_n}")
        if result.ai_blocks_sent:
            lines.append(f"Передано в AI: {result.ai_blocks_sent}")
        if result.ai_llm_errors:
            lines.append(f"llm_error (AI не ответил): {result.ai_llm_errors}")
        if result.ollama_available is False:
            lines.append(
                "Ollama недоступна — для части блоков AI-оценка не выполнена."
            )
        return "\n".join(lines)

    def _index_blocks(self, result) -> None:
        from bigo.dependency_graph import block_graph_id

        self._blocks_by_id = {block_graph_id(b): b for b in result.all_blocks}
        self._results_by_id = dict(getattr(result, "block_results", {}) or {})
        self._ollama_available_last = result.ollama_available

    def _on_finished(self, result) -> None:
        self._analysis_running = False
        self._spinner_timer.stop()
        summary = self._format_source_summary(result)
        status_parts = ["Анализ завершён"]
        if result.ai_blocks_sent:
            status_parts.append(f"AI: {result.ai_blocks_sent}")
        if result.ollama_available is False:
            status_parts.append("Ollama недоступна")
        self._last_status_message = " · ".join(status_parts)
        self._set_ai_status(self._last_status_message)
        self._show_ai_sidebar()
        review = (result.review_text or "").rstrip()
        self._project_review_text = review + summary
        self._ai_sidebar_text.setPlainText(self._project_review_text)

        self._index_blocks(result)

        rows_by_file: dict[str, list[dict]] = {}
        for path, blocks in result.blocks_by_file.items():
            norm = os.path.normcase(os.path.abspath(path))
            rows_by_file[norm] = to_monaco_decorations(
                blocks, self._results_by_id
            )
        self._rows_by_file = rows_by_file
        if self._enabled:
            self.apply_for_active_tab()

    def _on_failed(self, message: str) -> None:
        self._analysis_running = False
        self._spinner_timer.stop()
        self._set_ai_status("Ошибка анализа")
        self._ai_sidebar_text.setPlainText(message)
        self._big_o_button.setChecked(False)
        self._enabled = False
        self._editor.clear_big_o_overlays()

    def _on_overlay_applied(self, result) -> None:
        if not result:
            return
        try:
            row = json.loads(str(result))
        except Exception:
            return
        if not row.get("ok", False):
            err = row.get("error", "unknown error")
            self._set_ai_status(f"Ошибка рендера Big-O: {err}")
            return
        count = int(row.get("decorations", 0) or 0)
        self._set_ai_status(f"Big-O блоки отображены: {count}")

    def review_block(self, block_id: str) -> None:
        """Сформировать локальную рецензию блока и показать её в правой панели.

        Не делает сетевых вызовов: использует данные, накопленные оркестратором.
        В правой панели полностью заменяет текст; для возврата к рецензии
        проекта пользователь может перезапустить анализ или переключить вкладку
        (overlay-кнопки обновляются автоматически).
        """
        if not block_id:
            self._set_ai_status("Big-O: пустой block_id, рецензия не построена")
            return
        block = self._blocks_by_id.get(block_id)
        if block is None:
            self._set_ai_status(
                f"Big-O: блок не найден (id={block_id[:8]}…), "
                "запустите анализ заново"
            )
            return
        analysis = self._results_by_id.get(block_id)
        text = build_block_review(
            block,
            analysis,
            use_ai_hint=self.use_ai,
            ai_available=self._ollama_available_last,
        )
        self._show_ai_sidebar()
        self._ai_sidebar_text.setPlainText(text)
        name = block.qualified_name or block.short_name
        self._set_ai_status(f"Рецензия блока: {name}")
