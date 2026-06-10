"""Простой граф вызовов между CodeBlock (без import resolution)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

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


@dataclass
class DependencyGraph:
    blocks_by_id: dict[str, CodeBlock] = field(default_factory=dict)
    edges: list[DependencyEdge] = field(default_factory=list)
    outgoing: dict[str, list[DependencyEdge]] = field(default_factory=dict)
    incoming: dict[str, list[DependencyEdge]] = field(default_factory=dict)
    unresolved_calls: list[DependencyEdge] = field(default_factory=list)

    def get_callees(self, block_id: str) -> list[DependencyEdge]:
        return list(self.outgoing.get(block_id, []))

    def get_callers(self, block_id: str) -> list[DependencyEdge]:
        return list(self.incoming.get(block_id, []))

    @property
    def resolved_count(self) -> int:
        return sum(1 for e in self.edges if e.resolved)

    @property
    def unresolved_count(self) -> int:
        return len(self.unresolved_calls)


def block_graph_id(block: CodeBlock) -> str:
    return block.stable_id or block.block_id


def _match_targets(
    call_name: str, source: CodeBlock, candidates: list[CodeBlock]
) -> list[CodeBlock]:
    matches: list[CodeBlock] = []
    for target in candidates:
        if target.block_id == source.block_id:
            continue
        if target.name == call_name:
            matches.append(target)
            continue
        qn = target.qualified_name or ""
        if qn.endswith(f".{call_name}") or qn == call_name:
            matches.append(target)
    unique: dict[str, CodeBlock] = {}
    for t in matches:
        unique[block_graph_id(t)] = t
    return list(unique.values())


def resolve_simple_calls(blocks: list[CodeBlock]) -> list[DependencyEdge]:
    """Разрешить вызовы по name / qualified_name без import resolver."""
    analyzable = analyzable_blocks(blocks)
    edges: list[DependencyEdge] = []

    for source in analyzable:
        source_id = block_graph_id(source)
        for call_name in source.calls:
            if not call_name:
                continue
            targets = _match_targets(call_name, source, analyzable)
            target_id: str | None = None
            resolved = False
            confidence = "medium"

            if len(targets) == 1:
                target_id = block_graph_id(targets[0])
                resolved = True
                confidence = "high"
            elif len(targets) > 1:
                same_file = [t for t in targets if t.file_path == source.file_path]
                if len(same_file) == 1:
                    target_id = block_graph_id(same_file[0])
                    resolved = True
                    confidence = "medium"
                else:
                    resolved = False
                    confidence = "low"
            else:
                resolved = False
                confidence = "low"

            edges.append(
                DependencyEdge(
                    source_block_id=source_id,
                    target_block_id=target_id,
                    call_name=call_name,
                    resolved=resolved,
                    confidence=confidence,
                )
            )

    return edges


def build_dependency_graph(blocks: list[CodeBlock]) -> DependencyGraph:
    analyzable = analyzable_blocks(blocks)
    blocks_by_id = {block_graph_id(b): b for b in analyzable}
    edges = resolve_simple_calls(blocks)

    outgoing: dict[str, list[DependencyEdge]] = defaultdict(list)
    incoming: dict[str, list[DependencyEdge]] = defaultdict(list)
    unresolved: list[DependencyEdge] = []

    for edge in edges:
        outgoing[edge.source_block_id].append(edge)
        if edge.resolved and edge.target_block_id:
            incoming[edge.target_block_id].append(edge)
        else:
            unresolved.append(edge)

    return DependencyGraph(
        blocks_by_id=blocks_by_id,
        edges=edges,
        outgoing=dict(outgoing),
        incoming=dict(incoming),
        unresolved_calls=unresolved,
    )


def topological_blocks(
    blocks: list[CodeBlock], graph: DependencyGraph
) -> list[CodeBlock]:
    """Callee перед caller; при циклах — остаток в исходном порядке."""
    analyzable = analyzable_blocks(blocks)
    id_to_block = {block_graph_id(b): b for b in analyzable}
    order_ids = [block_graph_id(b) for b in analyzable]
    in_degree = {bid: 0 for bid in order_ids}
    callers_of: dict[str, list[str]] = defaultdict(list)

    for edge in graph.edges:
        if not edge.resolved or not edge.target_block_id:
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
