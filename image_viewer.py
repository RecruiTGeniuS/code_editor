"""
Просмотрщик изображений для отдельной вкладки редактора.

Состав:
  ImageViewer (QWidget, QVBoxLayout)
    ├── QGraphicsView (scene с одним QGraphicsPixmapItem)
    └── QLabel-статусбар (имя файла · размеры · вес · масштаб)

Почему `QGraphicsView`, а не `QScrollArea` + `QLabel`:
  • из коробки даёт «панорамирование за рукой» (`ScrollHandDrag`);
  • встроенный зум через `view.scale()` с привязкой к курсору
    (`AnchorUnderMouse`) — изображение зумится туда, куда указано мышкой;
  • сглаженная трансформация через `SmoothPixmapTransform`.

Поддерживаемые форматы — те же, что у `QImageReader` (png/jpg/gif/bmp/webp/svg
при наличии плагина SVG, ico). У `.ico` несколько фреймов разного размера —
автоматически выбираем самый крупный, иначе можно случайно показать иконку 16×16.

Управление:
  • Ctrl + колесо — зум к курсору.
  • Двойной клик — fit-to-window (повторный — 1:1).
  • Перетаскивание — пан (drag mode = ScrollHandDrag, активен по умолчанию).
"""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QFileInfo, QRectF, Qt, QTimer
from PySide6.QtGui import QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import (
    QGraphicsScene,
    QGraphicsView,
    QLabel,
    QVBoxLayout,
    QWidget,
)


# Множество расширений, которые мы трактуем как «открыть в просмотрщике, а
# не в Monaco». Импортируется тaб-менеджером для маршрутизации `open_file`.
IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico", ".tiff"}
)


