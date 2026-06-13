from __future__ import annotations

import hashlib
import os
import re
import ast
import textwrap
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

_BUILTIN_CONTAINER_CALLS = {
    "all",
    "any",
    "deque",
    "enumerate",
    "heapify",
    "heappop",
    "heappush",
    "len",
    "max",
    "min",
    "range",
    "set",
    "sorted",
    "sum",
    "zip",
}

_CONTAINER_METHODS = {
    "append",
    "extend",
    "insert",
    "pop",
    "remove",
    "sort",
    "add",
    "clear",
    "copy",
    "discard",
    "get",
    "items",
    "keys",
    "setdefault",
    "update",
    "values",
}

_DYNAMIC_CALL_NAMES = {"eval", "exec", "getattr", "globals", "locals"}


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def _normalized_source(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if stripped:
            lines.append(re.sub(r"\s+", " ", stripped))
    return "\n".join(lines)


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


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode(
        "utf-8", errors="ignore"
    ).strip()


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


def _extract_parameters(node: Node, source: bytes) -> list[str]:
    params = node.child_by_field_name("parameters")
    if params is None:
        return []
    names: list[str] = []

    def walk(n: Node) -> None:
        if n.type == "identifier":
            name = _node_text(n, source)
            if name and name not in names:
                names.append(name)
            return
        for child in n.children:
            walk(child)

    walk(params)
    return names


def _body_line_range(node: Node, source: bytes, start_line: int, end_line: int):
    body = node.child_by_field_name("body")
    if body is None:
        return (start_line + 1 if end_line > start_line else start_line, end_line)
    body_start = body.start_point[0] + 1
    body_end = body.end_point[0] + 1
    return body_start, body_end


def _body_byte_range(node: Node) -> tuple[int | None, int | None]:
    body = node.child_by_field_name("body")
    if body is None:
        return (None, None)
    return (body.start_byte, body.end_byte)


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


def _call_function_node(node: Node) -> Node | None:
    fn = node.child_by_field_name("function")
    if fn is None:
        fn = node.child_by_field_name("name")
    if fn is not None:
        return fn
    for child in node.children:
        if child.type in ("identifier", "attribute", "field_expression"):
            return child
    return None


def _call_receiver(fn: Node | None, source: bytes) -> str | None:
    if fn is None:
        return None
    raw = _node_text(fn, source)
    if "." not in raw:
        return None
    return raw.rsplit(".", 1)[0].strip() or None


def _loop_kind_from_node(node_type: str) -> str:
    if "while" in node_type or node_type == "do_statement":
        return "while"
    if "for" in node_type:
        return "for"
    return "loop"


def _loop_bound_hint(node: Node, source: bytes) -> str:
    raw = _node_text(node, source)
    if "while" in node.type:
        if re.search(r"/=\s*2|//=\s*2|>>=\s*1|mid\s*=", raw):
            return "logarithmic"
        if re.search(r"\+=\s*1|-=\s*1|=\s*\w+\s*[+-]\s*1", raw):
            return "linear"
        return "unknown"
    if "range(" in raw:
        args = re.search(r"range\s*\((.*?)\)", raw, re.DOTALL)
        if args and re.fullmatch(r"\s*\d+\s*", args.group(1)):
            return "constant"
        return "linear"
    if re.search(r"\bin\s+\[.*\]|\bin\s+\(.*\)", raw, re.DOTALL):
        return "constant"
    return "data_dependent"


def _extract_loop_summaries(node: Node, source: bytes) -> list[dict]:
    summaries: list[dict] = []

    def walk(n: Node, depth: int, parent_index: int | None) -> None:
        next_depth = depth
        active_parent = parent_index
        if n.type in _LOOP_TYPES:
            raw = _node_text(n, source)
            idx = len(summaries)
            bound_hint = _loop_bound_hint(n, source)
            summaries.append(
                {
                    "kind": _loop_kind_from_node(n.type),
                    "start_line": n.start_point[0] + 1,
                    "end_line": n.end_point[0] + 1,
                    "start_byte": n.start_byte,
                    "end_byte": n.end_byte,
                    "nesting_depth": depth + 1,
                    "parent_loop_index": parent_index,
                    "raw_expression": raw.splitlines()[0] if raw else "",
                    "bound_hint": bound_hint,
                    "estimated_complexity": (
                        "O(log n)" if bound_hint == "logarithmic"
                        else "O(1)" if bound_hint == "constant"
                        else "unknown" if bound_hint in {"unknown", "data_dependent"}
                        else "O(n)"
                    ),
                    "has_break": bool(re.search(r"\bbreak\b", raw)),
                    "has_continue": bool(re.search(r"\bcontinue\b", raw)),
                    "has_return": bool(re.search(r"\breturn\b", raw)),
                }
            )
            next_depth = depth + 1
            active_parent = idx
        for child in n.children:
            walk(child, next_depth, active_parent)

    walk(node, 0, None)
    return summaries


def _extract_call_summaries(node: Node, source: bytes) -> list[dict]:
    summaries: list[dict] = []

    def walk(n: Node, loop_depth: int) -> None:
        next_depth = loop_depth + 1 if n.type in _LOOP_TYPES else loop_depth
        if n.type in _CALL_NODE_TYPES:
            name = _call_name_from_call_node(n, source)
            if name and name not in _KEYWORDS:
                fn = _call_function_node(n)
                raw_fn = _node_text(fn, source) if fn is not None else name
                receiver = _call_receiver(fn, source)
                raw = _node_text(n, source)
                is_dynamic = name in _DYNAMIC_CALL_NAMES or (
                    name == "getattr" and "," in raw
                )
                summaries.append(
                    {
                        "call_name": name,
                        "name": name,
                        "raw_expression": raw,
                        "receiver": receiver,
                        "qualified_hint": raw_fn,
                        "start_line": n.start_point[0] + 1,
                        "end_line": n.end_point[0] + 1,
                        "start_byte": n.start_byte,
                        "end_byte": n.end_byte,
                        "inside_loop_depth": loop_depth,
                        "is_method": receiver is not None,
                        "is_dynamic": is_dynamic,
                        "is_builtin_like": (
                            name in _BUILTIN_CONTAINER_CALLS
                            or name in _CONTAINER_METHODS
                        ),
                        "is_project_candidate": (
                            name not in _BUILTIN_CONTAINER_CALLS
                            and name not in _CONTAINER_METHODS
                        ),
                    }
                )
        for child in n.children:
            walk(child, next_depth)

    walk(node, 0)
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
            if (
                name in seen
                or name in _KEYWORDS
                or name in _BUILTIN_CONTAINER_CALLS
                or name in _CONTAINER_METHODS
            ):
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


def _extract_branch_summaries(node: Node, source: bytes) -> list[dict]:
    out: list[dict] = []
    branch_types = {
        "if_statement",
        "elif_clause",
        "else_clause",
        "match_statement",
        "case_clause",
        "try_statement",
        "except_clause",
    }

    def walk(n: Node) -> None:
        if n.type in branch_types:
            out.append(
                {
                    "kind": n.type,
                    "start_line": n.start_point[0] + 1,
                    "end_line": n.end_point[0] + 1,
                    "raw_expression": _node_text(n, source).splitlines()[0],
                }
            )
        for child in n.children:
            walk(child)

    walk(node)
    return out


def _extract_container_operations(node: Node, source: bytes) -> list[dict]:
    out: list[dict] = []
    calls = _extract_call_summaries(node, source)
    for call in calls:
        name = call.get("name")
        receiver = call.get("receiver")
        if name in _BUILTIN_CONTAINER_CALLS or name in _CONTAINER_METHODS:
            op_type = "builtin" if receiver is None else "method"
            out.append(
                {
                    "operation": name,
                    "operation_type": op_type,
                    "receiver": receiver,
                    "line": call.get("start_line"),
                    "raw_expression": call.get("raw_expression"),
                    "inside_loop_depth": call.get("inside_loop_depth", 0),
                }
            )
    raw = _node_text(node, source)
    for lineno, line in enumerate(raw.splitlines(), start=node.start_point[0] + 1):
        stripped = line.strip()
        if " in " in stripped and not stripped.startswith(("for ", "async for ")):
            out.append(
                {
                    "operation": "membership",
                    "operation_type": "container",
                    "line": lineno,
                    "raw_expression": stripped,
                }
            )
        if any(tok in stripped for tok in ("[", "{")) and " for " in stripped:
            out.append(
                {
                    "operation": "comprehension",
                    "operation_type": "container",
                    "line": lineno,
                    "raw_expression": stripped,
                }
            )
    return out


def _extract_python_imports(text: str) -> list[dict]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    imports: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(
                    {
                        "kind": "import",
                        "module": alias.name,
                        "name": alias.name.split(".")[0],
                        "alias": alias.asname,
                        "line": node.lineno,
                    }
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                imports.append(
                    {
                        "kind": "from_import",
                        "module": module,
                        "name": alias.name,
                        "alias": alias.asname,
                        "line": node.lineno,
                    }
                )
    return imports


def _extract_local_symbols_python(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return sorted(names)


def _ast_call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _ast_receiver(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        value = node.value
        if isinstance(value, ast.Name):
            return value.id
        if isinstance(value, ast.Attribute):
            parts: list[str] = []
            cur: ast.AST = value
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
                return ".".join(reversed(parts))
    return None


def _ast_call_summaries(tree: ast.AST, line_offset: int) -> list[dict]:
    out: list[dict] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.loop_depth = 0

        def visit_For(self, node: ast.For) -> None:  # noqa: N802
            self.loop_depth += 1
            self.generic_visit(node)
            self.loop_depth -= 1

        def visit_AsyncFor(self, node: ast.AsyncFor) -> None:  # noqa: N802
            self.visit_For(node)

        def visit_While(self, node: ast.While) -> None:  # noqa: N802
            self.loop_depth += 1
            self.generic_visit(node)
            self.loop_depth -= 1

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            name = _ast_call_name(node.func)
            if name and name not in _KEYWORDS:
                receiver = _ast_receiver(node.func)
                start = line_offset + int(getattr(node, "lineno", 1))
                end = line_offset + int(getattr(node, "end_lineno", getattr(node, "lineno", 1)))
                is_builtin_like = name in _BUILTIN_CONTAINER_CALLS or name in _CONTAINER_METHODS
                out.append(
                    {
                        "call_name": name,
                        "name": name,
                        "receiver": receiver,
                        "qualified_hint": f"{receiver}.{name}" if receiver else name,
                        "start_line": start,
                        "end_line": end,
                        "inside_loop_depth": self.loop_depth,
                        "is_method": receiver is not None,
                        "is_dynamic": name in _DYNAMIC_CALL_NAMES,
                        "is_builtin_like": is_builtin_like,
                        "is_project_candidate": not is_builtin_like,
                    }
                )
            self.generic_visit(node)

    Visitor().visit(tree)
    return out


def _ast_loop_summaries(tree: ast.AST, line_offset: int) -> list[dict]:
    out: list[dict] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.depth = 0
            self.parent_stack: list[int] = []

        def _add_loop(self, node: ast.AST, kind: str, bound_hint: str) -> None:
            idx = len(out)
            parent = self.parent_stack[-1] if self.parent_stack else None
            start = line_offset + int(getattr(node, "lineno", 1))
            end = line_offset + int(getattr(node, "end_lineno", getattr(node, "lineno", 1)))
            out.append(
                {
                    "kind": kind,
                    "start_line": start,
                    "end_line": end,
                    "nesting_depth": self.depth + 1,
                    "parent_loop_index": parent,
                    "bound_hint": bound_hint,
                    "estimated_complexity": "unknown" if bound_hint == "unknown" else "O(n)",
                    "has_break": any(isinstance(n, ast.Break) for n in ast.walk(node)),
                    "has_continue": any(isinstance(n, ast.Continue) for n in ast.walk(node)),
                    "has_return": any(isinstance(n, ast.Return) for n in ast.walk(node)),
                }
            )
            self.depth += 1
            self.parent_stack.append(idx)
            self.generic_visit(node)
            self.parent_stack.pop()
            self.depth -= 1

        def visit_For(self, node: ast.For) -> None:  # noqa: N802
            self._add_loop(node, "for", "linear")

        def visit_AsyncFor(self, node: ast.AsyncFor) -> None:  # noqa: N802
            self._add_loop(node, "for", "linear")

        def visit_While(self, node: ast.While) -> None:  # noqa: N802
            self._add_loop(node, "while", "unknown")

    Visitor().visit(tree)
    return out


def _ast_branch_summaries(tree: ast.AST, line_offset: int) -> list[dict]:
    out: list[dict] = []
    branch_types = (ast.If, ast.Match, ast.Try, ast.ExceptHandler)
    for node in ast.walk(tree):
        if isinstance(node, branch_types):
            start = line_offset + int(getattr(node, "lineno", 1))
            end = line_offset + int(getattr(node, "end_lineno", getattr(node, "lineno", 1)))
            out.append({"kind": type(node).__name__, "start_line": start, "end_line": end})
    return out


def _ast_max_loop_depth(tree: ast.AST) -> tuple[int, int]:
    loop_types = (ast.For, ast.AsyncFor, ast.While)
    total = 0

    def walk(node: ast.AST, depth: int) -> int:
        nonlocal total
        next_depth = depth
        if isinstance(node, loop_types):
            total += 1
            next_depth += 1
        best = next_depth
        for child in ast.iter_child_nodes(node):
            best = max(best, walk(child, next_depth))
        return best

    return total, walk(tree, 0)


def _apply_python_ast_selection_features(
    block: CodeBlock,
    parse_text: str,
    line_offset: int,
) -> bool:
    try:
        tree = ast.parse(parse_text)
    except SyntaxError:
        return False

    calls = _ast_call_summaries(tree, line_offset)
    loops = _ast_loop_summaries(tree, line_offset)
    branches = _ast_branch_summaries(tree, line_offset)
    loop_count, max_depth = _ast_max_loop_depth(tree)
    block.calls = [
        c["call_name"]
        for c in calls
        if not c.get("is_builtin_like") and c.get("call_name") not in _KEYWORDS
    ]
    block.error_state = False
    block.features = _build_features(block)
    block.features.loop_count = loop_count
    block.features.max_loop_depth = max_depth
    block.features.loop_summaries = loops
    block.features.call_summaries = calls
    block.features.branch_summaries = branches
    block.features.branch_count = len(branches)
    block.features.container_operations = [
        {
            "operation": c.get("call_name"),
            "operation_type": "method" if c.get("receiver") else "builtin",
            "receiver": c.get("receiver"),
            "line": c.get("start_line"),
            "inside_loop_depth": c.get("inside_loop_depth", 0),
        }
        for c in calls
        if c.get("is_builtin_like")
    ]
    block.features.local_symbols = _extract_local_symbols_python(parse_text)
    block.features.defined_symbols = [block.name]
    flags: set[str] = set()
    for loop in loops:
        if loop.get("bound_hint") == "unknown":
            flags.add("loop_bound_unknown")
    for call in calls:
        if call.get("is_dynamic"):
            flags.add(f"dynamic_call:{call.get('name')}")
    block.features.uncertainty_flags = sorted(flags)
    return True


def _top_level_statement_ranges(text: str) -> list[tuple[int, int]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    ranges: list[tuple[int, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)):
            continue
        if (
            isinstance(node, ast.Expr)
            and isinstance(getattr(node, "value", None), ast.Constant)
            and isinstance(node.value.value, str)
        ):
            continue
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None) or start
        if start is not None and end is not None:
            ranges.append((int(start), int(end)))
    return ranges


def _line_to_byte_offsets(text: str) -> list[int]:
    offsets = [0]
    total = 0
    for line in text.splitlines(keepends=True):
        total += len(line.encode("utf-8", errors="ignore"))
        offsets.append(total)
    return offsets


def _extract_top_level_executable(
    text: str,
    source: bytes,
    file_path: str,
    lang_id: str,
    file_imports: list[dict],
    idx: int,
) -> CodeBlock | None:
    ranges = _top_level_statement_ranges(text)
    if not ranges:
        return None
    start_line = min(r[0] for r in ranges)
    end_line = max(r[1] for r in ranges)
    lines = text.splitlines()
    raw = "\n".join(lines[start_line - 1 : end_line])
    if not raw.strip():
        return None
    offsets = _line_to_byte_offsets(text)
    start_byte = offsets[start_line - 1] if start_line - 1 < len(offsets) else 0
    end_byte = offsets[end_line] if end_line < len(offsets) else len(source)
    source_hash = _sha1(raw)
    stable_id = _make_stable_id(
        file_path,
        lang_id,
        "top_level_executable",
        "<top-level>",
        start_line,
        end_line,
        source_hash,
    )
    synthetic_source = raw.encode("utf-8", errors="ignore")
    parser = Parser(get_language(lang_id))
    tree = parser.parse(synthetic_source)
    root = tree.root_node
    block = CodeBlock(
        block_id=f"{file_path}#{idx}",
        file_path=file_path,
        language_id=lang_id,
        kind="top_level_executable",
        name="<top-level>",
        start_line=start_line,
        end_line=end_line,
        source=raw,
        source_hash=source_hash,
        calls=_extract_calls(root, raw, synthetic_source),
        stable_id=stable_id,
        qualified_name="<top-level>",
        signature=None,
        normalized_hash=_sha1(_normalized_source(raw)),
        start_byte=start_byte,
        end_byte=end_byte,
        body_start_byte=start_byte,
        body_end_byte=end_byte,
        body_start_line=start_line,
        body_end_line=end_line,
        error_state=_node_has_error(root),
        is_container=False,
    )
    loop_count, max_depth = _loop_metrics(root)
    block.features = _build_features(block)
    block.features.loop_count = loop_count
    block.features.max_loop_depth = max_depth
    block.features.loop_summaries = _extract_loop_summaries(root, synthetic_source)
    block.features.call_summaries = _extract_call_summaries(root, synthetic_source)
    block.features.branch_summaries = _extract_branch_summaries(root, synthetic_source)
    block.features.branch_count = len(block.features.branch_summaries)
    block.features.container_operations = _extract_container_operations(root, synthetic_source)
    block.features.import_summaries = list(file_imports)
    block.features.local_symbols = _extract_local_symbols_python(raw)
    block.features.defined_symbols = ["<top-level>"]
    flags = set(block.features.uncertainty_flags)
    if block.error_state:
        flags.add("syntax_error")
    for call in block.features.call_summaries:
        if call.get("is_dynamic"):
            flags.add(f"dynamic_call:{call.get('name')}")
    block.features.uncertainty_flags = sorted(flags)
    return block


def build_selection_block(
    file_path: str,
    language_id: str,
    source: str,
    start_line: int,
    end_line: int,
) -> CodeBlock:
    """Создать synthetic CodeBlock для анализа выделенных строк."""
    raw = source.rstrip("\n")
    parse_text = textwrap.dedent(raw).strip("\n") or raw
    synthetic_source = parse_text.encode("utf-8", errors="ignore")
    source_hash = _sha1(raw)
    line_offset = start_line - 1
    stable_id = _make_stable_id(
        file_path,
        language_id,
        "selection",
        f"<selection:{start_line}-{end_line}>",
        start_line,
        end_line,
        source_hash,
    )

    try:
        parser = Parser(get_language(language_id))
        tree = parser.parse(synthetic_source)
        root = tree.root_node
        calls = _extract_calls(root, parse_text, synthetic_source)
        error_state = _node_has_error(root)
    except Exception:
        root = None
        calls = [m.group(1) for m in _CALL_RE.finditer(parse_text) if m.group(1) not in _KEYWORDS]
        error_state = True

    block = CodeBlock(
        block_id=f"{file_path}#selection:{start_line}-{end_line}:{source_hash[:10]}",
        file_path=file_path,
        language_id=language_id,
        kind="selection",
        name=f"Выделение {start_line}-{end_line}",
        start_line=start_line,
        end_line=end_line,
        source=raw,
        source_hash=source_hash,
        calls=calls,
        stable_id=stable_id,
        qualified_name=f"Выделение {start_line}-{end_line}",
        signature=None,
        normalized_hash=_sha1(_normalized_source(raw)),
        start_byte=0,
        end_byte=len(raw.encode("utf-8", errors="ignore")),
        body_start_byte=0,
        body_end_byte=len(raw.encode("utf-8", errors="ignore")),
        body_start_line=start_line,
        body_end_line=end_line,
        error_state=error_state,
        is_container=False,
    )
    if language_id == "python" and _apply_python_ast_selection_features(
        block, parse_text, line_offset
    ):
        return block

    if root is not None:
        loop_count, max_depth = _loop_metrics(root)
        block.features = _build_features(block)
        block.features.loop_count = loop_count
        block.features.max_loop_depth = max_depth
        block.features.loop_summaries = _extract_loop_summaries(root, synthetic_source)
        block.features.call_summaries = _extract_call_summaries(root, synthetic_source)
        block.features.branch_summaries = _extract_branch_summaries(root, synthetic_source)
        for row in block.features.loop_summaries:
            if row.get("start_line") is not None:
                row["start_line"] += line_offset
            if row.get("end_line") is not None:
                row["end_line"] += line_offset
        for row in block.features.call_summaries:
            if row.get("start_line") is not None:
                row["start_line"] += line_offset
            if row.get("end_line") is not None:
                row["end_line"] += line_offset
        for row in block.features.branch_summaries:
            if row.get("start_line") is not None:
                row["start_line"] += line_offset
            if row.get("end_line") is not None:
                row["end_line"] += line_offset
        block.features.branch_count = len(block.features.branch_summaries)
        block.features.container_operations = _extract_container_operations(root, synthetic_source)
        for row in block.features.container_operations:
            if row.get("line") is not None:
                row["line"] += line_offset
        block.features.local_symbols = _extract_local_symbols_python(parse_text)
        block.features.defined_symbols = [block.name]
        flags = set(block.features.uncertainty_flags)
        if block.error_state:
            flags.add("syntax_error")
        for call in block.features.call_summaries:
            if call.get("is_dynamic"):
                flags.add(f"dynamic_call:{call.get('name')}")
        block.features.uncertainty_flags = sorted(flags)
    else:
        block.features = _build_features(block)
        block.features.uncertainty_flags = ["syntax_error"]
    return block


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
        parameters=list(block.parameters),
    )


def _extract_blocks_in_file(
    tree,
    source: bytes,
    file_path: str,
    lang_id: str,
) -> list[CodeBlock]:
    blocks: list[CodeBlock] = []
    by_stable: dict[str, CodeBlock] = {}
    idx = 0
    full_text = source.decode("utf-8", errors="ignore")
    file_imports = _extract_python_imports(full_text) if lang_id == "python" else []

    def visit(
        node: Node,
        qual_stack: list[str],
        parent_block_id: str | None,
    ) -> None:
        nonlocal idx
        if node.type not in _BLOCK_TYPES:
            for child in node.children:
                visit(child, qual_stack, parent_block_id)
            return

        raw = source[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")
        if not raw.strip():
            for child in node.children:
                visit(child, qual_stack, parent_block_id)
            return

        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        name = _best_name(node, source)
        is_container = node.type in _CONTAINER_TYPES
        kind = _normalize_kind(node.type, is_container)
        parent_block = by_stable.get(parent_block_id) if parent_block_id else None
        if (
            not is_container
            and parent_block is not None
            and parent_block.kind == "class"
            and kind == "function"
        ):
            kind = "constructor" if name == "__init__" else "method"
        source_hash = _sha1(raw)
        normalized_hash = _sha1(_normalized_source(raw))
        qualified = _qualified_name(name, qual_stack, is_container)
        signature = _extract_signature(node, source)
        parameters = _extract_parameters(node, source)
        body_start_line, body_end_line = _body_line_range(
            node, source, start_line, end_line
        )
        body_start_byte, body_end_byte = _body_byte_range(node)
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
            parent_block_id=parent_block_id,
            qualified_name=qualified,
            signature=signature,
            parameters=parameters,
            normalized_hash=normalized_hash,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            body_start_byte=body_start_byte,
            body_end_byte=body_end_byte,
            body_start_line=body_start_line,
            body_end_line=body_end_line,
            error_state=_node_has_error(node),
            is_container=is_container,
        )
        loop_count, max_depth = _loop_metrics(node)
        block.features = _build_features(block)
        block.features.loop_count = loop_count
        block.features.max_loop_depth = max_depth
        block.features.loop_summaries = _extract_loop_summaries(node, source)
        block.features.call_summaries = _extract_call_summaries(node, source)
        block.features.branch_summaries = _extract_branch_summaries(node, source)
        block.features.branch_count = len(block.features.branch_summaries)
        block.features.container_operations = _extract_container_operations(node, source)
        block.features.import_summaries = list(file_imports)
        block.features.local_symbols = _extract_local_symbols_python(raw) if lang_id == "python" else []
        block.features.defined_symbols = [name] if name else []
        block.features.parameters = list(parameters)
        uncertainty = set(block.features.uncertainty_flags)
        if block.error_state:
            uncertainty.add("syntax_error")
        for loop in block.features.loop_summaries:
            if loop.get("bound_hint") in {"unknown", "data_dependent"}:
                uncertainty.add(f"loop_bound_{loop.get('bound_hint')}")
        for call in block.features.call_summaries:
            if call.get("is_dynamic"):
                uncertainty.add(f"dynamic_call:{call.get('name')}")
            if call.get("is_method") and not call.get("receiver"):
                uncertainty.add(f"unknown_receiver:{call.get('name')}")
        block.features.uncertainty_flags = sorted(uncertainty)

        blocks.append(block)
        by_stable[stable_id] = block
        idx += 1

        if parent_block_id and parent_block_id in by_stable:
            by_stable[parent_block_id].children_ids.append(stable_id)

        if is_container:
            child_qual = [name]
            child_parent = stable_id
            for child in node.children:
                visit(child, child_qual, child_parent)
        else:
            child_qual = qual_stack + [name]
            for child in node.children:
                visit(child, child_qual, stable_id)

    visit(tree.root_node, [], None)
    if lang_id == "python":
        top_level = _extract_top_level_executable(full_text, source, file_path, lang_id, file_imports, idx)
        if top_level is not None:
            blocks.append(top_level)
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
