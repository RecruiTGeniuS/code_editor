from __future__ import annotations

import re
from typing import Any

from .block_utils import analyzable_blocks
from .dependency_graph import block_graph_id
from .models import BIG_O_CLASSES, AnalysisResult, CodeBlock
from .ollama_client import OllamaBigOClient

MAX_RECOMMENDATIONS = 5
MAX_SOURCE_LINES = 45
MAX_TEXT_CHARS = 180
_GENERIC_AI_TEXT_RE = re.compile(
    r"\b(recommendation|advice|performance|complexity|optimi[sz]e)\b",
    re.IGNORECASE,
)


def pick_project_recommendation_blocks(
    blocks: list[CodeBlock], limit: int = MAX_RECOMMENDATIONS
) -> list[CodeBlock]:
    rank = {name: i for i, name in enumerate(BIG_O_CLASSES)}

    def score(block: CodeBlock) -> tuple[int, int, int, int]:
        complexity_rank = rank.get(block.complexity or "", -1)
        needs_review = 1 if block.complexity in (None, "unknown") else 0
        loop_depth = getattr(block.features, "max_loop_depth", 0) or 0
        call_count = getattr(block.features, "call_count", 0) or 0
        return (complexity_rank, needs_review, loop_depth, call_count)

    candidates = [
        b
        for b in analyzable_blocks(blocks)
        if b.complexity in {"O(n^2)", "O(n^2 log n)", "O(n^3)", "O(2^n)", "O(n!)"}
        or b.complexity in (None, "unknown")
        or getattr(b.features, "max_loop_depth", 0) >= 2
    ]
    return sorted(candidates, key=score, reverse=True)[:limit]


def _source_excerpt(block: CodeBlock) -> str:
    lines = block.source.splitlines()
    if len(lines) <= MAX_SOURCE_LINES:
        return block.source
    return "\n".join(lines[:MAX_SOURCE_LINES])


def _compact_block_payload(
    block: CodeBlock,
    analysis: AnalysisResult | None,
) -> dict[str, Any]:
    features = (analysis.features if analysis and analysis.features else block.features)
    return {
        "block_id": block_graph_id(block),
        "name": block.qualified_name or block.short_name,
        "language": block.language_id,
        "complexity": block.complexity,
        "source_kind": block.source_kind,
        "confidence": analysis.confidence if analysis else None,
        "reason": (analysis.reasoning_summary or analysis.reason) if analysis else block.reason,
        "features": {
            "max_loop_depth": features.max_loop_depth,
            "loop_count": features.loop_count,
            "call_count": features.call_count,
            "has_recursion": features.has_recursion,
            "has_sorting": features.has_sorting or features.has_sort_call,
            "uncertainty_flags": features.uncertainty_flags[:8],
            "calls": features.call_summaries[:6],
            "loops": features.loop_summaries[:5],
        },
        "source": _source_excerpt(block),
    }


def _normalize_similarity_key(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.lower(), flags=re.UNICODE)


def _is_similar_to_used(text: str, used: set[str]) -> bool:
    key = _normalize_similarity_key(text)
    if not key:
        return True
    if key in used:
        return True
    return any(key in old or old in key for old in used if min(len(key), len(old)) > 40)


def _remember_text(text: str, used: set[str]) -> None:
    key = _normalize_similarity_key(text)
    if key:
        used.add(key)


