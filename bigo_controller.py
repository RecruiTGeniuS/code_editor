"""Слой связи между GUI (MainWindow) и подсистемой bigo.

Контроллер владеет режимом Big-O: запуск/остановка анализа, кэш overlay-строк
по файлам, подсветка активной вкладки и обновление правой AI-панели.

Также обрабатывает клик по кнопке "рецензия блока" внутри Monaco editor:
сигнал из JS (через QWebChannel + BigOBridge) приходит как
`editor.block_review_requested(block_id)` и вызывает review_block(block_id).
"""

from __future__ import annotations

import base64
import html
import json
import os
import threading
from typing import Callable

from PySide6.QtCore import (
    QByteArray,
    QBuffer,
    QEvent,
    QIODevice,
    QObject,
    QRectF,
    QTimer,
    Qt,
    QUrl,
)
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QMessageBox,
    QPushButton,
    QTextEdit,
    QWidget,
)

from bigo.block_review import build_block_review
from bigo.block_utils import analyzable_blocks
from bigo.dependency_graph import block_graph_id
from bigo.models import BIG_O_CLASSES, AnalysisResult, CodeBlock
from bigo.orchestrator import BigOOrchestrator
from bigo.overlay_model import complexity_color_class, to_monaco_decorations
from bigo.project_recommendations import pick_project_recommendation_blocks
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


