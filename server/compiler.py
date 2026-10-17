"""Compilador de cartuchos (§5): .md → trechos indexados (RAG) + dados estruturados extraídos pelo LLM.

Roda uma vez por cartucho (e de novo só se o hash do .md mudar). Toda saída é validada com Pydantic;
itens inválidos vão para `revisao.json` em vez de serem descartados em silêncio. O cartucho fica com
status `pendente_revisao` até o Host aprovar (`aprovar_cartucho`).

    python -m server.compiler sistema tormenta20
    python -m server.compiler campanha coracao-de-rubi
    python -m server.compiler aprovar campanha coracao-de-rubi
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import unicodedata
from pathlib import Path

from .llm.schemas import Contexto, ExtracaoCampanha, ExtracaoSecao
from .map_engine import gerar_tilemap
from .rag import IndiceRAG, fatiar_markdown

log = logging.getLogger("ai_vtt.compiler")

PROMPT_SISTEMA = """Você extrai dados estruturados de um livro de RPG ({sistema}). Leia APENAS a seção fornecida e devolva
os monstros/criaturas (ficha de combate: PV, Defesa/CA, deslocamento em quadrados, bônus de iniciativa, ataques com bônus,
expressão de dano como '1d8+3', tipo de dano, alcance em quadrados; perícias com bônus) e as condições (modificadores
numéricos de Defesa e ataque, dano por turno como expressão de dados ou null, duração padrão em rodadas) que aparecerem.
Ids em snake_case sem acentos. Se a seção não tiver nada disso, devolva listas vazias. Nunca invente valores: se um número
não estiver no texto, não inclua o item."""

PROMPT_CAMPANHA = """Você prepara uma campanha de RPG para uma mesa virtual. A partir do texto, liste os NPCs (id snake_case,
nome, facção, personalidade em 1–2 frases, voz entre NARRADOR/grave/agudo/feminina/sussurro, postura inicial, o id do monstro
do sistema que serve de modelo quando for uma criatura comum ou null, PV e Defesa estimados coerentes com o texto) e as cenas
(id snake_case, nome, descrição de 2–3 frases para o narrador, tipo de mapa, ids dos NPCs presentes, ids das cenas vizinhas).
Indique a cena inicial. Use somente o que está no texto."""


def _slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _secoes(texto: str, max_chars: int = 12000) -> list[tuple[str, str]]:
    """Seções de nível ## (ou o documento inteiro), limitadas a ~3k tokens cada."""
    partes: list[tuple[str, str]] = []
    titulo, buf = "(início)", []
    for linha in texto.splitlines():
        m = re.match(r"^##\s+(.*)", linha)
        if m:
            if buf:
                partes.append((titulo, "\n".join(buf)))
            titulo, buf = m.group(1).strip(), [linha]
        else:
            buf.append(linha)
    if buf:
        partes.append((titulo, "\n".join(buf)))
    out = []
    for t, corpo in partes:
        for i in range(0, max(1, len(corpo)), max_chars):
            out.append((t, corpo[i:i + max_chars]))
    return [(t, c) for t, c in out if c.strip()]


