"""Provedor Gemini (free tier do AI Studio) — §17.3. Chave e nomes de modelo vêm do .env."""
from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

from .schemas import Contexto


class GeminiProvider:
    nome = "gemini"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.modelo_plano = os.getenv("MODELO_PLANO", "gemini-3.5-flash-lite")
        self.modelo_narracao = os.getenv("MODELO_NARRACAO", "gemini-3.8-flash")
        self.modelo_atual = self.modelo_plano
        self.ultimos_tokens: tuple[int | None, int | None] = (None, None)
        self._client = None

    @property
    def ativo(self) -> bool:
        return bool(self.api_key)

    def _cliente(self):
        if self._client is None:
            from google import genai                 # import tardio: dependência opcional
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _config(self, ctx: Contexto, **extra):
        from google.genai import types
        return types.GenerateContentConfig(system_instruction=ctx.system_prompt, **extra)

    def _tokens(self, resp) -> None:
        u = getattr(resp, "usage_metadata", None)
        if u:
            self.ultimos_tokens = (getattr(u, "prompt_token_count", None), getattr(u, "candidates_token_count", None))

    @staticmethod
    def _transitorio(exc: Exception) -> bool:
        msg = str(exc)
        return "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower()

    async def _gerar_json(self, ctx: Contexto, temperatura: float):
        self.modelo_atual = self.modelo_plano
        for tentativa in range(2):
            try:
                resp = await self._cliente().aio.models.generate_content(
                    model=self.modelo_plano, contents=ctx.conteudo,
                    config=self._config(ctx, response_mime_type="application/json", response_schema=ctx.schema, temperature=temperatura))
                break
            except Exception as exc:
                if tentativa == 1 or not self._transitorio(exc):
                    raise
                await asyncio.sleep(2)                                   # pico de demanda: tenta uma vez mais
        self._tokens(resp)
        return ctx.schema.model_validate_json(resp.text)            # inválido → exceção → próximo provedor

    async def planejar(self, ctx: Contexto):
        return await self._gerar_json(ctx, 0.4)

    async def narrar_stream(self, ctx: Contexto) -> AsyncIterator[str]:
        modelos = [self.modelo_plano] if ctx.economico else [self.modelo_narracao, self.modelo_plano]
        for i, modelo in enumerate(modelos):
            self.modelo_atual = modelo
            try:
                stream = await self._cliente().aio.models.generate_content_stream(
                    model=modelo, contents=ctx.conteudo, config=self._config(ctx, temperature=0.9))
                ultimo = None
                async for chunk in stream:
                    ultimo = chunk
                    if chunk.text:
                        yield chunk.text
                if ultimo is not None:
                    self._tokens(ultimo)
                return
            except Exception as exc:
                if i == len(modelos) - 1 or not self._transitorio(exc):
                    raise
                await asyncio.sleep(1)                                   # modelo principal sobrecarregado: cai para o lite

    async def estruturado(self, ctx: Contexto):
        return await self._gerar_json(ctx, 0.3)
