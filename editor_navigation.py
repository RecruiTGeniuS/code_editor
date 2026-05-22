"""
Мост PySide ↔ Monaco для навигации «назад/вперёд» по позициям курсора.

Идея: VS Code «Go Back / Go Forward» — это перемещение по истории позиций
курсора. В Monaco Editor для этого есть две встроенные команды:

    cursorUndo  — вернуться к предыдущей позиции курсора
    cursorRedo  — повторить отменённое перемещение

Их и использует VS Code для базовой навигации внутри одного файла. Снаружи
доступны через ``editor.trigger(source, commandId, payload)``. Никакой свой
стек позиций строить не нужно — Monaco хранит его сам и корректно сбрасывает
forward-стек при новой пользовательской навигации.

Этот модуль инкапсулирует все JS-вызовы в одном месте, чтобы из остального
кода (например, из обработчиков кнопок) можно было дёргать Python-методы
``go_back()`` / ``go_forward()``, не зная про ``runJavaScript``.
"""

from __future__ import annotations

from PySide6.QtCore import QObject


class EditorNavigation(QObject):
    """Управляет историей позиций курсора в Monaco через JS-bridge."""

    # `source` для editor.trigger — Monaco требует строку, иначе пишет warning
    # в консоль; конкретное значение неважно, главное чтобы было непустым.
    _SOURCE = "qt-bridge"

    def __init__(self, editor, parent: QObject | None = None):
        super().__init__(parent)
        self._editor = editor

    def go_back(self) -> None:
        """Откатить курсор на предыдущую позицию (аналог `Alt+←` в VS Code)."""
        self._trigger("cursorUndo")

    def go_forward(self) -> None:
        """Вернуть курсор на отменённую позицию (аналог `Alt+→` в VS Code)."""
        self._trigger("cursorRedo")

    def _trigger(self, command_id: str) -> None:
        # editor.trigger напрямую не виден в глобальной области JS, поэтому
        # берём первый редактор через monaco.editor.getEditors(). У нас он один,
        # а если когда-нибудь будет несколько — поправим тут централизованно.
        # focus() после команды вернёт фокус в редактор, иначе он остаётся
        # на кнопке и пользователь не видит мерцающий каретный курсор.
        js = (
            "(function(){"
            "  var eds = monaco.editor.getEditors();"
            "  if (!eds.length) return;"
            "  var ed = eds[0];"
            f"  ed.trigger('{self._SOURCE}', '{command_id}', null);"
            "  ed.focus();"
            "})();"
        )
        self._editor.page().runJavaScript(js)
