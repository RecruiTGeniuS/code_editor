from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING

from .block_utils import is_analyzable_block
from .complexity_ops import call_cost_with_loops, is_call_inside_loop
from .rules import try_rule_patterns
from .dependency_graph import block_graph_id
from .models import (
    AnalysisResult,
    BlockFeatures,
    CodeBlock,
    is_ranked_complexity,
    max_complexity,
)

if TYPE_CHECKING:
    from .dependency_graph import DependencyGraph

_BRANCH_RE = re.compile(r"\b(if|elif|else)\b")
_SORT_RE = re.compile(r"\bsort(ed)?\s*\(|qsort\s*\(")
_LOG_RE = re.compile(r">>\s*1|/=\s*2|/2\b|mid\s*=|binary_search")
_DYNAMIC_TEXT_RE = re.compile(
    r"\b(eval|exec|getattr|globals|locals|__import__|compile)\s*\("
    r"|importlib\s*\.\s*import_module",
    re.IGNORECASE,
)

RULES_VERSION = "static-v9"


def _container_skip_result() -> AnalysisResult:
    return AnalysisResult(
        complexity="N/A",
        reason="Блок является контейнером и не оценивается напрямую.",
        reasoning_summary="Блок является контейнером и не оценивается напрямую.",
        confidence="high",
        analyzer_kind="none",
        needs_human_review=False,
        rules_version=RULES_VERSION,
    )


def analyze_block_static(
    block: CodeBlock,
    dependency_graph: DependencyGraph | None = None,
    known_results: dict[str, AnalysisResult] | None = None,
) -> AnalysisResult:
    """Rule-based анализ блока; опционально учитывает сложность callees из графа."""
    if not is_analyzable_block(block):
        return _container_skip_result()
    features = _build_analysis_features(block, dependency_graph, known_results)
    block.features = features
    local = _rule_analyze_local(block, features)
    result = _merge_with_project_callees(
        local, block, features, dependency_graph, known_results or {}
    )
    block.complexity = result.complexity
    block.reason = result.reason or result.reasoning_summary
    return result


