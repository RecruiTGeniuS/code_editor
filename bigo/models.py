from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .dependency_graph import DependencyGraph

BIG_O_CLASSES = (
    "O(1)",
    "O(log n)",
    "O(n)",
    "O(n log n)",
    "O(n^2)",
    "O(n^2 log n)",
    "O(n^3)",
    "O(2^n)",
    "O(n!)",
)

BIG_O_ORDER = {name: i for i, name in enumerate(BIG_O_CLASSES)}

NON_RANKED_COMPLEXITIES = frozenset({"unknown", "N/A", "container"})


def complexity_rank(complexity: str | None) -> int:
    if not complexity or complexity in NON_RANKED_COMPLEXITIES:
        return -1
    return BIG_O_ORDER.get(complexity, -1)


def is_ranked_complexity(complexity: str | None) -> bool:
    return complexity_rank(complexity) >= 0


def max_complexity(a: str | None, b: str | None) -> str | None:
    if not is_ranked_complexity(a):
        return b if is_ranked_complexity(b) else a
    if not is_ranked_complexity(b):
        return a
    return a if complexity_rank(a) >= complexity_rank(b) else b


@dataclass(slots=True)
class BlockFeatures:
    """Признаки блока для rule-based анализа и AI fallback (v1 + расширения)."""

    loop_count: int = 0
    max_loop_depth: int = 0
    branch_count: int = 0
    call_count: int = 0
    project_call_count: int = 0
    external_call_count: int = 0
    has_recursion: bool = False
    recursion_kind: str | None = None
    has_sorting: bool = False
    has_log_pattern: bool = False
    container_operations: list[dict] = field(default_factory=list)
    loop_summaries: list[dict] = field(default_factory=list)
    call_summaries: list[dict] = field(default_factory=list)
    branch_summaries: list[dict] = field(default_factory=list)
    import_summaries: list[dict] = field(default_factory=list)
    defined_symbols: list[str] = field(default_factory=list)
    local_symbols: list[str] = field(default_factory=list)
    parameters: list[str] = field(default_factory=list)
    uncertainty_flags: list[str] = field(default_factory=list)
    # Legacy-поля (используются static_analyzer и project_index v1).
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
    source_kind: str = "static"  # static | llm | cache | rule
    stable_id: str | None = None
    parent_block_id: str | None = None
    qualified_name: str | None = None
    signature: str | None = None
    parameters: list[str] = field(default_factory=list)
    normalized_hash: str | None = None
    start_byte: int | None = None
    end_byte: int | None = None
    body_start_byte: int | None = None
    body_end_byte: int | None = None
    body_start_line: int | None = None
    body_end_line: int | None = None
    error_state: bool = False
    is_container: bool = False
    children_ids: list[str] = field(default_factory=list)

    @property
    def short_name(self) -> str:
        if self.name:
            return self.name
        return self.kind

    def get_display_name(self) -> str:
        if self.qualified_name:
            return self.qualified_name
        if self.name:
            return self.name
        return self.kind


@dataclass(slots=True)
class AnalysisResult:
    """Результат анализа одного блока (rule / static / llm)."""

    complexity: str | None = None
    reason: str = ""
    confidence: str = "medium"
    assumptions: list[str] = field(default_factory=list)
    reasoning_summary: str = ""
    analyzer_kind: str = "rule"
    needs_human_review: bool = False
    evidence_ranges: list[dict] = field(default_factory=list)
    duration_ms: int | None = None
    model_id: str | None = None
    prompt_version: str | None = None
    rules_version: str | None = None
    cache_key: str | None = None
    dependency_hash: str | None = None
    payload_hash: str | None = None
    features: BlockFeatures | None = None
    optimization_advice: list[str] = field(default_factory=list)

    def is_uncertain(self) -> bool:
        if self.needs_human_review:
            return True
        if self.complexity is None:
            return True
        return self.confidence == "low"

    def short_label(self) -> str:
        return self.complexity or "O(?)"

    @classmethod
    def from_static_tuple(
        cls,
        complexity: str | None,
        reason: str,
        *,
        features: BlockFeatures | None = None,
    ) -> AnalysisResult:
        """Собрать результат из текущего API analyze_block_static (без смены анализатора)."""
        needs_review = complexity is None
        return cls(
            complexity=complexity,
            reason=reason,
            reasoning_summary=reason,
            confidence="low" if needs_review else "medium",
            analyzer_kind="rule",
            needs_human_review=needs_review,
            features=features,
        )


@dataclass(slots=True)
class ProjectAnalysis:
    root_path: str
    files_scanned: list[str]
    blocks_by_file: dict[str, list[CodeBlock]]
    all_blocks: list[CodeBlock]
    review_text: str = ""
    dependency_graph: DependencyGraph | None = None
    ai_blocks_sent: int = 0
    ai_llm_errors: int = 0
    ollama_available: bool | None = None
    block_results: dict[str, "AnalysisResult"] = field(default_factory=dict)
    storage_path: str | None = None
    project_recommendations: dict[str, str] = field(default_factory=dict)

    def complexity_counts(self) -> dict[str, int]:
        from .block_utils import analyzable_blocks

        counts = {k: 0 for k in BIG_O_CLASSES}
        for b in analyzable_blocks(self.all_blocks):
            if b.complexity in counts:
                counts[b.complexity] += 1
        return counts

    def source_kind_counts(self) -> dict[str, int]:
        from .block_utils import analyzable_blocks

        counts: dict[str, int] = {}
        for b in analyzable_blocks(self.all_blocks):
            key = b.source_kind or "static"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def unknown_block_count(self) -> int:
        from .block_utils import analyzable_blocks

        n = 0
        for b in analyzable_blocks(self.all_blocks):
            if b.complexity in (None, "unknown"):
                n += 1
        return n
