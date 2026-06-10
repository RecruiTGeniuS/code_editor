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

_CONTAINER_TYPES = {
    "class_definition",
    "class_declaration",
    "class_specifier",
    "interface_declaration",
}

_CALL_NODE_TYPES = {
    "call",
    "call_expression",
    "function_call",
    "method_invocation",
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


def _make_stable_id(
    file_path: str,
    language_id: str,
    kind: str,
    name: str,
    start_line: int,
    end_line: int,
    source_hash: str,
) -> str:
    payload = (
        f"{file_path}|{language_id}|{kind}|{name}|"
        f"{start_line}|{end_line}|{source_hash}"
    )
    return _sha1(payload)


def _iter_source_files(root_path: str):
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIRS]
        for name in filenames:
            path = os.path.join(dirpath, name)
            lang = detect_language_from_path(path)
            if not lang:
                continue
            yield path, lang


def _node_has_error(node: Node) -> bool:
    if getattr(node, "has_error", False) or getattr(node, "is_error", False):
        return True
    for child in node.children:
        if _node_has_error(child):
            return True
    return False


def _best_name(node: Node, source: bytes) -> str:
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return source[name_node.start_byte:name_node.end_byte].decode(
            "utf-8", errors="ignore"
        ).strip()
    raw = source[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")
    first = raw.splitlines()[0] if raw else ""
    return first[:80].strip()


def _normalize_kind(node_type: str, is_container: bool) -> str:
    if is_container:
        if "class" in node_type or node_type == "interface_declaration":
            return "class"
        return "container"
    if node_type in ("method_definition", "method_declaration"):
        return "method"
    if node_type == "lambda_expression":
        return "lambda"
    if node_type == "constructor_declaration":
        return "constructor"
    return "function"


def _qualified_name(name: str, qual_stack: list[str], is_container: bool) -> str:
    if is_container:
        return name
    if qual_stack:
        return ".".join(qual_stack + [name])
    return name


def _extract_signature(node: Node, source: bytes) -> str | None:
    body = node.child_by_field_name("body")
    if body is not None and body.start_byte > node.start_byte:
        sig = source[node.start_byte : body.start_byte].decode(
            "utf-8", errors="ignore"
        ).strip()
        if sig:
            return sig
    raw = source[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")
    lines = raw.splitlines()
    if not lines:
        return None
    first = lines[0].strip()
    if first.endswith(":"):
        return first
    return first[:200] if first else None


def _body_line_range(node: Node, source: bytes, start_line: int, end_line: int):
    body = node.child_by_field_name("body")
    if body is None:
        return (start_line + 1 if end_line > start_line else start_line, end_line)
    body_start = body.start_point[0] + 1
    body_end = body.end_point[0] + 1
    return body_start, body_end


def _call_name_from_call_node(node: Node, source: bytes) -> str | None:
    fn = node.child_by_field_name("function")
    if fn is None:
        fn = node.child_by_field_name("name")
    if fn is None:
        for child in node.children:
            if child.type in ("identifier", "attribute", "field_expression"):
                fn = child
                break
    if fn is None:
        return None
    if fn.type == "attribute":
        attr = fn.child_by_field_name("attribute")
        if attr is not None:
            return source[attr.start_byte : attr.end_byte].decode(
                "utf-8", errors="ignore"
            ).strip()
        raw = source[fn.start_byte : fn.end_byte].decode("utf-8", errors="ignore")
        if "." in raw:
            return raw.rsplit(".", 1)[-1].strip()
        return raw.strip()
    if fn.type == "identifier":
        return source[fn.start_byte : fn.end_byte].decode("utf-8", errors="ignore").strip()
    raw = source[fn.start_byte : fn.end_byte].decode("utf-8", errors="ignore").strip()
    if "." in raw:
        return raw.rsplit(".", 1)[-1].strip()
    return raw or None


def _loop_kind_from_node(node_type: str) -> str:
    if "while" in node_type or node_type == "do_statement":
        return "while"
    if "for" in node_type:
        return "for"
    return "loop"


def _extract_loop_summaries(node: Node) -> list[dict]:
    summaries: list[dict] = []

    def walk(n: Node) -> None:
        if n.type in _LOOP_TYPES:
            summaries.append(
                {
                    "kind": _loop_kind_from_node(n.type),
                    "start_line": n.start_point[0] + 1,
                    "end_line": n.end_point[0] + 1,
                    "start_byte": n.start_byte,
                    "end_byte": n.end_byte,
                    "estimated_complexity": "O(n)",
                }
            )
        for child in n.children:
            walk(child)

    walk(node)
    return summaries


def _extract_call_summaries(node: Node, source: bytes) -> list[dict]:
    summaries: list[dict] = []

    def walk(n: Node) -> None:
        if n.type in _CALL_NODE_TYPES:
            name = _call_name_from_call_node(n, source)
            if name and name not in _KEYWORDS:
                summaries.append(
                    {
                        "call_name": name,
                        "name": name,
                        "start_line": n.start_point[0] + 1,
                        "end_line": n.end_point[0] + 1,
                        "start_byte": n.start_byte,
                        "end_byte": n.end_byte,
                    }
                )
        for child in n.children:
            walk(child)

    walk(node)
    return summaries


def _extract_calls_from_tree(node: Node, source: bytes) -> list[str]:
    return [
        s["call_name"]
        for s in _extract_call_summaries(node, source)
    ]


def _merge_call_names(*parts: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for name in part:
            if name in seen or name in _KEYWORDS:
                continue
            seen.add(name)
            out.append(name)
    return out


def _extract_calls_regex(code: str) -> list[str]:
    lines = code.splitlines()
    body = "\n".join(lines[1:]) if len(lines) > 1 else code
    calls: list[str] = []
    for m in _CALL_RE.finditer(body):
        name = m.group(1)
        if name in _KEYWORDS:
            continue
        calls.append(name)
    return calls


def _extract_calls(node: Node, code: str, source: bytes) -> list[str]:
    from_ts = _extract_calls_from_tree(node, source)
    from_re = _extract_calls_regex(code)
    return _merge_call_names(from_ts, from_re)


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


def _extract_blocks_in_file(
    tree,
    source: bytes,
    file_path: str,
    lang_id: str,
) -> list[CodeBlock]:
    blocks: list[CodeBlock] = []
    idx = 0

    def visit(
        node: Node,
        qual_stack: list[str],
        parent_container_id: str | None,
        container_children: dict[str, list[str]],
    ) -> None:
        nonlocal idx
        if node.type not in _BLOCK_TYPES:
            for child in node.children:
                visit(child, qual_stack, parent_container_id, container_children)
            return

        raw = source[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")
        if not raw.strip():
            for child in node.children:
                visit(child, qual_stack, parent_container_id, container_children)
            return

        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        name = _best_name(node, source)
        is_container = node.type in _CONTAINER_TYPES
        kind = _normalize_kind(node.type, is_container)
        source_hash = _sha1(raw)
        qualified = _qualified_name(name, qual_stack, is_container)
        signature = _extract_signature(node, source)
        body_start_line, body_end_line = _body_line_range(
            node, source, start_line, end_line
        )
        stable_id = _make_stable_id(
            file_path, lang_id, kind, name, start_line, end_line, source_hash
        )
        calls = _extract_calls(node, raw, source)

        block = CodeBlock(
            block_id=f"{file_path}#{idx}",
            file_path=file_path,
            language_id=lang_id,
            kind=kind,
            name=name,
            start_line=start_line,
            end_line=end_line,
            source=raw,
            source_hash=source_hash,
            calls=calls,
            stable_id=stable_id,
            parent_block_id=parent_container_id,
            qualified_name=qualified,
            signature=signature,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            body_start_line=body_start_line,
            body_end_line=body_end_line,
            error_state=_node_has_error(node),
            is_container=is_container,
        )
        loop_count, max_depth = _loop_metrics(node)
        block.features = _build_features(block)
        block.features.loop_count = loop_count
        block.features.max_loop_depth = max_depth
        block.features.loop_summaries = _extract_loop_summaries(node)
        block.features.call_summaries = _extract_call_summaries(node, source)

        blocks.append(block)
        idx += 1

        if parent_container_id:
            container_children.setdefault(parent_container_id, []).append(stable_id)

        if is_container:
            child_qual = [name]
            child_parent = stable_id
            child_children: list[str] = []
            container_children[stable_id] = child_children
            for child in node.children:
                visit(child, child_qual, child_parent, container_children)
            block.children_ids = child_children
        else:
            child_qual = qual_stack + [name]
            for child in node.children:
                visit(child, child_qual, parent_container_id, container_children)

    visit(tree.root_node, [], None, {})
    return blocks


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
            continue

        local_blocks = _extract_blocks_in_file(tree, source, file_path, lang_id)
        blocks_by_file[file_path] = local_blocks
        all_blocks.extend(local_blocks)

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
