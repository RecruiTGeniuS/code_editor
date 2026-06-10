import json
import sys
import os

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
)

from bottom_status import LINE_COL_PLACEHOLDER, language_label_for_monaco_id
from bigo_controller import BigOController
from editor_navigation import EditorNavigation
from editor_theme import ONE_DARK_PRO_THEME, ONE_DARK_PRO_THEME_NAME
from file_tree import DARK_MENU_STYLE, Sidebar
from image_viewer import ImageViewer
from language_grammars import LANGUAGE_GRAMMARS
from monaco_widget import CustomMonaco
from tab_manager import TabManager, language_from_path
from ui_functions import UIFunctions
from main_ui import Ui_MainWindow
import resources_from_qt_rc  # noqa: F401  (нужен для подгрузки иконок из ресурсов)

os.environ["QT_FONT_DPI"] = "96"

# Чтобы Windows показывал нашу иконку в панели задач, а не значок python.exe,
# приложению нужен собственный AppUserModelID. Должно вызываться до QApplication.
if sys.platform == "win32":
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
        "SeniorThesis.CodeEditor.1.0"
    )

LOGO_RESOURCE_PATH = ":/Images/images/logo.png"
APP_LOGO_SIZE_PX = 22

widgets = None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        global widgets
        widgets = self.ui

        logo_pixmap = QPixmap(LOGO_RESOURCE_PATH).scaled(
            APP_LOGO_SIZE_PX,
            APP_LOGO_SIZE_PX,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.ui.appLogo.setPixmap(logo_pixmap)

        self._setup_editor()
        self._setup_bigo_ui()
        self._setup_sidebar()
        self._setup_tabs()
        self._setup_bigo_controller()
        self._setup_navigation()
        self._setup_file_menu()
        self._setup_shortcuts()
        self._setup_bottom_bar_status()

        UIFunctions.ui_definitions(self)

    def _setup_editor(self):
        editor_layout = QVBoxLayout(self.ui.monacoFrame)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(0)

        # Внутри monacoFrame — стэк из двух «видов»: Monaco для текстовых
        # файлов и ImageViewer для картинок. Тaб-менеджер переключает текущую
        # страницу стэка по типу активной вкладки.
        self.view_stack = QStackedWidget(self.ui.monacoFrame)

        self.editor = CustomMonaco(self.view_stack)
        # Фон Chromium до загрузки Monaco — точно совпадает с фоном нашей темы,
        # чтобы при первом старте не мелькало никаких артефактов.
        self.editor.page().setBackgroundColor(QColor(49, 51, 56))
        self.editor.set_language("python")
        self.editor.initialized.connect(self._apply_custom_theme)
        self.view_stack.addWidget(self.editor)

        self.image_viewer = ImageViewer(self.view_stack)
        self.view_stack.addWidget(self.image_viewer)

        editor_layout.addWidget(self.view_stack)

    def _apply_custom_theme(self):
        # Делаем это после сигнала `initialized`, чтобы JS-объект monaco уже существовал.
        # Шаги:
        #   1. defineTheme — регистрируем One Dark Pro палитру.
        #   2. setMonarchTokensProvider для каждого языка из LANGUAGE_GRAMMARS —
        #      подменяем встроенный тонкенайзер на «умный», который различает
        #      class.name / function.name / function.call / variable / decorator
        #      (нужно, чтобы эти типы токенов отличались по цвету).
        #   3. setTheme — применяем тему уже после регистрации грамматик, чтобы
        #      обновлённые токены сразу окрасились правильно.
        theme_name_js = json.dumps(ONE_DARK_PRO_THEME_NAME)
        theme_js = json.dumps(ONE_DARK_PRO_THEME)
        grammars_js = json.dumps(LANGUAGE_GRAMMARS)
        js_code = (
            "monaco.editor.defineTheme(" + theme_name_js + ", " + theme_js + ");"
            "var __grammars = " + grammars_js + ";"
            "for (var __lang in __grammars) {"
            "  monaco.languages.setMonarchTokensProvider(__lang, __grammars[__lang]);"
            "}"
            "monaco.editor.setTheme(" + theme_name_js + ");"
        )
        self.editor.page().runJavaScript(js_code)

    def _setup_tabs(self):
        # Защита от коллапса соседних с tabBarFrame фреймов: пустой QFrame в
        # QHBoxLayout без минимума схлопывается в 0px, и tabBarFrame визуально
        # «съезжает», накрывая место под стрелочки и кнопки добавления.
        # Форсируем минимальную ширину равной максимальной, которую разработчик
        # задаёт в Qt Designer (если максимум вообще задан — дефолтное значение
        # QWIDGETSIZE_MAX = 16777215 игнорируем).
        for frame in (self.ui.arrowFrame, self.ui.filesAddListFrame):
            max_w = frame.maximumWidth()
            if max_w < 16777215:
                frame.setMinimumWidth(max_w)

        self.tab_manager = TabManager(
            self.ui.tabBarFrame, self.editor, self.image_viewer, self.view_stack
        )

        self.ui.addFileBtn.clicked.connect(self.tab_manager.create_new_tab)
        self.ui.showAllFilesBtn.clicked.connect(
            lambda: self.tab_manager.show_all_files_menu(self.ui.showAllFilesBtn)
        )
        # Big-O: подсветка при смене вкладки (контроллер создаётся позже в __init__).

    def _setup_bigo_ui(self):
        """Кнопка Big-O + правый AI sidebar (виджеты; логика — в BigOController)."""
        # Кнопка в самом блоке rightButtons, перед системными кнопками окна.
        bigo_btn = QPushButton(self.ui.rightButtons)
        bigo_btn.setObjectName("bigOButton")
        bigo_btn.setMinimumSize(30, 30)
        bigo_btn.setMaximumSize(30, 30)
        bigo_btn.setCursor(Qt.PointingHandCursor)
        bigo_btn.setCheckable(True)
        bigo_btn.setToolTip("Big-O анализ проекта")
        bigo_btn.setStyleSheet(
            """
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 30);
            }
            QPushButton:checked {
                background-color: rgba(255, 255, 255, 45);
            }
            """
        )
        bigo_btn.setIcon(QIcon(":/Icons/icons/blocks_rating.png"))
        bigo_btn.setIconSize(QSize(20, 20))
        self.ui.horizontalLayout_4.insertWidget(0, bigo_btn)
        self.big_o_button = bigo_btn
        # clicked → BigOController.toggle_mode (в _setup_bigo_controller)

        # Правый sidebar (AI review + progress).
        self.ai_sidebar = QFrame(self.ui.content)
        self.ai_sidebar.setObjectName("aiSidebar")
        self.ai_sidebar.setMinimumWidth(260)
        self.ai_sidebar.setMaximumWidth(420)
        self.ai_sidebar.setStyleSheet(
            """
            #aiSidebar {
                background-color: rgb(32, 33, 38);
                border-left: 1px solid rgb(63, 65, 68);
            }
            #aiSidebarHeader {
                font-size: 11px;
                font-weight: bold;
                letter-spacing: 1px;
                color: rgb(220, 220, 220);
                padding: 8px 12px 6px 12px;
            }
            #aiSidebarStatus {
                color: rgb(180, 180, 180);
                font-size: 11px;
                padding: 4px 12px;
            }
            #aiSidebarText {
                background-color: rgb(32, 33, 38);
                color: rgb(220, 220, 220);
                border: none;
                padding: 8px 12px;
                font-size: 12px;
            }
            #aiSidebarSettings {
                color: rgb(200, 200, 200);
                font-size: 11px;
            }
            #aiSidebarHint {
                color: rgb(140, 140, 140);
                font-size: 10px;
                padding: 0 12px 8px 12px;
            }
            """
        )
        ai_l = QVBoxLayout(self.ai_sidebar)
        ai_l.setContentsMargins(0, 0, 0, 0)
        ai_l.setSpacing(0)
        header = QLabel("AI РЕЦЕНЗИЯ", self.ai_sidebar)
        header.setObjectName("aiSidebarHeader")
        ai_l.addWidget(header)

        settings = QFrame(self.ai_sidebar)
        settings.setObjectName("aiSidebarSettings")
        settings_l = QVBoxLayout(settings)
        settings_l.setContentsMargins(12, 4, 12, 4)
        settings_l.setSpacing(6)

        self.ai_use_checkbox = QCheckBox(
            "Использовать ИИ для сложных блоков", settings
        )
        self.ai_use_checkbox.setChecked(False)
        settings_l.addWidget(self.ai_use_checkbox)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Модель:", settings))
        self.ai_model_edit = QLineEdit("qwen2.5-coder:7b", settings)
        model_row.addWidget(self.ai_model_edit, 1)
        settings_l.addLayout(model_row)

        timeout_row = QHBoxLayout()
        timeout_row.addWidget(QLabel("Таймаут (с):", settings))
        self.ai_timeout_spin = QSpinBox(settings)
        self.ai_timeout_spin.setRange(5, 600)
        self.ai_timeout_spin.setValue(60)
        timeout_row.addWidget(self.ai_timeout_spin)
        timeout_row.addStretch(1)
        settings_l.addLayout(timeout_row)

        ai_l.addWidget(settings)

        hint = QLabel(
            "ИИ вызывается только для блоков, которые не удалось уверенно "
            "оценить правилами.",
            self.ai_sidebar,
        )
        hint.setObjectName("aiSidebarHint")
        hint.setWordWrap(True)
        ai_l.addWidget(hint)

        self.ai_sidebar_status = QLabel("", self.ai_sidebar)
        self.ai_sidebar_status.setObjectName("aiSidebarStatus")
        ai_l.addWidget(self.ai_sidebar_status)
        self.ai_sidebar_text = QTextEdit(self.ai_sidebar)
        self.ai_sidebar_text.setObjectName("aiSidebarText")
        self.ai_sidebar_text.setReadOnly(True)
        ai_l.addWidget(self.ai_sidebar_text, 1)
        self.ai_sidebar.hide()

        self.ui.sideAiBtn.clicked.connect(self._toggle_ai_sidebar)

    # Стартовая ширина sidebar при первом раскрытии. Запоминаем последний
    # вручную выставленный размер, чтобы повторное раскрытие возвращало его же.
    _SIDEBAR_DEFAULT_WIDTH = 240
    _AI_SIDEBAR_DEFAULT_WIDTH = 300

    def _setup_sidebar(self):
        """Вставить QSplitter [Sidebar | monacoContainer] внутрь content.

        bottomBar лежит ниже content в стэк-лэйауте contentBottom — он не
        затрагивается, как и хотел пользователь (стилистика Sublime Text:
        статус-бар идёт под боковой панелью, а не сбоку).
        """
        self.sidebar = Sidebar(self.ui.content)
        self.sidebar.tree.file_activated.connect(self.tab_manager_open_file_safe)

        splitter = QSplitter(Qt.Horizontal, self.ui.content)
        splitter.setObjectName("contentSplitter")
        # Запрещаем «сжать в 0» — иначе можно случайно потерять виджет
        # перетаскиванием границы. Кнопка-toggle спрячет sidebar полностью.
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(2)
        splitter.setStyleSheet(
            """
            QSplitter::handle:horizontal {
                background-color: rgb(63, 65, 68);
            }
            QSplitter::handle:horizontal:hover {
                background-color: rgb(90, 92, 95);
            }
            """
        )

        # monacoContainer уже сидит в horizontalLayout `content`.
        # Перевешиваем его и sidebar внутрь сплиттера.
        content_layout = self.ui.content.layout()
        content_layout.removeWidget(self.ui.monacoContainer)
        splitter.addWidget(self.sidebar)
        splitter.addWidget(self.ui.monacoContainer)
        splitter.addWidget(self.ai_sidebar)
        # Sidebar — фиксированный «груз», monaco растягивается на остаток.
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        content_layout.addWidget(splitter)

        self._splitter = splitter
        self._sidebar_last_width = self._SIDEBAR_DEFAULT_WIDTH
        self._ai_sidebar_last_width = self._AI_SIDEBAR_DEFAULT_WIDTH
        # Старт — sidebar скрыт. Виден только когда пользователь сам нажмёт
        # toggle или выберет «Открыть папку».
        self.sidebar.hide()
        self.ai_sidebar.hide()

        self.ui.treeSideToggleBtn.clicked.connect(self._toggle_sidebar)

    def tab_manager_open_file_safe(self, path: str) -> None:
        """Прокидываем сигнал из дерева в tab_manager (защищаем от падения)."""
        try:
            self.tab_manager.open_file(path)
        except Exception as exc:  # noqa: BLE001 — UX-обёртка над любыми ошибками
            QMessageBox.critical(self, "Ошибка открытия файла", str(exc))

    def _toggle_sidebar(self):
        if self.sidebar.isVisible():
            # Запоминаем текущую ширину, чтобы при повторном раскрытии вернуть
            # её же — пользователь не теряет результат ручной перетяжки.
            current = self.sidebar.width()
            if current > 0:
                self._sidebar_last_width = current
            self.sidebar.hide()
            return

        self.sidebar.show()
        sizes = self._splitter.sizes()
        total = sum(sizes) or self._splitter.width()
        while len(sizes) < 3:
            sizes.append(0)
        sizes[0] = max(self.sidebar.minimumWidth(), self._sidebar_last_width)
        sizes[2] = self.ai_sidebar.width() if self.ai_sidebar.isVisible() else 0
        sizes[1] = max(0, total - sizes[0] - sizes[2])
        self._splitter.setSizes(sizes)

    def _toggle_ai_sidebar(self):
        if self.ai_sidebar.isVisible():
            cur = self.ai_sidebar.width()
            if cur > 0:
                self._ai_sidebar_last_width = cur
            self.ai_sidebar.hide()
            sizes = self._splitter.sizes()
            while len(sizes) < 3:
                sizes.append(0)
            sizes[2] = 0
            sizes[1] = max(0, sum(sizes) - sizes[0])
            self._splitter.setSizes(sizes)
            return

        self.ai_sidebar.show()
        sizes = self._splitter.sizes()
        while len(sizes) < 3:
            sizes.append(0)
        total = sum(sizes) or self._splitter.width()
        sizes[2] = max(self.ai_sidebar.minimumWidth(), self._ai_sidebar_last_width)
        if self.sidebar.isVisible():
            sizes[0] = max(self.sidebar.minimumWidth(), self._sidebar_last_width)
        else:
            sizes[0] = 0
        sizes[1] = max(0, total - sizes[0] - sizes[2])
        self._splitter.setSizes(sizes)

    def _show_ai_sidebar(self):
        if not self.ai_sidebar.isVisible():
            self._toggle_ai_sidebar()

    def _set_ai_status(self, text: str) -> None:
        self.ai_sidebar_status.setText(text)

    def _setup_file_menu(self):
        # Кнопка «Файл» в верхней панели — раскрывающийся список с базовыми
        # действиями. Стилистика меню совпадает с выпадашкой showAllFilesBtn.
        self.ui.fileButton.clicked.connect(
            lambda: self._show_file_menu(self.ui.fileButton)
        )

    def _show_file_menu(self, anchor):
        menu = QMenu(anchor)
        menu.setStyleSheet(DARK_MENU_STYLE)

        a_new = menu.addAction("Новый файл\tCtrl+N")
        a_new.triggered.connect(self.tab_manager.create_new_tab)

        a_open = menu.addAction("Открыть файл…\tCtrl+O")
        a_open.triggered.connect(self._open_file_dialog)

        a_open_dir = menu.addAction("Открыть папку…")
        a_open_dir.triggered.connect(self._open_folder_dialog)

        menu.addSeparator()

        a_save = menu.addAction("Сохранить\tCtrl+S")
        a_save.triggered.connect(self._save_file)
        a_save_as = menu.addAction("Сохранить как…\tCtrl+Shift+S")
        a_save_as.triggered.connect(self._save_file_as)

        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))

    def _open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть файл", os.getcwd(), "Все файлы (*.*)"
        )
        if path:
            self.tab_manager.open_file(path)

    def _open_folder_dialog(self):
        path = QFileDialog.getExistingDirectory(
            self, "Открыть папку", os.getcwd()
        )
        if not path:
            return
        self.sidebar.set_root(path)
        # Если sidebar был скрыт — автоматически показываем его, иначе
        # пользователь не увидит результат и подумает, что ничего не произошло.
        if not self.sidebar.isVisible():
            self._toggle_sidebar()

    def _sync_bigo_ai_settings(self) -> None:
        self.bigo_controller.sync_ai_settings(
            use_ai=self.ai_use_checkbox.isChecked(),
            ai_model=self.ai_model_edit.text(),
            ai_timeout=self.ai_timeout_spin.value(),
        )

    def _setup_bigo_controller(self):
        self.bigo_controller = BigOController(
            self,
            editor=self.editor,
            tab_manager=self.tab_manager,
            get_project_root=lambda: self.sidebar.root_path,
            big_o_button=self.big_o_button,
            ai_sidebar_text=self.ai_sidebar_text,
            show_ai_sidebar=self._show_ai_sidebar,
            set_ai_status=self._set_ai_status,
            read_ai_settings=self._sync_bigo_ai_settings,
            use_ai=False,
            ai_model="qwen2.5-coder:7b",
            ai_timeout=60,
        )
        self.big_o_button.clicked.connect(self.bigo_controller.toggle_mode)
        self.tab_manager.active_tab_changed.connect(
            self.bigo_controller.on_active_tab_changed
        )

    def _setup_navigation(self):
        # Аналог VS Code «Go Back / Go Forward»: внутри Monaco это встроенные
        # команды cursorUndo / cursorRedo. Сами кнопки и их стили описаны
        # прямо в main.ui (goBackBtn / goForwardBtn внутри arrowFrame), здесь
        # только подключаем их к Python-обёртке навигации и хоткеям.
        self.navigation = EditorNavigation(self.editor, self)
        self.ui.goBackBtn.clicked.connect(self.navigation.go_back)
        self.ui.goForwardBtn.clicked.connect(self.navigation.go_forward)

        back_sc = QShortcut(QKeySequence("Alt+Left"), self)
        back_sc.setContext(Qt.ApplicationShortcut)
        back_sc.activated.connect(self.navigation.go_back)

        fwd_sc = QShortcut(QKeySequence("Alt+Right"), self)
        fwd_sc.setContext(Qt.ApplicationShortcut)
        fwd_sc.activated.connect(self.navigation.go_forward)

    def _setup_shortcuts(self):
        # ApplicationShortcut нужен, чтобы Ctrl+S/Ctrl+Shift+S срабатывали даже
        # когда фокус внутри QWebEngineView (Monaco). С обычным WindowShortcut
        # Chromium может перехватить клавиши до Qt.
        save_sc = QShortcut(QKeySequence.Save, self)
        save_sc.setContext(Qt.ApplicationShortcut)
        save_sc.activated.connect(self._save_file)

        save_as_sc = QShortcut(QKeySequence.SaveAs, self)
        save_as_sc.setContext(Qt.ApplicationShortcut)
        save_as_sc.activated.connect(self._save_file_as)

        new_tab_sc = QShortcut(QKeySequence.New, self)
        new_tab_sc.setContext(Qt.ApplicationShortcut)
        new_tab_sc.activated.connect(self.tab_manager.create_new_tab)

        open_file_sc = QShortcut(QKeySequence.Open, self)
        open_file_sc.setContext(Qt.ApplicationShortcut)
        open_file_sc.activated.connect(self._open_file_dialog)

    def _setup_bottom_bar_status(self):
        """Путь к файлу, строка/столбец курсора Monaco, язык подсветки."""
        self.ui.filePathLabel.setText("")
        self.ui.lineColumnLabel.setText(LINE_COL_PLACEHOLDER)
        self.ui.languageLabel.setText("")
        self.ui.filePathLabel.setToolTip("")

        self._cursor_poll_line = -1
        self._cursor_poll_col = -1
        # Сбрасывается при смене вкладки; отсекает устаревшие ответы runJavaScript.
        self._cursor_req_id = 0
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setInterval(50)
        self._cursor_timer.timeout.connect(self._poll_monaco_cursor)

        self.tab_manager.active_tab_changed.connect(self._refresh_bottom_bar_static)
        self.editor.language_changed.connect(self._refresh_language_label)
        self.editor.initialized.connect(self._on_monaco_initialized_status)

        # Догоняем, если мост Monaco поднялся до подключения слотов.
        if self.editor.bridge_initialized:
            self._on_monaco_initialized_status()
        else:
            self._refresh_bottom_bar_static()

    def _on_monaco_initialized_status(self) -> None:
        self._refresh_bottom_bar_static()
        self._update_cursor_timer_running()
        self._poll_monaco_cursor()

    def _refresh_bottom_bar_static(self) -> None:
        self._cursor_poll_line = -1
        self._cursor_poll_col = -1
        self._cursor_req_id += 1
        self._refresh_file_path_label()
        self._refresh_language_label()
        self._update_cursor_timer_running()
        if (
            not self.tab_manager.has_tabs
            or self.tab_manager.active_kind != "text"
        ):
            self.ui.lineColumnLabel.setText(LINE_COL_PLACEHOLDER)
        else:
            self._poll_monaco_cursor()

    def _refresh_file_path_label(self) -> None:
        path = self.tab_manager.file_path
        self.ui.filePathLabel.setText(path if path else "")
        self.ui.filePathLabel.setToolTip(path if path else "")

    def _refresh_language_label(self) -> None:
        if not self.tab_manager.has_tabs:
            self.ui.languageLabel.setText("")
            return
        if self.tab_manager.active_kind == "image":
            self.ui.languageLabel.setText("Изображение")
            return
        # Режим подсветки в Monaco — совпадает с тем, что реально рендерит редактор.
        lid = self.editor.get_language()
        self.ui.languageLabel.setText(language_label_for_monaco_id(lid))

    def _update_cursor_timer_running(self) -> None:
        run = (
            self.editor.bridge_initialized
            and self.tab_manager.has_tabs
            and self.tab_manager.active_kind == "text"
            and self.view_stack.currentWidget() is self.editor
        )
        if run:
            if not self._cursor_timer.isActive():
                self._cursor_timer.start(50)
        else:
            self._cursor_timer.stop()

    def _poll_monaco_cursor(self) -> None:
        if not self.tab_manager.has_tabs:
            self.ui.lineColumnLabel.setText(LINE_COL_PLACEHOLDER)
            return
        if self.tab_manager.active_kind != "text":
            self.ui.lineColumnLabel.setText(LINE_COL_PLACEHOLDER)
            return
        if self.view_stack.currentWidget() is not self.editor:
            self.ui.lineColumnLabel.setText(LINE_COL_PLACEHOLDER)
            return
        if not self.editor.bridge_initialized:
            return

        # qtmonaco держит `current_cursor` на дефолте — реальную позицию берём из Monaco API.
        self._cursor_req_id += 1
        req = self._cursor_req_id
        self.editor.request_cursor_position(
            lambda res, rid=req: self._apply_monaco_cursor_js(rid, res)
        )

    def _apply_monaco_cursor_js(self, req_id: int, result) -> None:
        if req_id != self._cursor_req_id:
            return
        if not self.tab_manager.has_tabs:
            return
        if self.tab_manager.active_kind != "text":
            return
        if self.view_stack.currentWidget() is not self.editor:
            return

        pos = self.editor.parse_cursor_js_result(result)
        if pos is None:
            return
        line, col = pos
        if line == self._cursor_poll_line and col == self._cursor_poll_col:
            return
        self._cursor_poll_line = line
        self._cursor_poll_col = col
        self.ui.lineColumnLabel.setText(f"Лин. {line}, Столб. {col}")

    def _save_file(self):
        # Image-вкладка — это просмотр, а не редактор: сохранять текст из
        # скрытого Monaco в .png / .ico было бы катастрофой.
        if self.tab_manager.active_kind == "image":
            return
        if self.tab_manager.file_path is None:
            self._save_file_as()
            return
        self._write_to(self.tab_manager.file_path)

    def _save_file_as(self):
        if self.tab_manager.active_kind == "image":
            return
        suggested = self.tab_manager.file_path or os.path.join(
            os.getcwd(), "untitled.txt"
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить файл как",
            suggested,
            "Все файлы (*.*)",
        )
        if not path:
            return
        self._write_to(path)

    def _write_to(self, path: str):
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(self.editor.get_text())
        except OSError as exc:
            QMessageBox.critical(
                self, "Ошибка сохранения", f"Не удалось сохранить файл:\n{exc}"
            )
            return

        self.tab_manager.attach_file_path(path)
        language = language_from_path(path)
        if language is not None:
            self.editor.set_language(language)
            self.tab_manager.update_active_language(language)

    def resizeEvent(self, event):
        UIFunctions.resize_grips(self)

    def mousePressEvent(self, event):
        self.drag_pos = QCursor.pos()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            UIFunctions.apply_window_corners(self)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(LOGO_RESOURCE_PATH))
    window = MainWindow()
    window.setWindowIcon(QIcon(LOGO_RESOURCE_PATH))
    window.show()
    sys.exit(app.exec())
