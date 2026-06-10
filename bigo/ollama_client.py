from __future__ import annotations

import concurrent.futures
import json
from dataclasses import asdict
from typing import Any

import requests

from .llm_contract import SYSTEM_INSTRUCTIONS
from .models import BIG_O_CLASSES, CodeBlock


def normalize_complexity(raw: str) -> str:
    t = (raw or "").strip()
    if t in BIG_O_CLASSES:
        return t
    if t == "unknown":
        return "unknown"
    low = t.lower().replace(" ", "")
    mapping = {
        "o(1)": "O(1)",
        "o(logn)": "O(log n)",
        "o(n)": "O(n)",
        "o(nlogn)": "O(n log n)",
        "o(n^2)": "O(n^2)",
        "o(n²)": "O(n^2)",
        "o(n^2logn)": "O(n^2 log n)",
        "o(n^3)": "O(n^3)",
        "o(2^n)": "O(2^n)",
        "o(n!)": "O(n!)",
    }
    return mapping.get(low, "O(n)")


class OllamaBigOClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5-coder:7b",
        timeout_s: float = 45.0,
        max_workers: int = 5,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.max_workers = max_workers

    def is_available(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=0.9)
            return r.ok
        except Exception:
            return False

    def _extract_telemetry(self, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "total_duration": data.get("total_duration"),
            "load_duration": data.get("load_duration"),
            "prompt_eval_count": data.get("prompt_eval_count"),
            "eval_count": data.get("eval_count"),
        }

    def chat_big_o_estimate(self, user_payload: dict) -> tuple[dict[str, Any], dict[str, Any]]:
        """POST /api/chat — компактный JSON-IR блока, ответ JSON по контракту."""
        url = f"{self.base_url}/api/chat"
        body = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False, indent=2),
                },
            ],
            "options": {"temperature": 0.0},
        }
        resp = requests.post(url, json=body, timeout=self.timeout_s)
        resp.raise_for_status()
        data = resp.json()
        message = data.get("message") or {}
        content = (message.get("content") or "").strip()
        telemetry = self._extract_telemetry(data)
        from .llm_contract import extract_json_object

        return extract_json_object(content), telemetry

    def _prompt_for_block(self, block: CodeBlock) -> str:
        """Legacy prompt для analyze_many / review."""
        return (
            "Ты статический ассистент по оценке алгоритмической сложности.\n"
            "Выбери ТОЛЬКО один класс Big-O из списка:\n"
            f"{', '.join(BIG_O_CLASSES)}\n\n"
            "Верни JSON строго формата:\n"
            '{"complexity":"O(n)","reason":"краткое обоснование"}\n\n'
            f"Язык: {block.language_id}\n"
            f"Тип блока: {block.kind}\n"
            f"Имя блока: {block.name}\n"
            f"Признаки: {json.dumps(asdict(block.features), ensure_ascii=False)}\n"
            f"Вызовы: {block.calls}\n\n"
            "Код блока:\n"
            "```"
            f"{block.source}"
            "```\n"
        )

    def _query_one(self, block: CodeBlock) -> tuple[str, str]:
        prompt = self._prompt_for_block(block)
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
        }
        resp = requests.post(url, json=payload, timeout=self.timeout_s)
        resp.raise_for_status()
        data = resp.json()
        txt = data.get("response", "").strip()
        if not txt:
            return "O(n)", "Пустой ответ Ollama, fallback на O(n)."
        try:
            row = json.loads(txt)
            comp = normalize_complexity(str(row.get("complexity", "")))
            reason = str(row.get("reason", "")).strip() or "Оценка от Ollama."
            return comp, reason
        except json.JSONDecodeError:
            comp = normalize_complexity(txt.splitlines()[0])
            return comp, "Оценка от Ollama (plain text)."

    def analyze_many(self, blocks: list[CodeBlock]) -> dict[str, tuple[str, str]]:
        out: dict[str, tuple[str, str]] = {}
        if not blocks:
            return out
        if not self.is_available():
            for b in blocks:
                out[b.block_id] = ("O(n)", "Ollama недоступен, fallback на O(n).")
            return out
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            fut_to_id = {ex.submit(self._query_one, b): b.block_id for b in blocks}
            for fut in concurrent.futures.as_completed(fut_to_id):
                bid = fut_to_id[fut]
                try:
                    out[bid] = fut.result()
                except Exception as exc:  # noqa: BLE001
                    out[bid] = ("O(n)", f"Ошибка Ollama: {exc}")
        return out
