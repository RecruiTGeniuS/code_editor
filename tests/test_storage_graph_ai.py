from __future__ import annotations

from pathlib import Path

from bigo.dependency_graph import block_graph_id, build_dependency_graph
from bigo.models import AnalysisResult, BlockFeatures, CodeBlock
from bigo.ollama_client import normalize_complexity
from bigo.storage import BigoStorage, SQLiteBlockComplexityCache


def _block(
    name: str,
    *,
    file_path: str,
    qualified_name: str | None = None,
    calls: list[str] | None = None,
    call_summaries: list[dict] | None = None,
    imports: list[dict] | None = None,
    parent: str | None = None,
    kind: str = "function",
    stable_id: str | None = None,
) -> CodeBlock:
    stable_id = stable_id or f"{file_path}:{qualified_name or name}"
    return CodeBlock(
        block_id=stable_id,
        stable_id=stable_id,
        file_path=file_path,
        language_id="python",
        kind=kind,
        name=name,
        qualified_name=qualified_name or name,
        parent_block_id=parent,
        start_line=1,
        end_line=3,
        source=f"def {name}():\n    pass\n",
        source_hash=f"hash-{stable_id}",
        normalized_hash=f"norm-{stable_id}",
        calls=calls or [],
        features=BlockFeatures(
            call_summaries=call_summaries or [],
            import_summaries=imports or [],
        ),
    )


def test_normalize_complexity_does_not_invent_linear_fallback():
    assert normalize_complexity("O(n)") == "O(n)"
    assert normalize_complexity("linear-ish") == "unknown"
    assert normalize_complexity("") == "unknown"


def test_graph_resolves_self_method_and_import_alias(tmp_path: Path):
    service_path = str(tmp_path / "service.py")
    util_path = str(tmp_path / "utils.py")
    cls = _block(
        "Worker",
        file_path=service_path,
        qualified_name="Worker",
        kind="class",
        stable_id="class-worker",
    )
    method = _block(
        "run",
        file_path=service_path,
        qualified_name="Worker.run",
        parent=block_graph_id(cls),
        calls=["helper", "tool"],
        call_summaries=[
            {
                "call_name": "helper",
                "name": "helper",
                "receiver": "self",
                "qualified_hint": "self.helper",
                "start_line": 2,
            },
            {
                "call_name": "tool",
                "name": "tool",
                "receiver": "u",
                "qualified_hint": "u.tool",
                "start_line": 3,
            },
        ],
        imports=[{"kind": "import", "module": "utils", "name": "utils", "alias": "u"}],
    )
    helper = _block(
        "helper",
        file_path=service_path,
        qualified_name="Worker.helper",
        parent=block_graph_id(cls),
    )
    tool = _block("tool", file_path=util_path, qualified_name="tool")

    graph = build_dependency_graph([cls, method, helper, tool])
    callees = graph.get_callees(block_graph_id(method))
    resolved_targets = {edge.call_name: edge.target_block_id for edge in callees}

    assert resolved_targets["helper"] == block_graph_id(helper)
    assert resolved_targets["tool"] == block_graph_id(tool)
    assert graph.resolved_count == 2


def test_sqlite_cache_roundtrip_without_source_storage(tmp_path: Path):
    src = tmp_path / "sample.py"
    src.write_text("def f(xs):\n    return len(xs)\n", encoding="utf-8")
    block = _block("f", file_path=str(src), qualified_name="f")
    graph = build_dependency_graph([block])

    storage = BigoStorage(str(tmp_path))
    run_id = storage.begin_run("test-model")
    storage.upsert_index([str(src)], [block], run_id)
    storage.replace_edges(graph)
    cache = SQLiteBlockComplexityCache(storage, graph=graph, model_id="test-model")
    analysis = AnalysisResult(
        complexity="O(1)",
        confidence="high",
        analyzer_kind="rule",
        reasoning_summary="constant work",
    )
    block.complexity = "O(1)"
    block.reason = "constant work"
    cache.upsert(block, analysis)

    probe = _block("f", file_path=str(src), qualified_name="f")
    assert cache.try_apply(probe) is True
    assert probe.complexity == "O(1)"

    rows = storage.conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    table_names = {row["name"] for row in rows}
    assert {"files", "blocks", "block_features", "edges", "analysis_results", "reviews"} <= table_names
    assert "def f" not in "\n".join(
        str(tuple(row))
        for row in storage.conn.execute("SELECT * FROM blocks").fetchall()
    )
    storage.close()