def _sanitize_recommendation(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip(" -•\t\r\n"))
    cleaned = re.sub(
        r"^(рекомендация|совет|recommendation|advice)\s*[:：-]\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    if not cleaned:
        return ""
    if _GENERIC_AI_TEXT_RE.search(cleaned) and not re.search(r"[А-Яа-яЁё]", cleaned):
        return ""
    if len(cleaned) <= MAX_TEXT_CHARS:
        return cleaned if cleaned.endswith((".", "!", "?")) else f"{cleaned}."
    shortened = cleaned[:MAX_TEXT_CHARS].rsplit(" ", 1)[0].rstrip(".,;:")
    return f"{shortened}."


def fallback_project_recommendation(block: CodeBlock, used_texts: set[str] | None = None) -> str:
    """Короткий локальный совет, если AI недоступен или ответ не подходит."""
    used_texts = used_texts if used_texts is not None else set()
    f = block.features
    flags = " ".join(f.uncertainty_flags or [])
    calls_in_loops = any(
        int(call.get("inside_loop_depth") or 0) > 0
        for call in (f.call_summaries or [])
        if isinstance(call, dict)
    )

    candidates: list[str] = []
    if block.complexity in {"O(2^n)", "O(n!)"} or f.has_recursion:
        candidates.append(
            "Сократите повторные ветви рекурсии: сохраните промежуточные результаты или перейдите к динамическому программированию."
        )
    if f.max_loop_depth >= 3 or block.complexity == "O(n^3)":
        candidates.append(
            "Разбейте тройную вложенность: заранее сгруппируйте данные или замените внутренний поиск индексом."
        )
    if f.has_sorting or f.has_sort_call:
        candidates.append(
            "Не сортируйте данные повторно в горячем месте; подготовьте порядок один раз или поддерживайте готовую структуру."
        )
    if calls_in_loops:
        candidates.append(
            "Проверьте вызовы внутри цикла: вынесите неизменные расчёты наружу или кэшируйте их результат."
        )
    if f.max_loop_depth == 2 or block.complexity in {"O(n^2)", "O(n^2 log n)"}:
        candidates.append(
            "Уберите лишний внутренний проход: подготовьте словарь, множество или индекс для быстрых проверок."
        )
    if "dynamic_call" in flags:
        candidates.append(
            "Замените динамический вызов явным маршрутом, чтобы стоимость была предсказуемой и проверяемой."
        )
    if block.complexity in (None, "unknown") or flags:
        candidates.append(
            "Уточните зависимость от размера входа и стоимость вызываемых функций, затем зафиксируйте оценку вручную."
        )
    candidates.append(
        "Проверьте этот горячий участок на реальных данных и уберите повторную работу из основного прохода."
    )

    for text in candidates:
        cleaned = _sanitize_recommendation(text)
        if cleaned and not _is_similar_to_used(cleaned, used_texts):
            _remember_text(cleaned, used_texts)
            return cleaned
    cleaned = _sanitize_recommendation(candidates[-1])
    _remember_text(cleaned, used_texts)
    return cleaned


def build_ai_project_recommendations(
    blocks: list[CodeBlock],
    block_results: dict[str, AnalysisResult],
    client: OllamaBigOClient | None,
    *,
    limit: int = MAX_RECOMMENDATIONS,
    check_available: bool = True,
) -> dict[str, str]:
    selected = pick_project_recommendation_blocks(blocks, limit)
    if not selected or client is None:
        return {}
    if check_available and not client.is_available():
        return {}

    selected_ids = [block_graph_id(block) for block in selected]
    allowed_ids = set(selected_ids)
    name_to_id = {
        (block.qualified_name or block.short_name): block_graph_id(block)
        for block in selected
    }
    payload = {
        "task": "write_short_big_o_recommendations",
        "language": "ru",
        "style": (
            "one short practical Russian sentence per block; no generic filler; "
            "texts must differ from each other"
        ),
        "max_chars_per_text": MAX_TEXT_CHARS,
        "blocks": [
            _compact_block_payload(block, block_results.get(block_graph_id(block)))
            for block in selected
        ],
        "response_schema": {
            "recommendations": [
                {"block_id": "same block_id", "text": "short Russian recommendation"}
            ]
        },
    }
    system = (
        "You write concise Russian performance recommendations for code blocks. "
        "Return JSON only. For each input block, provide exactly one specific actionable "
        "sentence in Russian, up to 180 characters. Do not use English filler words. "
        "Do not repeat the same wording. Base each sentence on visible causes: nested "
        "loops, recursion, sorting, calls in loops, dynamic calls, caching, indexing, "
        "precomputation, or data structures."
    )
    try:
        data, _telemetry = client.chat_json(
            system=system,
            payload=payload,
            num_predict=512,
            temperature=0.15,
        )
    except Exception:
        return {}

    rows = (
        data.get("recommendations")
        or data.get("items")
        or data.get("advice")
        or data.get("results")
    )
    if isinstance(rows, dict):
        rows = [{"block_id": key, "text": value} for key, value in rows.items()]
    if not isinstance(rows, list):
        return {}

    out: dict[str, str] = {}
    used_texts: set[str] = set()
    selected_by_id = {block_graph_id(block): block for block in selected}
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            row = {"text": str(row)}
        bid = str(
            row.get("block_id")
            or row.get("id")
            or row.get("block")
            or ""
        )
        if bid not in allowed_ids:
            bid = name_to_id.get(str(row.get("name") or row.get("function") or ""), bid)
        if bid not in allowed_ids and idx < len(selected_ids):
            bid = selected_ids[idx]
        if bid not in allowed_ids:
            continue
        text = _sanitize_recommendation(
            str(
                row.get("text")
                or row.get("recommendation")
                or row.get("advice")
                or row.get("message")
                or ""
            )
        )
        if text:
            if _is_similar_to_used(text, used_texts):
                text = fallback_project_recommendation(selected_by_id[bid], used_texts)
            else:
                _remember_text(text, used_texts)
            out[bid] = text
    return out
