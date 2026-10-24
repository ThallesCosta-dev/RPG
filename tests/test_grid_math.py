from server import grid_math as gm

MAPA = [
    "##########",
    "#........#",
    "#..P.....#",
    "#........#",
    "#..^^....#",
    "#..^^..~~#",
    "#........#",
    "##########",
]


def test_distancias_por_metrica():
    assert gm.distancia_quadrados((0, 0), (3, 3), "1-1-1") == 3
    assert gm.distancia_quadrados((0, 0), (3, 3), "1-2-1-2") == 4      # 1+2+1
    assert gm.distancia_quadrados((0, 0), (2, 2), "1-2-1-2") == 3      # 1+2
    assert gm.distancia_quadrados((0, 0), (3, 3), "manhattan") == 6
    assert gm.distancia_quadrados((1, 1), (5, 2), "1-2-1-2") == 4


def test_custos_respeitam_paredes_e_terreno():
    mapa = gm.MapaLogico(MAPA)
    custos = gm.custos_de_movimento((1, 1), mapa, "1-2-1-2", limite=6)
    assert (3, 2) not in custos                       # pilastra
    assert (7, 5) not in custos                       # água funda
    assert custos[(2, 1)] == 1
    assert custos[(3, 4)] == 5                    # (1,1)→(1,2)→(1,3)→(2,3) + diagonal em terreno difícil (1×2)
    assert all(c <= 6 for c in custos.values())


def test_nao_corta_quina_de_parede():
    mapa = gm.MapaLogico(["....", ".#..", "....", "...."])
    custos = gm.custos_de_movimento((0, 0), mapa, "1-1-1")
    # (1,1) é parede; de (0,0) a (1,1)? bloqueado. De (2,0) a (1,1)? bloqueado. De (0,0) direto para (1,1) não existe.
    assert (1, 1) not in custos
    # (1,0)→(2,1) é diagonal com a parede (1,1) na quina: proibido; vai por (2,0), custo 3
    assert custos[(2, 1)] == 3
    # idem para (1,2): via (0,2), custo 3
    assert custos[(1, 2)] == 3


def test_tokens_bloqueiam_e_diagonais_alternam():
    mapa = gm.MapaLogico(["......", "......", "......"], ocupados={(1, 0)})
    custos = gm.custos_de_movimento((0, 0), mapa, "1-2-1-2")
    assert (1, 0) not in custos
    assert custos[(2, 2)] == 3     # duas diagonais: 1 + 2
    assert custos[(1, 1)] == 1


def test_caminho_e_mais_proximo():
    mapa = gm.MapaLogico(MAPA)
    res = gm.caminho((1, 1), (8, 6), mapa, "1-2-1-2")
    assert res is not None
    pontos, custo = res
    assert pontos[0] == (1, 1) and pontos[-1] == (8, 6)
    assert all(mapa.passavel(*p) for p in pontos[1:])
    assert gm.caminho((1, 1), (3, 2), mapa) is None        # pilastra
    perto = gm.mais_proximo_alcancavel((1, 1), (8, 6), mapa, "1-2-1-2", limite=3)
    assert gm.distancia_quadrados(perto, (8, 6)) < gm.distancia_quadrados((1, 1), (8, 6))


def test_linha_de_visao():
    mapa = gm.MapaLogico(MAPA)
    assert gm.linha_de_visao((1, 2), (8, 2), mapa) is False     # pilastra em (3,2)
    assert gm.linha_de_visao((1, 1), (8, 1), mapa) is True
    assert gm.linha_de_visao((1, 5), (8, 5), mapa) is True      # água não bloqueia visão
    mapa.obstaculos[(4, 1)] = "parede_de_gelo"
    assert gm.linha_de_visao((1, 1), (8, 1), mapa) is False


def test_areas():
    mapa = gm.MapaLogico(MAPA)
    raio = gm.area_raio((5, 3), 1, mapa)
    assert (5, 3) in raio and (6, 4) in raio and len(raio) == 9
    linha = gm.area_linha((1, 2), (1, 0), 5, mapa)
    assert linha == [(2, 2)]                                    # para na pilastra (3,2)
    cone = gm.area_cone((5, 3), (1, 0), 2, mapa)
    assert (7, 3) in cone and (6, 2) in cone and (3, 3) not in cone


def test_validar_tilemap():
    assert gm.validar_tilemap(["##", "#."]) == []
    assert gm.validar_tilemap(["##", "#"]) != []
    assert gm.validar_tilemap(["#X"]) != []


def test_agua_rasa_passavel_com_custo_dobrado():
    mapa = gm.MapaLogico(["....", ".w~.", "...."])
    custos = gm.custos_de_movimento((0, 1), mapa, "1-1-1")
    assert custos[(1, 1)] == 2                                   # água rasa: custo x2
    assert (2, 1) not in custos                                  # água funda bloqueia
    assert gm.linha_de_visao((0, 1), (3, 1), mapa) is True       # nenhuma das duas bloqueia visão
    assert gm.validar_tilemap(["w~"]) == []
