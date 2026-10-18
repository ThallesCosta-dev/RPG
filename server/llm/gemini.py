"""Provedor Gemini (free tier do AI Studio) — §17.3. Chave e nomes de modelo vêm do .env."""
from __future__ import annotations

import asyncio
import os
import time
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
        self._indisponivel_ate: dict[str, float] = {}       # cooldown por modelo (429 de cota é por modelo)
        self._sem_thinking_cfg: set[str] = set()            # modelos que rejeitaram thinking_config

    @property
    def ativo(self) -> bool:
        return bool(self.api_key)

    def _cliente(self):
        if self._client is None:
            from google import genai                 # import tardio: dependência opcional
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _config(self, ctx: Contexto, modelo: str | None = None, sem_pensar: bool = False, **extra):
        from google.genai import types
        nivel = os.getenv("GEMINI_THINKING_LEVEL", "")           # ex.: "low" (Gemini 3.x) ou "0" (budget, Gemini 2.5)
        if sem_pensar and nivel and modelo and modelo not in self._sem_thinking_cfg:
            try:                                              # Flash "pensa" antes de responder; na narração isso custa segundos
                extra["thinking_config"] = types.ThinkingConfig(thinking_budget=int(nivel)) if nivel.isdigit() else types.ThinkingConfig(thinking_level=nivel)
            except Exception:
                pass
        return types.GenerateContentConfig(system_instruction=ctx.system_prompt, **extra)

    def modelo_disponivel(self, modelo: str) -> bool:
        return self._indisponivel_ate.get(modelo, 0) < time.time()

    def penalizar_modelo(self, modelo: str, segundos: float = 120) -> None:
        self._indisponivel_ate[modelo] = time.time() + segundos

    @staticmethod
    def _cota(exc: Exception) -> bool:
        msg = str(exc)
        return "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower()

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
        candidatos = [self.modelo_plano] if ctx.economico else [self.modelo_narracao, self.modelo_plano]
        modelos = [m for m in dict.fromkeys(candidatos) if self.modelo_disponivel(m)] or [self.modelo_plano]
        for i, modelo in enumerate(modelos):
            self.modelo_atual = modelo
            try:
                stream = await self._cliente().aio.models.generate_content_stream(
                    model=modelo, contents=ctx.conteudo, config=self._config(ctx, modelo, sem_pensar=True, temperature=0.9))
                ultimo = None
                async for chunk in stream:
                    ultimo = chunk
                    if chunk.text:
                        yield chunk.text
                if ultimo is not None:
                    self._tokens(ultimo)
                return
            except Exception as exc:
                msg = str(exc).lower()
                if ("thinking" in msg or "invalid_argument" in msg or "400" in msg) and modelo not in self._sem_thinking_cfg                         and os.getenv("GEMINI_THINKING_LEVEL", ""):
                    self._sem_thinking_cfg.add(modelo)                       # modelo não aceita o parâmetro: tenta sem
                    modelos.insert(i + 1, modelo)
                    continue
                if self._cota(exc):
                    self.penalizar_modelo(modelo, 120)                       # cota deste modelo; o lite continua valendo
                if i == len(modelos) - 1 or not (self._transitorio(exc) or self._cota(exc)):
                    raise
                await asyncio.sleep(1)                                       # principal indisponível: cai para o lite

    async def estruturado(self, ctx: Contexto):
        return await self._gerar_json(ctx, 0.3)
