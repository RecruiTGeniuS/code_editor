from __future__ import annotations

import json

from .models import BIG_O_CLASSES, CodeBlock
from .ollama_client import OllamaBigOClient


def _fallback_review(blocks: list[CodeBlock]) -> str:
    counts = {k: 0 for k in BIG_O_CLASSES}
    for b in blocks:
        if b.complexity in counts:
            counts[b.complexity] += 1
    heavy = sorted(
        [b for b in blocks if b.complexity in {"O(n^2)", "O(n^3)", "O(2^n)", "O(n!)"}],
        key=lambda x: (x.file_path, x.start_line),
    )[:10]
    lines = ["Краткая рецензия по сложности проекта:"]
    lines.append("Распределение блоков:")
    for k in BIG_O_CLASSES:
        lines.append(f"- {k}: {counts[k]}")
    if heavy:
        lines.append("Потенциальные hotspots:")
        for b in heavy:
            lines.append(f"- {b.file_path}:{b.start_line}-{b.end_line} -> {b.complexity} ({b.short_name})")
    else:
        lines.append("Явных тяжелых hotspots не найдено.")
    lines.append("Рекомендация: проверить красные блоки на вложенные циклы/рекурсию.")
    return "\n".join(lines)


def build_project_review(blocks: list[CodeBlock], ollama: OllamaBigOClient | None) -> str:
    if not blocks:
        return "Анализ завершён: в проекте не найдено поддерживаемых блоков кода."
    if ollama is None or not ollama.is_available():
        return _fallback_review(blocks)

    counts = {k: 0 for k in BIG_O_CLASSES}
    for b in blocks:
        if b.complexity in counts:
            counts[b.complexity] += 1
    top = sorted(
        [b for b in blocks if b.complexity in {"O(n^2)", "O(n^3)", "O(2^n)", "O(n!)"}],
        key=lambda x: (x.file_path, x.start_line),
    )[:20]
    summary = {
        "total_blocks": len(blocks),
        "counts": counts,
        "hotspots": [
            {
                "file": b.file_path,
                "line_start": b.start_line,
                "line_end": b.end_line,
                "complexity": b.complexity,
                "name": b.short_name,
            }
            for b in top
        ],
    }

    prompt = (
        "Сделай краткую и обоснованную рецензию сложности проекта по данным ниже.\n"
        "Пиши по-русски, 5-10 пунктов, практичные советы.\n"
        "Данные:\n"
        f"{json.dumps(summary, ensure_ascii=False, indent=2)}"
    )
    try:
        # Переиспользуем endpoint generate, без строгого json формата.
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
    return _fallback_review(blocks)

