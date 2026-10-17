import pytest

from server import rules_engine as re_


def test_parser_de_dados():
    r = re_.rolar("1d20+8")
    assert 9 <= r["total"] <= 28 and r["termos"][0]["termo"] == "1d20" and r["termos"][1]["termo"] == "+8"
    r = re_.rolar("2d20kh1+5")
    assert len(r["termos"][0]["dados"]) == 2 and len(r["termos"][0]["mantidos"]) == 1
    assert r["termos"][0]["mantidos"][0] == max(r["termos"][0]["dados"])
    r = re_.rolar("2d6+1d4+3")
    assert 6 <= r["total"] <= 19
    r = re_.rolar("d6-1")
    assert 0 <= r["total"] <= 5
    r = re_.rolar("1d8+5", mult_dados=3)
    assert len(r["termos"][0]["dados"]) == 3


@pytest.mark.parametrize("expr", ["", "abc", "1d20+", "101d6", "1d1", "1d20 x", "1d20++3"])
def test_expressoes_invalidas(expr):
    assert not re_.expressao_valida(expr)
    with pytest.raises(ValueError):
        re_.rolar(expr)


def test_determinismo_com_semente():
    re_.usar_semente(7)
    a = re_.rolar("3d6")
    re_.usar_semente(7)
    b = re_.rolar("3d6")
    assert a == b


def _cfg():
    return {"campo_defesa": "defesa", "ataque": {"expressao": "1d20+{bonus}"},
            "critico": {"margem_padrao": 20, "multiplicador_padrao": 2}, "condicoes": {"sangrando": {"duracao_padrao": 3}}}


def _p(pid, pv=30, defesa=15):
    return {"id": pid, "nome": pid, "tipo": "jogador", "faccao": "aliado", "x": 0, "y": 0,
            "barras": {"pv": {"atual": pv, "max": pv}}, "defesa": defesa, "condicoes": [], "caido": False, "ataques": [], "pericias": {}}


def test_ataque_acerto_erro_critico():
    atq = {"id": "espada", "bonus": 5, "dano": "1d8+2", "tipo_dano": "corte", "condicoes_ao_acertar": ["sangrando"]}
    teste = {"expressao": "1d20+5", "total": 20, "termos": [{"termo": "1d20", "dados": [15], "mantidos": [15]}, {"termo": "+5"}]}
    evs = re_.resolver_ataque(_p("a"), _p("b"), atq, _cfg(), teste)
    assert evs[0]["tipo"] == "ataque" and evs[0]["acertou"] and not evs[0]["critico"]
    assert evs[1]["tipo"] == "dano" and evs[1]["alvo"] == "b" and 3 <= evs[1]["valor"] <= 10
    assert evs[2] == {"tipo": "condicao", "alvo": "b", "condicao": "sangrando", "rodadas": 3}

    teste["total"], teste["termos"][0]["mantidos"] = 6, [1]
    evs = re_.resolver_ataque(_p("a"), _p("b"), atq, _cfg(), teste)
    assert not evs[0]["acertou"] and len(evs) == 1           # natural 1 erra mesmo com total alto

    teste["total"], teste["termos"][0]["mantidos"] = 25, [20]
    evs = re_.resolver_ataque(_p("a"), _p("b", defesa=30), atq, _cfg(), teste)
    assert evs[0]["acertou"] and evs[0]["critico"]           # natural 20 acerta e é crítico
    assert len(evs[1]["rolagem"]["termos"][0]["dados"]) == 2  # dados dobrados


def test_cobertura_e_condicoes_na_defesa():
    cfg = _cfg()
    cfg["condicoes"]["caido"] = {"mod_defesa": -2}
    alvo = _p("b", defesa=15)
    alvo["condicoes"] = [{"id": "caido", "rodadas_restantes": 1}]
    assert re_.defesa_efetiva(alvo, cfg) == 13
    assert re_.defesa_efetiva(alvo, cfg, em_cobertura=True) == 15


def test_iniciativa_ordena_com_desempate():
    pers = {"a": {**_p("a"), "iniciativa_bonus": 2}, "b": {**_p("b"), "iniciativa_bonus": 5},
            "n": {**_p("n"), "tipo": "npc", "iniciativa_bonus": 2}}
    res = [{"personagem": "a", "total": 15}, {"personagem": "b", "total": 15}, {"personagem": "n", "total": 15}]
    assert re_.ordenar_iniciativa(res, pers) == ["b", "a", "n"]


def test_condicoes_por_turno():
    cfg = {"condicoes": {"sangrando": {"dano_por_turno": "1d6"}}}
    p = _p("a")
    p["condicoes"] = [{"id": "sangrando", "rodadas_restantes": 1}, {"id": "inspirado", "rodadas_restantes": None}]
    ini = re_.inicio_de_turno(p, cfg)
    assert ini[0]["tipo"] == "dano" and 1 <= ini[0]["valor"] <= 6
    fim = re_.fim_de_turno(p)
    assert fim == [{"tipo": "condicao_removida", "alvo": "a", "condicao": "sangrando"}]


def test_catalogo_de_efeitos_limita_valores():
    cat = {"dano_ambiental_medio": {"dano": "2d6", "tipo_dano": "impacto"}, "nenhum": {},
           "condicao_curta": {"condicoes_permitidas": ["caido"], "duracao_rodadas": 1}}
    evs = re_.aplicar_efeito_catalogo("dano_ambiental_medio", cat, _p("a"), [_p("b")])
    assert evs[0]["tipo"] == "dano" and 2 <= evs[0]["valor"] <= 12
    assert re_.aplicar_efeito_catalogo("nenhum", cat, _p("a"), [_p("b")]) == []
    assert re_.aplicar_efeito_catalogo("inexistente", cat, _p("a"), [_p("b")]) == []
    evs = re_.aplicar_efeito_catalogo("condicao_curta", cat, _p("a"), [_p("b")])
    assert evs[0]["condicao"] == "caido"
