"""Локальная рецензия одного блока для UI-кнопки в Monaco.

Не отправляет данные в AI; собирает текст из CodeBlock + AnalysisResult.
Реальный AI-ревью одного блока выполняется через estimate_with_ai,
если orchestrator работает с use_ai=True (это происходит во время
project-анализа, не в этом модуле).
"""

from __future__ import annotations

import os

from .models import AnalysisResult, CodeBlock


_KIND_LABEL = {
    "rule": "rule",
    "static": "rule",
    "llm": "llm (AI)",
    "llm_error": "llm_error (AI недоступен)",
    "cache": "cache",
    "none": "none",
}


def _format_source_kind(analysis: AnalysisResult | None, block: CodeBlock) -> str:
    if analysis and analysis.analyzer_kind:
        return _KIND_LABEL.get(analysis.analyzer_kind, analysis.analyzer_kind)
    return _KIND_LABEL.get(block.source_kind or "static", block.source_kind or "static")


def _features_lines(block: CodeBlock) -> list[str]:
    f = block.features
    if f is None:
        return []
    parts: list[str] = []
    if f.loop_count or f.max_loop_depth:
        parts.append(f"циклов: {f.loop_count}, макс. глубина: {f.max_loop_depth}")
    if f.branch_count:
        parts.append(f"ветвлений: {f.branch_count}")
    if f.call_count or f.project_call_count or f.external_call_count:
        parts.append(
            "вызовов: "
            f"всего={f.call_count}, "
            f"внутри проекта={f.project_call_count}, "
            f"внешних={f.external_call_count}"
        )
    if f.has_recursion:
        kind = f.recursion_kind or "yes"
        parts.append(f"рекурсия: {kind}")
    if f.has_sorting or f.has_sort_call:
        parts.append("есть sort/сортировка")
    if f.has_log_pattern:
        parts.append("есть log-паттерн (бинарный/двоичный поиск)")
    if f.uncertainty_flags:
        parts.append("uncertainty: " + ", ".join(f.uncertainty_flags))
    return parts


def build_block_review(
    block: CodeBlock,
    analysis: AnalysisResult | None = None,
    *,
    use_ai_hint: bool = False,
    ai_available: bool | None = None,
) -> str:
    """Сформировать текстовую рецензию одного блока для правой панели.

    Использует уже посчитанные данные:
    - CodeBlock.complexity / reason / source_kind / features;
    - AnalysisResult (если сохранён orchestrator-ом).

    AI-вызовов внутри нет: рецензия чисто локальная.
    """
    name = block.qualified_name or block.short_name
    lines: list[str] = []
    lines.append(f"Рецензия блока: {name}")
    lines.append("-" * max(20, len("Рецензия блока: " + name)))
    file_name = os.path.basename(block.file_path) if block.file_path else "?"
    lines.append(f"Файл: {file_name} (строки {block.start_line}–{block.end_line})")
    if block.signature:
        lines.append(f"Сигнатура: {block.signature}")

    complexity = (
        analysis.complexity
        if analysis and analysis.complexity
        else (block.complexity or "unknown")
    )
    lines.append(f"Сложность: {complexity}")

    confidence = analysis.confidence if analysis else "—"
    lines.append(f"Уверенность: {confidence}")

    lines.append(f"Источник оценки: {_format_source_kind(analysis, block)}")

    needs_review = bool(analysis.needs_human_review) if analysis else (
        block.complexity in (None, "unknown")
    )
    if needs_review:
        lines.append("Требует ручной проверки: да")

    reasoning = ""
    if analysis and (analysis.reasoning_summary or analysis.reason):
        reasoning = analysis.reasoning_summary or analysis.reason
    elif block.reason:
        reasoning = block.reason
    if reasoning:
        lines.append("")
        lines.append("Обоснование:")
        lines.append(reasoning.strip())

    if analysis and analysis.assumptions:
        lines.append("")
        lines.append("Допущения:")
        for a in analysis.assumptions:
            lines.append(f"- {a}")

    if analysis and analysis.optimization_advice:
        lines.append("")
        lines.append("Идеи оптимизации:")
        for tip in analysis.optimization_advice:
            lines.append(f"- {tip}")

    feature_parts = _features_lines(block)
    if feature_parts:
        lines.append("")
        lines.append("Признаки блока:")
        for p in feature_parts:
            lines.append(f"- {p}")

    if block.calls:
        lines.append("")
        preview = ", ".join(block.calls[:8])
        if len(block.calls) > 8:
            preview += f" … (+{len(block.calls) - 8})"
        lines.append(f"Вызывает: {preview}")

    if use_ai_hint:
        lines.append("")
        if ai_available is False:
            lines.append(
                "Замечание: AI-рецензия недоступна — Ollama не отвечает."
            )
        elif analysis is None or analysis.analyzer_kind in (None, "rule", "static", "cache"):
            lines.append(
                "Замечание: показана локальная рецензия; "
                "AI-оценка не выполнялась для этого блока."
            )
    return "\n".join(lines)
