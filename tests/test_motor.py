import copy

from server import heuristic_ai, rules_engine
from server.events import aplicar, projetar


def test_cena_posiciona_grupo_e_npcs(estado_salao):
    _, estado = estado_salao
    assert estado["cena"]["id"] == "salao_do_trono"
    assert estado["personagens"]["boss_orc"]["x"] == 6 and estado["personagens"]["boss_orc"]["y"] == 4
    assert "goblin_arqueiro_2" not in estado["personagens"]
    assert estado["personagens"]["player_thorin"]["x"] == 6


def test_alcance_e_preview(motor, estado_salao):
    _, estado = estado_salao
    alc = motor.alcance(estado, "player_thorin")
    assert (6, 4) not in alc                                  # ocupado pelo orc
    assert max(alc.values()) <= 6
    prev = motor.caminho_preview(estado, "u1", (6, 8))
    assert prev and prev["custo"] == 3 and prev["caminho"][0] == [6, 5]
    assert motor.caminho_preview(estado, "u1", (6, 4)) is None
    assert motor.caminho_preview(estado, "u1", (6, 13)) is None   # longe demais


def test_validar_declaracao(motor, estado_salao):
    _, estado = estado_salao
    ok = {"slots": {"padrao": {"tipo": "ataque", "ataque_id": "machado_de_batalha", "alvo_id": "boss_orc"}},
          "movimento": None}
    assert motor.validar_declaracao(estado, "u1", ok) == []
    longe = {"slots": {"padrao": {"tipo": "ataque", "ataque_id": "machado_de_batalha", "alvo_id": "goblin_arqueiro"}}}
    assert motor.validar_declaracao(estado, "u1", longe)
    arco = {"slots": {"padrao": {"tipo": "ataque", "ataque_id": "arco_longo", "alvo_id": "goblin_arqueiro"}}}
    assert motor.validar_declaracao(estado, "u2", arco) == []
    assert motor.validar_declaracao(estado, "u1", {"slots": {"padrao": {"tipo": "ataque", "ataque_id": "arco_longo", "alvo_id": "boss_orc"}}})
    assert motor.validar_declaracao(estado, "u1", {"slots": {"xyz": {"tipo": "fala", "texto": "oi"}}})
    assert motor.validar_declaracao(estado, "u1", {"slots": {"livre": {"tipo": "fala", "texto": "x" * 501}}})
    assert motor.validar_declaracao(estado, "u1", {"movimento": {"destino": [6, 4]}, "slots": {}})
    assert motor.validar_declaracao(estado, "u1", {"slots": {"padrao": {"tipo": "ataque", "ataque_id": "machado_de_batalha", "alvo_id": "player_lia"}}})


def test_opcoes_validas_menu(motor, estado_salao):
    _, estado = estado_salao
    op = motor.opcoes_validas(estado)
    assert set(op) == {"boss_orc", "goblin_arqueiro"}
    agora = {(a["ataque_id"], a["alvo_id"]) for a in op["boss_orc"]["ataques_agora"]}
    assert ("machado_serrilhado", "player_thorin") in agora
    movendo = {(a["ataque_id"], a["alvo_id"]) for a in op["boss_orc"]["ataques_movendo"]}
    assert ("machado_serrilhado", "player_lia") in movendo or ("machadinha", "player_lia") in movendo
    gob = {(a["ataque_id"], a["alvo_id"]) for a in op["goblin_arqueiro"]["ataques_agora"]}
    assert ("arco_curto", "player_thorin") in gob
    texto = motor.opcoes_validas_texto(estado, op)
    assert "boss_orc" in texto and "machado_serrilhado" in texto


def test_rolagem_por_slot(motor):
    rol = {}
    r = motor.rolar_para_slot(rol, "u1", "padrao", "1d20+5")
    assert r["id"].startswith("r-") and 9 <= r["total"] <= 28
    try:
        motor.rolar_para_slot(rol, "u1", "padrao", "1d20+5")
        assert False, "segunda rolagem no mesmo slot deveria falhar"
    except ValueError:
        pass
    motor.rolar_para_slot(rol, "u1", "livre_dado", "1d6")
    motor.rolar_para_slot(rol, "u1", "livre_dado", "1d6")    # dados rápidos são livres


