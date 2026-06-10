"""QWebChannel-мост между Monaco (JS) и BigOController (Python).

Регистрируется как объект `bigoBridge` на канале qtmonaco. Из JS вызывается
`window.bigoBridge.reviewBlock(blockId)` при клике по кнопке рецензии блока;
сигнал `block_review_requested` ретранслируется наружу (CustomMonaco).
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot


class BigOBridge(QObject):
    """Минимальный мост; держим узкий API ради безопасности расширения."""

    block_review_requested = Signal(str)

    @Slot(str)
    def reviewBlock(self, block_id: str) -> None:
        if not isinstance(block_id, str):
            return
        block_id = block_id.strip()
        if not block_id:
            return
        self.block_review_requested.emit(block_id)
