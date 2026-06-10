"""Типовые rule-based паттерны сложности (без AI)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import BlockFeatures, CodeBlock, complexity_rank, max_complexity


@dataclass(slots=True)
class PatternHit:
    pattern_id: str
    complexity: str
    reasoning: str
    confidence: str
    assumptions: list[str] = field(default_factory=list)
    uncertainty_flags: list[str] = field(default_factory=list)


_BOUND_NAMES = r"(?:left|right|low|high|l|r|start|end)"


def _pick_best(hits: list[PatternHit]) -> PatternHit | None:
    if not hits:
        return None
    best = hits[0]
    for h in hits[1:]:
        if complexity_rank(h.complexity) > complexity_rank(best.complexity):
            best = h
    return best


def detect_binary_search(code: str) -> PatternHit | None:
    if not re.search(r"\bwhile\b", code):
        return None
    if not re.search(rf"\b{_BOUND_NAMES}\b", code, re.IGNORECASE):
        return None
    if not re.search(r"\bmid\b", code, re.IGNORECASE):
        return None
    if not re.search(
        rf"(left|right|low|high|l|r)\s*=\s*mid|mid\s*[=+\-]",
        code,
        re.IGNORECASE,
    ):
        return None
    return PatternHit(
        pattern_id="binary_search",
        complexity="O(log n)",
        reasoning="Обнаружен шаблон бинарного поиска (while, границы, mid, сужение диапазона).",
        confidence="high",
        assumptions=["Диапазон поиска делится пополам на каждой итерации."],
    )


def detect_linear_while_pointer(code: str) -> PatternHit | None:
    if not re.search(r"\bwhile\b", code):
        return None
    if re.search(rf"\bwhile\s+{_BOUND_NAMES}\s*[<>=]", code, re.IGNORECASE):
        return None
    if re.search(
        r"\b\w+\s*(?:\+=|-=)\s*1\b|\b(?:left|right|i|j|ptr)\s*(?:\+=|-=)",
        code,
    ):
        return PatternHit(
            pattern_id="linear_while_pointer",
            complexity="O(n)",
            reasoning="Линейный while с монотонным сдвигом индекса/указателя.",
            confidence="medium",
            assumptions=["Указатель изменяется монотонно и не сбрасывается."],
            uncertainty_flags=["while_pointer_monotonic_assumed"],
        )
    return None


def detect_two_pointers(code: str) -> PatternHit | None:
    if not re.search(
        rf"\bwhile\s+({_BOUND_NAMES})\s*<\s*({_BOUND_NAMES})\b",
        code,
        re.IGNORECASE,
    ):
        return None
    if not re.search(
        r"(left|right|l|r|low|high)\s*(?:\+=|-=)",
        code,
        re.IGNORECASE,
    ):
        return None
    return PatternHit(
        pattern_id="two_pointers",
        complexity="O(n)",
        reasoning="Обнаружен паттерн двух указателей (while left < right с движением границ).",
        confidence="high",
        assumptions=["Каждый указатель движется только вперёд по входу."],
    )


def detect_sliding_window(code: str, f: BlockFeatures) -> PatternHit | None:
    if not re.search(r"\bfor\b", code) or not re.search(r"\bwhile\b", code):
        return None
    if not re.search(rf"\b{_BOUND_NAMES}\b", code, re.IGNORECASE):
        return None
    if not re.search(r"left\s*\+=\s*1|left\s*=\s*left\s*\+\s*1", code, re.IGNORECASE):
        if not re.search(r"\bleft\s*[-+]=", code, re.IGNORECASE):
            return None
    return PatternHit(
        pattern_id="sliding_window",
        complexity="O(n)",
        reasoning="Паттерн sliding window: внешний проход и сдвиг left внутри while.",
        confidence="medium",
        assumptions=["Каждый индекс входа обрабатывается ограниченное число раз."],
        uncertainty_flags=["sliding_window_heuristic"],
    )


def detect_sort_then_scan(code: str, f: BlockFeatures) -> PatternHit | None:
    if not f.has_sorting and not re.search(r"\bsort(ed)?\s*\(|\.sort\s*\(", code):
        return None
    if f.loop_count < 1 and not re.search(r"\bfor\b", code):
        return None
    return PatternHit(
        pattern_id="sort_then_scan",
        complexity="O(n log n)",
        reasoning="Сортировка доминирует над последующим линейным проходом.",
        confidence="high",
        assumptions=["sort/sorted выполняется до линейного сканирования."],
    )


def detect_dependent_nested_loop(code: str, f: BlockFeatures) -> PatternHit | None:
    if f.max_loop_depth < 2 and code.count("for ") < 2:
        return None
    if re.search(
        r"for\s+\w+\s+in\s+range\s*\(\s*\w+\s*\)",
        code,
    ) or re.search(r"for\s+\w+\s+in\s+range\s*\(\s*0\s*,\s*\w+\s*\)", code):
        return PatternHit(
            pattern_id="dependent_nested_loop",
            complexity="O(n^2)",
            reasoning="Внутренний цикл зависит от внешнего индекса (типичный треугольный проход).",
            confidence="medium",
            assumptions=["Внутренний диапазон растёт линейно с внешним индексом."],
            uncertainty_flags=["dependent_inner_loop_heuristic"],
        )
    if re.search(r"for\s+\w+\s+in\s+range\s*\([^)]*:\s*\w+\s*\)", code):
        return PatternHit(
            pattern_id="dependent_nested_loop",
            complexity="O(n^2)",
            reasoning="Вложенные циклы с зависимым диапазоном внутреннего прохода.",
            confidence="medium",
            assumptions=["Суммарно ~n^2/2 итераций."],
        )
    return None


def try_rule_patterns(block: CodeBlock, f: BlockFeatures) -> PatternHit | None:
    """Вернуть лучший совпавший паттерн или None."""
    code = block.source
    hits: list[PatternHit] = []
    for detector in (
        lambda: detect_binary_search(code),
        lambda: detect_dependent_nested_loop(code, f),
        lambda: detect_sort_then_scan(code, f),
        lambda: detect_two_pointers(code),
        lambda: detect_sliding_window(code, f),
        lambda: detect_linear_while_pointer(code),
    ):
        hit = detector()
        if hit:
            hits.append(hit)
    return _pick_best(hits)
