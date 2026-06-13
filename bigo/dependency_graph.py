"""Project dependency graph for CodeBlock objects.

The public entry points are intentionally kept compatible with the earlier
implementation: build_dependency_graph(...), block_graph_id(...),
resolve_simple_calls(...), and topological_blocks(...).
"""

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .block_utils import analyzable_blocks
from .models import CodeBlock


@dataclass(slots=True)
class DependencyEdge:
    source_block_id: str
    call_name: str
    target_block_id: str | None = None
    edge_type: str = "CALLS"
    confidence: str = "medium"
    resolved: bool = False
    source_range: dict | None = None
    raw_expression: str | None = None
    source_line: int | None = None
    inside_loop_depth: int = 0
    resolved_state: str = "unresolved"
    metadata: dict = field(default_factory=dict)


@dataclass
class DependencyGraph:
    blocks_by_id: dict[str, CodeBlock] = field(default_factory=dict)
    edges: list[DependencyEdge] = field(default_factory=list)
    outgoing: dict[str, list[DependencyEdge]] = field(default_factory=dict)
    incoming: dict[str, list[DependencyEdge]] = field(default_factory=dict)
    unresolved_calls: list[DependencyEdge] = field(default_factory=list)
    structural_edges: list[DependencyEdge] = field(default_factory=list)
    import_edges: list[DependencyEdge] = field(default_factory=list)
    recursive_block_ids: set[str] = field(default_factory=set)
    recursive_groups: list[list[str]] = field(default_factory=list)

    def get_callees(self, block_id: str) -> list[DependencyEdge]:
        return [e for e in self.outgoing.get(block_id, []) if e.edge_type == "CALLS"]

    def get_callers(self, block_id: str) -> list[DependencyEdge]:
        return [e for e in self.incoming.get(block_id, []) if e.edge_type == "CALLS"]

    @property
    def resolved_count(self) -> int:
        return sum(1 for e in self.edges if e.edge_type == "CALLS" and e.resolved)

    @property
    def unresolved_count(self) -> int:
        return len(self.unresolved_calls)


def block_graph_id(block: CodeBlock) -> str:
    return block.stable_id or block.block_id


def _module_name(path: str) -> str:
    return Path(path).with_suffix("").name


def _dedupe_blocks(blocks: list[CodeBlock]) -> list[CodeBlock]:
    seen: set[str] = set()
    out: list[CodeBlock] = []
    for block in blocks:
        bid = block_graph_id(block)
        if bid in seen:
            continue
        seen.add(bid)
        out.append(block)
    return out


class _Resolver:
    def __init__(self, blocks: list[CodeBlock]):
        self.blocks = blocks
        self.analyzable = analyzable_blocks(blocks)
        self.by_id = {block_graph_id(b): b for b in blocks}
        self.by_name: dict[str, list[CodeBlock]] = defaultdict(list)
        self.by_qualified: dict[str, CodeBlock] = {}
        self.by_file_name: dict[tuple[str, str], list[CodeBlock]] = defaultdict(list)
        self.methods_by_class: dict[tuple[str, str], list[CodeBlock]] = defaultdict(list)
        for block in self.analyzable:
            self.by_name[block.name].append(block)
            if block.qualified_name:
                self.by_qualified[block.qualified_name] = block
            module = _module_name(block.file_path)
            self.by_file_name[(module, block.name)].append(block)
            if block.qualified_name and "." in block.qualified_name:
                cls_name, method_name = block.qualified_name.rsplit(".", 1)
                self.methods_by_class[(cls_name, method_name)].append(block)

    def _file_scope(self, source: CodeBlock, candidates: list[CodeBlock]) -> list[CodeBlock]:
        return [b for b in candidates if os.path.normcase(b.file_path) == os.path.normcase(source.file_path)]

    def _import_aliases(self, source: CodeBlock) -> dict[str, dict]:
        aliases: dict[str, dict] = {}
        for row in source.features.import_summaries:
            name = row.get("name")
            alias = row.get("alias") or name
            if alias:
                aliases[str(alias)] = dict(row)
        return aliases

    def _resolve_self_method(self, source: CodeBlock, call_name: str) -> list[CodeBlock]:
        qn = source.qualified_name or ""
        if "." not in qn:
            return []
        cls_name = qn.rsplit(".", 1)[0]
        return self.methods_by_class.get((cls_name, call_name), [])

    def _resolve_imported(self, source: CodeBlock, receiver: str | None, call_name: str) -> list[CodeBlock]:
        aliases = self._import_aliases(source)
        if receiver and receiver in aliases:
            imp = aliases[receiver]
            module = str(imp.get("module") or imp.get("name") or "").split(".")[-1]
            return self.by_file_name.get((module, call_name), [])
        if call_name in aliases:
            imp = aliases[call_name]
            imported_name = str(imp.get("name") or call_name)
            module = str(imp.get("module") or "").split(".")[-1]
            candidates: list[CodeBlock] = []
            if module:
                candidates.extend(self.by_file_name.get((module, imported_name), []))
            candidates.extend(self.by_name.get(imported_name, []))
            return _dedupe_blocks(candidates)
        return []

    def resolve_call(self, source: CodeBlock, call: dict) -> tuple[list[CodeBlock], str]:
        call_name = str(call.get("call_name") or call.get("name") or "")
        receiver = call.get("receiver")
        qualified_hint = str(call.get("qualified_hint") or "")
        if not call_name:
            return ([], "unresolved")
        if call.get("is_dynamic"):
            return ([], "unresolved")

        if receiver == "self":
            targets = self._resolve_self_method(source, call_name)
            if targets:
                return (_dedupe_blocks(targets), "resolved")

        imported = self._resolve_imported(source, str(receiver) if receiver else None, call_name)
        if imported:
            return (_dedupe_blocks(imported), "resolved" if len(imported) == 1 else "ambiguous")

        if qualified_hint in self.by_qualified:
            target = self.by_qualified[qualified_hint]
            if block_graph_id(target) != block_graph_id(source):
                return ([target], "resolved")

        same_file = self._file_scope(source, self.by_name.get(call_name, []))
        same_file = [b for b in same_file if block_graph_id(b) != block_graph_id(source)]
        if same_file:
            return (_dedupe_blocks(same_file), "resolved" if len(same_file) == 1 else "ambiguous")

        all_named = [b for b in self.by_name.get(call_name, []) if block_graph_id(b) != block_graph_id(source)]
        if all_named:
            return (_dedupe_blocks(all_named), "resolved" if len(all_named) == 1 else "ambiguous")

        return ([], "unresolved")


