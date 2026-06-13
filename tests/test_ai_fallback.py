"""Тесты AI fallback без реального Ollama."""

from __future__ import annotations

import json
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from bigo.ai_fallback import (
    build_llm_block_payload,
    estimate_with_ai,
    needs_ai_fallback,
    parse_llm_response_to_analysis_result,
)
from bigo.llm_contract import extract_json_object
from bigo.models import AnalysisResult, BlockFeatures
from bigo.models import CodeBlock


def _sample_block() -> CodeBlock:
    return CodeBlock(
        block_id="f.py#0",
        file_path="f.py",
        language_id="python",
        kind="function",
        name="orchestrate",
        start_line=1,
        end_line=6,
        source="def orchestrate(a, b, c):\n    return a + b + c\n",
        source_hash="abc",
        calls=["helper_one", "helper_two", "helper_three"],
        features=BlockFeatures(uncertainty_flags=["many_calls_no_loops"]),
    )


def test_needs_ai_fallback_flags():
    assert needs_ai_fallback(
        AnalysisResult(complexity=None, needs_human_review=True)
    )
    assert needs_ai_fallback(
        AnalysisResult(complexity="unknown", confidence="low")
    )
    assert needs_ai_fallback(
        AnalysisResult(complexity="O(n)", confidence="low")
    )
    assert not needs_ai_fallback(
        AnalysisResult(complexity="O(n)", confidence="high")
    )


def test_build_llm_block_payload_structure():
    block = _sample_block()
    rule = AnalysisResult(
        complexity=None,
        confidence="low",
        reasoning_summary="Много вызовов",
        needs_human_review=True,
        features=block.features,
    )
    payload = build_llm_block_payload(block, rule)
    assert payload["task"] == "estimate_upper_bound_big_o"
    assert payload["name"] == "orchestrate"
    assert payload["rule"]["needs_human_review"] is True
    assert "instructions" in payload
    assert "source" in payload
    assert "unknown" in payload["instructions"]


def test_parse_valid_llm_json():
    data = {
        "complexity": "O(n^2)",
        "variables": ["n"],
        "assumptions": ["Внешний цикл линейный"],
        "reasoning_summary": "Два вложенных цикла",
        "confidence": "medium",
        "needs_human_review": False,
        "optimization_advice": ["Рассмотреть кэш"],
    }
    result = parse_llm_response_to_analysis_result(
        data, model_id="test-model", rule_result=AnalysisResult()
    )
    assert result.complexity == "O(n^2)"
    assert result.analyzer_kind == "llm"
    assert result.confidence == "medium"
    assert result.optimization_advice == ["Рассмотреть кэш"]
    assert result.model_id == "test-model"
    assert result.prompt_version == "v3-forced-estimate"


def test_parse_unknown_llm_json_gets_conservative_estimate():
    rule = AnalysisResult(
        complexity="unknown",
        confidence="low",
        features=BlockFeatures(call_count=2, external_call_count=2),
    )
    result = parse_llm_response_to_analysis_result(
        {
            "complexity": "unknown",
            "confidence": "low",
            "needs_human_review": True,
            "reasoning_summary": "dynamic calls",
        },
        model_id="test-model",
        rule_result=rule,
    )
    assert result.complexity == "O(n)"
    assert result.confidence == "low"
    assert result.needs_human_review is True


def test_extract_json_from_markdown_fence():
    text = '```json\n{"complexity":"O(n)","confidence":"high","variables":[],"assumptions":[],"reasoning_summary":"ok","needs_human_review":false,"optimization_advice":[]}\n```'
    row = extract_json_object(text)
    assert row["complexity"] == "O(n)"


def test_parse_invalid_json_returns_error_result():
    block = _sample_block()
    rule = AnalysisResult(
        complexity=None,
        needs_human_review=True,
        features=block.features,
    )
    client = MagicMock()
    client.is_available.return_value = True
    client.chat_big_o_estimate.side_effect = json.JSONDecodeError("err", "x", 0)

    result = estimate_with_ai(block, rule, client=client)
    assert result.analyzer_kind == "llm_error"
    assert result.needs_human_review is True
    assert "невалидный JSON" in result.reasoning_summary or "JSON" in result.reasoning_summary


def test_estimate_with_ai_success_mock():
    block = _sample_block()
    rule = AnalysisResult(
        complexity=None,
        confidence="low",
        needs_human_review=True,
        features=block.features,
    )
    client = MagicMock()
    client.is_available.return_value = True
    client.chat_big_o_estimate.return_value = (
        {
            "complexity": "O(n)",
            "variables": ["n"],
            "assumptions": [],
            "reasoning_summary": "Линейный проход по вызовам",
            "confidence": "medium",
            "needs_human_review": False,
            "optimization_advice": [],
        },
        {"total_duration": 5_000_000_000},
    )

    result = estimate_with_ai(block, rule, client=client, model="test-model")
    assert result.analyzer_kind == "llm"
    assert result.complexity == "O(n)"
    client.chat_big_o_estimate.assert_called_once()


def test_ai_fallback_only_when_flagged():
    """needs_ai_fallback — единственный триггер для очереди AI в orchestrator."""
    ok = AnalysisResult(complexity="O(n)", confidence="high")
    bad = AnalysisResult(complexity="O(n)", confidence="low")
    assert not needs_ai_fallback(ok)
    assert needs_ai_fallback(bad)


def test_rule_unknown_for_uncertain_many_calls():
    from bigo.static_analyzer import analyze_block_static

    block = _sample_block()
    result = analyze_block_static(block)
    assert result.complexity == "unknown"
    assert result.confidence == "low"
    assert result.needs_human_review is True


