from __future__ import annotations

from .block_utils import is_overlayable_block
from .dependency_graph import block_graph_id
from .models import BIG_O_ORDER, AnalysisResult, CodeBlock


def complexity_color_class(complexity: str | None) -> str:
    if complexity in {None, "", "unknown"}:
        return "gray"
    if complexity in {"O(1)", "O(log n)"}:
        return "green"
    if complexity == "O(n)":
        return "gray"
    if complexity in {"O(n log n)", "O(n^2 log n)"}:
        return "yellow"
    return "red"


def decoration_label(block: CodeBlock) -> str:
    """Подпись для Monaco: сложность + видимые маркеры только для AI/unknown."""
    c = block.complexity
    if c in (None, "", "unknown"):
        return "unknown"
    if block.source_kind == "llm":
        return f"{c} · AI"
    return c


def decoration_hover(block: CodeBlock) -> str:
    base = (block.reason or block.complexity or "").strip()
    kind = block.source_kind or "static"
    if kind == "llm":
        return f"{base}\n[оценка: AI]".strip()
    if kind == "cache":
        return f"{base}\n[оценка: cache]".strip()
    if block.complexity in (None, "unknown"):
        return f"{base}\n[требует проверки]".strip()
    return f"{base}\n[оценка: rule]".strip()


def to_monaco_decorations(
    blocks: list[CodeBlock],
    results_by_id: dict[str, AnalysisResult] | None = None,
) -> list[dict]:
    """JS-overlay rows. block_id совпадает с block_graph_id (stable_id).

    `results_by_id` опционально пополняет каждую строку confidence и
    analyzer_kind из AnalysisResult — controller передаёт это после
    завершения анализа, чтобы кнопка рецензии в Monaco могла отличать
    rule/llm/llm_error и показывать степень уверенности.
    """
    out: list[dict] = []
    results_by_id = results_by_id or {}
    for b in blocks:
        if not is_overlayable_block(b):
            continue
        bid = block_graph_id(b)
        analysis = results_by_id.get(bid)
        if analysis is not None and analysis.analyzer_kind:
            analyzer_kind = analysis.analyzer_kind
        else:
            analyzer_kind = b.source_kind or "static"
        confidence = analysis.confidence if analysis else None
        out.append(
            {
                "blockId": bid,
                "filePath": b.file_path,
                "startLine": b.start_line,
                "endLine": b.end_line,
                "complexity": b.complexity,
                "confidence": confidence,
                "analyzerKind": analyzer_kind,
                "label": decoration_label(b),
                "severity": complexity_color_class(b.complexity),
                "hover": decoration_hover(b),
            }
        )
    return out
