from __future__ import annotations

import concurrent.futures

from typing import Protocol

from .ai_fallback import ai_error_result, estimate_with_ai
from .models import AnalysisResult, CodeBlock
from .ollama_client import OllamaBigOClient


class AiAdapter(Protocol):
    def is_available(self) -> bool:
        ...

    def estimate_complexity(
        self,
        block: CodeBlock,
        rule_result: AnalysisResult,
        dependency_graph=None,
        known_results: dict[str, AnalysisResult] | None = None,
    ) -> AnalysisResult:
        ...


class OllamaAiAdapter:
    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5-coder:7b",
        timeout_s: float = 60.0,
        max_workers: int = 4,
    ):
        self.model = model
        self.client = OllamaBigOClient(
            base_url=base_url,
            model=model,
            timeout_s=timeout_s,
            max_workers=max_workers,
        )
        self.timeout_s = timeout_s
        self.max_workers = max(1, int(max_workers))

    def is_available(self) -> bool:
        return self.client.is_available()

    def prewarm(self) -> bool:
        return self.client.prewarm()

    def estimate_complexity(
        self,
        block: CodeBlock,
        rule_result: AnalysisResult,
        dependency_graph=None,
        known_results: dict[str, AnalysisResult] | None = None,
    ) -> AnalysisResult:
        return estimate_with_ai(
            block,
            rule_result,
            dependency_graph,
            known_results,
            model=self.model,
            client=self.client,
            timeout_s=self.timeout_s,
            check_available=False,
        )

    def estimate_many(
        self,
        jobs: list[tuple[CodeBlock, AnalysisResult]],
        dependency_graph=None,
        known_results: dict[str, AnalysisResult] | None = None,
        progress_callback=None,
    ) -> dict[str, AnalysisResult]:
        from .dependency_graph import block_graph_id

        out: dict[str, AnalysisResult] = {}
        if not jobs:
            return out
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            future_to_block = {
                ex.submit(
                    self.estimate_complexity,
                    block,
                    rule_result,
                    dependency_graph,
                    known_results,
                ): block
                for block, rule_result in jobs
            }
            total = len(future_to_block)
            done = 0
            for future in concurrent.futures.as_completed(future_to_block):
                block = future_to_block[future]
                try:
                    out[block_graph_id(block)] = future.result()
                except Exception as exc:  # noqa: BLE001
                    rule = next((r for b, r in jobs if b is block), AnalysisResult())
                    out[block_graph_id(block)] = ai_error_result(rule, str(exc))
                done += 1
                if progress_callback is not None:
                    progress_callback(done, total)
        return out
