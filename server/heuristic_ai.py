"""IA heurística de NPC (nível 4 da escada e fallback de intenções inválidas) — §9.3, §10.4.

Regras simples e previsíveis:
- feridos (< 25% PV) com postura cauteloso/fugindo: fogem do inimigo mais próximo;
- atacar o alvo atacável agora (preferência: mais ferido se "mais_ferido", senão mais próximo);
- senão, mover para alcançar alguém e atacar;
- senão, aproximar-se do inimigo mais próximo; sem inimigos, defender.
"""
from __future__ import annotations

from . import grid_math as gm
from .rules_engine import vivo


def planejar_npc(npc_id: str, estado: dict, opcoes: dict, metrica: str, preferencia: str = "mais_proximo") -> dict:
    """Devolve uma intenção no formato de IntencaoNPC (dict), sempre válida segundo `opcoes`."""
    npc = estado["personagens"][npc_id]
    op = opcoes[npc_id]
    inimigos = [p for p in estado["personagens"].values()
                if vivo(p) and p["faccao"] != npc["faccao"] and p["id"] != npc_id]
    base = {"npc_id": npc_id, "alvo_id": None, "ataque_ou_habilidade_id": None,
            "destino_x": None, "destino_y": None, "se_alvo_invalido": preferencia,
            "postura": npc.get("postura") or "agressivo", "fala": None}
    if not inimigos or npc.get("faccao") == "neutro":
        return {**base, "acao": "esperar"}

    pv = npc["barras"].get("pv", {"atual": 1, "max": 1})
    ferido = pv["max"] and pv["atual"] / pv["max"] < 0.25
    if ferido and npc.get("postura") in ("cauteloso", "fugindo") and inimigos and op["fuga"]:
        return {**base, "acao": "fugir", "destino_x": op["fuga"][0], "destino_y": op["fuga"][1], "postura": "fugindo"}

    def escolher(cands: list[dict]) -> dict | None:
        if not cands:
            return None
        if preferencia == "mais_ferido":
            return min(cands, key=lambda c: (c["pv_frac"], c["distancia"]))
        return min(cands, key=lambda c: (c["distancia"], c["pv_frac"]))

    agora = escolher(op["ataques_agora"])
    if agora:
        return {**base, "acao": "atacar", "alvo_id": agora["alvo_id"], "ataque_ou_habilidade_id": agora["ataque_id"]}

    movendo = escolher(op["ataques_movendo"])
    if movendo:
        return {**base, "acao": "atacar", "alvo_id": movendo["alvo_id"], "ataque_ou_habilidade_id": movendo["ataque_id"],
                "destino_x": movendo["via"][0], "destino_y": movendo["via"][1]}

    if inimigos and op["alcance"]:
        alvo = min(inimigos, key=lambda p: gm.distancia_quadrados((npc["x"], npc["y"]), (p["x"], p["y"]), metrica))
        destino = min(op["alcance"], key=lambda c: (gm.distancia_quadrados(c, (alvo["x"], alvo["y"]), metrica), op["alcance"][c]))
        if destino != (npc["x"], npc["y"]):
            return {**base, "acao": "mover", "destino_x": destino[0], "destino_y": destino[1]}
    return {**base, "acao": "defender"}


def planejar_rodada(estado: dict, opcoes: dict, metrica: str) -> dict:
    """Plano completo no formato de PlanoRodada (dict). Sem arbitragens: criativas viram teste simples."""
    intencoes = [planejar_npc(nid, estado, opcoes, metrica) for nid in opcoes]
    return {"intencoes_npcs": intencoes, "arbitragens": [], "iniciar_combate": False, "mudar_cena_para": None}