class _ProjectReviewResizeFilter(QObject):
    """Debounce-перерисовка HTML-отчёта при изменении ширины правой панели."""

    def __init__(self, controller: "BigOController", parent=None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(controller._rerender_project_review_if_visible)

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.Type.Resize:
            self._timer.start()
        return super().eventFilter(obj, event)


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
        project_review_button: QPushButton | None = None,
        block_reviews_button: QPushButton | None = None,
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
        self._project_review_button = project_review_button
        self._block_reviews_button = block_reviews_button
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
        self._last_project_result = None
        self._showing_project_review = False
        self._project_review_chart_width: int | None = None
        self._block_review_history: dict[str, str] = {}
        self._block_review_order: list[str] = []
        self._active_block_review_id: str | None = None
        self._spinner_step = 0
        self._last_status_message = ""
        self._last_prewarm_model: str | None = None

        self._spinner_timer = QTimer(parent)
        self._spinner_timer.setInterval(350)
        self._spinner_timer.timeout.connect(self._tick_spinner)

        self._orchestrator: BigOOrchestrator | None = None
        self._rebuild_orchestrator()
        self._prewarm_ai_model()

        try:
            self._editor.block_review_requested.connect(self.review_block)
        except Exception:
            pass
        if hasattr(self._ai_sidebar_text, "anchorClicked"):
            try:
                self._ai_sidebar_text.anchorClicked.connect(
                    self._on_sidebar_link_clicked
                )
            except Exception:
                pass
        self._review_resize_filter = _ProjectReviewResizeFilter(
            self, self._ai_sidebar_text
        )
        self._ai_sidebar_text.viewport().installEventFilter(self._review_resize_filter)
        self._setup_review_tabs()
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

    def _setup_review_tabs(self) -> None:
        if self._project_review_button is not None:
            self._project_review_button.clicked.connect(self.show_project_review_tab)
            self._set_review_button_active(self._project_review_button, True)
        if self._block_reviews_button is not None:
            self._block_reviews_button.clicked.connect(self.show_block_reviews_tab)
            self._block_reviews_button.hide()
            self._set_review_button_active(self._block_reviews_button, False)

    @staticmethod
    def _set_review_button_active(button: QPushButton, active: bool) -> None:
        button.setProperty("active", active)
        button.style().unpolish(button)
        button.style().polish(button)

    def _set_active_review_tab(self, tab: str) -> None:
        project_active = tab == "project"
        if self._project_review_button is not None:
            self._set_review_button_active(
                self._project_review_button, project_active
            )
        if self._block_reviews_button is not None:
            self._set_review_button_active(
                self._block_reviews_button, not project_active
            )

    def _set_block_tab_visible(self, visible: bool) -> None:
        if self._block_reviews_button is not None:
            self._block_reviews_button.setVisible(visible)

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
        self._prewarm_ai_model()

    def _prewarm_ai_model(self) -> None:
        model = (self.ai_model or "").strip()
        if not model or model == self._last_prewarm_model:
            return
        self._last_prewarm_model = model

        def worker() -> None:
            try:
                from bigo.ollama_client import OllamaBigOClient

                client = OllamaBigOClient(model=model, timeout_s=min(self.ai_timeout, 20))
                client.prewarm()
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

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
        self._last_project_result = None
        self._showing_project_review = False
        self._project_review_chart_width = None
        self._block_review_history.clear()
        self._block_review_order.clear()
        self._active_block_review_id = None
        self._set_block_tab_visible(False)
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
        self._last_project_result = None
        self._showing_project_review = False
        self._project_review_chart_width = None
        self._block_review_history.clear()
        self._block_review_order.clear()
        self._active_block_review_id = None
        self._set_block_tab_visible(False)
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
    def _complexity_color(complexity: str | None) -> str:
        palette = {
            "green": "rgba(80, 200, 100, 0.95)",
            "gray": "rgba(200, 200, 200, 0.95)",
            "yellow": "rgba(235, 210, 90, 0.95)",
            "red": "rgba(245, 110, 110, 0.95)",
        }
        return palette.get(complexity_color_class(complexity), palette["gray"])

    @staticmethod
    def _complexity_qcolor(complexity: str | None, alpha: int = 242) -> QColor:
        palette = {
            "green": QColor(80, 200, 100, alpha),
            "gray": QColor(200, 200, 200, alpha),
            "yellow": QColor(235, 210, 90, alpha),
            "red": QColor(245, 110, 110, alpha),
        }
        return palette.get(complexity_color_class(complexity), palette["gray"])

    @staticmethod
    def _count_complexities(blocks: list[CodeBlock]) -> dict[str, int]:
        counts = {k: 0 for k in BIG_O_CLASSES}
        counts["unknown"] = 0
        for block in blocks:
            if block.complexity in counts:
                counts[block.complexity] += 1
            elif block.complexity in (None, "unknown"):
                counts["unknown"] += 1
        return counts

    @staticmethod
    def _block_label(block: CodeBlock) -> str:
        return block.qualified_name or block.short_name or block.kind

    def _pick_project_recommendations(
        self, blocks: list[CodeBlock], limit: int = 5
    ) -> list[CodeBlock]:
        return pick_project_recommendation_blocks(blocks, limit)

    def _project_review_summary(
        self, analyzed: list[CodeBlock], counts: dict[str, int]
    ) -> str:
        total = len(analyzed)
        if total == 0:
            return "В проекте не найдено анализируемых функций или методов."
        heavy = sum(
            counts.get(k, 0)
            for k in ("O(n^2)", "O(n^2 log n)", "O(n^3)", "O(2^n)", "O(n!)")
        )
        linear_or_better = sum(counts.get(k, 0) for k in ("O(1)", "O(log n)", "O(n)"))
        if heavy == 0:
            return (
                "Проект выглядит умеренным по сложности: большая часть блоков "
                "имеет линейную или лучшую оценку, явных тяжёлых hotspots не найдено."
            )
        if heavy <= max(1, total // 5):
            return (
                "Общая картина хорошая, но есть отдельные тяжёлые места. "
                "Их стоит проверить первыми, потому что именно они сильнее всего "
                "влияют на рост времени выполнения на больших данных."
            )
        if linear_or_better >= heavy:
            return (
                "В проекте смешанная картина: базовая часть кода выглядит приемлемо, "
                "но заметная доля блоков имеет квадратичную или более высокую "
                "сложность. Нужна приоритизация hotspots."
            )
        return (
            "Проект требует внимания по производительности: тяжёлые блоки занимают "
            "значительную часть результатов анализа. Начните с самых дорогих "
            "циклов, рекурсии и повторяющихся вызовов."
        )

    @staticmethod
    def _recommendation_text(block: CodeBlock, ai_text: str | None = None) -> str:
        if ai_text:
            return ai_text
        f = block.features
        if block.complexity in {"O(2^n)", "O(n!)"} or f.has_recursion:
            return "Проверить рекурсию и повторные вычисления; рассмотреть memoization или итеративный DP."
        if block.complexity in {"O(n^3)", "O(n^2)", "O(n^2 log n)"} or f.max_loop_depth >= 2:
            return "Проверить вложенные циклы; искать возможность вынести инварианты, добавить индекс/хеш-таблицу или снизить вложенность."
        if f.has_sorting:
            return "Проверить, нельзя ли сортировать один раз заранее или заменить повторную сортировку структурой данных."
        if block.complexity in (None, "unknown"):
            return "Оценка не уверенная: проверить вручную зависимости от входа и стоимость вызываемых функций."
        return "Проверить горячий путь и убедиться, что оценка соответствует реальным данным."

    @staticmethod
    def _chart_complexity_label(complexity: str) -> str:
        labels = {
            "O(1)": "1",
            "O(log n)": "log",
            "O(n)": "n",
            "O(n log n)": "n·log",
            "O(n^2)": "n²",
            "O(n^2 log n)": "n²·log",
            "O(n^3)": "n³",
            "O(2^n)": "2ⁿ",
            "O(n!)": "n!",
            "unknown": "?",
        }
        return labels.get(complexity, complexity)

    def _review_content_width(self) -> int:
        width = 340
        try:
            width = self._ai_sidebar_text.viewport().width() - 40
        except Exception:
            pass
        return max(240, min(520, width))

    def _complexity_chart_data_uri(self, counts: dict[str, int], width: int) -> str:
        """Нарисовать столбчатую диаграмму как PNG для QTextBrowser.

        QTextBrowser поддерживает только ограниченный HTML/CSS, поэтому flex/div
        chart не отображается как в браузере. PNG надёжно показывает прозрачный
        фон и реальные столбцы внутри той же правой панели.
        """
        width = max(240, int(width))
        height = 188
        left = 28
        right = 8
        top = 22
        bottom = 44
        plot_w = width - left - right
        plot_h = height - top - bottom
        baseline = top + plot_h
        max_count = max(counts.values(), default=0) or 1

        img = QImage(width, height, QImage.Format.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))

        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        axis_pen = QPen(QColor(255, 255, 255, 36))
        axis_pen.setWidth(1)
        painter.setPen(axis_pen)
        painter.drawLine(left, top, left, baseline)
        painter.drawLine(left, baseline, width - right, baseline)

        label_font = QFont("Segoe UI", 8)
        count_font = QFont("Segoe UI", 7)
        painter.setFont(count_font)
        painter.setPen(QColor(185, 185, 185, 220))
        painter.drawText(0, top - 2, left - 5, 14, Qt.AlignRight, str(max_count))
        painter.drawText(0, baseline - 7, left - 5, 14, Qt.AlignRight, "0")

        chart_classes = list(BIG_O_CLASSES)
        if counts.get("unknown", 0):
            chart_classes.append("unknown")
        n_classes = len(chart_classes)
        slot_w = plot_w / max(1, n_classes)
        bar_w = max(10, int(slot_w * 0.58))

        for idx, complexity in enumerate(chart_classes):
            count = counts.get(complexity, 0)
            bar_h = int((count / max_count) * (plot_h - 16)) if count else 3
            x = int(left + idx * slot_w + (slot_w - bar_w) / 2)
            y = baseline - bar_h
            color = self._complexity_qcolor(complexity, 245 if count else 70)
            painter.fillRect(x, y, bar_w, bar_h, color)

            painter.setFont(count_font)
            painter.setPen(QColor(220, 220, 220, 230))
            count_y = max(2, y - 18)
            painter.drawText(
                x - 6,
                count_y,
                bar_w + 12,
                12,
                Qt.AlignCenter,
                str(count),
            )

            painter.setFont(label_font)
            painter.setPen(QColor(190, 190, 190, 230))
            label_rect_x = int(left + idx * slot_w)
            label_text = self._chart_complexity_label(complexity)
            painter.drawText(
                label_rect_x,
                baseline + 8,
                int(slot_w),
                bottom - 6,
                Qt.AlignHCenter | Qt.AlignTop,
                label_text,
            )

        painter.end()

        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buffer, "PNG")
        buffer.close()
        encoded = base64.b64encode(bytes(data)).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    @staticmethod
    def _clear_button_data_uri() -> str:
        """Нарисовать кнопку очистки как PNG.

        QTextBrowser поддерживает только ограниченный CSS, поэтому border-radius
        у HTML-ссылки может не отображаться. PNG гарантирует видимую скруглённую
        рамку и фон, при этом сама картинка остаётся внутри кликабельной ссылки.
        """
        width = 78
        height = 24
        img = QImage(width, height, QImage.Format.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))

        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(1.0, 1.0, width - 2.0, height - 2.0)
        painter.setPen(QPen(QColor(245, 110, 110, 120), 1))
        painter.setBrush(QColor(245, 110, 110, 32))
        painter.drawRoundedRect(rect, 8.0, 8.0)
        painter.setPen(QColor(255, 185, 185, 245))
        painter.setFont(QFont("Segoe UI", 7))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Очистить")
        painter.end()

        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buffer, "PNG")
        buffer.close()
        encoded = base64.b64encode(bytes(data)).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def _format_project_review_html(self, result) -> str:
        analyzed = analyzable_blocks(result.all_blocks)
        counts = self._count_complexities(analyzed)
        recommendations = self._pick_project_recommendations(analyzed)
        ai_recommendations = getattr(result, "project_recommendations", {}) or {}
        chart_width = self._review_content_width()
        self._project_review_chart_width = chart_width
        chart_uri = self._complexity_chart_data_uri(counts, chart_width)

        rec_items: list[str] = []
        for block in recommendations:
            bid = block_graph_id(block)
            label = self._block_label(block)
            file_name = os.path.basename(block.file_path)
            complexity = block.complexity or "unknown"
            recommendation = self._recommendation_text(
                block,
                ai_recommendations.get(bid),
            )
            rec_items.append(
                f"""
                <div class="rec-card">
                  <a class="rec-title" href="bigo://block/{html.escape(bid)}">
                    {html.escape(label)}
                  </a>
                  <div class="rec-meta">
                    {html.escape(file_name)}:{block.start_line}-{block.end_line}
                    · {html.escape(complexity)}
                  </div>
                  <div class="rec-text">{html.escape(recommendation)}</div>
                </div>
                """
            )

        rec_html = (
            "".join(rec_items)
            if rec_items
            else '<div class="muted">Критичных hotspots по текущим правилам не найдено.</div>'
        )
        summary = self._project_review_summary(analyzed, counts)

        return f"""
        <html>
        <head>
        <style>
          body {{
            margin: 0;
            background: rgb(32, 33, 38);
            color: rgb(220, 220, 220);
            font-family: "Segoe UI", Arial, sans-serif;
            font-size: 12px;
          }}
          .wrap {{ padding: 4px 12px 14px 12px; }}
          .stat {{
            margin-bottom: 12px;
            color: rgb(210, 210, 210);
            font-size: 13px;
          }}
          h3 {{
            margin: 12px 0 8px 0;
            font-size: 12px;
            letter-spacing: 0.6px;
            text-transform: uppercase;
            color: rgb(235, 235, 235);
          }}
          .chart {{
            background: transparent;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 8px;
            padding: 6px;
            text-align: center;
          }}
          .chart-img {{ background: transparent; border: 0; }}
          .summary {{
            color: rgb(215, 215, 215);
            line-height: 1.45;
          }}
          .rec-card {{
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 8px;
            padding: 8px;
            margin: 7px 0;
            background: rgba(255, 255, 255, 0.025);
          }}
          .rec-title {{
            color: rgb(145, 190, 255);
            font-weight: 600;
            text-decoration: none;
          }}
          .rec-meta {{
            color: rgb(165, 165, 165);
            font-size: 11px;
            margin-top: 3px;
          }}
          .rec-text {{
            color: rgb(215, 215, 215);
            line-height: 1.35;
            margin-top: 6px;
          }}
          .muted {{ color: rgb(165, 165, 165); }}
        </style>
        </head>
        <body>
        <div class="wrap">
          <div class="stat">
            Всего блоков проанализированно: <b>{len(analyzed)}</b>
          </div>

          <h3>Распределение по сложности</h3>
          <div class="chart">
            <img class="chart-img" src="{chart_uri}" width="{chart_width}" height="188" />
          </div>

          <h3>Общая оценка</h3>
          <div class="summary">{html.escape(summary)}</div>

          <h3>Рекомендации</h3>
          {rec_html}
        </div>
        </body>
        </html>
        """

    def _format_block_reviews_html(self) -> str:
        if not self._block_review_order:
            return """
            <html><body style="background: rgb(32,33,38); color: rgb(190,190,190);
            font-family: 'Segoe UI', Arial, sans-serif; font-size: 12px; margin: 0;">
              <div style="padding: 10px 12px;">Рецензии отдельных блоков пока не открывались.</div>
            </body></html>
            """

        active_id = self._active_block_review_id or self._block_review_order[-1]
        nav_items: list[str] = []
        for bid in self._block_review_order:
            block = self._blocks_by_id.get(bid)
            if block is None:
                continue
            label = self._block_label(block)
            file_name = os.path.basename(block.file_path)
            active_class = " active" if bid == active_id else ""
            nav_items.append(
                f"""
                <div class="block-row">
                  <a class="block-pill{active_class}" href="bigo://review/{html.escape(bid)}">
                    {html.escape(label)} · {html.escape(file_name)}:{block.start_line}
                  </a>
                </div>
                """
            )

        active_block = self._blocks_by_id.get(active_id)
        goto_link = ""
        if active_block is not None:
            goto_link = (
                f'<a class="goto-link" href="bigo://block/{html.escape(active_id)}">'
                "Перейти к блоку в коде</a>"
            )
        review = html.escape(self._block_review_history.get(active_id, "")).replace(
            "\n", "<br>"
        )
        clear_button_uri = self._clear_button_data_uri()

        return f"""
        <html>
        <head>
        <style>
          body {{
            margin: 0;
            background: rgb(32, 33, 38);
            color: rgb(220, 220, 220);
            font-family: "Segoe UI", Arial, sans-serif;
            font-size: 12px;
          }}
          .wrap {{ padding: 10px 12px 14px 12px; }}
          h3 {{
            margin: 14px 0 7px 0;
            font-size: 12px;
            letter-spacing: 0.6px;
            text-transform: uppercase;
            color: rgb(235, 235, 235);
          }}
          .goto-link {{
            color: rgb(145, 190, 255);
            text-decoration: none;
            font-size: 11px;
          }}
          .review-box {{
            margin-top: 7px;
            line-height: 1.38;
            color: rgb(220, 220, 220);
          }}
          .block-list {{
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 7px;
            background: rgba(255, 255, 255, 0.018);
            padding: 6px;
            margin-top: 4px;
          }}
          .block-row {{
            display: block;
            margin: 0 0 6px 0;
            padding: 0;
          }}
          .block-row:last-child {{
            margin-bottom: 0;
          }}
          .block-pill {{
            display: block;
            color: rgb(205, 205, 205);
            text-decoration: none;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 5px;
            padding: 5px 7px;
            margin: 0;
            background: rgba(255, 255, 255, 0.025);
            font-size: 11px;
          }}
          .block-pill.active {{
            color: rgb(235, 240, 255);
            border-color: rgba(150, 180, 240, 0.38);
            background: rgba(120, 150, 210, 0.16);
          }}
          .clear-row {{
            display: block;
            padding-top: 18px;
          }}
          .clear-link {{ text-decoration: none; }}
          .clear-img {{ border: 0; }}
        </style>
        </head>
        <body>
          <div class="wrap">
            {goto_link}
            <div class="review-box">{review}</div>
            <h3>Проанализированные блоки</h3>
            <div class="block-list">{''.join(nav_items)}</div>
            <div class="clear-row">
              <a class="clear-link" href="bigo://clear/blocks">
                <img class="clear-img" src="{clear_button_uri}" width="78" height="24" />
              </a>
            </div>
          </div>
        </body>
        </html>
        """

    def show_project_review_tab(self) -> None:
        if not self._project_review_text:
            return
        self._show_ai_sidebar()
        self._showing_project_review = True
        self._set_ai_status("")
        self._set_active_review_tab("project")
        if hasattr(self._ai_sidebar_text, "setHtml"):
            self._ai_sidebar_text.setHtml(self._project_review_text)
        else:
            self._ai_sidebar_text.setPlainText(self._project_review_text)

    def show_block_reviews_tab(self) -> None:
        if not self._block_review_order:
            return
        self._show_ai_sidebar()
        self._showing_project_review = False
        self._set_active_review_tab("blocks")
        if hasattr(self._ai_sidebar_text, "setHtml"):
            self._ai_sidebar_text.setHtml(self._format_block_reviews_html())
        else:
            active_id = self._active_block_review_id or self._block_review_order[-1]
            self._ai_sidebar_text.setPlainText(
                self._block_review_history.get(active_id, "")
            )

    def clear_block_reviews(self) -> None:
        self._block_review_history.clear()
        self._block_review_order.clear()
        self._active_block_review_id = None
        result = self._last_project_result
        storage_path = getattr(result, "storage_path", None) if result is not None else None
        root_path = getattr(result, "root_path", None) if result is not None else None
        if storage_path and root_path:
            try:
                from bigo.storage import BigoStorage

                storage = BigoStorage(root_path, storage_path)
                storage.delete_block_reviews()
                storage.close()
            except Exception:
                pass
        self._set_block_tab_visible(False)
        self.show_project_review_tab()

    def _index_blocks(self, result) -> None:
        from bigo.dependency_graph import block_graph_id

        self._blocks_by_id = {block_graph_id(b): b for b in result.all_blocks}
        self._results_by_id = dict(getattr(result, "block_results", {}) or {})
        self._ollama_available_last = result.ollama_available

    def _on_finished(self, result) -> None:
        self._analysis_running = False
        self._spinner_timer.stop()
        self._last_status_message = ""
        self._set_ai_status("")
        self._show_ai_sidebar()

        self._index_blocks(result)
        self._last_project_result = result
        self._showing_project_review = True
        self._project_review_text = self._format_project_review_html(result)
        self._set_active_review_tab("project")
        if hasattr(self._ai_sidebar_text, "setHtml"):
            self._ai_sidebar_text.setHtml(self._project_review_text)
        else:
            self._ai_sidebar_text.setPlainText(result.review_text or "")

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
        if not self._showing_project_review:
            self._set_ai_status(f"Big-O блоки отображены: {count}")

    def _rerender_project_review_if_visible(self) -> None:
        if not self._showing_project_review or self._last_project_result is None:
            return
        if not hasattr(self._ai_sidebar_text, "setHtml"):
            return
        new_width = self._review_content_width()
        if (
            self._project_review_chart_width is not None
            and abs(new_width - self._project_review_chart_width) < 4
        ):
            return
        scroll_bar = self._ai_sidebar_text.verticalScrollBar()
        old_scroll = scroll_bar.value()
        self._project_review_text = self._format_project_review_html(
            self._last_project_result
        )
        self._ai_sidebar_text.setHtml(self._project_review_text)
        QTimer.singleShot(
            0,
            lambda value=old_scroll: self._ai_sidebar_text.verticalScrollBar().setValue(
                min(value, self._ai_sidebar_text.verticalScrollBar().maximum())
            ),
        )

    def _on_sidebar_link_clicked(self, url: QUrl) -> None:
        if url.scheme() != "bigo":
            return
        if url.host() == "block":
            block_id = url.path().lstrip("/")
            if block_id:
                self.go_to_block(block_id)
            return
        if url.host() == "review":
            block_id = url.path().lstrip("/")
            if block_id and block_id in self._block_review_history:
                self._active_block_review_id = block_id
                self.show_block_reviews_tab()
            return
        if url.host() == "clear" and url.path().lstrip("/") == "blocks":
            self.clear_block_reviews()
            return

    def go_to_block(self, block_id: str) -> None:
        block = self._blocks_by_id.get(block_id)
        if block is None:
            self._set_ai_status(
                f"Big-O: блок не найден (id={block_id[:8]}…), запустите анализ заново"
            )
            return
        self._tab_manager.open_file(block.file_path)
        self._editor.set_cursor(block.start_line, 1, move_to_position="center")

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
        result = self._last_project_result
        storage_path = getattr(result, "storage_path", None) if result is not None else None
        root_path = getattr(result, "root_path", None) if result is not None else None
        if storage_path and root_path:
            try:
                from bigo.storage import BigoStorage

                storage = BigoStorage(root_path, storage_path)
                storage.save_block_review(
                    block,
                    text,
                    source_kind="local",
                    model_id=getattr(analysis, "model_id", None) if analysis else None,
                )
                storage.close()
            except Exception:
                pass
        self._show_ai_sidebar()
        self._block_review_history[block_id] = text
        if block_id not in self._block_review_order:
            self._block_review_order.append(block_id)
        self._active_block_review_id = block_id
        self._set_block_tab_visible(True)
        self.show_block_reviews_tab()
        name = block.qualified_name or block.short_name
        self._set_ai_status(f"Рецензия блока: {name}")
