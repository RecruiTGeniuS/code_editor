from __future__ import annotations

from bigo.dependency_graph import block_graph_id
from bigo.models import AnalysisResult, BlockFeatures, CodeBlock
from bigo.overlay_model import to_monaco_decorations
from bigo.project_index import build_selection_block
from bigo.project_recommendations import (
    build_ai_project_recommendations,
    fallback_project_recommendation,
)
from bigo.static_analyzer import analyze_block_static
from bigo.ai_fallback import needs_ai_fallback
from bigo_controller import BigOController


def _block(
    name: str,
    *,
    complexity: str = "O(n^2)",
    features: BlockFeatures | None = None,
) -> CodeBlock:
    return CodeBlock(
        block_id=f"f.py#{name}",
        file_path="f.py",
        language_id="python",
        kind="function",
        name=name,
        start_line=1,
        end_line=5,
        source=f"def {name}(items):\n    return items\n",
        source_hash=name,
        stable_id=f"stable-{name}",
        qualified_name=name,
        complexity=complexity,
        features=features or BlockFeatures(max_loop_depth=2, loop_count=2),
    )


def test_project_recommendation_fallback_depends_on_features():
    used: set[str] = set()
    nested = _block("nested", features=BlockFeatures(max_loop_depth=2, loop_count=2))
    recursive = _block(
        "recursive",
        complexity="O(2^n)",
        features=BlockFeatures(has_recursion=True, self_call_count=2),
    )

    first = fallback_project_recommendation(nested, used)
    second = fallback_project_recommendation(recursive, used)

    assert first != second
    assert "внутренний" in first or "словарь" in first
    assert "рекур" in second.lower()


def test_ai_project_recommendations_map_json_by_block_id():
    block = _block("hotspot")
    bid = block_graph_id(block)

    class FakeClient:
        def is_available(self):
            return True

        def chat_json(self, **_kwargs):
            return {
                "recommendations": [
                    {
                        "block_id": bid,
                        "text": "Замените внутренний поиск словарём для быстрых проверок.",
                    }
                ]
            }, {}

    out = build_ai_project_recommendations(
        [block],
        {bid: AnalysisResult(complexity="O(n^2)", features=block.features)},
        FakeClient(),
    )

    assert out == {bid: "Замените внутренний поиск словарём для быстрых проверок."}


def test_duplicate_ai_recommendations_are_replaced_with_fallback():
    first = _block("first", features=BlockFeatures(max_loop_depth=2, loop_count=2))
    second = _block(
        "second",
        complexity="O(2^n)",
        features=BlockFeatures(has_recursion=True, self_call_count=2),
    )
    ids = [block_graph_id(first), block_graph_id(second)]

    class FakeClient:
        def is_available(self):
            return True

        def chat_json(self, **_kwargs):
            return {
                "recommendations": [
                    {"block_id": ids[0], "text": "Проверьте вложенные циклы."},
                    {"block_id": ids[1], "text": "Проверьте вложенные циклы."},
                ]
            }, {}

    out = build_ai_project_recommendations([first, second], {}, FakeClient())

    assert out[ids[0]] == "Проверьте вложенные циклы."
    assert out[ids[1]] != out[ids[0]]
    assert "рекур" in out[ids[1]].lower()


def test_selection_block_static_analysis_and_overlay_row():
    block = build_selection_block(
        file_path="f.py",
        language_id="python",
        source="total = 0\nfor item in items:\n    total += item\n",
        start_line=10,
        end_line=12,
    )
    result = analyze_block_static(block)
    block.complexity = result.complexity or "unknown"
    block.reason = result.reason or result.reasoning_summary
    bid = block_graph_id(block)

    rows = to_monaco_decorations([block], {bid: result})
    rows[0]["removable"] = True

    assert block.kind == "selection"
    assert result.complexity == "O(n)"
    assert rows[0]["blockId"] == bid
    assert rows[0]["startLine"] == 10
    assert rows[0]["endLine"] == 12
    assert rows[0]["analyzerKind"] == "rule"
    assert rows[0]["removable"] is True


def test_selection_block_unknown_call_inside_loop_delegates_to_ai():
    block = build_selection_block(
        file_path="f.py",
        language_id="python",
        source="for item in items:\n    result.append(expensive_lookup(item))\n",
        start_line=20,
        end_line=21,
    )
    result = analyze_block_static(block)

    assert block.features.call_summaries
    assert result.needs_human_review is True
    assert needs_ai_fallback(result)
    assert result.complexity == "unknown"


def test_selection_block_builtin_loop_stays_static():
    block = build_selection_block(
        file_path="f.py",
        language_id="python",
        source="total = 0\nfor item in items:\n    total += item.get('amount', 0)\n",
        start_line=30,
        end_line=32,
    )
    result = analyze_block_static(block)

    assert result.complexity == "O(n)"
    assert result.needs_human_review is False


def test_controller_selection_overlap_detection():
    controller = BigOController.__new__(BigOController)
    controller._rows_by_file = {"f.py": [{"startLine": 10, "endLine": 20}]}
    controller._selection_rows_by_file = {
        "f.py": [{"startLine": 30, "endLine": 35}]
    }
    controller._pending_selection_ranges_by_file = {"f.py": {(40, 45)}}

    assert controller._range_overlaps_existing("f.py", 12, 14)
    assert controller._range_overlaps_existing("f.py", 28, 32)
    assert controller._range_overlaps_existing("f.py", 42, 43)
    assert not controller._range_overlaps_existing("f.py", 21, 29)


def test_controller_clear_selection_state_keeps_project_blocks():
    controller = BigOController.__new__(BigOController)
    project = _block("project")
    selection = _block("selection")
    project_id = block_graph_id(project)
    selection_id = block_graph_id(selection)
    controller._selection_blocks_by_id = {selection_id: selection}
    controller._selection_results_by_id = {selection_id: AnalysisResult()}
    controller._selection_rows_by_file = {"f.py": [{"blockId": selection_id}]}
    controller._pending_selection_ranges_by_file = {"f.py": {(40, 45)}}
    controller._blocks_by_id = {project_id: project, selection_id: selection}
    controller._results_by_id = {
        project_id: AnalysisResult(),
        selection_id: AnalysisResult(),
    }
    controller._block_review_history = {project_id: "project", selection_id: "selection"}
    controller._block_review_order = [project_id, selection_id]
    controller._active_block_review_id = selection_id

    controller._clear_selection_state()

    assert controller._selection_blocks_by_id == {}
    assert controller._selection_results_by_id == {}
    assert controller._selection_rows_by_file == {}
    assert controller._pending_selection_ranges_by_file == {}
    assert project_id in controller._blocks_by_id
    assert selection_id not in controller._blocks_by_id
    assert controller._block_review_order == [project_id]
    assert controller._active_block_review_id == project_id