def _build_analysis_features(
    block: CodeBlock,
    dependency_graph: DependencyGraph | None = None,
    known_results: dict[str, AnalysisResult] | None = None,
) -> BlockFeatures:
    code = block.source
    indexed = block.features
    known_results = known_results or {}

    has_log = bool(_LOG_RE.search(code)) or indexed.has_log_pattern
    has_sort = bool(_SORT_RE.search(code)) or indexed.has_sort_call
    self_calls = indexed.self_call_count or sum(
        1 for c in block.calls if c == block.name
    )

    uncertainty: list[str] = list(indexed.uncertainty_flags or [])
    if _DYNAMIC_TEXT_RE.search(code):
        uncertainty.append("dynamic_call:runtime_dispatch")
    call_summaries: list[dict] = []
    project_call_count = 0
    external_call_count = 0
    seen_calls: set[str] = set()
    bid = block_graph_id(block)

    index_calls_by_name: dict[str, list[dict]] = defaultdict(list)
    for cs in indexed.call_summaries or []:
        key = cs.get("call_name") or cs.get("name")
        if key:
            index_calls_by_name[key].append(dict(cs))

    if dependency_graph is not None:
        for edge in dependency_graph.get_callees(bid):
            seen_calls.add(edge.call_name)
            if edge.resolved and edge.target_block_id:
                kr = known_results.get(edge.target_block_id)
                callee_c = kr.complexity if kr else None
                entry: dict = {
                    "name": edge.call_name,
                    "call_name": edge.call_name,
                    "kind": "project",
                    "resolved": True,
                    "target_block_id": edge.target_block_id,
                }
                sites = index_calls_by_name.get(edge.call_name, [])
                if sites:
                    site = sites.pop(0)
                    entry.update(
                        start_line=site.get("start_line"),
                        end_line=site.get("end_line"),
                        start_byte=site.get("start_byte"),
                        end_byte=site.get("end_byte"),
                    )
                if is_ranked_complexity(callee_c):
                    entry["complexity"] = callee_c
                    project_call_count += 1
                else:
                    entry["complexity"] = None
                call_summaries.append(entry)
            else:
                external_call_count += 1
                uncertainty.append(f"unresolved_call:{edge.call_name}")
                entry = {
                    "name": edge.call_name,
                    "call_name": edge.call_name,
                    "kind": "external",
                    "resolved": False,
                }
                sites = index_calls_by_name.get(edge.call_name, [])
                if sites:
                    entry.update(sites.pop(0))
                call_summaries.append(entry)

    for name in block.calls:
        if name in seen_calls or name == block.name:
            continue
        kind = "self" if name == block.name else "unknown"
        entry = {"name": name, "call_name": name, "kind": kind}
        sites = index_calls_by_name.get(name, [])
        if sites:
            entry.update(sites.pop(0))
        call_summaries.append(entry)
        if kind != "self":
            external_call_count += 1
            uncertainty.append(f"unknown_call:{name}")

    loop_summaries: list[dict] = [
        dict(ls)
        for ls in (indexed.loop_summaries or [])
        if ls.get("start_line") is not None
    ]
    if not loop_summaries and indexed.loop_count > 0:
        loop_summaries.append(
            {
                "count": indexed.loop_count,
                "max_depth": indexed.max_loop_depth,
            }
        )

    recursion_kind: str | None = None
    has_recursion = self_calls >= 1
    if dependency_graph is not None and bid in getattr(dependency_graph, "recursive_block_ids", set()):
        has_recursion = True
        recursion_kind = "mutual"
    if self_calls >= 2:
        recursion_kind = "multi_branch"
    elif self_calls == 1:
        recursion_kind = "linear"

    call_count = len(block.calls)
    if (
        call_count >= 3
        and indexed.max_loop_depth == 0
        and not has_recursion
        and project_call_count == 0
    ):
        uncertainty.append("many_calls_no_loops")

    return BlockFeatures(
        loop_count=indexed.loop_count,
        max_loop_depth=indexed.max_loop_depth,
        branch_count=len(_BRANCH_RE.findall(code)),
        call_count=call_count,
        project_call_count=project_call_count,
        external_call_count=external_call_count,
        has_recursion=has_recursion,
        recursion_kind=recursion_kind,
        has_sorting=has_sort,
        has_log_pattern=has_log,
        has_sort_call=has_sort,
        self_call_count=self_calls,
        container_operations=list(indexed.container_operations),
        loop_summaries=loop_summaries,
        call_summaries=call_summaries,
        branch_summaries=list(indexed.branch_summaries),
        import_summaries=list(indexed.import_summaries),
        defined_symbols=list(indexed.defined_symbols),
        local_symbols=list(indexed.local_symbols),
        parameters=list(indexed.parameters),
        uncertainty_flags=sorted(set(uncertainty)),
    )


def _result(
    *,
    complexity: str | None,
    reasoning: str,
    confidence: str,
    assumptions: list[str],
    features: BlockFeatures,
    needs_human_review: bool = False,
) -> AnalysisResult:
    return AnalysisResult(
        complexity=complexity,
        reason=reasoning,
        reasoning_summary=reasoning,
        confidence=confidence,
        assumptions=assumptions,
        analyzer_kind="rule",
        needs_human_review=needs_human_review,
        features=features,
        rules_version=RULES_VERSION,
    )


def _has_dynamic_or_invalid_syntax(f: BlockFeatures) -> bool:
    return any(
        flag == "syntax_error" or flag.startswith("dynamic_call:")
        for flag in f.uncertainty_flags
    )


def _opaque_call_names(f: BlockFeatures) -> list[str]:
    names: list[str] = []
    for flag in f.uncertainty_flags:
        if flag.startswith(("unknown_call:", "unresolved_call:")):
            names.append(flag.split(":", 1)[1])
    return names


def _has_opaque_call_inside_loop(f: BlockFeatures) -> bool:
    for call in f.call_summaries:
        if call.get("kind") not in {"external", "unknown"}:
            continue
        if call.get("is_builtin_like"):
            continue
        try:
            depth = int(call.get("inside_loop_depth") or 0)
        except (TypeError, ValueError):
            depth = 0
        if depth > 0:
            return True
    return False


def _needs_ai_before_static_rules(f: BlockFeatures) -> bool:
    return _has_dynamic_or_invalid_syntax(f)


