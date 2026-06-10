from __future__ import annotations

import json
import os

from .block_utils import (
    analyzable_blocks,
    container_blocks,
    group_blocks_by_class,
    group_blocks_by_file,
)
from .dependency_graph import DependencyGraph
from .models import BIG_O_CLASSES, CodeBlock
from .ollama_client import OllamaBigOClient


def _dependency_summary_lines(graph: DependencyGraph | None) -> list[str]:
    if graph is None:
        return []
    return [
        f"Граф вызовов: связанных вызовов {graph.resolved_count}, "
        f"неразрешённых {graph.unresolved_count}.",
        "Часть оценок учитывает сложность resolved-вызовов между блоками проекта.",
        "Часть имён вызовов не удалось однозначно сопоставить с блоками проекта.",
    ]


def _fallback_review(
    all_blocks: list[CodeBlock],
    dependency_graph: DependencyGraph | None = None,
) -> str:
    analyzed = analyzable_blocks(all_blocks)
    containers = container_blocks(all_blocks)
    if not analyzed:
        return "Анализ завершён: не найдено анализируемых функций/методов."

    counts = {k: 0 for k in BIG_O_CLASSES}
    for b in analyzed:
        if b.complexity in counts:
            counts[b.complexity] += 1

    heavy = sorted(
        [
            b
            for b in analyzed
            if b.complexity in {"O(n^2)", "O(n^3)", "O(2^n)", "O(n!)"}
        ],
        key=lambda x: (x.file_path, x.start_line),
    )[:10]

    lines = ["Краткая рецензия по сложности проекта:"]
    lines.append(
        f"Проанализировано функций/методов: {len(analyzed)}; "
        f"контейнеров (классы и т.п.): {len(containers)}."
    )
    lines.append("Распределение по сложности (только исполняемые блоки):")
    for k in BIG_O_CLASSES:
        lines.append(f"- {k}: {counts[k]}")

    by_file = group_blocks_by_file(analyzed)
    lines.append("По файлам:")
    for path in sorted(by_file.keys()):
        file_blocks = by_file[path]
        file_counts = {k: 0 for k in BIG_O_CLASSES}
        for b in file_blocks:
            if b.complexity in file_counts:
                file_counts[b.complexity] += 1
        summary = ", ".join(f"{k}={v}" for k, v in file_counts.items() if v)
        lines.append(f"- {os.path.basename(path)}: {len(file_blocks)} блок(ов) ({summary or '—'})")

    by_class = group_blocks_by_class(analyzed, all_blocks)
    class_keys = [k for k in by_class if k != "<top-level>"]
    if class_keys:
        lines.append("По классам:")
        for cls_name in sorted(class_keys):
            cls_blocks = by_class[cls_name]
            lines.append(
                f"- {cls_name}: {len(cls_blocks)} метод(ов)/функций"
            )

    if heavy:
        lines.append("Потенциальные hotspots:")
        for b in heavy:
            label = b.qualified_name or b.short_name
            lines.append(
                f"- {b.file_path}:{b.start_line}-{b.end_line} -> "
                f"{b.complexity} ({label})"
            )
    else:
        lines.append("Явных тяжелых hotspots не найдено.")
    lines.append("Рекомендация: проверить красные блоки на вложенные циклы/рекурсию.")
    lines.extend(_dependency_summary_lines(dependency_graph))
    return "\n".join(lines)


def build_project_review(
    blocks: list[CodeBlock],
    ollama: OllamaBigOClient | None,
    dependency_graph: DependencyGraph | None = None,
) -> str:
    analyzed = analyzable_blocks(blocks)
    containers = container_blocks(blocks)
    if not analyzed and not containers:
        return "Анализ завершён: в проекте не найдено поддерживаемых блоков кода."
    if not analyzed:
        return (
            f"Найдено контейнеров: {len(containers)}; "
            "анализируемых функций/методов нет."
        )

    if ollama is None or not ollama.is_available():
        return _fallback_review(blocks, dependency_graph)

    counts = {k: 0 for k in BIG_O_CLASSES}
    for b in analyzed:
        if b.complexity in counts:
            counts[b.complexity] += 1
    top = sorted(
        [
            b
            for b in analyzed
            if b.complexity in {"O(n^2)", "O(n^3)", "O(2^n)", "O(n!)"}
        ],
        key=lambda x: (x.file_path, x.start_line),
    )[:20]

    by_file = group_blocks_by_file(analyzed)
    by_class = group_blocks_by_class(analyzed, blocks)
    summary = {
        "analyzed_blocks": len(analyzed),
        "container_blocks": len(containers),
        "counts": counts,
        "by_file": {
            os.path.basename(path): len(file_blocks)
            for path, file_blocks in by_file.items()
        },
        "by_class": {
            name: len(cls_blocks)
            for name, cls_blocks in by_class.items()
            if name != "<top-level>"
        },
        "hotspots": [
            {
                "file": b.file_path,
                "line_start": b.start_line,
                "line_end": b.end_line,
                "complexity": b.complexity,
                "name": b.qualified_name or b.short_name,
            }
            for b in top
        ],
    }

    prompt = (
        "Сделай краткую и обоснованную рецензию сложности проекта по данным ниже.\n"
        "Пиши по-русски, 5-10 пунктов, практичные советы.\n"
        "Учитывай только analyzed_blocks (функции/методы), не container_blocks.\n"
        "Данные:\n"
        f"{json.dumps(summary, ensure_ascii=False, indent=2)}"
    )
    try:
        import requests

        resp = requests.post(
            f"{ollama.base_url}/api/generate",
            json={
                "model": ollama.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.2},
            },
            timeout=max(ollama.timeout_s, 60),
        )
        resp.raise_for_status()
        text = resp.json().get("response", "").strip()
        if text:
            return text
    except Exception:
        pass
    return _fallback_review(blocks, dependency_graph)
