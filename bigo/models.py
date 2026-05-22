from __future__ import annotations

from dataclasses import dataclass, field

BIG_O_CLASSES = (
    "O(1)",
    "O(log n)",
    "O(n)",
    "O(n log n)",
    "O(n^2)",
    "O(n^3)",
    "O(2^n)",
    "O(n!)",
)

BIG_O_ORDER = {name: i for i, name in enumerate(BIG_O_CLASSES)}


@dataclass(slots=True)
class BlockFeatures:
    loop_count: int = 0
    max_loop_depth: int = 0
    has_log_pattern: bool = False
    has_sort_call: bool = False
    self_call_count: int = 0


@dataclass(slots=True)
class CodeBlock:
    block_id: str
    file_path: str
    language_id: str
    kind: str
    name: str
    start_line: int
    end_line: int
    source: str
    source_hash: str
    calls: list[str] = field(default_factory=list)
    called_by: list[str] = field(default_factory=list)
    features: BlockFeatures = field(default_factory=BlockFeatures)
    complexity: str | None = None
    reason: str = ""
    source_kind: str = "static"  # static | llm | cache

    @property
    def short_name(self) -> str:
        if self.name:
            return self.name
        return self.kind


@dataclass(slots=True)
class ProjectAnalysis:
    root_path: str
    files_scanned: list[str]
    blocks_by_file: dict[str, list[CodeBlock]]
    all_blocks: list[CodeBlock]
    review_text: str = ""

    def complexity_counts(self) -> dict[str, int]:
        counts = {k: 0 for k in BIG_O_CLASSES}
        for b in self.all_blocks:
            if b.complexity in counts:
                counts[b.complexity] += 1
        return counts

