"""Cadeia de provedores + gestor de cota + escada de degradação (§10.4, §17.4).

Mesma interface para todos: `planejar(ctx)`, `narrar_stream(ctx)`, `estruturado(ctx)` (memória, mapa, extração).
O último provedor (heurístico + templates) nunca falha.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from collections.abc import AsyncIterator

from .schemas import Contexto

log = logging.getLogger("ai_vtt.llm")

NIVEIS = {1: "Normal", 2: "Econômico", 3: "Local", 4: "Sem LLM"}


class GestorCota:
    """Conta requisições por minuto e por dia por provedor; limites do .env. Erros 429 abrem um cooldown."""

    def __init__(self, rpm: int | None = None, rpd: int | None = None, limiar: float | None = None):
        self.rpm = rpm if rpm is not None else int(os.getenv("COTA_RPM", "10"))
        self.rpd = rpd if rpd is not None else int(os.getenv("COTA_RPD", "250"))
        self.limiar = limiar if limiar is not None else float(os.getenv("COTA_LIMIAR_ECONOMICO", "0.7"))
        self._minuto: dict[str, deque] = {}
        self._dia: dict[str, deque] = {}
        self._cooldown: dict[str, float] = {}

    def _limpar(self, nome: str) -> None:
        agora = time.time()
        m = self._minuto.setdefault(nome, deque())
        d = self._dia.setdefault(nome, deque())
        while m and m[0] < agora - 60:
            m.popleft()
        while d and d[0] < agora - 86400:
            d.popleft()

    def registrar(self, nome: str) -> None:
        self._limpar(nome)
        t = time.time()
        self._minuto[nome].append(t)
        self._dia[nome].append(t)

    def penalizar(self, nome: str, segundos: float = 60) -> None:
        self._cooldown[nome] = time.time() + segundos

    def disponivel(self, nome: str, limitado: bool = True) -> bool:
        if self._cooldown.get(nome, 0) > time.time():
            return False
        if not limitado:
            return True
        self._limpar(nome)
        return len(self._minuto[nome]) < self.rpm and len(self._dia[nome]) < self.rpd

    def fracao_diaria(self, nome: str) -> float:
        self._limpar(nome)
        return len(self._dia[nome]) / self.rpd if self.rpd else 0.0

    def resumo(self, nome: str) -> dict:
        self._limpar(nome)
        return {"rpm_usado": len(self._minuto[nome]), "rpm": self.rpm, "rpd_usado": len(self._dia[nome]), "rpd": self.rpd,
                "cooldown_s": max(0, round(self._cooldown.get(nome, 0) - time.time()))}


class CadeiaProvedores:
    def __init__(self, provedores: list, cota: GestorCota | None = None, store=None):
        self.provedores = provedores            # [GeminiProvider, LocalProvider, HeuristicoProvider]
        self.cota = cota or GestorCota()
        self.store = store                      # EventStore para `chamadas_llm` (opcional)
        self.nivel_forcado: int | None = None
        self.ultimo_provedor: str = "heuristico"

    # ---------------------------------------------------------------- níveis
    def _por_nome(self, nome: str):
        return next((p for p in self.provedores if p.nome == nome), None)

    def nivel(self) -> int:
        if self.nivel_forcado:
            return self.nivel_forcado
        g = self._por_nome("gemini")
        if g and g.ativo and self.cota.disponivel("gemini"):
            return 2 if self.cota.fracao_diaria("gemini") >= self.cota.limiar else 1
        l = self._por_nome("local")
        if l and l.ativo and self.cota.disponivel("local", limitado=False):
            return 3
        return 4

    def _disponiveis(self) -> list:
        n = self.nivel()
        ordem = {1: ["gemini", "local", "heuristico"], 2: ["gemini", "local", "heuristico"],
                 3: ["local", "heuristico"], 4: ["heuristico"]}[n]
        out = []
        for nome in ordem:
            p = self._por_nome(nome)
            if p is None or not p.ativo:
                continue
            if nome == "gemini" and not self.cota.disponivel("gemini"):
                continue
            if nome == "local" and not self.cota.disponivel("local", limitado=False):
                continue
            out.append(p)
        return out

    def status(self) -> dict:
        n = self.nivel()
        return {"nivel": n, "nome": NIVEIS[n], "forcado": self.nivel_forcado, "provedor": self.ultimo_provedor,
                "cota": {p.nome: self.cota.resumo(p.nome) for p in self.provedores}}

    # ---------------------------------------------------------------- registro
    def _registrar(self, ctx: Contexto, p, inicio: float, resposta: str | None, erro: str | None,
                   tokens: tuple[int | None, int | None] = (None, None)) -> None:
        if self.store is None:
            return
        try:
            self.store.registrar_chamada_llm(ctx.sala_id, ctx.rodada, ctx.tipo, p.nome, getattr(p, "modelo_atual", "-"),
                                             tokens[0], tokens[1], int((time.time() - inicio) * 1000),
                                             ctx.system_prompt + "\n\n" + ctx.conteudo, resposta, erro)
        except Exception:
            log.exception("falha ao registrar chamada")

    def _tratar_erro(self, p, exc: Exception, ctx: Contexto | None = None) -> None:
        msg = str(exc)
        if p.nome == "gemini" and ("429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower()):
            if ctx is not None and ctx.tipo == "narrar":
                return                                       # a narração já caiu para o modelo lite por conta própria
            self.cota.penalizar("gemini", 60)
        elif p.nome == "local":
            self.cota.penalizar("local", 120)

    # ---------------------------------------------------------------- interface
    async def planejar(self, ctx: Contexto):
        ctx.economico = ctx.economico or self.nivel() == 2
        for p in self._disponiveis():
            inicio = time.time()
            try:
                plano = await asyncio.wait_for(p.planejar(ctx), timeout=getattr(p, "timeout_planejar", 25))
                if p.nome != "heuristico":
                    self.cota.registrar(p.nome)
                self.ultimo_provedor = p.nome
                self._registrar(ctx, p, inicio, json.dumps(plano.model_dump() if hasattr(plano, "model_dump") else plano, ensure_ascii=False), None,
                                getattr(p, "ultimos_tokens", (None, None)))
                return plano
            except Exception as exc:
                log.warning("planejar falhou em %s: %s", p.nome, exc)
                self._registrar(ctx, p, inicio, None, str(exc)[:500])
                self._tratar_erro(p, exc, ctx)
        raise RuntimeError("nenhum provedor respondeu")   # não ocorre: o heurístico não falha

    async def narrar_stream(self, ctx: Contexto) -> AsyncIterator[str]:
        ctx.economico = ctx.economico or self.nivel() == 2
        for p in self._disponiveis():
            falou = False
            inicio = time.time()
            partes: list[str] = []
            try:
                async for texto in p.narrar_stream(ctx):
                    falou = True
                    partes.append(texto)
                    yield texto
                if p.nome != "heuristico":
                    self.cota.registrar(p.nome)
                self.ultimo_provedor = p.nome
                self._registrar(ctx, p, inicio, "".join(partes), None, getattr(p, "ultimos_tokens", (None, None)))
                return
            except Exception as exc:
                log.warning("narração falhou em %s: %s", p.nome, exc)
                self._registrar(ctx, p, inicio, "".join(partes) or None, str(exc)[:500])
                self._tratar_erro(p, exc, ctx)
                if falou:          # já narrou uma parte: encerra; o state_sync mantém o tabuleiro certo
                    return

    async def responder(self, ctx: Contexto) -> str:
        """Texto curto (diálogo de NPC): junta o stream do primeiro provedor que responder."""
        partes: list[str] = []
        async for t in self.narrar_stream(ctx):
            partes.append(t)
        return " ".join("".join(partes).split())

    async def estruturado(self, ctx: Contexto):
        """Memória, layout de mapa e extração de cartuchos: JSON validado por `ctx.schema`. None se só o heurístico restar e ele não souber."""
        for p in self._disponiveis():
            inicio = time.time()
            try:
                fn = getattr(p, "estruturado", None)
                if fn is None:
                    continue
                res = await asyncio.wait_for(fn(ctx), timeout=90)
                if p.nome != "heuristico":
                    self.cota.registrar(p.nome)
                self.ultimo_provedor = p.nome
                self._registrar(ctx, p, inicio, json.dumps(res.model_dump(), ensure_ascii=False) if res is not None else None, None,
                                getattr(p, "ultimos_tokens", (None, None)))
                return res
            except Exception as exc:
                log.warning("%s falhou em %s: %s", ctx.tipo, p.nome, exc)
                self._registrar(ctx, p, inicio, None, str(exc)[:500])
                self._tratar_erro(p, exc, ctx)
        return None
