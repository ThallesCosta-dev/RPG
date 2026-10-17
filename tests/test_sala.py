"""Testes da Sala com WebSockets falsos: todos confirmam, jogador sai, timer, fora de fase, reconexão, cliente travado."""
import asyncio
import copy

import pytest

from server.cartuchos import montar_cena_inicial
from server.events import EventStore
from server.gpu_scheduler import GPUScheduler
from server.llm.heuristico import HeuristicoProvider
from server.llm.provider import CadeiaProvedores, GestorCota
from server.motor import Motor
from server.room import Fase, Sala
from server.tts_engine import PipelineNarracao


class WSFalso:
    def __init__(self, lento=False):
        self.msgs = []
        self.fechado = None
        self.lento = lento

    async def send_json(self, msg):
        if self.lento:
            await asyncio.sleep(3600)
        self.msgs.append(msg)

    async def close(self, code=1000):
        self.fechado = code

    def tipos(self):
        return [m["type"] for m in self.msgs]

    def ultima(self, tipo):
        return next((m for m in reversed(self.msgs) if m["type"] == tipo), None)


async def ult(ws, tipo):
    await asyncio.sleep(0.02)
    return ws.ultima(tipo)


@pytest.fixture
def sala(sistema, campanha):
    motor = Motor(sistema.config, sistema.efeitos, campanha.cenas, sistema.plugin)
    store = EventStore(":memory:")
    pers = {p: copy.deepcopy(campanha.personagens[p]) for p in ("player_thorin", "player_lia")}
    jog = {"u1": {"player_id": "u1", "nome": "T", "papel": "host", "personagem_id": "player_thorin", "conectado": False},
           "u2": {"player_id": "u2", "nome": "A", "papel": "jogador", "personagem_id": "player_lia", "conectado": False},
           "u3": {"player_id": "u3", "nome": "E", "papel": "espectador", "personagem_id": None, "conectado": False}}
    store.criar_sala("s", "tormenta20", "coracao-de-rubi", "u1", montar_cena_inicial(campanha, "salao_do_trono"), pers, jog)
    store.adicionar_jogador("s", "u1", "T", "host", "player_thorin")
    gpu = GPUScheduler({})
    llm = CadeiaProvedores([HeuristicoProvider()], GestorCota(), store)
    s = Sala("s", store, motor, llm, PipelineNarracao(gpu), gpu, sistema, campanha, None, {"NARRADOR": {}},
             timeout_combate=0.3, timeout_exploracao=0.3)
    return s


async def _espera(cond, timeout=5.0):
    fim = asyncio.get_event_loop().time() + timeout
    while not cond():
        if asyncio.get_event_loop().time() > fim:
            raise AssertionError("timeout esperando condição")
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_fluxo_todos_confirmam(sala):
    w1, w2, w3 = WSFalso(), WSFalso(), WSFalso()
    await sala.conectar("u1", w1)
    await sala.conectar("u2", w2)
    await sala.conectar("u3", w3)
    await asyncio.sleep(0.01)
    assert w1.msgs[0]["type"] == "room_state" and w1.msgs[0]["eu"]["papel"] == "host"
    assert w3.msgs[0]["eu"]["papel"] == "espectador"
    await sala.confirmar("u1", {"slots": {}})
    assert (await ult(w1, "error"))["code"] == "fora_de_fase"

    await sala.comando_host("u2", {"comando": "iniciar"})
    assert (await ult(w2, "error"))["code"] == "sem_permissao"
    await sala.comando_host("u1", {"comando": "iniciar"})
    await asyncio.sleep(0.01)
    assert sala.fase is Fase.PLANEJAMENTO
    assert (await ult(w1, "alcance"))["personagem_id"] == "player_thorin"
    assert (await ult(w3, "alcance")) is None
    estado = sala.store.estado_atual("s")
    assert any(p["tipo"] == "npc" for p in estado["personagens"].values())     # NPCs da cena instanciados

    await sala.rolar("u1", "padrao", "1d20+8")
    await sala.rolar("u1", "padrao", "1d20+8")
    assert (await ult(w1, "error"))["code"] == "rolagem_invalida"
    await sala.rolar("u1", "padrao", "1d20+8; DROP TABLE")
    assert (await ult(w2, "dice_result"))["player_id"] == "u1"

    await sala.preview("u1", [99, 99])
    assert (await ult(w1, "error"))["code"] == "destino_invalido"
    await sala.confirmar("u3", {"slots": {}})
    assert (await ult(w3, "error"))["code"] == "sem_personagem"

    await sala.confirmar("u1", {"slots": {"padrao": {"tipo": "defender"}}})
    await asyncio.sleep(0.01)
    assert (await ult(w2, "ready_status"))["prontos"] == ["u1"] and w2.ultima("ready_status")["total"] == 2
    assert sala.fase is Fase.PLANEJAMENTO
    await sala.confirmar("u2", {"slots": {"livre": {"tipo": "fala", "texto": "Vamos!"}}})
    await _espera(lambda: w2.ultima("narration_end") is not None and sala.fase is Fase.PLANEJAMENTO)
    tipos = w2.tipos()
    assert "round_log" in tipos and "narration_segment" in tipos and "narration_end" in tipos
    i_log, i_sync = tipos.index("round_log"), tipos.index("state_sync", tipos.index("round_log"))
    assert i_log < tipos.index("narration_segment") < i_sync
    assert (await ult(w2, "state_sync"))["state"]["rodada"] == 1
    assert any(e["tipo"] == "fala" for a in (await ult(w2, "round_log"))["acoes"] for e in a["eventos"])
    assert (await ult(w1, "nivel_ia"))["nivel"] == 4


