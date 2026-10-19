"""Construtor de ficha por classe e habilidades de classe no motor."""
import copy

import pytest

from server import rules_engine
from server.cartuchos import Biblioteca, montar_cena_inicial
from server.events import EventStore
from server.fichas import construir_ficha, modelo_ficha
from server.motor import Motor
from tests.conftest import RAIZ

VOZES = {"NARRADOR": {}, "grave": {}, "feminina": {}}


@pytest.fixture(scope="module")
def dnd():
    return Biblioteca(RAIZ / "cartuchos").sistema("dnd5e")


@pytest.fixture(scope="module")
def t20():
    return Biblioteca(RAIZ / "cartuchos").sistema("tormenta20")


def test_modelo_ficha_lista_classes(dnd, t20):
    m = modelo_ficha(dnd)
    assert m["modo"] == "classes" and {c["id"] for c in m["classes"]} >= {"guerreiro", "mago", "clerigo", "ladino"}
    assert any(a["id"] == "espada_longa" for a in m["armas"]) and any(a["id"] == "cota_de_malha" for a in m["armaduras"])
    assert modelo_ficha(t20)["modo"] == "classes" and modelo_ficha(t20)["progressao"]["tipo"] == "t20"


def test_construir_guerreiro_5e(dnd):
    ficha, erros = construir_ficha({"nome": "Bruenor", "classe_id": "guerreiro", "nivel": 3, "atributos": {"FOR": 3, "DES": 1, "CON": 2, "INT": 0, "SAB": 1, "CAR": -1},
                                    "pericias": ["atletismo", "percepcao", "religiao"], "armas": ["espada_longa", "arco_longo", "machadinha"],
                                    "armadura_id": "cota_de_malha", "escudo": True, "voz": "grave"}, dnd, VOZES)
    assert erros == [], erros
    assert ficha["barras"]["pv"]["max"] == 10 + 2 + 2 * (6 + 2)                    # d10+CON, depois 6+CON por nível
    assert ficha["defesa"] == 16 + 0 + 2                                             # cota (DES máx 0) + escudo
    espada = next(a for a in ficha["ataques"] if a["id"] == "espada_longa")
    assert espada["bonus"] == 2 + 3 and espada["dano"] == "1d8+3"                   # proficiência +2 no nível 3
    arco = next(a for a in ficha["ataques"] if a["id"] == "arco_longo")
    assert arco["bonus"] == 2 + 1 and arco["alcance"] == 30
    assert any(a["id"] == "machadinha_arremesso" and a["alcance"] == 4 for a in ficha["ataques"])
    assert ficha["pericias"]["atletismo"] == 5 and ficha["pericias"]["arcanismo"] == 0 and "religiao" in ficha["pericias_treinadas"]
    ids = {h["id"] for h in ficha["habilidades"]}
    assert {"retomar_folego", "surto_de_acao", "estilo_duelo"} <= ids and "ataque_extra" not in ids
    assert ficha["usos"]["retomar_folego"] == 1 and ficha["voz"] == "grave" and ficha["classe"].startswith("Guerreiro")


def test_construir_erros(dnd):
    _, erros = construir_ficha({"nome": "X", "classe_id": "ninja"}, dnd, VOZES)
    assert erros and "classe inválida" in erros[0]
    _, erros = construir_ficha({"nome": "X", "classe_id": "mago", "nivel": 1, "atributos": {"FOR": 5, "DES": 5, "CON": 5, "INT": 5, "SAB": 0, "CAR": 0},
                                "pericias": ["arcanismo", "historia", "investigacao", "medicina"], "armas": ["bordao"]}, dnd, VOZES)
    assert any("soma dos modificadores" in e for e in erros) and any("permite 2 perícias" in e for e in erros)
    _, erros = construir_ficha({"nome": "X", "classe_id": "mago", "armas": ["canhao"]}, dnd, VOZES)
    assert any("arma desconhecida" in e for e in erros)


def test_construir_arcanista_t20(t20):
    ficha, erros = construir_ficha({"nome": "Vyn", "classe_id": "arcanista", "nivel": 4, "atributos": {"FOR": -1, "DES": 2, "CON": 1, "INT": 4, "SAB": 1, "CAR": 0},
                                    "pericias": ["conhecimento", "percepcao"], "armas": ["adaga"], "armadura_id": "nenhuma", "escudo": False}, t20, VOZES)
    assert erros == [], erros
    assert ficha["barras"]["pv"]["max"] == 8 + 1 + 3 * (2 + 1) and ficha["barras"]["pm"]["max"] == 24
    assert ficha["pericias"]["misticismo"] == 2 + 4 + 2 and ficha["pericias"]["atletismo"] == 2 - 1      # ½ nível + atributo (+2 treinada)
    assert ficha["magia"]["cd"] == 10 + 2 + 4 and ficha["defesa"] == 12
    assert {h["id"] for h in ficha["habilidades"]} == {"raio_arcano", "seta_infalivel", "explosao_de_chamas", "armadura_arcana"}


