"""Provedor heurístico (nível 4): IA de NPC sem LLM + narração por template. Nunca falha."""
from __future__ import annotations

from collections.abc import AsyncIterator

from .. import heuristic_ai
from ..narrador_template import narrar_rodada, stream_de_texto
from .schemas import Contexto, LayoutMapa, Memoria, PlanoRodada


class HeuristicoProvider:
    nome = "heuristico"
    ativo = True
    modelo_atual = "template"

    async def planejar(self, ctx: Contexto) -> PlanoRodada:
        d = ctx.dados
        plano = heuristic_ai.planejar_rodada(d["estado"], d["opcoes"], d.get("metrica", "1-2-1-2"))
        return PlanoRodada.model_validate(plano)

    async def narrar_stream(self, ctx: Contexto) -> AsyncIterator[str]:
        if ctx.tipo == "dialogo":
            npc = ctx.dados.get("npc", {})
            postura = npc.get("postura")
            if npc.get("caido"):
                fala = "..."
            elif npc.get("faccao") == "inimigo" and postura in ("agressivo", None):
                fala = f"{npc.get('nome', 'O inimigo')} rosna e não responde com palavras."
            elif postura == "rendido":
                fala = "Eu me rendo! Não me matem... pergunte o que quiser."
            else:
                fala = f"{npc.get('nome', 'O personagem')} encara você em silêncio por um momento e assente devagar."
            yield fala
            return
        acoes = ctx.dados.get("acoes_log", [])
        estado = ctx.dados.get("estado", {})
        falas = []
        for a in acoes:
            for e in a.get("eventos", []):
                if e["tipo"] == "fala":
                    p = estado.get("personagens", {}).get(e["personagem"], {})
                    if p.get("tipo") == "npc" and p.get("voz"):
                        falas.append({"voz": e["personagem"], "texto": e["texto"]})
        async for pedaco in stream_de_texto(narrar_rodada(acoes, falas)):
            yield pedaco

    async def estruturado(self, ctx: Contexto):
        """Memória: mantém a atual. Mapa: parâmetros padrão. Extração: não sabe (None)."""
        if ctx.schema is Memoria:
            m = (ctx.dados.get("estado") or {}).get("memoria")
            if m:
                npcs = m.get("npcs_conhecidos") or {}
                return Memoria(resumo=m.get("resumo", ""), fatos=list(m.get("fatos", [])), missoes_abertas=list(m.get("missoes_abertas", [])),
                               npcs_conhecidos=[{"id": k, "descricao": v} for k, v in (npcs.items() if isinstance(npcs, dict) else [(n["id"], n["descricao"]) for n in npcs])])
            return Memoria(resumo="", fatos=[], npcs_conhecidos=[], missoes_abertas=[])
        if ctx.schema is LayoutMapa:
            return LayoutMapa(tipo=ctx.dados.get("tipo_mapa", "masmorra"), largura=20, altura=15,
                              descricao_visual=ctx.dados.get("descricao", ""), elementos=["pilastras", "cobertura"])
        return None