@pytest.mark.asyncio
async def test_timer_expira_e_desconexao_reavalia(sala):
    w1, w2 = WSFalso(), WSFalso()
    await sala.conectar("u1", w1)
    await sala.conectar("u2", w2)
    await sala.comando_host("u1", {"comando": "iniciar"})
    await _espera(lambda: (w1.ultima("state_sync") or {}).get("state", {}).get("rodada") == 1, timeout=5)   # ninguém confirmou: timer (0.3 s) dispara
    await _espera(lambda: sala.fase is Fase.PLANEJAMENTO)
    await sala.confirmar("u1", {"slots": {"padrao": {"tipo": "defender"}}})
    rodada_antes = sala.store.estado_atual("s")["rodada"]
    await sala.desconectar("u2", w2)                                       # quem faltava saiu → dispara
    await _espera(lambda: sala.store.estado_atual("s")["rodada"] == rodada_antes + 1)


@pytest.mark.asyncio
async def test_reconexao_fecha_antiga_e_cliente_travado_nao_bloqueia(sala):
    w1a, w1b, w2 = WSFalso(), WSFalso(), WSFalso(lento=True)
    await sala.conectar("u1", w1a)
    await sala.conectar("u1", w1b)
    await asyncio.sleep(0.01)
    assert w1a.fechado == 4009 and sala.clientes["u1"].ws is w1b
    await sala.desconectar("u1", w1a)                                      # conexão antiga não derruba a nova
    assert "u1" in sala.clientes
    await sala.conectar("u2", w2)
    for _ in range(30):                                                   # fila de 256 estoura → cliente travado é fechado
        for _ in range(10):
            sala.broadcast({"type": "phase", "fase": "lobby"})
        await asyncio.sleep(0.005)                                        # o cliente normal drena; o lento acumula
    assert w2.fechado == 4008 and "u2" not in sala.clientes
    assert (await ult(w1b, "phase")) is not None


