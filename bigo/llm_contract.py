from __future__ import annotations

import json
import re
from typing import Any

PROMPT_VERSION = "v3-forced-estimate"
TASK_NAME = "estimate_upper_bound_big_o"

ALLOWED_COMPLEXITIES = [
    "O(1)",
    "O(log n)",
    "O(n)",
    "O(n log n)",
    "O(n^2)",
    "O(n^2 log n)",
    "O(n^3)",
    "O(2^n)",
    "O(n!)",
    "unknown",
]

LLM_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "required": ["complexity", "confidence", "needs_human_review", "reasoning_summary"],
    "properties": {
        "complexity": {"type": "string", "enum": ALLOWED_COMPLEXITIES},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "needs_human_review": {"type": "boolean"},
        "reasoning_summary": {"type": "string"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
}

SYSTEM_INSTRUCTIONS = (
    "Estimate upper-bound Big-O for exactly one code block. "
    "Return JSON only, no markdown. "
    "Allowed complexity values: "
    + ", ".join(ALLOWED_COMPLEXITIES)
    + ". Keep it short: complexity, confidence, needs_human_review, reasoning_summary. "
    "Prefer a conservative Big-O class over unknown. "
    "Use unknown only for empty, syntactically broken, or non-code input. "
    "For dynamic or unresolved calls, estimate a plausible conservative upper bound "
    "from visible loops, recursion, container operations, and call placement; set confidence=low."
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
