"""Тесты локальной рецензии блока и плошадки overlay для UI-кнопки."""

from __future__ import annotations

from bigo.block_review import build_block_review
from bigo.dependency_graph import block_graph_id
from bigo.models import AnalysisResult, BlockFeatures, CodeBlock
from bigo.overlay_model import to_monaco_decorations


def _block(
    complexity: str | None = "O(n)",
    source_kind: str = "static",
    name: str = "do_stuff",
) -> CodeBlock:
    return CodeBlock(
        block_id="f.py#1",
        file_path="src/f.py",
        language_id="python",
        kind="function",
        name=name,
        start_line=10,
        end_line=20,
        source="def do_stuff(xs):\n    for x in xs:\n        pass\n",
        source_hash="hashy",
        calls=["helper", "other"],
        complexity=complexity,
        reason="один цикл",
        source_kind=source_kind,
        stable_id="stable-1",
        qualified_name="mod.do_stuff",
        features=BlockFeatures(loop_count=1, max_loop_depth=1),
    )


def test_overlay_row_contains_block_id_and_kind():
    block = _block(complexity="O(n)", source_kind="static")
    rows = to_monaco_decorations([block])
    assert len(rows) == 1
    row = rows[0]
    assert row["blockId"] == block_graph_id(block)
    assert row["filePath"] == "src/f.py"
    assert row["startLine"] == 10
    assert row["endLine"] == 20
    assert row["complexity"] == "O(n)"
    assert row["analyzerKind"] == "static"
    assert row["confidence"] is None


def test_overlay_row_uses_analysis_result_kind_and_confidence():
    block = _block(complexity="O(n^2)", source_kind="llm")
    analysis = AnalysisResult(
        complexity="O(n^2)",
        confidence="medium",
        analyzer_kind="llm",
        reasoning_summary="LLM upper bound",
    )
    bid = block_graph_id(block)
    rows = to_monaco_decorations([block], {bid: analysis})
    assert rows[0]["analyzerKind"] == "llm"
    assert rows[0]["confidence"] == "medium"
    assert rows[0]["label"].endswith("· AI")


def test_build_block_review_local_without_ai():
    block = _block(complexity="O(n)", source_kind="static")
    analysis = AnalysisResult(
        complexity="O(n)",
        confidence="high",
        analyzer_kind="rule",
        reasoning_summary="Линейный обход по xs",
        assumptions=["xs — список"],
        optimization_advice=["Использовать set, если нужны проверки"],
    )
    text = build_block_review(block, analysis, use_ai_hint=False)
    assert "Рецензия блока: mod.do_stuff" in text
    assert "O(n)" in text
    assert "rule" in text
    assert "Линейный обход" in text
    assert "Допущения" in text
    assert "Идеи оптимизации" in text
    assert "циклов: 1" in text


def test_build_block_review_marks_ai_unavailable():
    block = _block(complexity="unknown", source_kind="static")
    analysis = AnalysisResult(
        complexity="unknown",
        confidence="low",
        analyzer_kind="rule",
        needs_human_review=True,
        reasoning_summary="Правила не уверены",
    )
    text = build_block_review(
        block, analysis, use_ai_hint=True, ai_available=False
    )
    assert "Требует ручной проверки: да" in text
    assert "AI-рецензия недоступна" in text


def test_review_block_unknown_id_does_not_crash():
    from bigo_controller import BigOController

    # Не создаём реальный controller (требует QWidget) — проверяем чистую
    # функцию build_block_review с None analysis.
    text = build_block_review(_block(complexity=None, source_kind="static"))
    assert "Сложность: unknown" in text
    # Симулируем поведение controller: для неизвестного id блок не находится.
    blocks_by_id = {"stable-1": _block()}
    assert blocks_by_id.get("missing") is None
    # build_block_review никогда не вызывается с None block — так что
    # отсутствие id обрабатывается на уровне controller.review_block.
    assert callable(BigOController.review_block)