def _needs_ai_after_static_rules(f: BlockFeatures) -> bool:
    if _has_dynamic_or_invalid_syntax(f):
        return True
    flags = set(f.uncertainty_flags)
    if "loop_bound_unknown" in flags and f.max_loop_depth > 0:
        return True
    if _has_opaque_call_inside_loop(f):
        return True
    opaque_calls = _opaque_call_names(f)
    if f.max_loop_depth == 0 and not f.has_recursion and len(opaque_calls) >= 3:
        return True
    return False


def _uncertain_external_result(
    f: BlockFeatures, base_assumptions: list[str]
) -> AnalysisResult:
    flags = sorted(set(f.uncertainty_flags + ["needs_ai_or_human"]))
    enriched = BlockFeatures(
        loop_count=f.loop_count,
        max_loop_depth=f.max_loop_depth,
        branch_count=f.branch_count,
        call_count=f.call_count,
        project_call_count=f.project_call_count,
        external_call_count=f.external_call_count,
        has_recursion=f.has_recursion,
        recursion_kind=f.recursion_kind,
        has_sorting=f.has_sorting,
        has_log_pattern=f.has_log_pattern,
        has_sort_call=f.has_sort_call,
        self_call_count=f.self_call_count,
        container_operations=list(f.container_operations),
        loop_summaries=list(f.loop_summaries),
        call_summaries=list(f.call_summaries),
        branch_summaries=list(f.branch_summaries),
        import_summaries=list(f.import_summaries),
        defined_symbols=list(f.defined_symbols),
        local_symbols=list(f.local_symbols),
        parameters=list(f.parameters),
        uncertainty_flags=flags,
    )
    return AnalysisResult(
        complexity="unknown",
        reason="Block contains unresolved or dynamic behavior; AI fallback should estimate it.",
        reasoning_summary="Block contains unresolved or dynamic behavior; AI fallback should estimate it.",
        confidence="low",
        assumptions=base_assumptions,
        analyzer_kind="rule",
        needs_human_review=True,
        features=enriched,
        rules_version=RULES_VERSION,
    )


