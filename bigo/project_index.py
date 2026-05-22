from __future__ import annotations

import hashlib
import os
import re
from collections import defaultdict

from tree_sitter import Node, Parser
from tree_sitter_language_pack import (
    detect_language_from_path,
    get_language,
)

from .models import BlockFeatures, CodeBlock

_IGNORED_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
    "code_editor_backup",
    "code_editor_backup_2",
    "code_editor_backup_3",
    "code_editor_backup_4",
    "code_editor_backup_5",
}

# Узлы-tree-sitter, которые считаем «выделяемыми блоками» для оценки.
_BLOCK_TYPES = {
    "function_definition",
    "function_declaration",
    "method_definition",
    "method_declaration",
    "function_item",
    "class_definition",
    "class_declaration",
    "class_specifier",
    "interface_declaration",
    "constructor_declaration",
    "lambda_expression",
}

_LOOP_TYPES = {
    "for_statement",
    "for_in_statement",
    "for_expression",
    "while_statement",
    "do_statement",
    "enhanced_for_statement",
}

_CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_KEYWORDS = {
    "if", "for", "while", "switch", "return", "sizeof", "catch", "new",
    "delete", "elif", "def", "class", "print", "with", "except",
}


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def _iter_source_files(root_path: str):
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIRS]
        for name in filenames:
            path = os.path.join(dirpath, name)
            lang = detect_language_from_path(path)
            if not lang:
                continue
            yield path, lang


def _walk(node: Node):
    yield node
    for child in node.children:
        yield from _walk(child)


def _best_name(node: Node, source: bytes) -> str:
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return source[name_node.start_byte:name_node.end_byte].decode(
            "utf-8", errors="ignore"
        ).strip()
    # Фолбэк: первая строка сигнатуры.
    raw = source[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")
    first = raw.splitlines()[0] if raw else ""
    return first[:80].strip()


def _extract_calls(code: str) -> list[str]:
    # Первая строка большинства блоков — сигнатура (def foo(...), function foo(...)),
    # её нельзя считать вызовом. Иначе почти каждый блок выглядит рекурсивным.
    lines = code.splitlines()
    body = "\n".join(lines[1:]) if len(lines) > 1 else code
    calls: list[str] = []
    for m in _CALL_RE.finditer(body):
        name = m.group(1)
        if name in _KEYWORDS:
            continue
        calls.append(name)
    # Сохраняем порядок первого появления без дублей.
    out: list[str] = []
    seen: set[str] = set()
    for name in calls:
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _loop_metrics(node: Node) -> tuple[int, int]:
    total = 0

    def walk(n: Node, depth: int) -> int:
        nonlocal total
        next_depth = depth
        if n.type in _LOOP_TYPES:
            total += 1
            next_depth += 1
        best = next_depth
        for c in n.children:
            best = max(best, walk(c, next_depth))
        return best

    max_depth = walk(node, 0)
    return total, max_depth


def _build_features(block: CodeBlock) -> BlockFeatures:
    code = block.source
    has_log = bool(
        re.search(r">>\s*1|/=\s*2|/2\b|mid\s*=|binary_search", code)
    )
    has_sort = bool(re.search(r"\bsort(ed)?\s*\(|qsort\s*\(", code))
    self_calls = sum(1 for c in block.calls if c == block.name)
    return BlockFeatures(
        has_log_pattern=has_log,
        has_sort_call=has_sort,
        self_call_count=self_calls,
    )


def build_index(root_path: str) -> tuple[list[str], dict[str, list[CodeBlock]], list[CodeBlock]]:
    files_scanned: list[str] = []
    blocks_by_file: dict[str, list[CodeBlock]] = {}
    all_blocks: list[CodeBlock] = []

    for file_path, lang_id in _iter_source_files(root_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue

        files_scanned.append(file_path)
        source = text.encode("utf-8", errors="ignore")

        try:
            parser = Parser(get_language(lang_id))
            tree = parser.parse(source)
        except Exception:
            # На случай несовпадения grammar/версии: пропускаем файл.
            continue

        local_blocks: list[CodeBlock] = []
        idx = 0
        for node in _walk(tree.root_node):
            if node.type not in _BLOCK_TYPES:
                continue
            raw = source[node.start_byte:node.end_byte].decode(
                "utf-8", errors="ignore"
            )
            if not raw.strip():
                continue
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            name = _best_name(node, source)
            calls = _extract_calls(raw)
            block = CodeBlock(
                block_id=f"{file_path}#{idx}",
                file_path=file_path,
                language_id=lang_id,
                kind=node.type,
                name=name,
                start_line=start_line,
                end_line=end_line,
                source=raw,
                source_hash=_sha1(raw),
                calls=calls,
            )
            loop_count, max_depth = _loop_metrics(node)
            block.features = _build_features(block)
            block.features.loop_count = loop_count
            block.features.max_loop_depth = max_depth
            local_blocks.append(block)
            idx += 1

        blocks_by_file[file_path] = local_blocks
        all_blocks.extend(local_blocks)

    # Граф связей: called_by через имя функции/метода (легковесный v1).
    by_name: dict[str, list[str]] = defaultdict(list)
    by_id: dict[str, CodeBlock] = {b.block_id: b for b in all_blocks}
    for b in all_blocks:
        if b.name:
            by_name[b.name].append(b.block_id)
    for b in all_blocks:
        for call in b.calls:
            for target_id in by_name.get(call, []):
                if target_id == b.block_id:
                    continue
                by_id[target_id].called_by.append(b.block_id)
    for b in all_blocks:
        if b.called_by:
            b.called_by = sorted(set(b.called_by))

    return files_scanned, blocks_by_file, all_blocks