def _edge_from_call(
    source: CodeBlock,
    call: dict,
    targets: list[CodeBlock],
    state: str,
) -> DependencyEdge:
    call_name = str(call.get("call_name") or call.get("name") or "")
    target_id: str | None = None
    confidence = "low"
    resolved = False
    if state == "resolved" and len(targets) == 1:
        target_id = block_graph_id(targets[0])
        confidence = "high"
        resolved = True
    elif state == "ambiguous":
        confidence = "low"
    edge = DependencyEdge(
        source_block_id=block_graph_id(source),
        target_block_id=target_id,
        call_name=call_name,
        edge_type="CALLS",
        confidence=confidence,
        resolved=resolved,
        source_range={
            "start_line": call.get("start_line"),
            "end_line": call.get("end_line"),
            "start_byte": call.get("start_byte"),
            "end_byte": call.get("end_byte"),
        },
        raw_expression=call.get("raw_expression"),
        source_line=call.get("start_line"),
        inside_loop_depth=int(call.get("inside_loop_depth") or 0),
        resolved_state=state,
        metadata={
            "receiver": call.get("receiver"),
            "qualified_hint": call.get("qualified_hint"),
            "candidate_target_ids": [block_graph_id(t) for t in targets],
        },
    )
    return edge


def resolve_simple_calls(blocks: list[CodeBlock]) -> list[DependencyEdge]:
    resolver = _Resolver(blocks)
    edges: list[DependencyEdge] = []
    for source in resolver.analyzable:
        summaries = source.features.call_summaries or [
            {"call_name": name, "name": name} for name in source.calls
        ]
        for call in summaries:
            if call.get("is_builtin_like"):
                continue
            targets, state = resolver.resolve_call(source, call)
            edges.append(_edge_from_call(source, call, targets, state))
    return edges


def _build_structural_edges(blocks: list[CodeBlock]) -> list[DependencyEdge]:
    edges: list[DependencyEdge] = []
    by_id = {b.stable_id: b for b in blocks if b.stable_id}
    for block in blocks:
        source_id = f"file:{os.path.normcase(os.path.abspath(block.file_path))}"
        block_id = block_graph_id(block)
        edges.append(
            DependencyEdge(
                source_block_id=source_id,
                target_block_id=block_id,
                call_name="contains",
                edge_type="CONTAINS",
                resolved=True,
                resolved_state="resolved",
                confidence="high",
            )
        )
        if block.parent_block_id and block.parent_block_id in by_id:
            edges.append(
                DependencyEdge(
                    source_block_id=block.parent_block_id,
                    target_block_id=block_id,
                    call_name="contains",
                    edge_type="CONTAINS",
                    resolved=True,
                    resolved_state="resolved",
                    confidence="high",
                )
            )
    return edges