def _rule_analyze_local(block: CodeBlock, f: BlockFeatures) -> AnalysisResult:
    name_l = (block.name or "").lower()
    base_assumptions = [
        "Размер входа обозначен как n.",
        "Вложенные циклы итерируют по тем же n, если не указано иное.",
    ]

    if f.self_call_count >= 1 and ("factorial" in name_l or "permut" in name_l):
        return _result(
            complexity="O(n!)",
            reasoning="Рекурсия с шаблоном factorial/permutation.",
            confidence="medium",
            assumptions=base_assumptions
            + ["Рекурсия соответствует факториальному шаблону по имени."],
            features=f,
        )

    if f.self_call_count >= 2:
        return _result(
            complexity="O(2^n)",
            reasoning="Две и более рекурсивных ветки self-call.",
            confidence="high",
            assumptions=base_assumptions
            + ["Каждая рекурсивная ветка удваивает пространство вызовов."],
            features=f,
        )

    if _needs_ai_before_static_rules(f):
        return _uncertain_external_result(f, base_assumptions)

    pattern = try_rule_patterns(block, f)
    if pattern is not None:
        flags = sorted(set(f.uncertainty_flags + pattern.uncertainty_flags))
        pf = BlockFeatures(
            loop_count=f.loop_count,
            max_loop_depth=f.max_loop_depth,
            branch_count=f.branch_count,
            call_count=f.call_count,
            project_call_count=f.project_call_count,
            external_call_count=f.external_call_count,
            has_recursion=f.has_recursion,
            recursion_kind=f.recursion_kind,
            has_sorting=f.has_sorting,
            has_log_pattern=f.has_log_pattern,
            has_sort_call=f.has_sort_call,
            self_call_count=f.self_call_count,
            container_operations=list(f.container_operations),
            loop_summaries=list(f.loop_summaries),
            call_summaries=list(f.call_summaries),
            branch_summaries=list(f.branch_summaries),
            import_summaries=list(f.import_summaries),
            defined_symbols=list(f.defined_symbols),
            local_symbols=list(f.local_symbols),
            parameters=list(f.parameters),
            uncertainty_flags=flags,
        )
        return _result(
            complexity=pattern.complexity,
            reasoning=pattern.reasoning,
            confidence=pattern.confidence,
            assumptions=base_assumptions + pattern.assumptions,
            features=pf,
        )

    if _needs_ai_after_static_rules(f):
        return _uncertain_external_result(f, base_assumptions)

    if f.max_loop_depth >= 3:
        return _result(
            complexity="O(n^3)",
            reasoning=f"Вложенность циклов: {f.max_loop_depth}.",
            confidence="high",
            assumptions=base_assumptions,
            features=f,
        )

    if f.max_loop_depth == 2:
        return _result(
            complexity="O(n^2)",
            reasoning="Два вложенных цикла.",
            confidence="high",
            assumptions=base_assumptions,
            features=f,
        )

    if f.max_loop_depth == 1:
        if f.has_sorting or f.has_log_pattern:
            return _result(
                complexity="O(n log n)",
                reasoning="Один цикл + log/sort паттерн.",
                confidence="medium",
                assumptions=base_assumptions
                + ["Операция sort/log внутри одного цикла доминирует как n log n."],
                features=f,
            )
        if f.has_log_pattern:
            return _result(
                complexity="O(log n)",
                reasoning="Обнаружен логарифмический паттерн (деление диапазона).",
                confidence="medium",
                assumptions=base_assumptions,
                features=f,
            )
        return _result(
            complexity="O(n)",
            reasoning="Один линейный цикл.",
            confidence="high",
            assumptions=base_assumptions,
            features=f,
        )

    if f.self_call_count == 1:
        if f.has_log_pattern:
            return _result(
                complexity="O(log n)",
                reasoning="Одиночная рекурсия с уменьшением задачи.",
                confidence="medium",
                assumptions=base_assumptions + ["Рекурсия делит задачу логарифмически."],
                features=f,
            )
        return _result(
            complexity="O(n)",
            reasoning="Одиночная линейная рекурсия.",
            confidence="medium",
            assumptions=base_assumptions + ["Один self-call на проход."],
            features=f,
        )

    if f.has_sorting:
        return _result(
            complexity="O(n log n)",
            reasoning="Обнаружен вызов sort/sorted/qsort.",
            confidence="high",
            assumptions=base_assumptions + ["Доминирует стандартная сортировка."],
            features=f,
        )

    if f.call_count >= 3 and "many_calls_no_loops" in f.uncertainty_flags:
        return _uncertain_many_calls(f, base_assumptions)

    return _result(
        complexity="O(1)",
        reasoning="Нет циклов, рекурсии и log/sort паттернов (локально).",
        confidence="high",
        assumptions=base_assumptions,
        features=f,
    )