def test_rodada_completa_com_plano_valido(motor, estado_salao):
    store, estado = estado_salao
    rol = {}
    r = motor.rolar_para_slot(rol, "u1", "padrao", "1d20+5")
    acoes = {"u1": {"slots": {"padrao": {"tipo": "ataque", "ataque_id": "machado_de_batalha", "alvo_id": "boss_orc", "rolagem_id": r["id"]},
                              "livre": {"tipo": "fala", "texto": "Pela honra do meu clã!"}}},
             "u2": {"slots": {"padrao": {"tipo": "criativa", "texto": "Atiro na corrente do lustre para ele cair em cima do orc!"}}}}
    plano = {"intencoes_npcs": [
        {"npc_id": "boss_orc", "acao": "atacar", "alvo_id": "player_thorin", "ataque_ou_habilidade_id": "machado_serrilhado",
         "destino_x": None, "destino_y": None, "se_alvo_invalido": "mais_proximo", "postura": "agressivo"},
        {"npc_id": "goblin_arqueiro", "acao": "atacar", "alvo_id": "player_lia", "ataque_ou_habilidade_id": "arco_curto",
         "destino_x": None, "destino_y": None, "se_alvo_invalido": "mais_proximo", "postura": "cauteloso"}],
        "arbitragens": [{"personagem_id": "player_lia", "pericia": "pontaria", "dificuldade": "media", "motivo": "lustre",
                         "efeito_sucesso": "dano_ambiental_medio", "efeito_falha": "nenhum", "alvos": ["boss_orc"]}],
        "iniciar_combate": True, "mudar_cena_para": None}
    eventos, log = motor.resolver_rodada(estado, acoes, plano, rol)
    tipos = [e["tipo"] for e in eventos]
    assert tipos[0] == "rodada_iniciada" and "combate_iniciado" in tipos and tipos[-1] == "rodada_concluida"
    assert "intencao_rejeitada" not in tipos
    assert any(e["tipo"] == "ataque" and e["atacante"] == "player_thorin" and e["rolagem"]["total"] == r["total"] for e in eventos)
    assert any(e["tipo"] == "teste" and e["personagem"] == "player_lia" and e["cd"] == 15 for e in eventos)
    assert any(e["tipo"] == "fala" for e in eventos)
    assert all(a["id"] == f"e{i + 1}" for i, a in enumerate(log))
    store.anexar("t", eventos, rodada=1)
    novo = store.estado_atual("t")
    assert novo["modo"] == "combate" and novo["rodada"] == 1 and len(novo["iniciativa"]) == 4
    assert novo["cronica"] and novo["cronica"][0]["rodada"] == 1


def test_intencao_invalida_cai_no_heuristico(motor, estado_salao):
    _, estado = estado_salao
    plano = {"intencoes_npcs": [
        {"npc_id": "boss_orc", "acao": "atacar", "alvo_id": "player_lia", "ataque_ou_habilidade_id": "bola_de_fogo",
         "destino_x": None, "destino_y": None, "se_alvo_invalido": "mais_proximo", "postura": "agressivo"},
        {"npc_id": "fantasma", "acao": "atacar", "alvo_id": "player_lia", "ataque_ou_habilidade_id": "x",
         "destino_x": None, "destino_y": None, "se_alvo_invalido": "mais_proximo", "postura": "agressivo"}],
        "arbitragens": [], "iniciar_combate": False, "mudar_cena_para": None}
    eventos, _ = motor.resolver_rodada(estado, {}, plano)
    rej = [e for e in eventos if e["tipo"] == "intencao_rejeitada"]
    assert len(rej) == 2
    assert any(e["tipo"] == "ataque" and e["atacante"] == "boss_orc" and e["alvo"] == "player_thorin" for e in eventos)


