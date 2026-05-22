from __future__ import annotations

from .models import BIG_O_ORDER, CodeBlock


def complexity_color_class(complexity: str | None) -> str:
    if complexity in {"O(1)", "O(log n)"}:
        return "green"
    if complexity == "O(n)":
        return "gray"
    if complexity == "O(n log n)":
        return "yellow"
    return "red"


def to_monaco_decorations(blocks: list[CodeBlock]) -> list[dict]:
    out: list[dict] = []
    for b in blocks:
        if not b.complexity:
            continue
        out.append(
            {
                "startLine": b.start_line,
                "endLine": b.end_line,
                "label": b.complexity,
                "severity": complexity_color_class(b.complexity),
                "hover": (b.reason or b.complexity).strip(),
            }
        )
    return out

