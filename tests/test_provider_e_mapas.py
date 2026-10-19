import pytest

from server import grid_math as gm
from server import map_engine
from server.llm.heuristico import HeuristicoProvider
from server.llm.provider import CadeiaProvedores, GestorCota
from server.llm.schemas import Contexto, PlanoRodada


class ProvedorQuebrado:
    nome = "gemini"
    ativo = True
    modelo_atual = "x"

    def __init__(self):
        self.chamadas = 0

    async def planejar(self, ctx):
        self.chamadas += 1
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    async def narrar_stream(self, ctx):
        yield "Começo da narração. "
        raise RuntimeError("caiu no meio")


@pytest.mark.asyncio
async def test_cadeia_cai_para_heuristico_e_penaliza(motor, estado_salao):
    _, estado = estado_salao
    quebrado = ProvedorQuebrado()
    cadeia = CadeiaProvedores([quebrado, HeuristicoProvider()], GestorCota(rpm=5, rpd=10))
    assert cadeia.nivel() == 1
    op = motor.opcoes_validas(estado)
    ctx = Contexto("planejar", "s", "c", schema=PlanoRodada, dados={"estado": estado, "opcoes": op, "metrica": motor.metrica})
    plano = await cadeia.planejar(ctx)
    assert isinstance(plano, PlanoRodada) and plano.intencoes_npcs
    assert cadeia.ultimo_provedor == "heuristico"
    assert cadeia.nivel() == 4                      # 429 → cooldown do gemini → sem local → nível 4
    assert quebrado.chamadas == 1


@pytest.mark.asyncio
async def test_narracao_parcial_nao_repete():
    cadeia = CadeiaProvedores([ProvedorQuebrado(), HeuristicoProvider()], GestorCota())
    ctx = Contexto("narrar", "s", "c", dados={"acoes_log": [], "estado": {}})
    partes = [p async for p in cadeia.narrar_stream(ctx)]
    assert partes == ["Começo da narração. "]       # já narrou uma parte: não recomeça no próximo provedor


def test_gestor_cota_niveis():
    cota = GestorCota(rpm=2, rpd=4, limiar=0.5)
    assert cota.disponivel("gemini")
    cota.registrar("gemini"); cota.registrar("gemini")
    assert cota.disponivel("gemini")                 # contador local não bloqueia: só o 429 real
    assert cota.acima_dos_limites("gemini") and cota.fracao_diaria("gemini") == 0.5
    cota.penalizar("gemini", 60); cota.penalizar("gemini", 60)
    assert not cota.disponivel("gemini") and cota.resumo("gemini")["cooldown_s"] >= 100   # escalou
    cadeia = CadeiaProvedores([HeuristicoProvider()], cota)
    cadeia.nivel_forcado = 3
    assert cadeia.status()["nivel"] == 3


@pytest.mark.parametrize("tipo", ["masmorra", "caverna", "taverna", "rua", "floresta", "salao"])
def test_gerador_de_tilemaps_sempre_jogavel(tipo):
    tilemap, entrada = map_engine.gerar_tilemap(tipo, 20, 15, ["agua", "pilastras", "cobertura", "terreno_dificil"], seed=tipo)
    assert gm.validar_tilemap(tilemap) == []
    assert len(tilemap) == 15 and len(tilemap[0]) == 20
    mapa = gm.MapaLogico(tilemap)
    assert mapa.passavel(*entrada)
    chao = sum(l.count(".") for l in tilemap)
    assert len(gm.bfs_conectado(tilemap, entrada)) >= chao * 0.8
    # determinístico por semente
    assert map_engine.gerar_tilemap(tipo, 20, 15, ["agua"], seed=tipo)[0] == map_engine.gerar_tilemap(tipo, 20, 15, ["agua"], seed=tipo)[0]


def test_imagem_de_controle_png():
    png = map_engine.imagem_controle(["#.#", ".~."], px=4)
    assert png.startswith(b"\x89PNG") and len(png) > 50
    assert map_engine.chave_cache(["#"], "p", 1) != map_engine.chave_cache(["#"], "p", 2)