def test_alvo_caido_redireciona_ou_prepara(motor, estado_salao):
    store, estado = estado_salao
    # goblin com 1 PV; Lia atira no goblin, Thorin arremessa no goblin também: um dos dois mata, o outro redireciona/prepara
    store.anexar("t", [{"tipo": "personagem_editado", "personagem_id": "goblin_arqueiro", "campos": {"barras": {"pv": {"atual": 1}}, "x": 8, "y": 6}},
                       {"tipo": "personagem_editado", "personagem_id": "player_lia", "campos": {"x": 8, "y": 8}}])
    estado = store.estado_atual("t")
    rules_engine.usar_semente(3)
    acoes = {"u2": {"slots": {"padrao": {"tipo": "ataque", "ataque_id": "arco_longo", "alvo_id": "goblin_arqueiro"}}},
             "u1": {"slots": {"padrao": {"tipo": "ataque", "ataque_id": "machadinha_arremesso", "alvo_id": "goblin_arqueiro"}}}}
    for u, a in acoes.items():
        assert motor.validar_declaracao(estado, u, a) == [], u
    achou = False
    for seed in range(1, 40):
        rules_engine.usar_semente(seed)
        plano = {"intencoes_npcs": [], "arbitragens": [], "iniciar_combate": True, "mudar_cena_para": None}
        eventos, log = motor.resolver_rodada(estado, acoes, plano)
        if any(e["tipo"] == "caiu" and e["personagem"] == "goblin_arqueiro" for e in eventos):
            ataques = [e for e in eventos if e["tipo"] == "ataque"]
            # depois da queda, o segundo atacante jogador não ataca o goblin
            idx = next(i for i, e in enumerate(eventos) if e["tipo"] == "caiu")
            depois = [e for e in eventos[idx + 1:] if e["tipo"] in ("ataque", "preparar") and e.get("atacante", e.get("personagem")) in ("player_thorin", "player_lia")]
            assert all(e["tipo"] == "preparar" or e["alvo"] != "goblin_arqueiro" for e in depois)
            achou = True
            break
    assert achou


def test_desfazer_rodada(motor, estado_salao):
    store, estado = estado_salao
    plano = heuristic_ai.planejar_rodada(estado, motor.opcoes_validas(estado), motor.metrica)
    eventos, _ = motor.resolver_rodada(estado, {}, plano)
    store.anexar("t", eventos, rodada=1)
    assert store.estado_atual("t")["rodada"] == 1
    assert store.reverter_ultima_rodada("t") == 1
    de_novo = store.estado_atual("t")
    assert de_novo["rodada"] == 0 and de_novo["personagens"]["player_thorin"]["barras"]["pv"]["atual"] == 39
    assert store.reverter_ultima_rodada("t") == 0


def test_combate_inteiro_termina(motor, estado_salao):
    store, estado = estado_salao
    for _ in range(40):
        estado = store.estado_atual("t")
        inimigos = [p for p in estado["personagens"].values() if p["faccao"] == "inimigo" and rules_engine.vivo(p)]
        aliados = [p for p in estado["personagens"].values() if p["faccao"] == "aliado" and rules_engine.vivo(p)]
        if not inimigos or not aliados:
            break
        acoes = {}
        for uid, j in estado["jogadores"].items():
            p = estado["personagens"][j["personagem_id"]]
            if not rules_engine.vivo(p):
                continue
            atq = p["ataques"][0] if p["id"] == "player_thorin" else p["ataques"][0]
            alvo = next((o for o in inimigos if motor.em_alcance(estado, (p["x"], p["y"]), o, atq)), None)
            acoes[uid] = {"slots": {"padrao": {"tipo": "ataque", "ataque_id": atq["id"], "alvo_id": alvo["id"]} if alvo else {"tipo": "defender"}}}
        plano = heuristic_ai.planejar_rodada(estado, motor.opcoes_validas(estado), motor.metrica)
        eventos, _ = motor.resolver_rodada(estado, acoes, plano)
        store.anexar("t", eventos, rodada=estado["rodada"] + 1)
    estado = store.estado_atual("t")
    assert estado["rodada"] >= 2
    assert not [p for p in estado["personagens"].values() if p["faccao"] == "inimigo" and rules_engine.vivo(p)] or \
        not [p for p in estado["personagens"].values() if p["faccao"] == "aliado" and rules_engine.vivo(p)]


