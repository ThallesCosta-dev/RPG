import copy
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from server import rules_engine  # noqa: E402
from server.cartuchos import Biblioteca, montar_cena_inicial  # noqa: E402
from server.events import EventStore  # noqa: E402
from server.motor import Motor  # noqa: E402


def pytest_addoption(parser):
    parser.addoption("--regravar", action="store_true", default=False, help="regrava os golden tests")


@pytest.fixture(autouse=True)
def semente():
    rules_engine.usar_semente(1234)
    yield
    rules_engine.usar_semente(None)


@pytest.fixture(scope="session")
def biblioteca():
    return Biblioteca(RAIZ / "cartuchos")


@pytest.fixture
def sistema(biblioteca):
    return biblioteca.sistema("tormenta20")


@pytest.fixture
def campanha(biblioteca):
    return biblioteca.campanha("coracao-de-rubi")


@pytest.fixture
def motor(sistema, campanha):
    return Motor(sistema.config, sistema.efeitos, campanha.cenas, sistema.plugin)


@pytest.fixture
def estado_salao(motor, campanha):
    """Estado da cena do salão (§10.2): Thorin e Lia posicionados perto dos inimigos."""
    personagens = {pid: copy.deepcopy(campanha.personagens[pid]) for pid in ("player_thorin", "player_lia")}
    jogadores = {"u1": {"player_id": "u1", "nome": "Thalles", "papel": "host", "personagem_id": "player_thorin", "conectado": True},
                 "u2": {"player_id": "u2", "nome": "Ana", "papel": "jogador", "personagem_id": "player_lia", "conectado": True}}
    store = EventStore(":memory:")
    store.criar_sala("t", "tormenta20", "coracao-de-rubi", "u1", montar_cena_inicial(campanha, "salao_do_trono"), personagens, jogadores)
    estado = store.estado_atual("t")
    store.anexar("t", [motor.evento_mudar_cena(estado, "salao_do_trono")])
    store.anexar("t", [
        {"tipo": "personagem_editado", "personagem_id": "player_thorin", "campos": {"x": 6, "y": 5}},
        {"tipo": "personagem_editado", "personagem_id": "player_lia", "campos": {"x": 2, "y": 9}},
        {"tipo": "personagem_removido", "personagem_id": "goblin_arqueiro_2"},
    ])
    return store, store.estado_atual("t")
