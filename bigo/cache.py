from __future__ import annotations

import json
import os
from dataclasses import asdict

from .models import AnalysisResult, BlockFeatures, CodeBlock


class BlockComplexityCache:
    """Кэш результатов Big-O на уровне блока (JSON файл)."""

    VERSION = 2

    def __init__(self, cache_path: str):
        self.cache_path = cache_path
        self._data: dict[str, dict] = {}
        self._applied: dict[str, AnalysisResult] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.cache_path):
            self._data = {}
            return
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            self._data = {}
            return
        if payload.get("version") != self.VERSION:
            self._data = {}
            return
        self._data = payload.get("items", {})

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        payload = {"version": self.VERSION, "items": self._data}
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    @staticmethod
    def make_key(block: CodeBlock) -> str:
        return (
            f"{block.file_path}|{block.start_line}|{block.end_line}|"
            f"{block.kind}|{block.name}|{block.source_hash}"
        )

    def try_apply(self, block: CodeBlock) -> bool:
        key = self.make_key(block)
        row = self._data.get(key)
        if not row:
            return False
        complexity = row.get("complexity")
        reason = row.get("reason", "")
        if not complexity or complexity == "unknown":
            return False
        block.complexity = complexity
        block.reason = reason
        source_kind = str(row.get("source_kind") or "cache")
        if source_kind in {"llm", "ai"}:
            block.source_kind = "llm"
        elif source_kind in {"rule", "static"}:
            block.source_kind = "static"
        else:
            block.source_kind = "cache"
        self._applied[key] = AnalysisResult(
            complexity=block.complexity,
            reason=block.reason,
            reasoning_summary=block.reason,
            analyzer_kind=block.source_kind if block.source_kind in {"llm", "static"} else "cache",
            features=block.features,
        )
        return True

    def applied_result_for(self, block: CodeBlock) -> AnalysisResult | None:
        return self._applied.get(self.make_key(block))

    def upsert(self, block: CodeBlock) -> None:
        if not block.complexity or block.complexity == "unknown":
            return
        key = self.make_key(block)
        self._data[key] = {
            "complexity": block.complexity,
            "reason": block.reason,
            "source_kind": block.source_kind,
            "features": asdict(block.features),
        }

    def prune_to(self, blocks: list[CodeBlock]) -> None:
        alive = {self.make_key(b) for b in blocks}
        self._data = {k: v for k, v in self._data.items() if k in alive}