def test_projecao_eventos_basicos():
    estado = {"personagens": {"a": {"id": "a", "x": 0, "y": 0, "barras": {"pv": {"atual": 10, "max": 10}}, "condicoes": [], "caido": False}},
              "obstaculos": [], "iniciativa": [], "modo": "exploracao", "cronica": [], "cena": {"id": "c"}, "jogadores": {}}
    projetar(estado, [
        {"tipo": "dano", "alvo": "a", "valor": 4},
        {"tipo": "condicao", "alvo": "a", "condicao": "sangrando", "rodadas": 2},
        {"tipo": "condicao_tick", "alvo": "a", "condicao": "sangrando"},
        {"tipo": "movimento", "personagem": "a", "de": [0, 0], "para": [2, 3]},
        {"tipo": "obstaculo_adicionado", "x": 1, "y": 1, "tipo_obstaculo": "fogo_magico", "duracao_rodadas": 1},
        {"tipo": "obstaculos_tick"},
        {"tipo": "dano", "alvo": "a", "valor": 99},
        {"tipo": "caiu", "personagem": "a"},
        {"tipo": "cura", "alvo": "a", "valor": 3},
    ])
    a = estado["personagens"]["a"]
    assert a["barras"]["pv"]["atual"] == 3 and a["caido"] is False and (a["x"], a["y"]) == (2, 3)
    assert a["condicoes"] == [{"id": "sangrando", "rodadas_restantes": 1}]
    assert estado["obstaculos"] == []
    aplicar(estado, {"tipo": "evento_desconhecido"})   # ignorado sem erro


def test_criativa_com_ficha_sem_pericias(motor, estado_salao):
    """B1: ficha criada sem perícias + arbitragem com perícia inexistente não pode derrubar a rodada."""
    store, estado = estado_salao
    store.anexar("t", [{"tipo": "personagem_adicionado", "personagem": {
        "id": "pc_vyn", "nome": "Vyn", "tipo": "jogador", "faccao": "aliado", "x": 3, "y": 9, "cor": "#fff", "icone": "V",
        "barras": {"pv": {"atual": 12, "max": 12}}, "defesa": 13, "deslocamento": 6, "iniciativa_bonus": 0,
        "ataques": [{"id": "adaga", "nome": "Adaga", "bonus": 2, "dano": "1d4", "tipo_dano": "corte", "alcance": 1}],
        "pericias": {}, "condicoes": [], "caido": False}},
        {"tipo": "jogador_entrou", "player_id": "u3", "nome": "Ana", "papel": "jogador", "personagem_id": "pc_vyn"}])
    estado = store.estado_atual("t")
    acoes = {"u3": {"slots": {"padrao": {"tipo": "criativa", "texto": "Procuro algo suspeito"}}}}
    assert motor.validar_declaracao(estado, "u3", acoes["u3"]) == []
    # sem arbitragem (nível 4) e com arbitragem de perícia inexistente
    for plano in ({"intencoes_npcs": [], "arbitragens": [], "iniciar_combate": False, "mudar_cena_para": None},
                  {"intencoes_npcs": [], "arbitragens": [{"personagem_id": "pc_vyn", "pericia": "investigacao", "dificuldade": "media",
                                                          "motivo": "x", "efeito_sucesso": "revelar_informacao", "efeito_falha": "nenhum", "alvos": []}],
                   "iniciar_combate": False, "mudar_cena_para": None}):
        eventos, log = motor.resolver_rodada(estado, acoes, plano)
        teste = next(e for e in eventos if e["tipo"] == "teste")
        assert teste["personagem"] == "pc_vyn" and teste["pericia"] == "improviso" and teste["cd"] == 15
        assert not [e for e in eventos if e["tipo"] == "intencao_rejeitada"]