def is_image_path(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS


class ImageViewer(QWidget):
    """Виджет-вкладка с зумом, панорамированием и статусной строкой."""

    _STYLE = """
    #imageViewer { background-color: rgb(49, 51, 56); }
    QGraphicsView#imageView {
        background-color: rgb(40, 42, 47);
        border: none;
    }
    #imageStatus {
        color: rgb(180, 180, 180);
        background-color: rgb(38, 40, 44);
        padding: 4px 10px;
        font-size: 11px;
        border-top: 1px solid rgb(63, 65, 68);
    }
    /* Узкий полупрозрачный скроллбар — в стиле остальных панелей. */
    QGraphicsView#imageView QScrollBar:vertical,
    QGraphicsView#imageView QScrollBar:horizontal {
        background: transparent;
        border: none;
    }
    QGraphicsView#imageView QScrollBar:vertical { width: 8px; }
    QGraphicsView#imageView QScrollBar:horizontal { height: 8px; }
    QGraphicsView#imageView QScrollBar::handle {
        background: rgba(255, 255, 255, 35);
        border-radius: 3px;
        min-height: 30px;
        min-width: 30px;
    }
    QGraphicsView#imageView QScrollBar::handle:hover {
        background: rgba(255, 255, 255, 60);
    }
    QGraphicsView#imageView QScrollBar::add-line,
    QGraphicsView#imageView QScrollBar::sub-line {
        width: 0; height: 0; background: transparent; border: none;
    }
    """

    # Зум ограничен сверху и снизу: ниже — теряется смысл «открытого файла»,
    # выше — пиксели уже размером с пол-экрана.
    _MIN_ZOOM = 0.05
    _MAX_ZOOM = 16.0
    _ZOOM_STEP = 1.15

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("imageViewer")
        self.setStyleSheet(self._STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._scene = QGraphicsScene(self)
        self._view = QGraphicsView(self._scene, self)
        self._view.setObjectName("imageView")
        self._view.setRenderHints(
            QPainter.SmoothPixmapTransform | QPainter.Antialiasing
        )
        # Привязываем масштаб к точке под курсором — приятный зум как в Photos.
        self._view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self._view.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        # ScrollHandDrag — клик-и-тащи для перемещения, без удержания пробела.
        self._view.setDragMode(QGraphicsView.ScrollHandDrag)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        layout.addWidget(self._view, 1)

        self._status = QLabel("", self)
        self._status.setObjectName("imageStatus")
        self._status.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        layout.addWidget(self._status)

        self._item = None
        self._current_path: str | None = None

        # Перехватываем колесо и двойной клик через viewport — чтобы стандартное
        # поведение QGraphicsView (вертикальный скролл колесом) уходило только
        # туда, где не зажат Ctrl.
        self._view.viewport().installEventFilter(self)

    # ───────────────────────── Публичный API ─────────────────────────

    def load(self, path: str) -> bool:
        """Загрузить изображение по пути. Возвращает True при успехе."""
        pixmap = self._load_pixmap(path)
        if pixmap is None or pixmap.isNull():
            self._show_error(path)
            return False

        self._scene.clear()
        self._item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self._view.resetTransform()
        self._current_path = path

        # Большие картинки — сразу подгоняем под viewport, как делают
        # стандартные вьюверы. Маленькие показываем 1:1, иначе странно
        # «увеличивать» 16×16 ico на пол-экрана автоматически.
        QTimer.singleShot(0, self._fit_if_too_large)
        self._update_status(pixmap, path)
        return True

    def clear(self) -> None:
        self._scene.clear()
        self._item = None
        self._current_path = None
        self._status.clear()

    @property
    def current_path(self) -> str | None:
        return self._current_path

    # ───────────────────────── Внутреннее ─────────────────────────

    def _show_error(self, path: str) -> None:
        self._scene.clear()
        self._item = None
        err = QLabel(f"Не удалось открыть «{os.path.basename(path)}»")
        err.setStyleSheet("color: rgb(220, 80, 80); font-size: 12px;")
        proxy = self._scene.addWidget(err)
        proxy.setPos(20, 20)
        self._status.setText(os.path.basename(path) + "  ·  ошибка чтения")

    def _fit_if_too_large(self) -> None:
        if self._item is None:
            return
        viewport = self._view.viewport().rect()
        bounds = self._item.boundingRect()
        if bounds.isEmpty():
            return
        # Подгоняем только если картинка не помещается в видимую область,
        # иначе мелкие иконки превратились бы в мыло на весь экран.
        if bounds.width() > viewport.width() or bounds.height() > viewport.height():
            self._view.fitInView(bounds, Qt.KeepAspectRatio)
        self._update_zoom_in_status()

    def _zoom(self, factor: float) -> None:
        current = self._view.transform().m11()
        new = current * factor
        if new < self._MIN_ZOOM or new > self._MAX_ZOOM:
            return
        self._view.scale(factor, factor)
        self._update_zoom_in_status()

    def _reset_zoom(self) -> None:
        self._view.resetTransform()
        self._update_zoom_in_status()

    def _update_status(self, pixmap: QPixmap, path: str) -> None:
        size = QFileInfo(path).size()
        zoom_pct = int(round(self._view.transform().m11() * 100))
        self._status.setText(
            f"{os.path.basename(path)}  ·  "
            f"{pixmap.width()}×{pixmap.height()}  ·  "
            f"{self._format_bytes(size)}  ·  {zoom_pct}%"
        )

    def _update_zoom_in_status(self) -> None:
        # Перерисовать только зум-часть; пересчитываем строку целиком, потому
        # что собрать её из частей дешевле, чем парсить уже выставленный текст.
        if self._item is None or not self._current_path:
            return
        pixmap = self._item.pixmap()
        self._update_status(pixmap, self._current_path)

    # ─────────── Загрузка с особыми случаями ───────────

    @staticmethod
    def _load_pixmap(path: str) -> QPixmap | None:
        # `.ico` хранит несколько фреймов разного размера. По умолчанию
        # `QImageReader` отдаст первый — обычно 16×16. Берём самый крупный
        # по площади, чтобы пользователю было что разглядывать.
        if path.lower().endswith(".ico"):
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            count = reader.imageCount()
            if count > 1:
                best_img = None
                for i in range(count):
                    reader.jumpToImage(i)
                    img = reader.read()
                    if img.isNull():
                        continue
                    if (
                        best_img is None
                        or img.width() * img.height()
                        > best_img.width() * best_img.height()
                    ):
                        best_img = img
                if best_img is not None:
                    return QPixmap.fromImage(best_img)

        # Обычный путь: один кадр. SVG читается, если в Qt подгружен плагин
        # imageformats/qsvg (по умолчанию идёт с PySide6).
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        img = reader.read()
        if img.isNull():
            # Фолбэк: даём шанс самому QPixmap (анимированные GIF, например).
            pix = QPixmap(path)
            return pix if not pix.isNull() else None
        return QPixmap.fromImage(img)

    @staticmethod
    def _format_bytes(n: int) -> str:
        units = ("B", "KB", "MB", "GB", "TB")
        size = float(n)
        for unit in units:
            if size < 1024 or unit == units[-1]:
                # Целые байты без дроби — мелочь, но читается лучше.
                if unit == "B":
                    return f"{int(size)} B"
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{n} B"

    # ─────────── События ───────────

    def eventFilter(self, obj, event):
        if obj is self._view.viewport():
            if event.type() == QEvent.Wheel:
                # Зум — только с зажатым Ctrl, иначе колесо просто скроллит
                # картинку (стандартное поведение QGraphicsView).
                if event.modifiers() & Qt.ControlModifier:
                    delta = event.angleDelta().y()
                    if delta != 0:
                        factor = self._ZOOM_STEP if delta > 0 else 1.0 / self._ZOOM_STEP
                        self._zoom(factor)
                    return True
            elif event.type() == QEvent.MouseButtonDblClick:
                # Двойной клик: переключаем между fit-to-window и 1:1, ровно
                # как в нативных вьюверах.
                if self._item is not None:
                    current_scale = self._view.transform().m11()
                    bounds = self._item.boundingRect()
                    viewport = self._view.viewport().rect()
                    fit = (
                        bounds.width() > viewport.width()
                        or bounds.height() > viewport.height()
                    )
                    # Если сейчас «не 1:1» — сбрасываем, иначе fit (если нужно).
                    if abs(current_scale - 1.0) > 0.01:
                        self._reset_zoom()
                    elif fit:
                        self._view.fitInView(bounds, Qt.KeepAspectRatio)
                        self._update_zoom_in_status()
                return True
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # При первой загрузке картинки `_fit_if_too_large` запускался в
        # singleShot, до того как вьюпорт получил финальный размер. На случай
        # последующих ресайзов окна зум не пересчитываем — это раздражает,
        # если пользователь уже зумил вручную.
