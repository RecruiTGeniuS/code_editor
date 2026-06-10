#!/usr/bin/env python3
"""Ручная проверка Ollama Big-O fallback (не для pytest)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bigo.ai_fallback import build_llm_block_payload, estimate_with_ai
from bigo.models import AnalysisResult, BlockFeatures
from bigo.models import CodeBlock
from bigo.ollama_client import OllamaBigOClient


def main() -> None:
    block = CodeBlock(
        block_id="manual#0",
        file_path="manual.py",
        language_id="python",
        kind="function",
        name="main_loop_linear",
        start_line=1,
        end_line=5,
        source=(
            "def main_loop_linear(items):\n"
            "    for item in items:\n"
            "        helper_linear(items)\n"
        ),
        source_hash="manual",
        calls=["helper_linear"],
    )
    rule = AnalysisResult(
        complexity="O(1)",
        confidence="low",
        reasoning_summary="Локально O(1), вызов в цикле",
        needs_human_review=True,
        features=BlockFeatures(max_loop_depth=1, loop_count=1),
    )
    payload = build_llm_block_payload(block, rule)
    print("=== Payload ===")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    client = OllamaBigOClient(max_workers=1, timeout_s=120.0)
    print(f"\nOllama available: {client.is_available()}")
    if not client.is_available():
        print("Запустите Ollama и модель qwen2.5-coder:7b")
        return

    result = estimate_with_ai(block, rule, client=client)
    print("\n=== AnalysisResult ===")
    print(f"complexity: {result.complexity}")
    print(f"confidence: {result.confidence}")
    print(f"analyzer_kind: {result.analyzer_kind}")
    print(f"reasoning: {result.reasoning_summary}")


if __name__ == "__main__":
    main()
