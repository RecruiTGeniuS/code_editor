"""Контракт JSON для AI fallback Big-O (Ollama)."""

from __future__ import annotations

import json
import re
from typing import Any

PROMPT_VERSION = "v1"
TASK_NAME = "estimate_upper_bound_big_o"

LLM_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "required": [
        "complexity",
        "variables",
        "assumptions",
        "reasoning_summary",
        "confidence",
        "needs_human_review",
        "optimization_advice",
    ],
    "properties": {
        "complexity": {
            "type": "string",
            "description": "Одна из стандартных оценок Big-O, например O(n), O(n^2)",
        },
        "variables": {
            "type": "array",
            "items": {"type": "string"},
        },
        "assumptions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "reasoning_summary": {"type": "string"},
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
        },
        "needs_human_review": {"type": "boolean"},
        "optimization_advice": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}

SYSTEM_INSTRUCTIONS = (
    "Ты оцениваешь верхнюю асимптотическую сложность Big-O для одного блока кода.\n"
    "Ответь ТОЛЬКО валидным JSON без markdown.\n"
    "Не придумывай факты, которых нет во входных данных.\n"
    "Если можно обоснованно дать консервативную верхнюю оценку, верни O(...), а не unknown.\n"
    "При сомнениях снижай confidence и перечисляй assumptions.\n"
    "Если оценка зависит от неизвестных вызовов — confidence=low и needs_human_review=true.\n"
    "unknown допустим только когда оценка действительно невозможна по данным блока.\n"
    f"Схема ответа: {LLM_RESPONSE_SCHEMA}"
)


def extract_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise json.JSONDecodeError("empty response", raw, 0)
    try:
        row = json.loads(raw)
        if isinstance(row, dict):
            return row
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL | re.IGNORECASE)
    if fence:
        return json.loads(fence.group(1))
    brace = re.search(r"\{.*\}", raw, re.DOTALL)
    if brace:
        return json.loads(brace.group(0))
    raise json.JSONDecodeError("no JSON object found", raw, 0)