def _sala_5e():
    bib = Biblioteca(RAIZ / "cartuchos")
    sis, camp = bib.sistema("dnd5e"), bib.campanha("sombras-de-phandalin")
    motor = Motor(sis.config, sis.efeitos, camp.cenas)
    guerreiro, e1 = construir_ficha({"nome": "Bruenor", "classe_id": "guerreiro", "nivel": 3, "atributos": {"FOR": 3, "DES": 1, "CON": 2, "INT": 0, "SAB": 1, "CAR": -1},
                                     "pericias": ["atletismo"], "armas": ["espada_longa"], "armadura_id": "cota_de_malha", "escudo": True}, sis, VOZES)
    mago, e2 = construir_ficha({"nome": "Elian", "classe_id": "mago", "nivel": 5, "atributos": {"FOR": -1, "DES": 2, "CON": 1, "INT": 4, "SAB": 1, "CAR": 0},
                               "pericias": ["arcanismo"], "armas": ["bordao"], "armadura_id": "nenhuma"}, sis, VOZES)
    clerigo, e3 = construir_ficha({"nome": "Mirela", "classe_id": "clerigo", "nivel": 2, "atributos": {"FOR": 2, "DES": 0, "CON": 2, "INT": 0, "SAB": 3, "CAR": 1},
                                   "pericias": ["medicina"], "armas": ["maca"], "armadura_id": "cota_de_escamas", "escudo": True}, sis, VOZES)
    assert not (e1 or e2 or e3), (e1, e2, e3)
    store = EventStore(":memory:")
    pers = {p["id"]: p for p in (guerreiro, mago, clerigo)}
    jog = {f"u_{p['id']}": {"player_id": f"u_{p['id']}", "nome": p["nome"], "papel": "jogador", "personagem_id": p["id"], "conectado": True} for p in pers.values()}
    next(iter(jog.values()))["papel"] = "host"
    store.criar_sala("s", "dnd5e", "sombras-de-phandalin", next(iter(jog)), montar_cena_inicial(camp, "trilha_triboar"), pers, jog)
    store.anexar("s", [motor.evento_mudar_cena(store.estado_atual("s"), "trilha_triboar")])
    # posiciona: guerreiro adjacente ao goblin_1 (13,2); clériga ao lado; mago longe, com o goblin_2 (11,8) a 5 quadrados
    store.anexar("s", [{"tipo": "personagem_editado", "personagem_id": guerreiro["id"], "campos": {"x": 12, "y": 2}},
                       {"tipo": "personagem_editado", "personagem_id": mago["id"], "campos": {"x": 7, "y": 5}},
                       {"tipo": "personagem_editado", "personagem_id": clerigo["id"], "campos": {"x": 12, "y": 3, "barras": {"pv": {"atual": 5}}}}])
    return motor, store, guerreiro, mago, clerigo


