"""LLM local — nível 3 da escada. Ollama (API nativa, com saída estruturada por JSON Schema) ou qualquer
endpoint OpenAI-compatível (llama.cpp server, LM Studio).

`LLM_LOCAL_URL` terminando em `/v1` num host do Ollama → usa `/api/chat` com `format=<schema>` (mais confiável
para modelos pequenos do que pedir JSON no prompt). Outros hosts → `/chat/completions`.
"""
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
        self.timeout = float(os.getenv("LLM_LOCAL_TIMEOUT", "180"))
        self.timeout_planejar = self.timeout          # a cadeia usa isto no wait_for
        self.num_ctx = int(os.getenv("LLM_LOCAL_CTX", "8192"))
        self._ollama: bool | None = None

    @property
    def ativo(self) -> bool:
        return bool(self.url)

    @property
    def base_ollama(self) -> str:
        return self.url[:-3] if self.url.endswith("/v1") else self.url

    async def _eh_ollama(self, cli: httpx.AsyncClient) -> bool:
        if self._ollama is None:
            try:
                r = await cli.get(f"{self.base_ollama}/api/tags", timeout=5)
                self._ollama = r.status_code == 200 and "models" in r.json()
            except Exception:
                self._ollama = False
        return self._ollama

    def _mensagens(self, ctx: Contexto, json_mode: bool, com_schema_no_prompt: bool) -> list[dict]:
        system = ctx.system_prompt
        if json_mode and com_schema_no_prompt and ctx.schema is not None:
            system += "\n\nResponda SOMENTE com um objeto JSON (uma instância, não o esquema) que siga este esquema:\n" + \
                      json.dumps(ctx.schema.model_json_schema(), ensure_ascii=False)
        return [{"role": "system", "content": system}, {"role": "user", "content": ctx.conteudo}]

    @staticmethod
    def _extrair_json(texto: str) -> str:
        texto = texto.strip()
        if texto.startswith("```"):
            texto = texto.strip("`")
            texto = texto[4:] if texto.startswith("json") else texto
        m = RE_JSON.search(texto)
        return m.group(0) if m else texto

    async def _completar(self, ctx: Contexto, json_mode: bool, temperatura: float) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            if await self._eh_ollama(cli):
                corpo = {"model": self.modelo, "messages": self._mensagens(ctx, json_mode, False), "stream": False,
                         "options": {"temperature": temperatura, "num_ctx": self.num_ctx}}
                if json_mode and ctx.schema is not None:
                    corpo["format"] = ctx.schema.model_json_schema()
                r = await cli.post(f"{self.base_ollama}/api/chat", json=corpo)
                r.raise_for_status()
                data = r.json()
                self.ultimos_tokens = (data.get("prompt_eval_count"), data.get("eval_count"))
                return data["message"]["content"]
            corpo = {"model": self.modelo, "messages": self._mensagens(ctx, json_mode, True), "temperature": temperatura, "stream": False}
            if json_mode:
                corpo["response_format"] = {"type": "json_object"}
            r = await cli.post(f"{self.url}/chat/completions", json=corpo)
            r.raise_for_status()
            data = r.json()
            uso = data.get("usage") or {}
            self.ultimos_tokens = (uso.get("prompt_tokens"), uso.get("completion_tokens"))
            return data["choices"][0]["message"]["content"]

    async def planejar(self, ctx: Contexto):
        texto = await self._completar(ctx, True, 0.3)
        return ctx.schema.model_validate_json(self._extrair_json(texto))

    async def estruturado(self, ctx: Contexto):
        texto = await self._completar(ctx, True, 0.2)
        return ctx.schema.model_validate_json(self._extrair_json(texto))

    async def narrar_stream(self, ctx: Contexto) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            if await self._eh_ollama(cli):
                corpo = {"model": self.modelo, "messages": self._mensagens(ctx, False, False), "stream": True,
                         "options": {"temperature": 0.9, "num_ctx": self.num_ctx}}
                async with cli.stream("POST", f"{self.base_ollama}/api/chat", json=corpo) as r:
                    r.raise_for_status()
                    async for linha in r.aiter_lines():
                        if not linha.strip():
                            continue
                        try:
                            d = json.loads(linha)
                        except ValueError:
                            continue
                        if d.get("done"):
                            self.ultimos_tokens = (d.get("prompt_eval_count"), d.get("eval_count"))
                            break
                        delta = (d.get("message") or {}).get("content")
                        if delta:
                            yield delta
                return
            corpo = {"model": self.modelo, "messages": self._mensagens(ctx, False, False), "temperature": 0.9, "stream": True}
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
