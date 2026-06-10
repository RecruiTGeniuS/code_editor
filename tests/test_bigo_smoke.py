"""
Smoke-тесты подсистемы bigo (текущая версия статического анализа и индекса).

Не проверяют GUI/Qt. При смене эвристик в static_analyzer.py ожидания могут
потребовать обновления — это намеренно: тесты фиксируют поведение «как есть».
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from bigo.block_utils import analyzable_blocks, is_analyzable_block
from bigo.cache import BlockComplexityCache
from bigo.dependency_graph import (
    block_graph_id,
    build_dependency_graph,
    topological_blocks,
)
from bigo.complexity_ops import multiply_complexities
from bigo.models import BIG_O_CLASSES, AnalysisResult, BlockFeatures
from bigo.overlay_model import to_monaco_decorations
from bigo.project_index import build_index
from bigo.review import build_project_review
from bigo.static_analyzer import analyze_block_static

FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures"

EXPECTED_FIXTURE_NAMES = {
    "simple_loop.py",
    "nested_loop.py",
    "sorting_example.py",
    "recursion_example.py",
}


def _blocks_for_file(blocks_by_file: dict, filename: str) -> list:
    suffix = os.path.normcase(filename)
    for path, blocks in blocks_by_file.items():
        if os.path.normcase(path).endswith(suffix):
            return blocks
    return []


def _function_block(blocks, name: str):
    for b in blocks:
        if b.name == name and not b.is_container:
            return b
    pytest.fail(f"function {name!r} not found among {[b.name for b in blocks]}")


def _block_by_qualified(blocks, qualified_name: str):
    for b in blocks:
        if b.qualified_name == qualified_name:
            return b
    pytest.fail(
        f"block {qualified_name!r} not found among "
        f"{[b.qualified_name for b in blocks]}"
    )


def _analyze_named(filename: str, func_name: str) -> AnalysisResult:
    _, blocks_by_file, _ = build_index(str(FIXTURES_ROOT.resolve()))
    blocks = _blocks_for_file(blocks_by_file, filename)
    assert blocks, f"no blocks indexed for {filename}"
    block = _function_block(blocks, func_name)
    result = analyze_block_static(block)
    assert result.features is not None
    assert result.analyzer_kind == "rule"
    assert result.confidence in {"high", "medium", "low"}
    return result


def _assert_confident_rule_result(result: AnalysisResult, expected_complexity: str):
    assert result.complexity == expected_complexity
    assert result.needs_human_review is False
    assert result.confidence in {"high", "medium"}
    assert result.features is not None


@pytest.fixture(scope="module")
def fixture_index():
    files, blocks_by_file, all_blocks = build_index(str(FIXTURES_ROOT.resolve()))
    return files, blocks_by_file, all_blocks


def test_build_index_finds_python_functions(fixture_index):
    files, blocks_by_file, all_blocks = fixture_index
    basenames = {os.path.basename(p) for p in files}
    assert EXPECTED_FIXTURE_NAMES <= basenames

    for fname in EXPECTED_FIXTURE_NAMES:
        blocks = _blocks_for_file(blocks_by_file, fname)
        assert len(blocks) >= 1, fname
        assert any(b.kind in ("function", "method") for b in blocks), fname

    assert len(all_blocks) >= len(EXPECTED_FIXTURE_NAMES)


def test_index_enriches_codeblock_metadata(fixture_index):
    _, blocks_by_file, _ = fixture_index
    block = _function_block(_blocks_for_file(blocks_by_file, "simple_loop.py"), "sum_array")
    assert block.stable_id
    assert block.qualified_name == "sum_array"
    assert block.start_byte is not None
    assert block.end_byte is not None
    assert block.end_byte > block.start_byte
    assert block.kind == "function"


def test_container_skipped_from_rule_analysis_and_overlay():
    _, blocks_by_file, all_blocks = build_index(str(FIXTURES_ROOT.resolve()))
    blocks = _blocks_for_file(blocks_by_file, "class_example.py")
    cls = _block_by_qualified(blocks, "DataProcessor")
    method = _block_by_qualified(blocks, "DataProcessor.process_items")

    assert is_analyzable_block(method)
    assert not is_analyzable_block(cls)

    cls_result = analyze_block_static(cls)
    assert cls_result.complexity == "N/A"
    assert cls_result.analyzer_kind == "none"
    assert cls_result.complexity not in BIG_O_CLASSES

    method_result = analyze_block_static(method)
    assert method_result.complexity == "O(n)"
    assert method_result.analyzer_kind == "rule"

    cls.complexity = "O(n^2)"
    method.complexity = method_result.complexity
    method.reason = method_result.reasoning_summary
    rows = to_monaco_decorations([cls, method])
    assert len(rows) == 1
    assert rows[0]["label"] == "O(n)"


def test_project_review_uses_analyzable_blocks_only():
    _, blocks_by_file, _ = build_index(str(FIXTURES_ROOT.resolve()))
    blocks = _blocks_for_file(blocks_by_file, "class_example.py")
    for block in analyzable_blocks(blocks):
        result = analyze_block_static(block)
        if result.complexity and result.complexity in BIG_O_CLASSES:
            block.complexity = result.complexity
            block.reason = result.reasoning_summary

    review = build_project_review(blocks, None)
    assert "Проанализировано функций/методов: 1" in review
    assert "контейнеров" in review
    assert "DataProcessor" in review
    cls = _block_by_qualified(blocks, "DataProcessor")
    assert cls.complexity is None or cls.complexity not in BIG_O_CLASSES


def _analyze_fixture_in_topo_order(blocks):
    graph = build_dependency_graph(blocks)
    known_results: dict[str, AnalysisResult] = {}
    by_name: dict[str, AnalysisResult] = {}
    for block in topological_blocks(blocks, graph):
        result = analyze_block_static(block, graph, known_results)
        known_results[block_graph_id(block)] = result
        by_name[block.name] = result
    return graph, by_name


def test_multiply_complexities_algebra():
    assert multiply_complexities("O(n)", "O(n)") == "O(n^2)"
    assert multiply_complexities("O(n)", "O(n^2)") == "O(n^3)"
    assert multiply_complexities("O(n)", "O(n log n)") == "O(n^2 log n)"
    assert multiply_complexities("O(1)", "O(n)") == "O(n)"


def test_rule_patterns_examples():
    _, blocks_by_file, _ = build_index(str(FIXTURES_ROOT.resolve()))
    blocks = _blocks_for_file(blocks_by_file, "patterns_example.py")
    graph = build_dependency_graph(blocks)
    known: dict[str, AnalysisResult] = {}
    by_name: dict[str, AnalysisResult] = {}
    for block in topological_blocks(blocks, graph):
        r = analyze_block_static(block, graph, known)
        known[block_graph_id(block)] = r
        by_name[block.name] = r

    assert by_name["binary_search"].complexity == "O(log n)"
    assert by_name["two_sum_sorted"].complexity == "O(n)"
    assert by_name["sliding_window_sum"].complexity == "O(n)"
    assert by_name["sort_then_scan"].complexity == "O(n log n)"
    assert by_name["dependent_nested_loop"].complexity == "O(n^2)"

    for name in (
        "binary_search",
        "two_sum_sorted",
        "sliding_window_sum",
        "sort_then_scan",
        "dependent_nested_loop",
    ):
        r = by_name[name]
        assert r.analyzer_kind == "rule"
        assert r.confidence in {"high", "medium", "low"}
        assert r.reasoning_summary


def test_dependency_graph_edges_calls_example():
    _, blocks_by_file, _ = build_index(str(FIXTURES_ROOT.resolve()))
    blocks = _blocks_for_file(blocks_by_file, "calls_example.py")
    graph = build_dependency_graph(blocks)
    main_lin = _function_block(blocks, "main_linear")
    helper_lin = _function_block(blocks, "helper_linear")
    main_unk = _function_block(blocks, "main_unknown")

    lin_edge = graph.get_callees(block_graph_id(main_lin))[0]
    assert lin_edge.call_name == "helper_linear"
    assert lin_edge.resolved is True
    assert lin_edge.target_block_id == block_graph_id(helper_lin)

    unk_edges = [e for e in graph.get_callees(block_graph_id(main_unk)) if e.call_name == "external_func"]
    assert len(unk_edges) == 1
    assert unk_edges[0].resolved is False


def test_call_inside_loop_complexity():
    _, blocks_by_file, _ = build_index(str(FIXTURES_ROOT.resolve()))
    blocks = _blocks_for_file(blocks_by_file, "call_inside_loop_example.py")
    _, results = _analyze_fixture_in_topo_order(blocks)

    assert results["helper_linear"].complexity == "O(n)"
    assert results["helper_quadratic"].complexity == "O(n^2)"
    assert results["main_direct"].complexity == "O(n)"
    assert results["main_loop_linear"].complexity == "O(n^2)"
    assert results["main_loop_quadratic"].complexity == "O(n^3)"

    main_lin = results["main_loop_linear"]
    assert main_lin.confidence in {"high", "medium"}
    assert "helper_linear" in main_lin.reasoning_summary
    assert "внутри цикла" in main_lin.reasoning_summary or "×" in main_lin.reasoning_summary
    project_calls = [
        cs for cs in main_lin.features.call_summaries if cs.get("kind") == "project"
    ]
    assert any(cs.get("resolved") for cs in project_calls)


def test_callee_complexity_propagation_calls_example():
    _, blocks_by_file, _ = build_index(str(FIXTURES_ROOT.resolve()))
    blocks = _blocks_for_file(blocks_by_file, "calls_example.py")
    _, results = _analyze_fixture_in_topo_order(blocks)

    assert results["helper_linear"].complexity == "O(n)"
    assert results["main_linear"].complexity == "O(n)"
    assert results["helper_quadratic"].complexity == "O(n^2)"
    assert results["main_quadratic"].complexity == "O(n^2)"
    assert "unresolved_call:external_func" in results["main_unknown"].features.uncertainty_flags


def test_review_mentions_dependency_graph_stats():
    _, blocks_by_file, _ = build_index(str(FIXTURES_ROOT.resolve()))
    blocks = _blocks_for_file(blocks_by_file, "calls_example.py")
    graph = build_dependency_graph(blocks)
    review = build_project_review(blocks, None, graph)
    assert "Граф вызовов" in review
    assert str(graph.resolved_count) in review
    assert "resolved-вызовов" in review or "между блоками" in review


def test_class_fixture_container_and_method_qualified_name():
    _, blocks_by_file, _ = build_index(str(FIXTURES_ROOT.resolve()))
    blocks = _blocks_for_file(blocks_by_file, "class_example.py")
    cls = _block_by_qualified(blocks, "DataProcessor")
    assert cls.is_container is True
    assert cls.kind == "class"
    method = _block_by_qualified(blocks, "DataProcessor.process_items")
    assert method.is_container is False
    assert method.kind in ("function", "method")
    assert method.stable_id
    assert method.parent_block_id == cls.stable_id


def test_simple_loop_linear():
    result = _analyze_named("simple_loop.py", "sum_array")
    _assert_confident_rule_result(result, "O(n)")


def test_nested_loop_quadratic():
    result = _analyze_named("nested_loop.py", "count_pairs")
    _assert_confident_rule_result(result, "O(n^2)")


def test_sorting_n_log_n():
    result = _analyze_named("sorting_example.py", "sort_values")
    _assert_confident_rule_result(result, "O(n log n)")


def test_recursion_linear_smoke():
    result = _analyze_named("recursion_example.py", "walk_down")
    assert result.complexity in {"O(n)", "O(log n)"}
    assert result.needs_human_review is False
    assert result.features is not None
    assert result.features.has_recursion is True


def test_many_calls_uncertain():
    result = _analyze_named("many_calls.py", "orchestrate")
    assert result.complexity == "unknown"
    assert result.needs_human_review is True
    assert result.confidence == "low"
    assert "many_calls_no_loops" in result.features.uncertainty_flags


def test_block_features_import_and_defaults():
    f = BlockFeatures()
    assert f.loop_count == 0
    assert f.has_sort_call is False
    assert f.self_call_count == 0
    assert f.has_sorting is False
    assert f.uncertainty_flags == []


def test_analysis_result_metadata_from_static():
    result = _analyze_named("simple_loop.py", "sum_array")
    assert result.complexity == "O(n)"
    assert result.confidence == "high"
    assert result.analyzer_kind == "rule"
    assert result.needs_human_review is False
    assert result.is_uncertain() is False
    assert result.short_label() == "O(n)"
    assert result.reasoning_summary


def test_block_complexity_cache_roundtrip():
    _, blocks_by_file, _ = build_index(str(FIXTURES_ROOT.resolve()))
    block = _function_block(_blocks_for_file(blocks_by_file, "simple_loop.py"), "sum_array")
    result = analyze_block_static(block)
    block.complexity = result.complexity
    block.reason = result.reason or result.reasoning_summary
    block.source_kind = "static"

    with tempfile.TemporaryDirectory() as tmp:
        cache_path = os.path.join(tmp, ".bigo_cache.json")
        cache = BlockComplexityCache(cache_path)
        cache.upsert(block)
        cache.save()

        fresh = BlockComplexityCache(cache_path)
        probe = _function_block(
            _blocks_for_file(
                build_index(str(FIXTURES_ROOT.resolve()))[1],
                "simple_loop.py",
            ),
            "sum_array",
        )
        assert fresh.try_apply(probe) is True
        assert probe.complexity == result.complexity
        assert probe.source_kind == "cache"
        assert probe.source_hash == block.source_hash