def _merge_with_project_callees(
    local: AnalysisResult,
    block: CodeBlock,
    features: BlockFeatures,
    dependency_graph: DependencyGraph | None,
    known_results: dict[str, AnalysisResult],
) -> AnalysisResult:
    if local.needs_human_review or local.complexity is None:
        return local
    if dependency_graph is None:
        summary = (
            f"{local.reasoning_summary} "
            "(итог по локальным конструкциям блока)."
        )
        return _result(
            complexity=local.complexity,
            reasoning=summary,
            confidence=local.confidence,
            assumptions=list(local.assumptions),
            features=features,
            needs_human_review=False,
        )

    bid = block_graph_id(block)
    final_c = local.complexity
    assumptions = list(local.assumptions) + [
        "Итерации внешнего цикла считаются линейными по размеру входа n.",
        "Сложность вызываемой функции взята из результата анализа project graph.",
    ]
    callee_notes: list[str] = []
    unresolved_count = 0
    has_while_enclosure = False
    flags = list(features.uncertainty_flags)

    loop_summaries = [
        ls for ls in features.loop_summaries if ls.get("start_line") is not None
    ]
    calls_by_name = {
        (cs.get("call_name") or cs.get("name")): cs
        for cs in features.call_summaries
        if cs.get("kind") == "project"
    }

    for edge in dependency_graph.get_callees(bid):
        if edge.resolved and edge.target_block_id:
            kr = known_results.get(edge.target_block_id)
            callee_c = kr.complexity if kr else None
            if not is_ranked_complexity(callee_c):
                continue
            call_info = calls_by_name.get(edge.call_name) or {"call_name": edge.call_name}
            call_cost, detail, while_unc = call_cost_with_loops(
                callee_c, call_info, loop_summaries
            )
            if while_unc:
                has_while_enclosure = True
                if "while_loop_bound_unknown" not in flags:
                    flags.append("while_loop_bound_unknown")
            if call_cost is None:
                if "complexity_multiply_unknown" not in flags:
                    flags.append("complexity_multiply_unknown")
            else:
                final_c = max_complexity(final_c, call_cost)
                callee_notes.append(detail)
                assumptions.append(
                    f"Сложность вызова {edge.call_name} учтена по результату "
                    f"анализа блока {edge.call_name}: {callee_c}"
                )
        else:
            unresolved_count += 1

    reasoning = local.reasoning_summary
    if callee_notes:
        reasoning += "; " + "; ".join(callee_notes)
    reasoning += "; итог: max(локальная сложность, стоимость project-вызовов с учётом циклов)."

    confidence = local.confidence
    if unresolved_count >= 2:
        confidence = "low"
    elif unresolved_count >= 1 and confidence == "high":
        confidence = "medium"
    elif has_while_enclosure and confidence == "high":
        confidence = "medium"

    flags = sorted(set(flags))

    enriched = BlockFeatures(
        loop_count=features.loop_count,
        max_loop_depth=features.max_loop_depth,
        branch_count=features.branch_count,
        call_count=features.call_count,
        project_call_count=features.project_call_count,
        external_call_count=features.external_call_count,
        has_recursion=features.has_recursion,
        recursion_kind=features.recursion_kind,
        has_sorting=features.has_sorting,
        has_log_pattern=features.has_log_pattern,
        has_sort_call=features.has_sort_call,
        self_call_count=features.self_call_count,
        container_operations=list(features.container_operations),
        loop_summaries=list(features.loop_summaries),
        call_summaries=list(features.call_summaries),
        branch_summaries=list(features.branch_summaries),
        import_summaries=list(features.import_summaries),
        defined_symbols=list(features.defined_symbols),
        local_symbols=list(features.local_symbols),
        parameters=list(features.parameters),
        uncertainty_flags=sorted(set(flags)),
    )

    return _result(
        complexity=final_c,
        reasoning=reasoning,
        confidence=confidence,
        assumptions=assumptions,
        features=enriched,
        needs_human_review=False,
    )


def _uncertain_many_calls(
    f: BlockFeatures, base_assumptions: list[str]
) -> AnalysisResult:
    flags = list(f.uncertainty_flags)
    if "needs_ai_or_human" not in flags:
        flags.append("needs_ai_or_human")
    enriched = BlockFeatures(
        loop_count=f.loop_count,
        max_loop_depth=f.max_loop_depth,
        branch_count=f.branch_count,
        call_count=f.call_count,
        project_call_count=f.project_call_count,
        external_call_count=f.external_call_count,
        has_recursion=f.has_recursion,
        recursion_kind=f.recursion_kind,
        has_sorting=f.has_sorting,
        has_log_pattern=f.has_log_pattern,
        has_sort_call=f.has_sort_call,
        self_call_count=f.self_call_count,
        container_operations=list(f.container_operations),
        loop_summaries=list(f.loop_summaries),
        call_summaries=list(f.call_summaries),
        branch_summaries=list(f.branch_summaries),
        import_summaries=list(f.import_summaries),
        defined_symbols=list(f.defined_symbols),
        local_symbols=list(f.local_symbols),
        parameters=list(f.parameters),
        uncertainty_flags=flags,
    )
    return AnalysisResult(
        complexity="unknown",
        reason="Много вызовов без явных циклов; требуется контекст.",
        reasoning_summary="Много вызовов без явных циклов; требуется контекст.",
        confidence="low",
        assumptions=base_assumptions + ["Сложность зависит от неизвестных callees."],
        analyzer_kind="rule",
        needs_human_review=True,
        features=enriched,
        rules_version=RULES_VERSION,
    )
