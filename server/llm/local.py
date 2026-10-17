"""LLM local via endpoint OpenAI-compatível (llama.cpp server / Ollama) — nível 3 da escada."""
from __future__ import annotations

import json
import os
import re
from collections.abc import AsyncIterator

import httpx

from .schemas import Contexto

RE_JSON = re.compile(r"\{.*\}", re.S)


class LocalProvider:
    nome = "local"

    def __init__(self, url: str | None = None, modelo: str | None = None):
        self.url = (url if url is not None else os.getenv("LLM_LOCAL_URL", "")).rstrip("/")
        self.modelo = modelo or os.getenv("LLM_LOCAL_MODELO", "gemma3:12b")
        self.modelo_atual = self.modelo
        self.ultimos_tokens: tuple[int | None, int | None] = (None, None)
        self.timeout = float(os.getenv("LLM_LOCAL_TIMEOUT", "120"))

    @property
    def ativo(self) -> bool:
        return bool(self.url)

    def _mensagens(self, ctx: Contexto, json_mode: bool) -> list[dict]:
        system = ctx.system_prompt
        if json_mode and ctx.schema is not None:
            system += "\n\nResponda SOMENTE com um JSON válido que siga este esquema:\n" + json.dumps(ctx.schema.model_json_schema(), ensure_ascii=False)
        return [{"role": "system", "content": system}, {"role": "user", "content": ctx.conteudo}]

    async def _completar(self, ctx: Contexto, json_mode: bool, temperatura: float) -> str:
        corpo = {"model": self.modelo, "messages": self._mensagens(ctx, json_mode), "temperature": temperatura, "stream": False}
        if json_mode:
            corpo["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            r = await cli.post(f"{self.url}/chat/completions", json=corpo)
            r.raise_for_status()
            data = r.json()
        uso = data.get("usage") or {}
        self.ultimos_tokens = (uso.get("prompt_tokens"), uso.get("completion_tokens"))
        return data["choices"][0]["message"]["content"]

    @staticmethod
    def _extrair_json(texto: str) -> str:
        texto = texto.strip()
        if texto.startswith("```"):
            texto = texto.strip("`")
            texto = texto[4:] if texto.startswith("json") else texto
        m = RE_JSON.search(texto)
        return m.group(0) if m else texto

    async def planejar(self, ctx: Contexto):
        texto = await self._completar(ctx, True, 0.3)
        return ctx.schema.model_validate_json(self._extrair_json(texto))

    async def estruturado(self, ctx: Contexto):
        texto = await self._completar(ctx, True, 0.2)
        return ctx.schema.model_validate_json(self._extrair_json(texto))

    async def narrar_stream(self, ctx: Contexto) -> AsyncIterator[str]:
        corpo = {"model": self.modelo, "messages": self._mensagens(ctx, False), "temperature": 0.9, "stream": True}
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            async with cli.stream("POST", f"{self.url}/chat/completions", json=corpo) as r:
                r.raise_for_status()
                async for linha in r.aiter_lines():
                    if not linha.startswith("data:"):
                        continue
                    dado = linha[5:].strip()
                    if dado == "[DONE]":
                        break
                    try:
                        delta = json.loads(dado)["choices"][0]["delta"].get("content")
                    except (ValueError, KeyError, IndexError):
                        continue
                    if delta:
                        yield delta