def test_habilidades_no_motor():
    motor, store, g, m, c = _sala_5e()
    estado = store.estado_atual("s")
    ug, um, uc = f"u_{g['id']}", f"u_{m['id']}", f"u_{c['id']}"
    acoes = {
        ug: {"slots": {"padrao": {"tipo": "defender"},
                       "bonus": {"tipo": "habilidade", "habilidade_id": "surto_de_acao", "alvo_id": "goblin_1", "ataque_id": "espada_longa"}}},
        um: {"slots": {"padrao": {"tipo": "habilidade", "habilidade_id": "bola_de_fogo", "alvo_id": "goblin_2"}}},
        uc: {"slots": {"padrao": {"tipo": "habilidade", "habilidade_id": "curar_ferimentos", "alvo_id": c["id"]}}},
    }
    for u, a in acoes.items():
        assert motor.validar_declaracao(estado, u, a) == [], (u, motor.validar_declaracao(estado, u, a))
    # validações negativas
    assert motor.validar_declaracao(estado, ug, {"slots": {"padrao": {"tipo": "habilidade", "habilidade_id": "surto_de_acao", "alvo_id": "goblin_1"}}})   # slot errado
    assert motor.validar_declaracao(estado, ug, {"slots": {"bonus": {"tipo": "habilidade", "habilidade_id": "estilo_duelo"}}})                       # passiva
    assert motor.validar_declaracao(estado, uc, {"slots": {"padrao": {"tipo": "habilidade", "habilidade_id": "curar_ferimentos", "alvo_id": "goblin_2"}}})  # inimigo
    rules_engine.usar_semente(11)
    esperar = [{"npc_id": g_, "acao": "esperar", "alvo_id": None, "ataque_ou_habilidade_id": None, "destino_x": None, "destino_y": None,
                "se_alvo_invalido": "mais_proximo", "postura": "cauteloso", "fala": None} for g_ in ("goblin_1", "goblin_2", "goblin_3")]
    plano = {"intencoes_npcs": esperar, "arbitragens": [], "iniciar_combate": True, "mudar_cena_para": None}   # goblins só observam
    eventos, log = motor.resolver_rodada(estado, acoes, plano)
    tipos = [e["tipo"] for e in eventos]
    assert "habilidade" in tipos and "recurso" in tipos and "uso_gasto" in tipos
    # mago gastou 3 espaços; clériga gastou 1 e curou
    store.anexar("s", eventos, rodada=1)
    novo = store.estado_atual("s")
    assert novo["personagens"][m["id"]]["barras"]["espacos"]["atual"] == 4 - 3
    assert novo["personagens"][c["id"]]["barras"]["espacos"]["atual"] == 2 and novo["personagens"][c["id"]]["barras"]["pv"]["atual"] > 5
    assert novo["personagens"][g["id"]]["usos"]["surto_de_acao"] == 0
    # bola de fogo atingiu pelo menos o goblin_2 (área 4 em volta dele)
    danos_fogo = [e for e in eventos if e["tipo"] == "dano" and e.get("origem") == "bola_de_fogo"]
    assert danos_fogo and any(e["alvo"] == "goblin_2" for e in danos_fogo)
    # estilo de duelo: +2 em acertos corpo a corpo do guerreiro
    acertos = [e for e in eventos if e["tipo"] == "dano" and e.get("extras") and any(x["origem"] == "passiva" for x in e["extras"])]
    assert all(e["alvo"] == "goblin_1" for e in acertos)
    textos = " | ".join(a["texto"] for a in log)
    assert "usa Bola de Fogo" in textos and "usa Curar Ferimentos" in textos
    # segunda rodada: surto sem usos → declaração inválida; descanso curto devolve
    assert motor.validar_declaracao(novo, ug, {"slots": {"bonus": {"tipo": "habilidade", "habilidade_id": "surto_de_acao", "alvo_id": "goblin_1"}}})
    store.anexar("s", [{"tipo": "descanso", "tipo_descanso": "curto"}])
    pos = store.estado_atual("s")
    assert pos["personagens"][g["id"]]["usos"]["surto_de_acao"] == 1
    store.anexar("s", [{"tipo": "descanso", "tipo_descanso": "longo"}])
    pos = store.estado_atual("s")
    assert pos["personagens"][m["id"]]["barras"]["espacos"]["atual"] == 4 and pos["personagens"][c["id"]]["barras"]["pv"]["atual"] == c["barras"]["pv"]["max"]


def test_furtivo_e_furia():
    bib = Biblioteca(RAIZ / "cartuchos")
    sis = bib.sistema("dnd5e")
    ladino, e = construir_ficha({"nome": "Lyra", "classe_id": "ladino", "nivel": 3, "atributos": {"FOR": 0, "DES": 4, "CON": 1, "INT": 1, "SAB": 0, "CAR": 2},
                                 "pericias": ["furtividade", "acrobacia", "percepcao", "enganacao"], "armas": ["rapieira"], "armadura_id": "couro"}, sis, VOZES)
    assert not e, e
    alvo = {"id": "x", "nome": "X", "tipo": "npc", "faccao": "inimigo", "x": 1, "y": 0, "barras": {"pv": {"atual": 30, "max": 30}}, "defesa": 5,
            "condicoes": [{"id": "desprevenido", "rodadas_restantes": 1}], "caido": False, "ataques": [], "pericias": {}}
    rules_engine.usar_semente(5)
    evs = rules_engine.resolver_ataque(ladino, alvo, ladino["ataques"][0], sis.config)
    dano = next(e for e in evs if e["tipo"] == "dano")
    assert any(x["origem"] == "furtivo" and "d6" in x["rolagem"]["expressao"] for x in dano["extras"])     # 2d6 no nível 3
    assert any(x["rolagem"]["expressao"] == "2d6" for x in dano["extras"] if x["origem"] == "furtivo")
    barbaro, e = construir_ficha({"nome": "Grom", "classe_id": "barbaro", "nivel": 1, "atributos": {"FOR": 3, "DES": 1, "CON": 3, "INT": -1, "SAB": 0, "CAR": 0},
                                  "pericias": ["atletismo"], "armas": ["machado_grande"], "armadura_id": "nenhuma"}, sis, VOZES)
    assert not e and barbaro["defesa"] == 10 + 1 + 3                                   # defesa sem armadura: DES + CON
    barbaro["condicoes"] = [{"id": "furioso", "rodadas_restantes": 3}]
    for seed in range(1, 30):                                                          # até acertar (natural 1 erra)
        rules_engine.usar_semente(seed)
        evs = rules_engine.resolver_ataque(barbaro, alvo, barbaro["ataques"][0], sis.config)
        if any(e["tipo"] == "dano" for e in evs):
            break
    dano = next(e for e in evs if e["tipo"] == "dano")
    assert any(x["origem"] == "furioso" and x["valor"] == 2 for x in dano["extras"])
