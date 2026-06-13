from __future__ import annotations

import concurrent.futures
import json
from dataclasses import asdict
from typing import Any

try:
    import requests
except ModuleNotFoundError:  # pragma: no cover - depends on local runtime
    requests = None

from .llm_contract import SYSTEM_INSTRUCTIONS
from .models import BIG_O_CLASSES, CodeBlock

OLLAMA_KEEP_ALIVE = "30m"
ESTIMATE_NUM_PREDICT = 128
ESTIMATE_NUM_CTX = 4096


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
    return mapping.get(low, "unknown")


class OllamaBigOClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5-coder:7b",
        timeout_s: float = 45.0,
        max_workers: int = 1,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.max_workers = max(1, int(max_workers))
        self._session = requests.Session() if requests is not None else None

    def is_available(self) -> bool:
        if self._session is None:
            return False
        try:
            r = self._session.get(f"{self.base_url}/api/tags", timeout=0.9)
            return r.ok
        except Exception:
            return False

    def prewarm(self, *, keep_alive: str = OLLAMA_KEEP_ALIVE, timeout_s: float = 20.0) -> bool:
        if self._session is None:
            return False
        try:
            resp = self._session.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": "",
                    "stream": False,
                    "keep_alive": keep_alive,
                    "options": {"num_predict": 1, "temperature": 0.0},
                },
                timeout=timeout_s,
            )
            return resp.ok
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
        """POST /api/chat with compact JSON IR; response must be JSON."""
        if self._session is None:
            raise RuntimeError("requests is not installed; Ollama client is unavailable")
        url = f"{self.base_url}/api/chat"
        body = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False, separators=(",", ":")),
                },
            ],
            "options": {
                "temperature": 0.0,
                "seed": 7,
                "num_predict": ESTIMATE_NUM_PREDICT,
                "num_ctx": ESTIMATE_NUM_CTX,
            },
            "keep_alive": OLLAMA_KEEP_ALIVE,
        }
        resp = self._session.post(url, json=body, timeout=self.timeout_s)
        resp.raise_for_status()
        data = resp.json()
        message = data.get("message") or {}
        content = (message.get("content") or "").strip()
        telemetry = self._extract_telemetry(data)
        from .llm_contract import extract_json_object

        return extract_json_object(content), telemetry

    def chat_json(
        self,
        *,
        system: str,
        payload: dict,
        num_predict: int = 192,
        temperature: float = 0.1,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Small generic JSON chat helper for non-estimation Big-O tasks."""
        if self._session is None:
            raise RuntimeError("requests is not installed; Ollama client is unavailable")
        body = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                },
            ],
            "options": {
                "temperature": temperature,
                "seed": 11,
                "num_predict": max(32, int(num_predict)),
                "num_ctx": ESTIMATE_NUM_CTX,
            },
            "keep_alive": OLLAMA_KEEP_ALIVE,
        }
        resp = self._session.post(
            f"{self.base_url}/api/chat",
            json=body,
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        message = data.get("message") or {}
        content = (message.get("content") or "").strip()
        from .llm_contract import extract_json_object

        return extract_json_object(content), self._extract_telemetry(data)

    def _prompt_for_block(self, block: CodeBlock) -> str:
        """Legacy prompt for analyze_many compatibility."""
        return (
            "Estimate the upper-bound Big-O complexity for one code block.\n"
            "Return strict JSON only: {\"complexity\":\"O(n)\",\"reason\":\"short reason\"}.\n"
            f"Allowed classes: {', '.join(BIG_O_CLASSES)}, unknown.\n"
            f"Language: {block.language_id}\n"
            f"Kind: {block.kind}\n"
            f"Name: {block.name}\n"
            f"Features: {json.dumps(asdict(block.features), ensure_ascii=False)}\n"
            f"Calls: {block.calls}\n"
            f"Code:\n{block.source}\n"
        )

    def _query_one(self, block: CodeBlock) -> tuple[str, str]:
        if self._session is None:
            return "unknown", "requests is not installed; Ollama client is unavailable"
        prompt = self._prompt_for_block(block)
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0, "seed": 7, "num_predict": ESTIMATE_NUM_PREDICT},
            "keep_alive": OLLAMA_KEEP_ALIVE,
        }
        resp = self._session.post(url, json=payload, timeout=self.timeout_s)
        resp.raise_for_status()
        data = resp.json()
        txt = data.get("response", "").strip()
        if not txt:
            return "unknown", "Empty Ollama response."
        try:
            row = json.loads(txt)
            comp = normalize_complexity(str(row.get("complexity", "")))
            reason = str(row.get("reason", "")).strip() or "Ollama estimate."
            return comp, reason
        except json.JSONDecodeError:
            comp = normalize_complexity(txt.splitlines()[0])
            return comp, "Ollama returned plain text; normalized conservatively."

    def analyze_many(self, blocks: list[CodeBlock]) -> dict[str, tuple[str, str]]:
        out: dict[str, tuple[str, str]] = {}
        if not blocks:
            return out
        if not self.is_available():
            for b in blocks:
                out[b.block_id] = ("unknown", "Ollama is unavailable.")
            return out
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            fut_to_id = {ex.submit(self._query_one, b): b.block_id for b in blocks}
            for fut in concurrent.futures.as_completed(fut_to_id):
                bid = fut_to_id[fut]
                try:
                    out[bid] = fut.result()
                except Exception as exc:  # noqa: BLE001
                    out[bid] = ("unknown", f"Ollama error: {exc}")
        return out
