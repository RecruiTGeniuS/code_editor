"""
Управление вкладками открытых файлов в верхней панели `tabBarFrame`.

Архитектура (multi-tab):

  tabBarFrame (QFrame, host из main.ui)
    └── QHBoxLayout (без отступов)
        └── QScrollArea (горизонтальный скролл, видимый по необходимости)
            └── content (QWidget)
                └── QHBoxLayout: [EditorTab] [EditorTab] ... [stretch]

Один Monaco-редактор обслуживает все вкладки: при переключении сохраняем текст
текущей вкладки в её Python-буфер, грузим в редактор содержимое выбранной.
Не используем `monaco.editor.createModel` ради простоты — подобный «толстый»
вариант с моделями оставлен на будущее (даст per-tab undo и позицию курсора).

Логика заголовка вкладки (как и раньше, но теперь — на каждую вкладку):
- пока файл не сохранён, заголовок = первая непустая строка текста (с обрезкой)
  и обновляется при каждом изменении текста активной вкладки;
- после сохранения заголовок «прибит» к имени файла.

Ширина вкладок пересчитывается:
- при изменении размера viewport скролл-области;
- при добавлении/удалении вкладки.
Формула: target = clamp(MIN, MAX, viewport_width / N). Когда `viewport_width / N`
проваливается ниже MIN, все вкладки фиксируются на MIN, и QScrollArea сама
показывает горизонтальный ползунок.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QWidget,
)

from image_viewer import IMAGE_EXTENSIONS, ImageViewer


# Соответствие расширений файлов идентификаторам языков Monaco. Список покрывает
# распространённые языки; если расширение неизвестно, подсветка не меняется.
EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".pyw": "python",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".c": "c",
    ".h": "c",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".json": "json",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".md": "markdown",
    ".markdown": "markdown",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".ps1": "powershell",
    ".bat": "bat",
    ".cmd": "bat",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".xml": "xml",
    ".sql": "sql",
    ".rs": "rust",
    ".go": "go",
    ".rb": "ruby",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    ".php": "php",
    ".lua": "lua",
    ".r": "r",
    ".dart": "dart",
    ".toml": "ini",
    ".ini": "ini",
    ".cfg": "ini",
    ".vue": "html",
}


def language_from_path(path: str) -> str | None:
    """Подобрать идентификатор языка Monaco для пути к файлу."""
    base = os.path.basename(path).lower()
    if base == "dockerfile" or base.startswith("dockerfile."):
        return "dockerfile"
    ext = os.path.splitext(path)[1].lower()
    return EXTENSION_TO_LANGUAGE.get(ext)


@dataclass
class _TabState:
    """Содержимое одной вкладки, не относящееся к её Qt-виджету."""

    title: str = "Untitled"
    file_path: str | None = None
    content: str = ""
    language: str | None = None
    title_pinned: bool = False
    # Тип вкладки определяет, какой виджет показывать в QStackedWidget при
    # активации: "text" → Monaco, "image" → ImageViewer. Расширяемо, если
    # позже добавим, например, hex-просмотр или предпросмотр PDF.
    kind: str = "text"
    widget: "EditorTab" = field(default=None)  # type: ignore[assignment]


class EditorTab(QFrame):
    """Одна вкладка с заголовком и кнопкой закрытия."""

    clicked = Signal()
    close_clicked = Signal()

    # Базовая линия снизу совпадает по цвету с рамкой приложения rgb(63, 65, 68),
    # чтобы вкладка не «выбивалась» из темы. У активной вкладки линия на пиксель
    # толще и заметно светлее (rgb(120, 124, 132)) — холодный серый, без акцентных
    # цветов, чтобы было понятно «какая выбрана».
    _STYLE = """
    #editorTab {
        background-color: rgb(49, 51, 56);
        border-right: 1px solid rgb(63, 65, 68);
        border-bottom: 1px solid rgb(63, 65, 68);
    }
    #editorTab[active="true"] {
        border-bottom: 2px solid rgb(120, 124, 132);
    }
    #editorTabLabel {
        background-color: transparent;
        color: rgb(220, 220, 220);
        font-size: 12px;
        padding: 0px 4px;
    }
    #editorTabClose {
        background-color: transparent;
        border: none;
        border-radius: 4px;
        color: rgb(180, 180, 180);
        font-size: 18px;
        padding: 0px 0px 2px 0px;
    }
    #editorTabClose:hover {
        background-color: rgba(255, 255, 255, 30);
        color: rgb(230, 230, 230);
    }
    #editorTabClose:pressed {
        background-color: rgba(255, 255, 255, 50);
    }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("editorTab")
        # Свойство `active` нужно ВЫСТАВИТЬ до setStyleSheet, иначе Qt
        # сначала отрисует со значением None и `[active="true"]` не сработает.
        self.setProperty("active", False)
        self.setStyleSheet(self._STYLE)
        # Размер по горизонтали диктуется снаружи (TabManager пересчитывает),
        # по вертикали — растягиваемся под высоту панели.
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 6, 0)
        layout.setSpacing(6)

        self.label = QLabel("Untitled", self)
        self.label.setObjectName("editorTabLabel")
        self.label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        # Label занимает всё свободное место — иначе при сужении вкладки текст
        # съест кнопку закрытия. С setMinimumWidth(0) label сам урежется
        # эллипсом (см. set_title), а кнопка останется на месте.
        self.label.setMinimumWidth(0)
        self.label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.label, 1)

        self.close_btn = QPushButton("×", self)
        self.close_btn.setObjectName("editorTabClose")
        self.close_btn.setFixedSize(22, 22)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.clicked.connect(self.close_clicked.emit)
        layout.addWidget(self.close_btn)

    def set_title(self, title: str) -> None:
        # При узкой вкладке Qt сам не обрезает label эллипсом — обрежем
        # программно по доступной ширине, остальное оставим в tooltip.
        self._raw_title = title
        self.label.setToolTip(title)
        self._refresh_label()

    def _refresh_label(self) -> None:
        if not hasattr(self, "_raw_title"):
            return
        metrics = self.label.fontMetrics()
        avail = self.label.width()
        if avail <= 0:
            self.label.setText(self._raw_title)
            return
        elided = metrics.elidedText(self._raw_title, Qt.ElideRight, avail)
        self.label.setText(elided)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_label()

    def set_active(self, active: bool) -> None:
        """Переключить визуальное состояние «выбрана/не выбрана»."""
        if self.property("active") == active:
            return
        self.setProperty("active", active)
        # QSS со селектором по динамическому свойству нужно «перепрожевать»,
        # иначе Qt не перерисует виджет с новым стилем.
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        # ЛКМ по самой вкладке (не по крестику) — переключение. Крестик
        # обрабатывается своим кликом и до сюда не доходит, потому что у
        # QPushButton accept'ится событие.
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class TabManager(QObject):
    """Связывает Monaco-редактор и `tabBarFrame` (multi-tab)."""

    # Смена активной вкладки, пути, языка — чтобы обновить BottomBar и т.п.
    active_tab_changed = Signal()

    _MAX_TITLE_CHARS = 32
    # Разумный коридор ширины: читаемый минимум и не «жирная» полоса при одной
    # вкладке. Между ними — равномерная подгонка под доступное место.
    _MIN_TAB_WIDTH = 90
    _MAX_TAB_WIDTH = 200

    # Стили скролл-области и горизонтального ползунка в тёмной теме приложения.
    _SCROLL_STYLE = """
    QScrollArea {
        background: transparent;
        border: none;
    }
    QScrollArea > QWidget > QWidget {
        background: transparent;
    }
    QScrollBar:horizontal {
        background: transparent;
        border: none;
        height: 6px;
        margin: 0px;
    }
    QScrollBar::handle:horizontal {
        background: rgba(255, 255, 255, 35);
        min-width: 30px;
        border-radius: 3px;
    }
    QScrollBar::handle:horizontal:hover {
        background: rgba(255, 255, 255, 60);
    }
    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal {
        width: 0px;
        background: transparent;
        border: none;
    }
    QScrollBar::add-page:horizontal,
    QScrollBar::sub-page:horizontal {
        background: transparent;
    }
    """

    _MENU_STYLE = """
    QMenu {
        background-color: rgb(43, 45, 49);
        color: rgb(220, 220, 220);
        border: 1px solid rgb(63, 65, 68);
        padding: 4px 0px;
    }
    QMenu::item {
        padding: 6px 18px;
        background-color: transparent;
    }
    QMenu::item:selected {
        background-color: rgba(255, 255, 255, 25);
    }
    QMenu::item:disabled {
        color: rgb(140, 140, 140);
    }
    QMenu::separator {
        height: 1px;
        background-color: rgb(63, 65, 68);
        margin: 4px 8px;
    }
    """

    def __init__(
        self,
        tab_bar_frame: QFrame,
        editor,
        image_viewer: "ImageViewer",
        view_stack: "QStackedWidget",
    ):
        super().__init__(tab_bar_frame)
        self._tab_bar = tab_bar_frame
        self._editor = editor
        self._image_viewer = image_viewer
        self._stack = view_stack
        self._tabs: list[_TabState] = []
        self._active: _TabState | None = None
        # Когда меняем текст редактора программно (переключение вкладок), не
        # надо реагировать на text_changed как на пользовательский ввод.
        self._suppress_text_changed = False

        outer = QHBoxLayout(tab_bar_frame)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(tab_bar_frame)
        scroll.setObjectName("tabBarScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(self._SCROLL_STYLE)
        outer.addWidget(scroll)

        content = QWidget()
        content.setObjectName("tabBarScrollContent")
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addStretch(1)
        scroll.setWidget(content)

        self._scroll = scroll
        self._content = content
        self._content_layout = content_layout

        # Слушаем изменение размера viewport, чтобы пересчитывать ширину вкладок
        # «по факту» доступной области, а не по размеру самого фрейма.
        scroll.viewport().installEventFilter(self)

        editor.text_changed.connect(self._on_text_changed)

    def _notify_active_changed(self) -> None:
        self.active_tab_changed.emit()

    # ───────────────────────── Публичный API ─────────────────────────

    @property
    def has_tabs(self) -> bool:
        return bool(self._tabs)

    @property
    def file_path(self) -> str | None:
        """Путь активной вкладки (None, если активной нет или она не сохранена)."""
        return self._active.file_path if self._active else None

    @property
    def active_language(self) -> str | None:
        return self._active.language if self._active else None

    @property
    def active_kind(self) -> str | None:
        """Тип активной вкладки: "text", "image" или None, если вкладок нет."""
        return self._active.kind if self._active else None

    def create_new_tab(self) -> None:
        """Создать пустую Untitled-вкладку и переключиться на неё."""
        tab = self._add_tab_state(_TabState(title="Untitled"))
        self._switch_to(tab)

    def open_file(self, path: str) -> None:
        """Открыть файл с диска. Если он уже во вкладке — переключаемся на неё."""
        norm = os.path.normcase(os.path.abspath(path))
        for state in self._tabs:
            if state.file_path and os.path.normcase(
                os.path.abspath(state.file_path)
            ) == norm:
                self._switch_to(state)
                return

        ext = os.path.splitext(path)[1].lower()
        if ext in IMAGE_EXTENSIONS:
            # Картинки не читаем как текст: создаём image-вкладку и грузим
            # пиксели уже в `_switch_to` через `ImageViewer.load`.
            state = _TabState(
                title=os.path.basename(path),
                file_path=path,
                title_pinned=True,
                kind="image",
            )
            self._add_tab_state(state)
            self._switch_to(state)
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            QMessageBox.warning(
                self._tab_bar,
                "Не удалось открыть файл",
                f"{os.path.basename(path)}:\n{exc}",
            )
            return

        language = language_from_path(path)
        state = _TabState(
            title=os.path.basename(path),
            file_path=path,
            content=content,
            language=language,
            title_pinned=True,
        )
        self._add_tab_state(state)
        self._switch_to(state)
        if language is not None:
            self._editor.set_language(language)

    def attach_file_path(self, path: str) -> None:
        """Привязать сохранённый путь к АКТИВНОЙ вкладке."""
        if self._active is None:
            self._active = self._add_tab_state(_TabState())
            self._set_active_tab(self._active)
        self._active.file_path = path
        self._active.title_pinned = True
        self._active.title = os.path.basename(path)
        self._active.widget.set_title(self._active.title)
        self._notify_active_changed()

    def update_active_language(self, language: str | None) -> None:
        """Запомнить язык активной вкладки (вызывается после сохранения)."""
        if self._active is not None:
            self._active.language = language
        self._notify_active_changed()

    def show_all_files_menu(self, anchor: QWidget) -> None:
        """Показать выпадающий список вкладок под кнопкой `anchor`."""
        menu = QMenu(anchor)
        menu.setStyleSheet(self._MENU_STYLE)
        if not self._tabs:
            empty = menu.addAction("Нет открытых файлов")
            empty.setEnabled(False)
        else:
            for state in self._tabs:
                action = menu.addAction(state.title)
                action.setCheckable(True)
                action.setChecked(state is self._active)
                # default-arg фиксирует ссылку на конкретную вкладку, иначе
                # все лямбды захватят последнюю переменную цикла.
                action.triggered.connect(
                    lambda checked=False, s=state: self._switch_to(s)
                )
        # Якорь — нижний левый угол кнопки, чтобы меню «выросло» прямо из неё.
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))

    # ───────────────────────── Внутреннее ─────────────────────────

    def eventFilter(self, obj, event):
        if obj is self._scroll.viewport() and event.type() == QEvent.Resize:
            self._recalculate_widths()
        return super().eventFilter(obj, event)

    def _add_tab_state(self, state: _TabState) -> _TabState:
        widget = EditorTab(self._content)
        widget.set_title(state.title)
        widget.clicked.connect(lambda s=state: self._switch_to(s))
        widget.close_clicked.connect(lambda s=state: self._close_tab(s))
        state.widget = widget

        # Вставляем перед финальным stretch — он всегда последний элемент.
        insert_at = self._content_layout.count() - 1
        self._content_layout.insertWidget(insert_at, widget)
        self._tabs.append(state)
        self._recalculate_widths()
        return state

    def _switch_to(self, state: _TabState) -> None:
        if state is self._active:
            return
        # Сохраняем то, что пользователь успел напечатать в текущей вкладке —
        # только если она текстовая. Для image-вкладок редактор был скрыт и
        # его текст принадлежит другой (предыдущей текстовой) вкладке.
        if self._active is not None and self._active.kind == "text":
            self._active.content = self._editor.get_text()

        self._active = state
        self._set_active_tab(state)

        if state.kind == "image":
            # Переключаем стэк на просмотрщик и загружаем картинку. Если
            # путь почему-то пуст (image-вкладка без файла создаваться не
            # должна, но на всякий) — просто очищаем вьювер.
            self._stack.setCurrentWidget(self._image_viewer)
            if state.file_path:
                self._image_viewer.load(state.file_path)
            else:
                self._image_viewer.clear()
            self._notify_active_changed()
            return

        # Текстовая ветка: возвращаемся на Monaco, грузим содержимое вкладки.
        self._stack.setCurrentWidget(self._editor)
        # Программное set_text эмиттит text_changed — гасим, чтобы не перебить
        # заголовок «первой строкой» от автозаголовка.
        self._suppress_text_changed = True
        try:
            self._editor.set_text(state.content)
        finally:
            self._suppress_text_changed = False

        if state.language is not None:
            self._editor.set_language(state.language)

        self._notify_active_changed()

    def _close_tab(self, state: _TabState) -> None:
        if state not in self._tabs:
            return
        idx = self._tabs.index(state)
        was_active = state is self._active
        self._tabs.remove(state)
        self._content_layout.removeWidget(state.widget)
        state.widget.deleteLater()

        if not self._tabs:
            self._active = None
            # Возвращаемся к редактору — иначе после закрытия image-вкладки
            # стэк остался бы на просмотрщике и пустой Monaco стал недоступен.
            self._stack.setCurrentWidget(self._editor)
            self._image_viewer.clear()
            self._suppress_text_changed = True
            try:
                self._editor.set_text("")
            finally:
                self._suppress_text_changed = False
            self._recalculate_widths()
            self._notify_active_changed()
            return

        if was_active:
            # Стандартное поведение редакторов: переключиться на соседнюю
            # справа, если есть, иначе на крайнюю слева новой границы списка.
            new_idx = min(idx, len(self._tabs) - 1)
            self._active = None  # форсируем фактическое переключение
            self._switch_to(self._tabs[new_idx])
        self._recalculate_widths()

    def _set_active_tab(self, target: _TabState) -> None:
        for state in self._tabs:
            state.widget.set_active(state is target)

    def _on_text_changed(self, text: str) -> None:
        if self._suppress_text_changed:
            return
        # Если активна image-вкладка — Monaco скрыт, и любое изменение текста
        # пришло от старого содержимого предыдущей вкладки или программного
        # сброса. К состоянию активной вкладки это отношения не имеет.
        if self._active is not None and self._active.kind == "image":
            return
        # Backwards-совместимость: если пользователь начал печатать в пустой
        # редактор без вкладок (например, при первом запуске), создаём её
        # автоматически. Это сохраняет старый UX.
        if self._active is None:
            self._active = self._add_tab_state(_TabState())
            self._set_active_tab(self._active)
            self._notify_active_changed()
        self._active.content = text
        if not self._active.title_pinned:
            new_title = self._title_from_text(text)
            if new_title != self._active.title:
                self._active.title = new_title
                self._active.widget.set_title(new_title)

    def _recalculate_widths(self) -> None:
        n = len(self._tabs)
        viewport_w = self._scroll.viewport().width()
        if n == 0 or viewport_w <= 0:
            self._content.setMinimumWidth(0)
            return
        # Делим viewport поровну между вкладками; фиксируем диапазон.
        ideal = viewport_w // n
        target = max(self._MIN_TAB_WIDTH, min(self._MAX_TAB_WIDTH, ideal))
        for state in self._tabs:
            state.widget.setMinimumWidth(target)
            state.widget.setMaximumWidth(target)
        # Явно сообщаем content-виджету его минимум: при N*target > viewport
        # это «толкает» QScrollArea показать ползунок. Без этого Qt в некоторых
        # версиях позволяет content схлопнуться до viewport и скрывает скролл.
        self._content.setMinimumWidth(target * n)
        self._content.updateGeometry()

    @classmethod
    def _title_from_text(cls, text: str) -> str:
        # Ищем первую непустую строку — пустые верхние ничего не говорят
        # о содержимом.
        for raw in text.split("\n"):
            line = raw.strip()
            if line:
                if len(line) > cls._MAX_TITLE_CHARS:
                    return line[: cls._MAX_TITLE_CHARS] + "…"
                return line
        return "Untitled"