def test_decoration_label_llm_marker():
    from bigo.overlay_model import decoration_label, to_monaco_decorations

    block = _sample_block()
    block.complexity = "O(n^2)"
    block.source_kind = "llm"
    assert "AI" in decoration_label(block)
    rows = to_monaco_decorations([block])
    assert rows[0]["label"] == "O(n^2) · AI"


@patch("bigo.orchestrator.OllamaBigOClient")
@patch("bigo.orchestrator.build_project_review", return_value="ok")
@patch("bigo.orchestrator.topological_blocks")
@patch("bigo.orchestrator.build_dependency_graph")
@patch("bigo.orchestrator.build_index")
@patch("bigo.orchestrator.estimate_with_ai")
@patch("bigo.orchestrator.analyze_block_static")
def test_orchestrator_use_ai_false_keeps_unknown(
    mock_static,
    mock_ai,
    mock_build_index,
    mock_build_graph,
    mock_topo,
    _mock_review,
    _mock_ollama_cls,
):
    from bigo.orchestrator import BigOOrchestrator

    block = _sample_block()
    mock_build_index.return_value = (["f.py"], {"f.py": [block]}, [block])
    mock_build_graph.return_value = MagicMock()
    mock_topo.return_value = [block]
    mock_static.return_value = AnalysisResult(
        complexity=None,
        needs_human_review=True,
        confidence="low",
    )
    orch = BigOOrchestrator(use_ai=False)
    orch._generation = 1
    with tempfile.TemporaryDirectory() as tmp:
        orch._run(1, tmp)
    assert block.complexity == "unknown"
    assert block.source_kind == "static"
    mock_ai.assert_not_called()


@patch("bigo.orchestrator.OllamaBigOClient")
@patch("bigo.orchestrator.build_project_review", return_value="ok")
@patch("bigo.orchestrator.topological_blocks")
@patch("bigo.orchestrator.build_dependency_graph")
@patch("bigo.orchestrator.build_index")
@patch("bigo.orchestrator.estimate_with_ai")
@patch("bigo.orchestrator.analyze_block_static")
def test_orchestrator_use_ai_true_calls_ai_only_for_uncertain(
    mock_static,
    mock_ai,
    mock_build_index,
    mock_build_graph,
    mock_topo,
    _mock_review,
    mock_ollama_cls,
):
    mock_ollama_cls.return_value.is_available.return_value = True
    from bigo.orchestrator import BigOOrchestrator

    uncertain = _sample_block()
    confident = CodeBlock(
        block_id="f.py#1",
        file_path="f.py",
        language_id="python",
        kind="function",
        name="stable",
        start_line=10,
        end_line=12,
        source="def stable(x):\n    return x\n",
        source_hash="stable",
    )
    mock_build_index.return_value = (
        ["f.py"],
        {"f.py": [uncertain, confident]},
        [uncertain, confident],
    )
    mock_build_graph.return_value = MagicMock()
    mock_topo.return_value = [uncertain, confident]
    mock_static.side_effect = [
        AnalysisResult(complexity="unknown", confidence="low", needs_human_review=True),
        AnalysisResult(complexity="O(n)", confidence="high", needs_human_review=False),
    ]
    mock_ai.return_value = AnalysisResult(
        complexity="O(n^2)",
        confidence="medium",
        needs_human_review=True,
        analyzer_kind="llm",
        reasoning_summary="LLM conservative upper bound",
    )

    orch = BigOOrchestrator(use_ai=True)
    orch._generation = 1
    with tempfile.TemporaryDirectory() as tmp:
        orch._run(1, tmp)

    assert uncertain.complexity == "O(n^2)"
    assert uncertain.source_kind == "llm"
    assert confident.complexity == "O(n)"
    mock_ai.assert_called_once()


@patch("bigo.orchestrator.OllamaBigOClient")
@patch("bigo.orchestrator.build_project_review", return_value="ok")
@patch("bigo.orchestrator.topological_blocks")
@patch("bigo.orchestrator.build_dependency_graph")
@patch("bigo.orchestrator.build_index")
@patch("bigo.orchestrator.estimate_with_ai")
@patch("bigo.orchestrator.analyze_block_static")
def test_orchestrator_llm_error_does_not_crash_pipeline(
    mock_static,
    mock_ai,
    mock_build_index,
    mock_build_graph,
    mock_topo,
    _mock_review,
    mock_ollama_cls,
):
    from bigo.orchestrator import BigOOrchestrator

    mock_ollama_cls.return_value.is_available.return_value = True
    block = _sample_block()
    mock_build_index.return_value = (["f.py"], {"f.py": [block]}, [block])
    mock_build_graph.return_value = MagicMock()
    mock_topo.return_value = [block]
    mock_static.return_value = AnalysisResult(
        complexity="unknown",
        confidence="low",
        needs_human_review=True,
    )
    mock_ai.return_value = AnalysisResult(
        complexity="unknown",
        analyzer_kind="llm_error",
        needs_human_review=True,
        reasoning_summary="Ollama не отвечает",
    )

    finished: list = []

    orch = BigOOrchestrator(use_ai=True)
    orch.finished.connect(finished.append)
    orch._generation = 1
    with tempfile.TemporaryDirectory() as tmp:
        orch._run(1, tmp)

    assert finished, "pipeline should finish"
    result = finished[0]
    assert result.ai_blocks_sent == 1
    assert result.ai_llm_errors == 1
    assert block.complexity in (None, "unknown")
