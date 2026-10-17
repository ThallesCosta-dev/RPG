"""Sprint 1 — um combate inteiro pela linha de comando, sem IA e sem servidor.

    python scripts/simular_combate.py [--cena salao_do_trono] [--seed 42] [--max-rodadas 20] [--verbose]

Jogadores são controlados por uma política simples (atacar o inimigo mais próximo ao alcance, senão aproximar-se);
NPCs usam a IA heurística; a narração sai por template. O estado passa pelo Event Store em memória.
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import grid_math as gm                      # noqa: E402
from server import heuristic_ai, rules_engine           # noqa: E402
from server.cartuchos import Biblioteca, montar_cena_inicial  # noqa: E402
from server.events import EventStore                    # noqa: E402
from server.motor import Motor                          # noqa: E402
from server.narrador_template import narrar_rodada     # noqa: E402


def politica_jogador(motor: Motor, estado: dict, p: dict) -> dict:
    inimigos = motor.inimigos_de(estado, p)
    if not inimigos:
        return {"slots": {"padrao": {"tipo": "esperar"}}}
    mapa = motor.mapa_logico(estado, {p["id"]})
    # 1) ataque possível de onde está (melhor dano médio)
    for atq in sorted(p["ataques"], key=lambda a: -int(a["bonus"])):
        alvos = [o for o in inimigos if motor.em_alcance(estado, (p["x"], p["y"]), o, atq, mapa)]
        if alvos:
            alvo = min(alvos, key=lambda o: o["barras"]["pv"]["atual"])
            return {"slots": {"padrao": {"tipo": "ataque", "ataque_id": atq["id"], "alvo_id": alvo["id"]}}}
    # 2) mover e atacar
    alc = motor.alcance(estado, p["id"])
    for atq in sorted(p["ataques"], key=lambda a: -int(a["bonus"])):
        melhor = None
        for cel, custo in alc.items():
            for o in inimigos:
                if motor.em_alcance(estado, cel, o, atq, mapa) and (melhor is None or custo < melhor[1]):
                    melhor = (cel, custo, o)
        if melhor:
            cel, _, o = melhor
            return {"movimento": {"destino": list(cel)},
                    "slots": {"padrao": {"tipo": "ataque", "ataque_id": atq["id"], "alvo_id": o["id"]}}}
    # 3) aproximar
    perto = min(inimigos, key=lambda o: gm.distancia_quadrados((p["x"], p["y"]), (o["x"], o["y"]), motor.metrica))
    cel = min(alc, key=lambda c: (gm.distancia_quadrados(c, (perto["x"], perto["y"]), motor.metrica), alc[c]))
    return {"movimento": {"destino": list(cel)}, "slots": {"padrao": {"tipo": "defender"}}}


def imprimir_mapa(estado: dict) -> None:
    grade = [list(l) for l in estado["cena"]["tilemap"]]
    for p in estado["personagens"].values():
        if rules_engine.vivo(p):
            grade[p["y"]][p["x"]] = p["nome"][0].upper() if p["tipo"] == "jogador" else p["nome"][0].lower()
        else:
            grade[p["y"]][p["x"]] = "x"
    print("\n".join("".join(l) for l in grade))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cena", default="salao_do_trono")
    ap.add_argument("--campanha", default="coracao-de-rubi")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--max-rodadas", type=int, default=25)
    ap.add_argument("--jogadores", default="player_thorin,player_lia,player_maya,player_bruno")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    rules_engine.usar_semente(args.seed)
    bib = Biblioteca(Path(__file__).resolve().parents[1] / "cartuchos")
    camp = bib.campanha(args.campanha)
    sis = bib.sistema(camp.sistema_id)
    motor = Motor(sis.config, sis.efeitos, camp.cenas, sis.plugin)
    store = EventStore(":memory:")

    jogadores = {}
    personagens = {}
    for pid in args.jogadores.split(","):
        ficha = copy.deepcopy(camp.personagens[pid])
        personagens[pid] = ficha
        jogadores[f"u_{pid}"] = {"player_id": f"u_{pid}", "nome": ficha["nome"], "papel": "jogador",
                                 "personagem_id": pid, "conectado": True}
    jogadores["u_player_thorin"]["papel"] = "host"
    cena = montar_cena_inicial(camp, args.cena)
    store.criar_sala("sim", sis.id, camp.id, "u_player_thorin", cena, personagens, jogadores)
    # posiciona o grupo na entrada e instancia os NPCs da cena
    estado = store.estado_atual("sim")
    store.anexar("sim", [motor.evento_mudar_cena(estado, args.cena)])

    for rodada in range(1, args.max_rodadas + 1):
        estado = store.estado_atual("sim")
        vivos_inimigos = [p for p in estado["personagens"].values() if p["faccao"] == "inimigo" and rules_engine.vivo(p) and p.get("postura") != "rendido"]
        vivos_aliados = [p for p in estado["personagens"].values() if p["faccao"] == "aliado" and rules_engine.vivo(p)]
        if not vivos_inimigos or not vivos_aliados:
            break
        acoes = {}
        for uid, j in estado["jogadores"].items():
            p = estado["personagens"][j["personagem_id"]]
            if rules_engine.vivo(p):
                acao = politica_jogador(motor, estado, p)
                erros = motor.validar_declaracao(estado, uid, acao)
                assert not erros, (uid, acao, erros)
                acoes[uid] = acao
        opcoes = motor.opcoes_validas(estado)
        plano = heuristic_ai.planejar_rodada(estado, opcoes, motor.metrica)
        eventos, log = motor.resolver_rodada(estado, acoes, plano, {}, opcoes)
        store.anexar("sim", eventos, rodada=estado["rodada"] + 1)
        print(f"\n=== RODADA {rodada} ===")
        if args.verbose:
            print(motor.opcoes_validas_texto(estado, opcoes))
        for a in log:
            print(f"{a['id']:>4} {a['texto']}")
        if args.verbose:
            print("--- narração (template) ---")
            print(narrar_rodada(log))
            imprimir_mapa(store.estado_atual("sim"))

    estado = store.estado_atual("sim")
    print("\n=== FIM ===")
    for p in estado["personagens"].values():
        status = "caído" if p["caido"] else ("rendido" if p.get("postura") == "rendido" else "vivo")
        print(f"- {p['nome']:<24} PV {rules_engine.resumo_barra(p):>8}  ({status}) em ({p['x']},{p['y']})")
    print(f"modo: {estado['modo']}, rodadas: {estado['rodada']}, eventos: {store._seq['sim']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
