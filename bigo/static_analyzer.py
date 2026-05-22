from __future__ import annotations

import re

from .models import CodeBlock


def analyze_block_static(block: CodeBlock) -> tuple[str | None, str]:
    """Вернуть (complexity, reason) или (None, reason) если нужен LLM fallback."""
    f = block.features
    code = block.source
    name_l = (block.name or "").lower()

    if f.self_call_count >= 1 and ("factorial" in name_l or "permut" in name_l):
        return "O(n!)", "Рекурсия с шаблоном factorial/permutation."

    if f.self_call_count >= 2:
        return "O(2^n)", "Две и более рекурсивных ветки self-call."

    if f.max_loop_depth >= 3:
        return "O(n^3)", f"Вложенность циклов: {f.max_loop_depth}."

    if f.max_loop_depth == 2:
        return "O(n^2)", "Два вложенных цикла."

    if f.max_loop_depth == 1:
        if f.has_sort_call or f.has_log_pattern:
            return "O(n log n)", "Один цикл + log/sort паттерн."
        return "O(n)", "Один линейный цикл."

    if f.self_call_count == 1:
        if f.has_log_pattern:
            return "O(log n)", "Одиночная рекурсия с уменьшением задачи."
        return "O(n)", "Одиночная линейная рекурсия."

    if f.has_sort_call:
        return "O(n log n)", "Обнаружен вызов sort/sorted/qsort."

    if f.has_log_pattern:
        return "O(log n)", "Обнаружен логарифмический паттерн (деление диапазона)."

    # Частый неочевидный кейс: несколько helper-вызовов без циклов.
    # Оставляем fallback для LLM, если есть вызовы, но нет явных паттернов.
    if len(block.calls) >= 3:
        return None, "Много вызовов без явных циклов; требуется контекст."

    return "O(1)", "Нет циклов, рекурсии и log/sort паттернов."

