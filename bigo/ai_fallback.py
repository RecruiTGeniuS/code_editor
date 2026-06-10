"""AI fallback для блоков, которые rule-based анализатор не уверенно оценил."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from .dependency_graph import block_graph_id
from .llm_contract import PROMPT_VERSION, TASK_NAME, extract_json_object
from .models import AnalysisResult, BlockFeatures, CodeBlock, is_ranked_complexity
from .ollama_client import OllamaBigOClient, normalize_complexity

if TYPE_CHECKING:
    from .dependency_graph import DependencyGraph

_MAX_SOURCE_LINES = 120


def needs_ai_fallback(rule_result: AnalysisResult) -> bool:
    if rule_result.complexity is None or rule_result.complexity == "unknown":
        return True
    if rule_result.needs_human_review:
        return True
    return rule_result.confidence == "low"


def _source_excerpt(block: CodeBlock) -> str:
    lines = block.source.splitlines()
    if len(lines) <= _MAX_SOURCE_LINES:
        return block.source
    head = lines[: _MAX_SOURCE_LINES]
    return "\n".join(head) + f"\n# ... ({len(lines) - _MAX_SOURCE_LINES} lines truncated)"


def _known_callee_costs(
    block: CodeBlock,
    dependency_graph: DependencyGraph | None,
    known_results: dict[str, AnalysisResult] | None,
) -> list[dict]:
    if dependency_graph is None or not known_results:
        return []
    bid = block_graph_id(block)
    out: list[dict] = []
    for edge in dependency_graph.get_callees(bid):
        if not edge.resolved or not edge.target_block_id:
            continue
        kr = known_results.get(edge.target_block_id)
        if kr and kr.complexity:
            out.append(
                {
                    "call_name": edge.call_name,
                    "target_block_id": edge.target_block_id,
                    "complexity": kr.complexity,
                    "confidence": kr.confidence,
                }
            )
    return out


def build_llm_block_payload(
    block: CodeBlock,
    rule_result: AnalysisResult,
    dependency_graph: DependencyGraph | None = None,
    known_results: dict[str, AnalysisResult] | None = None,
) -> dict:
    features = rule_result.features or block.features
    features_dict = asdict(features) if features else {}
    return {
        "task": TASK_NAME,
        "language": block.language_id,
        "block_kind": block.kind,
        "block_name": block.name,
        "qualified_name": block.qualified_name or block.name,
        "file_path": block.file_path,
        "start_line": block.start_line,
        "end_line": block.end_line,
        "signature": block.signature,
        "source_excerpt": _source_excerpt(block),
        "features": features_dict,
        "called_names": list(block.calls),
        "known_callee_costs": _known_callee_costs(
            block, dependency_graph, known_results
        ),
        "rule_based_result": {
            "complexity": rule_result.complexity,
            "confidence": rule_result.confidence,
            "reasoning_summary": rule_result.reasoning_summary or rule_result.reason,
            "uncertainty_flags": list(features.uncertainty_flags) if features else [],
            "needs_human_review": rule_result.needs_human_review,
        },
        "instructions": (
            "Оцени верхнюю асимптотическую сложность Big-O для этого блока. "
            "Учти rule_based_result и known_callee_costs. "
            "Не выдумывай скрытые вызовы или импорты. "
            "Если по коду можно вывести приблизительную верхнюю оценку, верни O(...). "
            "При сомнениях снижай confidence и добавляй assumptions. "
            "Возвращай unknown только если оценка действительно невозможна: "
            "нет контекста, неразрешённые внешние вызовы, непонятная рекурсия "
            "или код нельзя разобрать."
        ),
    }


def parse_llm_response_to_analysis_result(
    data: dict[str, Any],
    *,
    model_id: str,
    rule_result: AnalysisResult,
    telemetry: dict[str, Any] | None = None,
) -> AnalysisResult:
    complexity = normalize_complexity(str(data.get("complexity", "")))
    if complexity == "O(n)" and not data.get("complexity"):
        complexity = rule_result.complexity or "unknown"

    confidence = str(data.get("confidence", "medium")).strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"

    assumptions = [str(x) for x in data.get("assumptions", []) if x]
    variables = [str(x) for x in data.get("variables", []) if x]
    if variables:
        assumptions = [f"Переменные: {', '.join(variables)}"] + assumptions

    advice = [str(x) for x in data.get("optimization_advice", []) if x]
    reasoning = str(data.get("reasoning_summary", "")).strip() or rule_result.reasoning_summary

    duration_ms = None
    if telemetry and telemetry.get("total_duration") is not None:
        duration_ms = int(telemetry["total_duration"] // 1_000_000)

    return AnalysisResult(
        complexity=complexity if is_ranked_complexity(complexity) or complexity == "unknown" else "unknown",
        reason=reasoning,
        reasoning_summary=reasoning,
        confidence=confidence,
        assumptions=assumptions,
        analyzer_kind="llm",
        needs_human_review=bool(data.get("needs_human_review", False)),
        optimization_advice=advice,
        model_id=model_id,
        prompt_version=PROMPT_VERSION,
        features=rule_result.features,
        duration_ms=duration_ms,
    )


def ai_error_result(rule_result: AnalysisResult, message: str) -> AnalysisResult:
    return AnalysisResult(
        complexity=rule_result.complexity or "unknown",
        reason=message,
        reasoning_summary=f"AI fallback недоступен: {message}",
        confidence="low",
        assumptions=list(rule_result.assumptions),
        analyzer_kind="llm_error",
        needs_human_review=True,
        features=rule_result.features,
        model_id=None,
        prompt_version=PROMPT_VERSION,
    )


def estimate_with_ai(
    block: CodeBlock,
    rule_result: AnalysisResult,
    dependency_graph: DependencyGraph | None = None,
    known_results: dict[str, AnalysisResult] | None = None,
    *,
    model: str = "qwen2.5-coder:7b",
    client: OllamaBigOClient | None = None,
    timeout_s: float = 60.0,
) -> AnalysisResult:
    payload = build_llm_block_payload(
        block, rule_result, dependency_graph, known_results
    )
    ollama = client or OllamaBigOClient(
        model=model, timeout_s=timeout_s, max_workers=1
    )
    if not ollama.is_available():
        return ai_error_result(rule_result, "Ollama не отвечает на /api/tags")

    try:
        parsed, telemetry = ollama.chat_big_o_estimate(payload)
        return parse_llm_response_to_analysis_result(
            parsed,
            model_id=model,
            rule_result=rule_result,
            telemetry=telemetry,
        )
    except json.JSONDecodeError as exc:
        return ai_error_result(rule_result, f"невалидный JSON от модели: {exc}")
    except Exception as exc:  # noqa: BLE001
        return ai_error_result(rule_result, str(exc))
