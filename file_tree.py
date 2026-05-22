"""
Левая панель проводника (Sidebar) с деревом файлов и папок.

Состав:
  Sidebar (QFrame)
   ├── Заголовок "ПАПКИ" (жирный, как в Sublime Text)
   ├── FileTreeView      ← когда открыта папка
   └── empty-state QLabel ← когда папка не выбрана

`FileTreeView` — QTreeView поверх `QFileSystemModel`. Это даёт нам:
  • реальный взгляд на ФС с автоматическим обновлением (под капотом QFileSystemWatcher);
  • встроенное переименование — `model.setData()` физически переименует файл;
  • быструю работу на больших папках за счёт ленивой подгрузки.

Иконки берём из ресурсов через `FileIconProvider`. Стрелки раскрытия /
сворачивания папок задаём через QSS — `tree_arrow_right.png` /
`tree_arrow_down.png`. Для папок в любом состоянии используем единый
`folder.png` — ровно как в VS Code; визуальную смену состояния даёт
ветка (chevron) слева. Если позже захочется «папка-открыта» как отдельная
иконка, это можно подменить через делегат, реагируя на signals expanded/collapsed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from PySide6.QtCore import QDir, QFileInfo, QModelIndex, QPoint, Qt, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileIconProvider,
    QFileSystemModel,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QTreeView,
    QVBoxLayout,
    QWidget,
)


# Расширения для подбора иконки в дереве. Списки нарочно небольшие — берём
# самые ходовые, остальное падает в дефолт `tree_code.png`. Важно, чтобы
# группы не пересекались: расширение «.svg» — image, а не code.
_CODE_EXT = {
    ".py", ".pyw", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx",
    ".cpp", ".cc", ".cxx", ".hpp", ".hxx", ".c", ".h", ".cs",
    ".rs", ".go", ".java", ".kt", ".kts", ".rb", ".php", ".swift",
    ".lua", ".r", ".dart", ".vue", ".html", ".htm", ".css", ".scss",
    ".less", ".md", ".markdown", ".txt", ".log",
}
_TERMINAL_EXT = {".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd"}
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".tiff"}
_ICO_EXT = {".ico"}
_DATA_EXT = {".json", ".xml", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".csv"}
_DB_EXT = {".db", ".sqlite", ".sqlite3", ".sql"}


# Стиль выпадающего меню — выделен в константу, чтобы и контекстное меню
# дерева, и меню кнопки «Файл» использовали один источник правды.
DARK_MENU_STYLE = """
QMenu {
    background-color: rgb(43, 45, 49);
    color: rgb(220, 220, 220);
    border: 1px solid rgb(63, 65, 68);
    padding: 4px 0px;
}
QMenu::item {
    padding: 6px 22px 6px 18px;
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


class FileIconProvider(QFileIconProvider):
    """Подменяем стандартные системные иконки на наш набор из ресурсов."""

    def __init__(self):
        super().__init__()
        # Загружаем заранее, чтобы не пересоздавать QIcon на каждый вызов.
        self._folder = QIcon(":/Icons/icons/folder.png")
        self._folder_open = QIcon(":/Icons/icons/folder_open.png")
        self._code = QIcon(":/Icons/icons/tree_code.png")
        self._terminal = QIcon(":/Icons/icons/tree_terminal.png")
        self._image = QIcon(":/Icons/icons/tree_image.png")
        self._ico = QIcon(":/Icons/icons/tree_ico.png")
        self._data = QIcon(":/Icons/icons/tree_data_object.png")
        self._db = QIcon(":/Icons/icons/tree_db.png")

    # `QFileIconProvider.icon` имеет два перегруза: по `IconType` (Folder, File…)
    # и по `QFileInfo`. В Python оба попадают в один метод — диспатчим по типу.
    def icon(self, type_or_info):  # type: ignore[override]
        if isinstance(type_or_info, QFileInfo):
            info = type_or_info
            if info.isDir():
                return self._folder
            ext = "." + info.suffix().lower() if info.suffix() else ""
            if ext in _CODE_EXT:
                return self._code
            if ext in _TERMINAL_EXT:
                return self._terminal
            if ext in _IMAGE_EXT:
                return self._image
            if ext in _ICO_EXT:
                return self._ico
            if ext in _DATA_EXT:
                return self._data
            if ext in _DB_EXT:
                return self._db
            return self._code  # дефолт — у нас нет «обобщённой» файловой иконки
        # Перегруз по IconType (Folder/File/Computer/...) — отдаём системные
        # дефолты, чтобы что-то да вернулось, если Qt спросит.
        if type_or_info == QFileIconProvider.Folder:
            return self._folder
        if type_or_info == QFileIconProvider.File:
            return self._code
        return super().icon(type_or_info)

    @property
    def folder_open_icon(self) -> QIcon:
        """Иконка раскрытой папки — отдаётся отдельно через модель."""
        return self._folder_open


class _FileSystemModel(QFileSystemModel):
    """`QFileSystemModel`, умеющий показывать «открытую» папку для развёрнутых узлов.

    Сама модель ничего не знает о состоянии раскрытия — оно живёт во вью.
    Поэтому держим слабую ссылку на `QTreeView`: в `data()` для папок
    спрашиваем `view.isExpanded(index)` и подменяем иконку. Перерисовку
    инициирует сам вью, эмитя `dataChanged` через `notify_expansion_changed`
    из обработчиков сигналов `expanded` / `collapsed`.
    """

    def __init__(self, view: QTreeView, icon_provider: FileIconProvider, parent=None):
        super().__init__(parent)
        self._view = view
        self._provider = icon_provider
        self.setIconProvider(icon_provider)

    def data(self, index, role=Qt.DisplayRole):  # type: ignore[override]
        if role == Qt.DecorationRole and index.isValid() and self.isDir(index):
            if self._view.isExpanded(index):
                return self._provider.folder_open_icon
        return super().data(index, role)

    def notify_expansion_changed(self, index) -> None:
        """Сообщить вью, что иконка для `index` изменилась."""
        if index.isValid():
            self.dataChanged.emit(index, index, [Qt.DecorationRole])


class FileTreeView(QTreeView):
    """Дерево файлов с контекстным меню и сигналом активации файла."""

    file_activated = Signal(str)  # путь файла, открытого двойным кликом

    _STYLE = """
    QTreeView#fileTree {
        background-color: rgb(32, 33, 38);
        color: rgb(220, 220, 220);
        border: none;
        outline: 0;
        font-size: 12px;
        show-decoration-selected: 1;
    }
    QTreeView#fileTree::item {
        height: 22px;
        padding: 0px 4px;
        border: 0px;
    }
    QTreeView#fileTree::item:hover:!selected {
        background-color: rgba(255, 255, 255, 12);
    }
    QTreeView#fileTree::item:selected {
        background-color: rgba(255, 255, 255, 28);
        color: rgb(240, 240, 240);
    }
    /* Сворачивание/раскрытие папки — наши стрелки из ресурсов. */
    QTreeView#fileTree::branch:has-children:!has-siblings:closed,
    QTreeView#fileTree::branch:closed:has-children:has-siblings {
        border-image: none;
        image: url(:/Icons/icons/tree_arrow_right.png);
    }
    QTreeView#fileTree::branch:open:has-children:!has-siblings,
    QTreeView#fileTree::branch:open:has-children:has-siblings {
        border-image: none;
        image: url(:/Icons/icons/tree_arrow_down.png);
    }
    /* Узкий ненавязчивый скроллбар в духе боковой панели. */
    QTreeView#fileTree QScrollBar:vertical {
        background: transparent;
        border: none;
        width: 8px;
        margin: 0px;
    }
    QTreeView#fileTree QScrollBar::handle:vertical {
        background: rgba(255, 255, 255, 35);
        min-height: 30px;
        border-radius: 3px;
    }
    QTreeView#fileTree QScrollBar::handle:vertical:hover {
        background: rgba(255, 255, 255, 60);
    }
    QTreeView#fileTree QScrollBar::add-line:vertical,
    QTreeView#fileTree QScrollBar::sub-line:vertical {
        height: 0px;
        background: transparent;
        border: none;
    }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("fileTree")
        self.setHeaderHidden(True)
        self.setIndentation(14)
        self.setAnimated(False)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setStyleSheet(self._STYLE)

        # Иконка-провайдер живёт отдельно, чтобы модель могла спрашивать у
        # него «открытую» иконку папки при раскрытии узла.
        self._icons = FileIconProvider()
        self._model = _FileSystemModel(self, self._icons, self)
        # Скрытые файлы не показываем (можно поменять при желании).
        self._model.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot | QDir.AllDirs)
        self.setModel(self._model)
        # Папка переключает иконку «закрыта/открыта» по сигналам вью —
        # модель сама не знает, какие узлы развёрнуты.
        self.expanded.connect(self._model.notify_expansion_changed)
        self.collapsed.connect(self._model.notify_expansion_changed)
        # У QFileSystemModel 4 столбца (имя, размер, тип, дата) — оставляем
        # только имя; всё остальное в боковой панели только мешает.
        for col in range(1, 4):
            self.hideColumn(col)

        self.doubleClicked.connect(self._on_double_clicked)

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

        # F2 — стандартная клавиша переименования в проводниках всех ОС.
        rename_sc = QShortcut(QKeySequence("F2"), self)
        rename_sc.activated.connect(self._rename_selected)
        del_sc = QShortcut(QKeySequence("Delete"), self)
        del_sc.activated.connect(self._delete_selected)

    @property
    def fs_model(self) -> QFileSystemModel:
        return self._model

    def set_root(self, path: str) -> None:
        """Выставить корнем дерева указанный путь и развернуть первый уровень."""
        idx = self._model.setRootPath(path)
        self.setRootIndex(idx)
        # Удобство: первый уровень виден сразу, как в Sublime/VS Code.
        self.expand(idx)

    # ───────────────── Обработчики ввода ─────────────────

    def _on_double_clicked(self, idx: QModelIndex) -> None:
        # Папки — открываем/закрываем (стандартное поведение QTreeView через
        # клик по chevron'у тоже сохраняем); по файлу — сигналим во вне.
        if self._model.isDir(idx):
            self.setExpanded(idx, not self.isExpanded(idx))
            return
        self.file_activated.emit(self._model.filePath(idx))

    def _on_context_menu(self, pos: QPoint) -> None:
        idx = self.indexAt(pos)
        is_valid = idx.isValid()
        is_dir = is_valid and self._model.isDir(idx)
        # Папка-якорь для «новый файл/папка»: либо выбранная папка, либо
        # родитель выбранного файла, либо сам корень, если ничего не выбрано.
        if is_valid:
            anchor_dir = (
                self._model.filePath(idx)
                if is_dir
                else os.path.dirname(self._model.filePath(idx))
            )
        else:
            anchor_dir = self._model.filePath(self.rootIndex())

        menu = QMenu(self)
        menu.setStyleSheet(DARK_MENU_STYLE)

        if is_valid and not is_dir:
            a_open = menu.addAction("Открыть")
            a_open.triggered.connect(
                lambda: self.file_activated.emit(self._model.filePath(idx))
            )
            menu.addSeparator()

        a_new_file = menu.addAction("Новый файл")
        a_new_file.triggered.connect(lambda: self._create_new_file(anchor_dir))
        a_new_dir = menu.addAction("Новая папка")
        a_new_dir.triggered.connect(lambda: self._create_new_folder(anchor_dir))

        if is_valid:
            menu.addSeparator()
            a_rename = menu.addAction("Переименовать\tF2")
            a_rename.triggered.connect(lambda: self._rename(idx))
            a_delete = menu.addAction("Удалить\tDel")
            a_delete.triggered.connect(lambda: self._delete(idx))
            menu.addSeparator()
            a_reveal = menu.addAction("Показать в проводнике")
            a_reveal.triggered.connect(
                lambda: self._reveal_in_explorer(self._model.filePath(idx))
            )

        if menu.actions():
            menu.exec(self.viewport().mapToGlobal(pos))

    # ───────────────── Файловые операции ─────────────────

    def _create_new_file(self, anchor_dir: str) -> None:
        name, ok = QInputDialog.getText(self, "Новый файл", "Имя файла:")
        if not ok or not name.strip():
            return
        path = os.path.join(anchor_dir, name.strip())
        if os.path.exists(path):
            QMessageBox.warning(self, "Создание файла", "Файл с таким именем уже существует.")
            return
        try:
            with open(path, "x", encoding="utf-8"):
                pass
        except OSError as exc:
            QMessageBox.critical(self, "Создание файла", f"Не удалось создать:\n{exc}")
            return
        self._select_path_when_visible(path)

    def _create_new_folder(self, anchor_dir: str) -> None:
        name, ok = QInputDialog.getText(self, "Новая папка", "Имя папки:")
        if not ok or not name.strip():
            return
        path = os.path.join(anchor_dir, name.strip())
        try:
            os.makedirs(path, exist_ok=False)
        except OSError as exc:
            QMessageBox.critical(self, "Создание папки", f"Не удалось создать:\n{exc}")
            return
        self._select_path_when_visible(path)

    def _rename_selected(self) -> None:
        idx = self.currentIndex()
        if idx.isValid():
            self._rename(idx)

    def _rename(self, idx: QModelIndex) -> None:
        # У нас editTriggers = NoEditTriggers, поэтому штатное редактирование
        # не запустится — заводим его руками. Модель сама выполнит rename.
        self.edit(idx)

    def _delete_selected(self) -> None:
        idx = self.currentIndex()
        if idx.isValid():
            self._delete(idx)

    def _delete(self, idx: QModelIndex) -> None:
        path = self._model.filePath(idx)
        is_dir = self._model.isDir(idx)
        kind = "папку" if is_dir else "файл"
        reply = QMessageBox.question(
            self,
            "Удаление",
            f"Удалить {kind} «{os.path.basename(path)}»?\nДействие необратимо.",
        )
        if reply != QMessageBox.Yes:
            return
        try:
            if is_dir:
                shutil.rmtree(path)
            else:
                os.remove(path)
        except OSError as exc:
            QMessageBox.critical(self, "Удаление", f"Не удалось удалить:\n{exc}")

    @staticmethod
    def _reveal_in_explorer(path: str) -> None:
        if not os.path.exists(path):
            return
        if sys.platform == "win32":
            # /select подсвечивает указанный файл в его папке. Quote-обёртка
            # не нужна, т.к. передаём список аргументов.
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path) or "."])

    def _select_path_when_visible(self, path: str) -> None:
        # QFileSystemModel асинхронно подгружает содержимое — иногда
        # сразу после создания файла индекс ещё пустой. На «потом»
        # подписываемся на directoryLoaded.
        target_dir = os.path.dirname(path)

        def select(loaded_dir: str) -> None:
            if os.path.normcase(os.path.abspath(loaded_dir)) != os.path.normcase(
                os.path.abspath(target_dir)
            ):
                return
            idx = self._model.index(path)
            if idx.isValid():
                self.setCurrentIndex(idx)
                self.scrollTo(idx)
            try:
                self._model.directoryLoaded.disconnect(select)
            except (TypeError, RuntimeError):
                pass

        # Если папка уже загружена — индекс будет валиден сразу.
        idx = self._model.index(path)
        if idx.isValid():
            self.setCurrentIndex(idx)
            self.scrollTo(idx)
        else:
            self._model.directoryLoaded.connect(select)


class Sidebar(QFrame):
    """Боковая панель с заголовком «ПАПКИ» и деревом файлов."""

    _STYLE = """
    #sidebar {
        background-color: rgb(32, 33, 38);
    }
    #sidebarHeader {
        color: rgb(220, 220, 220);
        background-color: transparent;
        font-size: 11px;
        font-weight: bold;
        letter-spacing: 1px;
        padding: 8px 12px 6px 12px;
    }
    #sidebarEmpty {
        color: rgb(140, 140, 140);
        background: transparent;
        padding: 8px 14px;
        font-size: 11px;
    }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setStyleSheet(self._STYLE)
        # Минимум, чтобы оставалось место под заголовок и хотя бы пару строк
        # дерева; ниже — вкладка визуально схлопывается и теряет смысл.
        self.setMinimumWidth(150)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = QLabel("ПАПКИ", self)
        self._header.setObjectName("sidebarHeader")
        layout.addWidget(self._header)

        # Физический отступ дерева от левого края панели (надёжнее, чем один
        # лишь QSS-padding — ветки и стрелки всегда съезжают вместе с viewport).
        tree_wrap = QWidget(self)
        tree_wrap.setStyleSheet("background-color: rgb(32, 33, 38);")
        wrap_l = QHBoxLayout(tree_wrap)
        wrap_l.setContentsMargins(5, 0, 0, 0)
        wrap_l.setSpacing(0)
        self._tree = FileTreeView(tree_wrap)
        wrap_l.addWidget(self._tree)
        layout.addWidget(tree_wrap, 1)

        self._empty = QLabel(
            "Папка не открыта.\nИспользуйте «Файл → Открыть папку…», "
            "чтобы выбрать рабочую директорию.",
            self,
        )
        self._empty.setObjectName("sidebarEmpty")
        self._empty.setWordWrap(True)
        self._empty.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        layout.addWidget(self._empty, 1)

        self.set_root(None)

    @property
    def tree(self) -> FileTreeView:
        return self._tree

    @property
    def root_path(self) -> str | None:
        return self._root_path if hasattr(self, "_root_path") else None

    def set_root(self, path: str | None) -> None:
        self._root_path = path
        if path:
            self._tree.set_root(path)
            self._tree.show()
            self._empty.hide()
        else:
            self._tree.hide()
            self._empty.show()