async def compilar_sistema(dir_cartucho: Path, llm, forcar: bool = False) -> dict:
    manifest = json.loads((dir_cartucho / "manifest.json").read_text(encoding="utf-8"))
    fonte = dir_cartucho / manifest.get("fonte", "sistema.md")
    comp = dir_cartucho / "compilado"
    comp.mkdir(exist_ok=True)
    if not fonte.exists():
        raise FileNotFoundError(f"fonte não encontrada: {fonte}")
    texto = fonte.read_text(encoding="utf-8")
    h = _hash(texto)
    if manifest.get("hash_fonte") == h and not forcar:
        log.info("sistema %s já compilado (hash igual)", manifest["id"])
        return {"status": "inalterado"}

    # 1) fatiamento + 2) indexação
    indice = IndiceRAG(comp / "rag_index.db")
    indice.limpar()
    n = indice.indexar(manifest["id"], fatiar_markdown(texto))
    indice.meta("hash_fonte", h)

    # 3) extração estruturada seção por seção
    monstros: dict = json.loads((comp / "monstros.json").read_text(encoding="utf-8")) if (comp / "monstros.json").exists() and not forcar else {}
    config_path = comp / "system_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else _config_padrao(manifest)
    revisao: list[dict] = []
    for titulo, corpo in _secoes(texto):
        ctx = Contexto("extrair", PROMPT_SISTEMA.format(sistema=manifest.get("nome", manifest["id"])),
                       f"SEÇÃO: {titulo}\n\n{corpo}", schema=ExtracaoSecao)
        try:
            res = await llm.estruturado(ctx)
        except Exception as exc:
            revisao.append({"secao": titulo, "erro": str(exc)[:300]})
            continue
        if res is None:
            revisao.append({"secao": titulo, "erro": "nenhum provedor LLM disponível para extração"})
            continue
        for m in res.monstros:
            mid = _slug(m.id or m.nome)
            if m.pv <= 0 or not m.ataques:
                revisao.append({"secao": titulo, "item": m.model_dump(), "motivo": "PV ou ataques ausentes"})
                continue
            monstros[mid] = {"nome": m.nome, "pv": m.pv, "defesa": m.defesa, "deslocamento": max(1, m.deslocamento), "iniciativa_bonus": m.iniciativa_bonus,
                             "ataques": [{**a.model_dump(), "id": _slug(a.id or a.nome)} for a in m.ataques], "pericias": m.pericias,
                             "descricao": m.descricao, "voz": "NARRADOR"}
        for c in res.condicoes:
            cid = _slug(c.id or c.nome)
            config.setdefault("condicoes", {})[cid] = {"nome": c.nome, "descricao": c.descricao, "mod_defesa": c.mod_defesa, "mod_ataque": c.mod_ataque,
                                                        "dano_por_turno": c.dano_por_turno, "duracao_padrao": max(1, c.duracao_padrao)}
    (comp / "monstros.json").write_text(json.dumps(monstros, ensure_ascii=False, indent=2), encoding="utf-8")
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    if not (comp / "efeitos.json").exists():
        (comp / "efeitos.json").write_text(json.dumps(_efeitos_padrao(), ensure_ascii=False, indent=2), encoding="utf-8")
    (comp / "revisao.json").write_text(json.dumps(revisao, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["hash_fonte"] = h
    manifest["status"] = "pendente_revisao"
    (dir_cartucho / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "pendente_revisao", "trechos": n, "monstros": len(monstros), "revisao": len(revisao)}


async def compilar_campanha(dir_cartucho: Path, llm, monstros: dict | None = None, forcar: bool = False) -> dict:
    manifest = json.loads((dir_cartucho / "manifest.json").read_text(encoding="utf-8"))
    fonte = dir_cartucho / manifest.get("fonte", "campanha.md")
    comp = dir_cartucho / "compilado"
    comp.mkdir(exist_ok=True)
    texto = fonte.read_text(encoding="utf-8")
    h = _hash(texto)
    if manifest.get("hash_fonte") == h and not forcar:
        return {"status": "inalterado"}
    indice = IndiceRAG(comp / "rag_index.db")
    indice.limpar()
    n = indice.indexar(manifest["id"], fatiar_markdown(texto))
    indice.meta("hash_fonte", h)

    ctx = Contexto("extrair", PROMPT_CAMPANHA, texto[:60000], schema=ExtracaoCampanha)
    res = await llm.estruturado(ctx)
    revisao: list[dict] = []
    if res is None:
        revisao.append({"erro": "nenhum provedor LLM disponível para extração; npcs.json e cenas.json mantidos"})
    else:
        monstros = monstros or {}
        npcs = {}
        for npc in res.npcs:
            nid = _slug(npc.id or npc.nome)
            base = monstros.get(npc.modelo_monstro or "", {})
            ficha = {"id": nid, "nome": npc.nome, "tipo": "npc", "faccao": npc.faccao, "voz": npc.voz, "postura": npc.postura,
                     "personalidade": npc.personalidade, "cor": "#7f1d1d" if npc.faccao == "inimigo" else "#2563eb",
                     "icone": "👹" if npc.faccao == "inimigo" else "🙂",
                     "barras": {"pv": {"atual": npc.pv or base.get("pv", 10), "max": npc.pv or base.get("pv", 10)}},
                     "defesa": npc.defesa or base.get("defesa", 12), "deslocamento": base.get("deslocamento", 6),
                     "iniciativa_bonus": base.get("iniciativa_bonus", 0),
                     "ataques": base.get("ataques") or [{"id": "golpe", "nome": "Golpe", "bonus": 2, "dano": "1d6", "tipo_dano": "impacto", "alcance": 1}],
                     "pericias": base.get("pericias", {}), "condicoes": [], "caido": False}
            npcs[nid] = ficha
        cenas = {}
        for c in res.cenas:
            cid = _slug(c.id or c.nome)
            presentes = [_slug(x) for x in c.npcs if _slug(x) in npcs]
            tilemap, entrada = gerar_tilemap(c.tipo_mapa, 20, 15, ["pilastras", "cobertura"], seed=cid)
            # NPCs distribuídos longe da entrada
            from .grid_math import MapaLogico, bfs_conectado, distancia_quadrados
            mapa = MapaLogico(tilemap)
            livres = sorted(bfs_conectado(tilemap, entrada), key=lambda p: -distancia_quadrados(p, entrada))
            refs = []
            for i, nid in enumerate(presentes):
                x, y = livres[min(i * 3, len(livres) - 1)] if livres else entrada
                refs.append(f"{nid}@{x},{y}")
            cenas[cid] = {"id": cid, "nome": c.nome, "descricao": c.descricao, "tipo_mapa": c.tipo_mapa, "entrada": list(entrada),
                          "npcs": refs, "transicoes": [_slug(t) for t in c.transicoes], "tilemap": tilemap}
            if not mapa.passavel(*entrada):
                revisao.append({"cena": cid, "motivo": "entrada bloqueada no tilemap gerado"})
        if npcs:
            (comp / "npcs.json").write_text(json.dumps(npcs, ensure_ascii=False, indent=2), encoding="utf-8")
        if cenas:
            (comp / "cenas.json").write_text(json.dumps(cenas, ensure_ascii=False, indent=2), encoding="utf-8")
            manifest["cena_inicial"] = _slug(res.cena_inicial) if _slug(res.cena_inicial) in cenas else next(iter(cenas))
    (comp / "revisao.json").write_text(json.dumps(revisao, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["hash_fonte"] = h
    manifest["status"] = "pendente_revisao"
    (dir_cartucho / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "pendente_revisao", "trechos": n, "revisao": len(revisao)}


def aprovar_cartucho(dir_cartucho: Path) -> None:
    manifest = json.loads((dir_cartucho / "manifest.json").read_text(encoding="utf-8"))
    manifest["status"] = "revisado"
    (dir_cartucho / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _config_padrao(manifest: dict) -> dict:
    return {"sistema_id": manifest["id"], "sistema_nome": manifest.get("nome", manifest["id"]), "versao_compilacao": 1,
            "grid": {"tamanho_quadrado_metros": 1.5, "metrica_diagonal": "1-2-1-2", "terreno_dificil_multiplicador": 2},
            "campo_defesa": "defesa", "bonus_cobertura": 2,
            "barras_status": [{"id": "pv", "nome": "Pontos de Vida", "cor_token": "--status-vida"}],
            "iniciativa": {"expressao": "1d20+{iniciativa}"}, "ataque": {"expressao": "1d20+{bonus}", "compara_com": "defesa"},
            "teste": {"expressao": "1d20+{bonus}"},
            "critico": {"margem_padrao": 20, "multiplicador_padrao": 2, "modo": "multiplica_dados"},
            "tabela_dificuldade": {"facil": 10, "media": 15, "dificil": 20, "muito_dificil": 25},
            "condicoes": {"defendendo": {"nome": "Defendendo", "mod_defesa": 2, "duracao_padrao": 1}},
            "slots_de_acao_por_turno": [
                {"id": "padrao", "label": "Ação Padrão", "icone": "⚔️", "tipos_permitidos": ["ataque", "pericia", "criativa"]},
                {"id": "movimento", "label": "Movimento", "icone": "🥾", "vinculado_ao_grid": True},
                {"id": "livre", "label": "Fala", "icone": "💬", "tipos_permitidos": ["fala"]}]}


def _efeitos_padrao() -> dict:
    return {"dano_ambiental_leve": {"dano": "1d6", "tipo_dano": "impacto"}, "dano_ambiental_medio": {"dano": "2d6", "tipo_dano": "impacto"},
            "dano_ambiental_forte": {"dano": "4d6", "tipo_dano": "impacto"},
            "condicao_curta": {"condicoes_permitidas": ["caido", "desprevenido", "ofuscado"], "duracao_rodadas": 1},
            "empurrar_alvo": {"quadrados_max": 2}, "bonus_aliado": {"bonus": 2, "duracao_rodadas": 1},
            "revelar_informacao": {}, "nenhum": {}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tipo", choices=["sistema", "campanha", "aprovar"])
    ap.add_argument("alvo", nargs="+")
    ap.add_argument("--forcar", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    from .bootstrap import App
    app = App(em_memoria=True)
    raiz = app.biblioteca.raiz
    if args.tipo == "aprovar":
        tipo, cid = args.alvo[0], args.alvo[1]
        aprovar_cartucho(raiz / ("sistemas" if tipo == "sistema" else "campanhas") / cid)
        print("aprovado")
        return 0
    if args.tipo == "sistema":
        print(asyncio.run(compilar_sistema(raiz / "sistemas" / args.alvo[0], app.llm, args.forcar)))
    else:
        d = raiz / "campanhas" / args.alvo[0]
        manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        monstros = {}
        try:
            monstros = app.biblioteca.sistema(manifest["sistema_id"]).monstros
        except Exception:
            pass
        print(asyncio.run(compilar_campanha(d, app.llm, monstros, args.forcar)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
