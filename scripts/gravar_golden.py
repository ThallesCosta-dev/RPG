"""Grava um caso golden a partir da cena do salão (plano fixo, como o Gemini devolveu em 17/10/2026).

    python scripts/gravar_golden.py [nome]
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import rules_engine  # noqa: E402
from server.cartuchos import Biblioteca, montar_cena_inicial  # noqa: E402
from server.events import EventStore  # noqa: E402
from server.motor import Motor  # noqa: E402

PLANO = {"intencoes_npcs": [
    {"npc_id": "boss_orc", "acao": "atacar", "alvo_id": "player_thorin", "ataque_ou_habilidade_id": "machado_serrilhado",
     "destino_x": None, "destino_y": None, "se_alvo_invalido": "mais_proximo", "postura": "agressivo"},
    {"npc_id": "goblin_arqueiro", "acao": "atacar", "alvo_id": "player_thorin", "ataque_ou_habilidade_id": "arco_curto",
     "destino_x": None, "destino_y": None, "se_alvo_invalido": "mais_proximo", "postura": "cauteloso"},
    {"npc_id": "goblin_arqueiro_2", "acao": "atacar", "alvo_id": "player_lia", "ataque_ou_habilidade_id": "arco_curto",
     "destino_x": None, "destino_y": None, "se_alvo_invalido": "mais_ferido", "postura": "cauteloso"}],
    "arbitragens": [{"personagem_id": "player_lia", "pericia": "pontaria", "dificuldade": "media",
                     "motivo": "Atirar na corrente para derrubar o lustre sobre o orc", "efeito_sucesso": "dano_ambiental_medio",
                     "efeito_falha": "sem efeito mecânico", "alvos": ["boss_orc"]}],
    "iniciar_combate": True, "mudar_cena_para": None}


def main(nome: str = "salao_rodada1") -> None:
    raiz = Path(__file__).resolve().parents[1]
    bib = Biblioteca(raiz / "cartuchos")
    camp, sis = bib.campanha("coracao-de-rubi"), bib.sistema("tormenta20")
    motor = Motor(sis.config, sis.efeitos, camp.cenas, sis.plugin)
    store = EventStore(":memory:")
    pers = {p: copy.deepcopy(camp.personagens[p]) for p in ("player_thorin", "player_lia")}
    jog = {"u1": {"player_id": "u1", "nome": "T", "papel": "host", "personagem_id": "player_thorin", "conectado": True},
           "u2": {"player_id": "u2", "nome": "A", "papel": "jogador", "personagem_id": "player_lia", "conectado": True}}
    store.criar_sala("g", sis.id, camp.id, "u1", montar_cena_inicial(camp, "salao_do_trono"), pers, jog)
    store.anexar("g", [motor.evento_mudar_cena(store.estado_atual("g"), "salao_do_trono")])
    store.anexar("g", [{"tipo": "personagem_editado", "personagem_id": "player_thorin", "campos": {"x": 6, "y": 5}},
                       {"tipo": "personagem_editado", "personagem_id": "player_lia", "campos": {"x": 2, "y": 9}}])
    estado = store.estado_atual("g")
    rules_engine.usar_semente(2026)
    rolagens = {}
    r = motor.rolar_para_slot(rolagens, "u1", "padrao", "1d20+8")
    acoes = {"u1": {"slots": {"padrao": {"tipo": "ataque", "ataque_id": "machado_batalha", "alvo_id": "boss_orc", "rolagem_id": r["id"]},
                              "livre": {"tipo": "fala", "texto": "Pela honra do meu clã!"}}},
             "u2": {"slots": {"padrao": {"tipo": "criativa", "texto": "Atiro na corrente do lustre para ele cair em cima do orc!"}}}}
    caso = {"sistema_id": sis.id, "campanha_id": camp.id, "seed": 2026, "estado": estado, "acoes": acoes, "plano": copy.deepcopy(PLANO),
            "rolagens": rolagens, "esperado": None}
    destino = raiz / "tests" / "golden" / f"{nome}.json"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(json.dumps(caso, ensure_ascii=False, indent=1), encoding="utf-8")
    print("gravado", destino, "— agora rode: python -m pytest tests/test_golden.py --regravar")


if __name__ == "__main__":
    main(*sys.argv[1:2])
