import asyncio

import pytest

from server.bootstrap import App
from server.fichas import modelo_ficha, validar_ficha
from tests.test_sala import WSFalso, _espera, ult

FICHA_OK = {"nome": "Grommash", "classe": "Bárbaro", "icone": "🪓", "cor": "#aa3311",
            "atributos": {"FOR": 4, "DES": 1, "CON": 3, "INT": -1, "SAB": 0, "CAR": 0},
            "barras": {"pv": 38, "pm": 2}, "defesa": 16, "deslocamento": 9, "iniciativa_bonus": 1,
            "pericias": {"luta": 7, "atletismo": 8, "fortitude": 6},
            "ataques": [{"nome": "Machado Enorme", "bonus": 7, "dano": "2d6+4", "tipo_dano": "corte", "alcance": 1},
                        {"nome": "Lança arremessada", "bonus": 5, "dano": "1d8+4", "tipo_dano": "perfuracao", "alcance": 6}]}


def test_modelo_ficha(sistema):
    m = modelo_ficha(sistema)
    assert m["atributos"] == ["FOR", "DES", "CON", "INT", "SAB", "CAR"] and "luta" in m["pericias"]
    assert [b["id"] for b in m["barras"]] == ["pv", "pm"] and "corte" in m["tipos_dano"]


def test_validar_ficha_ok_e_erros(sistema):
    ficha, erros = validar_ficha(FICHA_OK, sistema)
    assert erros == []
    assert ficha["id"].startswith("pc_grommash_") and ficha["tipo"] == "jogador" and ficha["barras"]["pv"] == {"atual": 38, "max": 38}
    assert ficha["ataques"][0]["id"] == "machado_enorme" and ficha["pericias"]["luta"] == 7 and ficha["atributos"]["FOR"] == 4
    ruim = {**FICHA_OK, "nome": "", "defesa": 999, "pericias": {"hackear": 3, "luta": 2}, "cor": "vermelho",
            "ataques": [{"nome": "X", "dano": "muito", "bonus": 2}]}
    _, erros = validar_ficha(ruim, sistema)
    assert any("nome" in e for e in erros) and any("defesa" in e for e in erros)
    assert any("hackear" in e for e in erros) and any("cor" in e for e in erros) and any("dano" in e for e in erros)
    _, erros = validar_ficha({**FICHA_OK, "ataques": []}, sistema)
    assert any("ataque" in e for e in erros)


@pytest.fixture
def app(tmp_path):
    import os
    os.environ["DIR_DADOS"] = str(tmp_path / "dados")
    a = App(em_memoria=True)
    a.llm.provedores = [p for p in a.llm.provedores if p.nome == "heuristico"]
    yield a
    os.environ.pop("DIR_DADOS", None)


def test_fluxo_ficha_no_lobby_e_escolha(app):
    r = app.criar_sala("Thalles", "tormenta20", "coracao-de-rubi", None)
    sala_id, host, convite = r["sala_id"], r["player_id"], r["convite"]
    # host sem personagem cria a própria ficha → fica vinculado
    ficha = app.criar_ficha(sala_id, FICHA_OK, player_id=host)
    estado = app.store.estado_atual(sala_id)
    assert estado["jogadores"][host]["personagem_id"] == ficha["id"] and ficha["id"] in estado["personagens"]
    # convidado cria ficha pelo convite (antes de entrar) e depois entra com ela
    ficha2 = app.criar_ficha(sala_id, {**FICHA_OK, "nome": "Vyn"}, convite=convite)
    lobby = app.lobby(sala_id)
    ids = {p["id"]: p["origem"] for p in lobby["personagens_disponiveis"]}
    assert ids[ficha2["id"]] == "sala" and ids["player_lia"] == "campanha" and ficha["id"] not in ids
    e = app.entrar(sala_id, convite, "Ana", ficha2["id"])
    assert e["papel"] == "jogador"
    estado = app.store.estado_atual(sala_id)
    assert estado["jogadores"][e["player_id"]]["personagem_id"] == ficha2["id"]
    assert list(estado["personagens"].values()).count(estado["personagens"][ficha2["id"]]) == 1
    # ficha salva reaparece em outra mesa do mesmo sistema
    r2 = app.criar_sala("Outro", "tormenta20", "coracao-de-rubi", None)
    salvas = {p["id"] for p in app.lobby(r2["sala_id"])["personagens_disponiveis"] if p["origem"] == "salva"}
    assert ficha["id"] in salvas and ficha2["id"] in salvas
    app.escolher_personagem(r2["sala_id"], r2["player_id"], ficha["id"])
    assert app.store.estado_atual(r2["sala_id"])["jogadores"][r2["player_id"]]["personagem_id"] == ficha["id"]
    with pytest.raises(ValueError):
        app.escolher_personagem(r2["sala_id"], r2["player_id"], "player_lia")      # já tem personagem
    with pytest.raises(PermissionError):
        app.criar_ficha(sala_id, FICHA_OK, convite="xxx")
    with pytest.raises(ValueError):
        app.criar_ficha(sala_id, {"nome": "Sem ataques", "ataques": []}, player_id=host)


@pytest.mark.asyncio
async def test_chat_mesa_e_npc(app):
    r = app.criar_sala("Thalles", "tormenta20", "coracao-de-rubi", "player_thorin")
    sala_id, host = r["sala_id"], r["player_id"]
    e = app.entrar(sala_id, r["convite"], "Esp", None)
    sala = app.obter_sala(sala_id)
    w1, w2 = WSFalso(), WSFalso()
    await sala.conectar(host, w1)
    await sala.conectar(e["player_id"], w2)
    await sala.comando_host(host, {"comando": "iniciar"})          # cena inicial: taverna com Bram
    await asyncio.sleep(0.02)
    await sala.chat(host, "Olá a todos!", None)
    m = await ult(w2, "chat_message")
    assert m["nome"] == "Thorin" and m["texto"] == "Olá a todos!" and m["para"] is None and not m["npc"]
    await sala.chat(e["player_id"], "oi", "bram")
    assert (await ult(w2, "error"))["code"] == "sem_personagem"
    await sala.chat(host, "Bram, onde está o rubi?", "bram")
    assert (await ult(w1, "chat_typing"))["personagem_id"] == "bram"
    await _espera(lambda: sum(1 for x in w1.msgs if x["type"] == "chat_message") >= 3)
    resp = w1.ultima("chat_message")
    assert resp["npc"] and resp["de"] == "bram" and resp["texto"]
    estado = app.store.estado_atual(sala_id)
    assert [c["nome"] for c in estado["chat"]] == ["Thorin", "Thorin", "Bram, o Taverneiro"]
    await sala.chat(host, "x" * 600, "inexistente")
    assert (await ult(w1, "error"))["code"] == "npc_invalido"
    await sala.comando_host(host, {"comando": "falar_como_npc", "personagem_id": "bram", "texto": "Psiu... venham aqui."})
    await _espera(lambda: (w2.ultima("chat_message") or {}).get("por_host") is True)
    await sala.encerrar()
