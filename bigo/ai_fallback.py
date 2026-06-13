from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .dependency_graph import block_graph_id
from .llm_contract import PROMPT_VERSION, TASK_NAME
from .models import AnalysisResult, BlockFeatures, CodeBlock, is_ranked_complexity
from .ollama_client import OllamaBigOClient, normalize_complexity

if TYPE_CHECKING:
    from .dependency_graph import DependencyGraph

_MAX_SOURCE_LINES = 80


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
    return "\n".join(lines[:_MAX_SOURCE_LINES])


def _compact_features(features: BlockFeatures | None) -> dict:
    if features is None:
        return {}
    return {
        "loop_count": features.loop_count,
        "max_loop_depth": features.max_loop_depth,
        "branch_count": features.branch_count,
        "calls": features.call_summaries[:10],
        "loops": features.loop_summaries[:8],
        "container_ops": features.container_operations[:10],
        "has_recursion": features.has_recursion,
        "recursion_kind": features.recursion_kind,
        "has_sorting": features.has_sorting or features.has_sort_call,
        "has_log_pattern": features.has_log_pattern,
        "uncertainty_flags": features.uncertainty_flags[:12],
    }


def _conservative_complexity_from_features(rule_result: AnalysisResult) -> tuple[str, str]:
    if is_ranked_complexity(rule_result.complexity):
        return (
            rule_result.complexity or "O(n)",
            "Kept the rule-based ranked estimate.",
        )

    f = rule_result.features
    if f is None:
        return (
            "O(n)",
            "Used conservative linear fallback because block features are incomplete.",
        )

    if f.self_call_count >= 2 or f.recursion_kind == "multi_branch":
        return ("O(2^n)", "Branching recursion suggests exponential growth.")
    if f.has_recursion or f.self_call_count == 1:
        return ("O(n)", "Simple recursion is conservatively treated as linear.")
    if f.has_sorting or f.has_sort_call:
        return ("O(n log n)", "Sorting dominates visible work.")
    if f.max_loop_depth >= 3:
        return ("O(n^3)", "Three or more nested loops dominate visible work.")
    if f.max_loop_depth == 2:
        return ("O(n^2)", "Two nested loops dominate visible work.")
    if f.max_loop_depth == 1:
        return ("O(n)", "One visible loop gives a conservative linear estimate.")
    if f.container_operations:
        return (
            "O(n)",
            "Visible container operation may scan input, so linear fallback is used.",
        )
    if f.call_count or f.external_call_count or f.uncertainty_flags:
        return (
            "O(n)",
            "Unresolved calls are conservatively treated as linear work.",
        )
    return ("O(1)", "No loops, recursion, or costly operations are visible.")


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
                    "call": edge.call_name,
                    "complexity": kr.complexity,
                    "confidence": kr.confidence,
                }
            )
    return out[:12]


def build_llm_block_payload(
    block: CodeBlock,
    rule_result: AnalysisResult,
    dependency_graph: DependencyGraph | None = None,
    known_results: dict[str, AnalysisResult] | None = None,
) -> dict:
    features = rule_result.features or block.features
    return {
        "task": TASK_NAME,
        "lang": block.language_id,
        "kind": block.kind,
        "name": block.qualified_name or block.name,
        "signature": block.signature,
        "source": _source_excerpt(block),
        "features": _compact_features(features),
        "known_callees": _known_callee_costs(block, dependency_graph, known_results),
        "rule": {
            "complexity": rule_result.complexity,
            "confidence": rule_result.confidence,
            "summary": rule_result.reasoning_summary or rule_result.reason,
            "needs_human_review": rule_result.needs_human_review,
        },
        "instructions": (
            "Return compact JSON only. Choose a Big-O class whenever possible. "
            "Use unknown only for empty, broken, or non-code input."
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
    confidence = str(data.get("confidence", "medium")).strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"

    assumptions = [str(x) for x in data.get("assumptions", []) if x]
    advice = [str(x) for x in data.get("optimization_advice", []) if x]
    reasoning = str(data.get("reasoning_summary", "")).strip()
    if not reasoning:
        reasoning = rule_result.reasoning_summary or rule_result.reason

    duration_ms = None
    if telemetry and telemetry.get("total_duration") is not None:
        duration_ms = int(telemetry["total_duration"] // 1_000_000)

    needs_review = bool(data.get("needs_human_review", False))
    if not is_ranked_complexity(complexity):
        complexity, fallback_reason = _conservative_complexity_from_features(rule_result)
        confidence = "low"
        needs_review = True
        assumptions = assumptions + [fallback_reason]
        if reasoning:
            reasoning = f"{reasoning} {fallback_reason}"
        else:
            reasoning = fallback_reason

    return AnalysisResult(
        complexity=complexity,
        reason=reasoning,
        reasoning_summary=reasoning,
        confidence=confidence,
        assumptions=assumptions,
        optimization_advice=advice,
        analyzer_kind="llm",
        needs_human_review=needs_review,
        model_id=model_id,
        prompt_version=PROMPT_VERSION,
        features=rule_result.features,
        duration_ms=duration_ms,
    )


def ai_error_result(rule_result: AnalysisResult, message: str) -> AnalysisResult:
    complexity, fallback_reason = _conservative_complexity_from_features(rule_result)
    reasoning = f"AI fallback unavailable: {message}. {fallback_reason}"
    return AnalysisResult(
        complexity=complexity,
        reason=reasoning,
        reasoning_summary=reasoning,
        confidence="low",
        assumptions=list(rule_result.assumptions) + [fallback_reason],
        analyzer_kind="llm_error",
        needs_human_review=True,
        features=rule_result.features,
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
    check_available: bool = True,
) -> AnalysisResult:
    ollama = client or OllamaBigOClient(model=model, timeout_s=timeout_s, max_workers=1)
    if check_available and not ollama.is_available():
        return ai_error_result(rule_result, "Ollama is unavailable")

    payload = build_llm_block_payload(block, rule_result, dependency_graph, known_results)
    try:
        parsed, telemetry = ollama.chat_big_o_estimate(payload)
        return parse_llm_response_to_analysis_result(
            parsed,
            model_id=model,
            rule_result=rule_result,
            telemetry=telemetry,
        )
    except json.JSONDecodeError as exc:
        return ai_error_result(rule_result, f"invalid JSON from model: {exc}")
    except Exception as exc:  # noqa: BLE001
        return ai_error_result(rule_result, str(exc))
