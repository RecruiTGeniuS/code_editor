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


def _sanitize_recommendation(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip(" -•\t\r\n"))
    if not cleaned:
        return ""
    if len(cleaned) <= MAX_TEXT_CHARS:
        return cleaned
    shortened = cleaned[:MAX_TEXT_CHARS].rsplit(" ", 1)[0].rstrip(".,;:")
    return f"{shortened}."


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
        "style": "one concise practical sentence per block, no generic filler",
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
        "Return JSON only. For each input block, provide one specific actionable sentence. "
        "Do not repeat the same wording for every block. Mention concrete visible causes "
        "such as nested loops, recursion, sorting, dynamic calls, caching, indexing, "
        "precomputation, or data structures when relevant."
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
            out[bid] = text
    return out
