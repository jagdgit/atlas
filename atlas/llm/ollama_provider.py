"""Ollama provider — local-first LLM access over Ollama's REST API.

Talks to a running ``ollama serve`` (default http://localhost:11434). Handles the
quirks of reasoning models (e.g. qwen3): chain-of-thought is separated out of the
returned text so callers always get a clean answer, with the reasoning available
on ``LLMResponse.thinking`` when present.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from atlas.exceptions import LLMError
from atlas.llm.provider import (
    ChatMessage,
    EmbeddingResponse,
    LLMResponse,
)

_THINK_BLOCK = re.compile(r"<think>(.*?)</think>", re.DOTALL)


class OllamaError(LLMError):
    """Ollama-specific failure; part of the typed ``LLMError`` family (ADR-0037)."""


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "qwen3:4b",
        embedding_model: str = "nomic-embed-text",
        *,
        temperature: float = 0.0,
        timeout: float = 120.0,
        keep_alive: str = "5m",
        think: bool = True,
        client: httpx.Client | None = None,
    ) -> None:
        self._host = host.rstrip("/")
        self._model = model
        self._embedding_model = embedding_model
        self._temperature = temperature
        self._keep_alive = keep_alive
        self._think = think
        self._client = client or httpx.Client(base_url=self._host, timeout=timeout)

    # --- public API -----------------------------------------------------
    def generate(self, prompt: str, **options: Any) -> LLMResponse:
        payload = {
            "model": options.get("model", self._model),
            "prompt": prompt,
            "stream": False,
            "keep_alive": options.get("keep_alive", self._keep_alive),
            "options": self._gen_options(options),
        }
        if (system := options.get("system")) is not None:
            payload["system"] = system
        data = self._post_with_think("/api/generate", payload, options)
        clean, thinking = self._split_thinking(
            data.get("response", ""), data.get("thinking")
        )
        return LLMResponse(
            text=clean,
            model=payload["model"],
            thinking=thinking,
            usage=self._usage(data),
            raw=data,
        )

    def chat(self, messages: list[ChatMessage], **options: Any) -> LLMResponse:
        payload = {
            "model": options.get("model", self._model),
            "messages": [m.as_dict() for m in messages],
            "stream": False,
            "keep_alive": options.get("keep_alive", self._keep_alive),
            "options": self._gen_options(options),
        }
        data = self._post_with_think("/api/chat", payload, options)
        message = data.get("message", {}) or {}
        clean, thinking = self._split_thinking(
            message.get("content", ""), message.get("thinking")
        )
        return LLMResponse(
            text=clean,
            model=payload["model"],
            thinking=thinking,
            usage=self._usage(data),
            raw=data,
        )

    def embed(self, texts: list[str], **options: Any) -> EmbeddingResponse:
        model = options.get("model", self._embedding_model)
        data = self._post(
            "/api/embed",
            {
                "model": model,
                "input": texts,
                "keep_alive": options.get("keep_alive", self._keep_alive),
            },
        )
        vectors = data.get("embeddings", [])
        return EmbeddingResponse(vectors=vectors, model=model)

    def list_models(self) -> list[str]:
        data = self._get("/api/tags")
        return [m["name"] for m in data.get("models", [])]

    def health(self) -> bool:
        try:
            self._get("/api/tags")
            return True
        except Exception:  # noqa: BLE001 - health must never raise
            return False

    def close(self) -> None:
        self._client.close()

    # --- internals ------------------------------------------------------
    def _gen_options(self, options: dict[str, Any]) -> dict[str, Any]:
        opts = {"temperature": options.get("temperature", self._temperature)}
        for key in ("num_predict", "top_p", "top_k", "seed", "stop"):
            if key in options:
                opts[key] = options[key]
        return opts

    def _post_with_think(
        self, path: str, payload: dict[str, Any], options: dict[str, Any]
    ) -> dict[str, Any]:
        """POST with the ``think`` flag, retrying without it if unsupported.

        Non-reasoning models reject the ``think`` parameter; rather than special-
        casing model names we try once and gracefully fall back.
        """
        think = options.get("think", self._think)
        timeout = options.get("timeout")
        try:
            return self._post(path, {**payload, "think": think}, timeout=timeout)
        except OllamaError as exc:
            if "think" in str(exc).lower() or "does not support" in str(exc).lower():
                return self._post(path, payload, timeout=timeout)
            raise

    def _post(
        self, path: str, payload: dict[str, Any], *, timeout: float | None = None
    ) -> dict[str, Any]:
        # A per-call ``timeout`` (e.g. the shorter interactive-chat wall-clock, D3.12c)
        # overrides the client default; omit it otherwise so the client default holds.
        try:
            if timeout is not None:
                resp = self._client.post(path, json=payload, timeout=timeout)
            else:
                resp = self._client.post(path, json=payload)
        except httpx.HTTPError as exc:
            raise OllamaError(f"request to {path} failed: {exc}") from exc
        if resp.status_code >= 400:
            raise OllamaError(f"{path} returned {resp.status_code}: {resp.text}")
        return resp.json()

    def _get(self, path: str) -> dict[str, Any]:
        try:
            resp = self._client.get(path)
        except httpx.HTTPError as exc:
            raise OllamaError(f"request to {path} failed: {exc}") from exc
        if resp.status_code >= 400:
            raise OllamaError(f"{path} returned {resp.status_code}: {resp.text}")
        return resp.json()

    @staticmethod
    def _split_thinking(
        text: str, explicit_thinking: str | None
    ) -> tuple[str, str | None]:
        """Separate chain-of-thought from the answer.

        Ollama may put reasoning in a dedicated ``thinking`` field, or a model may
        inline it as ``<think>...</think>`` in the text. Handle both.
        """
        if explicit_thinking:
            return text.strip(), explicit_thinking.strip()
        blocks = _THINK_BLOCK.findall(text)
        if blocks:
            clean = _THINK_BLOCK.sub("", text).strip()
            return clean, "\n".join(b.strip() for b in blocks)
        # Malformed case: some reasoning models (think disabled) inline their
        # reasoning ending in a stray "</think>" with no opening tag.
        if "</think>" in text:
            thinking, _, answer = text.partition("</think>")
            thinking = thinking.replace("<think>", "").strip()
            return answer.strip(), thinking or None
        return text.strip(), None

    @staticmethod
    def _usage(data: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "total_duration",
            "load_duration",
            "prompt_eval_count",
            "eval_count",
            "eval_duration",
        )
        return {k: data[k] for k in keys if k in data}
