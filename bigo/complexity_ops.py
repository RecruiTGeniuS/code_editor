"""Сравнение и умножение обозначений Big-O (простая эвристика)."""

from __future__ import annotations

from .models import is_ranked_complexity, max_complexity

# Степень n и log-фактор для полиномиально-логарифмического ряда.
_RANKED_FOR_MULTIPLY = frozenset(
    {
        "O(1)",
        "O(log n)",
        "O(n)",
        "O(n log n)",
        "O(n^2)",
        "O(n^2 log n)",
        "O(n^3)",
    }
)


def _parse_n_degree(complexity: str) -> tuple[int, int] | None:
    if complexity == "O(1)":
        return (0, 0)
    if complexity == "O(log n)":
        return (0, 1)
    if complexity == "O(n)":
        return (1, 0)
    if complexity == "O(n log n)":
        return (1, 1)
    if complexity == "O(n^2)":
        return (2, 0)
    if complexity == "O(n^2 log n)":
        return (2, 1)
    if complexity == "O(n^3)":
        return (3, 0)
    return None


def _format_n_degree(degree: int, log_factor: int) -> str | None:
    if degree < 0 or log_factor < 0:
        return None
    if degree == 0 and log_factor == 0:
        return "O(1)"
    if degree == 0 and log_factor >= 1:
        return "O(log n)"
    if degree == 1 and log_factor == 0:
        return "O(n)"
    if degree == 1 and log_factor == 1:
        return "O(n log n)"
    if degree == 2 and log_factor == 0:
        return "O(n^2)"
    if degree == 2 and log_factor == 1:
        return "O(n^2 log n)"
    if degree == 3 and log_factor == 0:
        return "O(n^3)"
    if degree >= 4:
        return None
    if degree == 3 and log_factor >= 1:
        return None
    return None


def multiply_complexities(a: str, b: str) -> str | None:
    if a not in _RANKED_FOR_MULTIPLY or b not in _RANKED_FOR_MULTIPLY:
        return None
    pa, pb = _parse_n_degree(a), _parse_n_degree(b)
    if pa is None or pb is None:
        return None
    return _format_n_degree(pa[0] + pb[0], pa[1] + pb[1])


def is_call_inside_loop(call_summary: dict, loop_summary: dict) -> bool:
    c_start = call_summary.get("start_line")
    c_end = call_summary.get("end_line")
    l_start = loop_summary.get("start_line")
    l_end = loop_summary.get("end_line")
    if None in (c_start, c_end, l_start, l_end):
        return False
    return int(l_start) <= int(c_start) and int(c_end) <= int(l_end)


def loops_containing_call(
    call_summary: dict, loop_summaries: list[dict]
) -> list[dict]:
    if not call_summary.get("start_line"):
        return []
    return [
        loop
        for loop in loop_summaries
        if loop.get("start_line") is not None and is_call_inside_loop(call_summary, loop)
    ]


def loop_enclosure_complexity(loops: list[dict]) -> tuple[str | None, bool]:
    if not loops:
        return ("O(1)", False)
    has_while = any(loop.get("kind") == "while" for loop in loops)
    product = "O(1)"
    for loop in loops:
        lc = loop.get("estimated_complexity") or "O(n)"
        if lc not in _RANKED_FOR_MULTIPLY:
            return (None, has_while)
        next_p = multiply_complexities(product, lc)
        if next_p is None:
            return (None, has_while)
        product = next_p
    return (product, has_while)


def call_cost_with_loops(
    callee_complexity: str,
    call_summary: dict,
    loop_summaries: list[dict],
) -> tuple[str | None, str, bool]:
    enclosing = loops_containing_call(call_summary, loop_summaries)
    if not enclosing:
        return (
            callee_complexity,
            f"вызов {call_summary.get('call_name', '?')} вне цикла, callee {callee_complexity}",
            False,
        )

    loop_cost, has_while = loop_enclosure_complexity(enclosing)
    if loop_cost is None:
        return (None, "не удалось оценить стоимость окружающих циклов", has_while)

    combined = multiply_complexities(loop_cost, callee_complexity)
    if combined is None:
        return (None, "не удалось перемножить сложности цикла и callee", has_while)

    name = call_summary.get("call_name") or call_summary.get("name", "?")
    detail = (
        f"вызов {name} внутри цикла(ов) {loop_cost} × callee {callee_complexity} → {combined}"
    )
    return (combined, detail, has_while)


def pick_max_costs(*costs: str | None) -> str | None:
    result: str | None = None
    for c in costs:
        if is_ranked_complexity(c):
            result = max_complexity(result, c)
    return result