def _build_import_edges(blocks: list[CodeBlock]) -> list[DependencyEdge]:
    seen: set[tuple[str, str, str]] = set()
    edges: list[DependencyEdge] = []
    for block in blocks:
        source_id = f"file:{os.path.normcase(os.path.abspath(block.file_path))}"
        for row in block.features.import_summaries:
            target = row.get("module") or row.get("name")
            if not target:
                continue
            key = (source_id, str(target), str(row.get("alias") or ""))
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                DependencyEdge(
                    source_block_id=source_id,
                    target_block_id=None,
                    call_name=str(target),
                    edge_type="IMPORTS",
                    resolved=False,
                    resolved_state="unresolved",
                    confidence="medium",
                    source_line=row.get("line"),
                    metadata=dict(row),
                )
            )
    return edges


def _find_call_sccs(call_edges: list[DependencyEdge]) -> list[list[str]]:
    graph: dict[str, list[str]] = defaultdict(list)
    nodes: set[str] = set()
    for edge in call_edges:
        nodes.add(edge.source_block_id)
        if edge.resolved and edge.target_block_id:
            graph[edge.source_block_id].append(edge.target_block_id)
            nodes.add(edge.target_block_id)

    index = 0
    stack: list[str] = []
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    on_stack: set[str] = set()
    groups: list[list[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in graph.get(node, []):
            if target not in indices:
                strongconnect(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] == indices[node]:
            group: list[str] = []
            while stack:
                item = stack.pop()
                on_stack.remove(item)
                group.append(item)
                if item == node:
                    break
            if len(group) > 1 or any(t == node for t in graph.get(node, [])):
                groups.append(group)

    for node in nodes:
        if node not in indices:
            strongconnect(node)
    return groups


def build_dependency_graph(blocks: list[CodeBlock]) -> DependencyGraph:
    blocks_by_id = {block_graph_id(b): b for b in blocks}
    call_edges = resolve_simple_calls(blocks)
    structural_edges = _build_structural_edges(blocks)
    import_edges = _build_import_edges(blocks)
    all_edges = call_edges + structural_edges + import_edges

    outgoing: dict[str, list[DependencyEdge]] = defaultdict(list)
    incoming: dict[str, list[DependencyEdge]] = defaultdict(list)
    unresolved: list[DependencyEdge] = []

    for edge in call_edges:
        outgoing[edge.source_block_id].append(edge)
        if edge.resolved and edge.target_block_id:
            incoming[edge.target_block_id].append(edge)
        else:
            unresolved.append(edge)

    recursive_groups = _find_call_sccs(call_edges)
    recursive_ids = {bid for group in recursive_groups for bid in group}
    for bid in recursive_ids:
        block = blocks_by_id.get(bid)
        if block is not None:
            block.features.has_recursion = True
            block.features.recursion_kind = (
                "mutual" if any(len(g) > 1 and bid in g for g in recursive_groups) else "self"
            )

    return DependencyGraph(
        blocks_by_id=blocks_by_id,
        edges=all_edges,
        outgoing=dict(outgoing),
        incoming=dict(incoming),
        unresolved_calls=unresolved,
        structural_edges=structural_edges,
        import_edges=import_edges,
        recursive_block_ids=recursive_ids,
        recursive_groups=recursive_groups,
    )


def topological_blocks(
    blocks: list[CodeBlock], graph: DependencyGraph
) -> list[CodeBlock]:
    """Return callees before callers; keep source order for unresolved cycles."""
    analyzable = analyzable_blocks(blocks)
    id_to_block = {block_graph_id(b): b for b in analyzable}
    order_ids = [block_graph_id(b) for b in analyzable]
    in_degree = {bid: 0 for bid in order_ids}
    callers_of: dict[str, list[str]] = defaultdict(list)

    for edge in graph.edges:
        if edge.edge_type != "CALLS" or not edge.resolved or not edge.target_block_id:
            continue
        src, tgt = edge.source_block_id, edge.target_block_id
        if src not in in_degree or tgt not in in_degree:
            continue
        in_degree[src] += 1
        callers_of[tgt].append(src)

    queue = [bid for bid in order_ids if in_degree[bid] == 0]
    sorted_ids: list[str] = []
    while queue:
        bid = queue.pop(0)
        sorted_ids.append(bid)
        for caller in callers_of.get(bid, []):
            in_degree[caller] -= 1
            if in_degree[caller] == 0:
                queue.append(caller)

    if len(sorted_ids) < len(order_ids):
        seen = set(sorted_ids)
        for bid in order_ids:
            if bid not in seen:
                sorted_ids.append(bid)

    return [id_to_block[bid] for bid in sorted_ids if bid in id_to_block]