@pytest.mark.asyncio
async def test_comandos_host_pausa_desfaz_edita(sala):
    w1 = WSFalso()
    await sala.conectar("u1", w1)
    await sala.comando_host("u1", {"comando": "iniciar"})
    await sala.comando_host("u1", {"comando": "pausar"})
    assert sala.fase is Fase.PAUSADO
    await sala.comando_host("u1", {"comando": "editar_personagem", "personagem_id": "player_thorin", "campos": {"barras": {"pv": {"atual": 10}}, "x": 0, "y": 0}})
    assert (await ult(w1, "error"))["code"] == "comando_falhou"                 # (0,0) é parede
    await sala.comando_host("u1", {"comando": "editar_personagem", "personagem_id": "player_thorin", "campos": {"barras": {"pv": {"atual": 10}}}})
    assert (await ult(w1, "state_sync"))["state"]["personagens"]["player_thorin"]["barras"]["pv"]["atual"] == 10
    await sala.comando_host("u1", {"comando": "mudar_nivel_ia", "nivel": 4})
    assert (await ult(w1, "nivel_ia"))["nivel"] == 4
    await sala.comando_host("u1", {"comando": "retomar"})
    assert sala.fase is Fase.PLANEJAMENTO
    await sala.comando_host("u1", {"comando": "resolver_agora"})
    await _espera(lambda: sala.store.estado_atual("s")["rodada"] == 1 and sala.fase is Fase.PLANEJAMENTO)
    await sala.comando_host("u1", {"comando": "desfazer_rodada"})
    assert sala.store.estado_atual("s")["rodada"] == 0
    await sala.comando_host("u1", {"comando": "mudar_cena", "cena_id": "estrada_norte"})
    assert (await ult(w1, "state_sync"))["state"]["cena"]["id"] == "estrada_norte"
    await sala.comando_host("u1", {"comando": "xyz"})
    assert (await ult(w1, "error"))["code"] == "comando_invalido"
    await sala.encerrar()


@pytest.mark.asyncio
async def test_revisao_de_arbitragem_pelo_host(sala):
    """§7.4: com a revisão ligada, o Host vê as arbitragens do Planejador e pode editá-las antes da resolução."""
    class PlanejadorComArbitragem:
        nome = "gemini"; ativo = True; modelo_atual = "fake"
        async def planejar(self, ctx):
            from server.llm.schemas import PlanoRodada
            return PlanoRodada.model_validate({"intencoes_npcs": [], "arbitragens": [
                {"personagem_id": "player_lia", "pericia": "pontaria", "dificuldade": "media", "motivo": "lustre",
                 "efeito_sucesso": "dano_ambiental_medio", "efeito_falha": "nenhum", "alvos": ["boss_orc"]}],
                "iniciar_combate": False, "mudar_cena_para": None})
        async def narrar_stream(self, ctx):
            yield "[VOZ:NARRADOR] [EVENTO:e1] Feito."
    sala.llm.provedores.insert(0, PlanejadorComArbitragem())
    sala.timeout_combate = sala.timeout_exploracao = 30
    w1, w2 = WSFalso(), WSFalso()
    await sala.conectar("u1", w1)
    await sala.conectar("u2", w2)
    await sala.comando_host("u1", {"comando": "revisar_arbitragens", "ativo": True})
    assert (await ult(w1, "config_sala"))["revisar_arbitragens"] is True
    await sala.comando_host("u1", {"comando": "iniciar"})
    await asyncio.sleep(0.02)
    await sala.confirmar("u1", {"slots": {"padrao": {"tipo": "defender"}}})
    await sala.confirmar("u2", {"slots": {"padrao": {"tipo": "criativa", "texto": "Atiro na corrente do lustre!"}}})
    arb = None
    for _ in range(100):
        await asyncio.sleep(0.02)
        arb = w1.ultima("arbitragens")
        if arb:
            break
    assert arb and arb["arbitragens"][0]["efeito_sucesso"] == "dano_ambiental_medio" and "nenhum" in arb["catalogo"]
    assert w2.ultima("arbitragens") is None                                   # só o Host vê
    assert (await ult(w2, "phase"))["aguardando_host"] is True
    editada = dict(arb["arbitragens"][0], dificuldade="dificil", efeito_sucesso="dano_ambiental_forte")
    await sala.comando_host("u1", {"comando": "editar_arbitragem", "arbitragens": [editada]})
    await _espera(lambda: w2.ultima("round_log") is not None)
    texto = " ".join(a["texto"] for a in w2.ultima("round_log")["acoes"])
    assert "CD 20" in texto                                                    # dificil → CD 20 da tabela
    await sala.comando_host("u1", {"comando": "aprovar_arbitragens"})
    assert (await ult(w1, "error"))["code"] == "sem_revisao_pendente"
    await sala.encerrar()
