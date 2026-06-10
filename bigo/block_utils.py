"""Утилиты отбора и группировки CodeBlock для анализа и overlay."""

from __future__ import annotations

import os
from collections import defaultdict

from .models import BIG_O_CLASSES, CodeBlock

NON_ANALYZABLE_KINDS = frozenset(
    {"class", "container", "module", "namespace", "file", "interface"}
)

ANALYZABLE_KINDS = frozenset(
    {
        "function",
        "method",
        "lambda",
        "constructor",
        "selection",
        "top_level_executable",
    }
)

NON_OVERLAY_COMPLEXITIES = frozenset({"N/A", "container", "unknown", None})


def is_analyzable_block(block: CodeBlock) -> bool:
    if block.is_container:
        return False
    if block.kind in NON_ANALYZABLE_KINDS:
        return False
    if block.kind in ANALYZABLE_KINDS:
        return True
    # Legacy tree-sitter kinds до нормализации в project_index.
    if block.kind in {
        "function_definition",
        "function_declaration",
        "method_definition",
        "method_declaration",
        "function_item",
        "constructor_declaration",
        "lambda_expression",
    }:
        return True
    return False


def analyzable_blocks(blocks: list[CodeBlock]) -> list[CodeBlock]:
    return [b for b in blocks if is_analyzable_block(b)]


def container_blocks(blocks: list[CodeBlock]) -> list[CodeBlock]:
    return [b for b in blocks if not is_analyzable_block(b)]


def is_overlayable_block(block: CodeBlock) -> bool:
    if not is_analyzable_block(block):
        return False
    if not block.complexity or block.complexity in NON_OVERLAY_COMPLEXITIES:
        return False
    return block.complexity in BIG_O_CLASSES


def group_blocks_by_file(blocks: list[CodeBlock]) -> dict[str, list[CodeBlock]]:
    grouped: dict[str, list[CodeBlock]] = defaultdict(list)
    for b in blocks:
        grouped[b.file_path].append(b)
    return dict(grouped)


def group_blocks_by_class(
    blocks: list[CodeBlock], all_blocks: list[CodeBlock] | None = None
) -> dict[str, list[CodeBlock]]:
    """Группировка по классу-контейнеру (parent_block_id → qualified_name класса)."""
    by_stable = {b.stable_id: b for b in (all_blocks or blocks) if b.stable_id}
    grouped: dict[str, list[CodeBlock]] = defaultdict(list)
    top_level: list[CodeBlock] = []

    for b in blocks:
        if b.parent_block_id:
            parent = by_stable.get(b.parent_block_id)
            key = (
                (parent.qualified_name or parent.name)
                if parent
                else (b.qualified_name.rsplit(".", 1)[0] if b.qualified_name and "." in b.qualified_name else "<?>")
            )
            grouped[key].append(b)
        else:
            top_level.append(b)

    if top_level:
        grouped["<top-level>"] = top_level
    return dict(grouped)


def basename(path: str) -> str:
    return os.path.basename(path)
