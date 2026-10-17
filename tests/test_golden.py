"""Golden tests (§18.1): rodadas gravadas (estado + ações + resposta do LLM) reproduzidas sem chamar a API.

Para regravar depois de uma mudança intencional no motor: `python -m pytest tests/test_golden.py --regravar`.
"""
import json
from pathlib import Path

import pytest

from server import rules_engine
from server.motor import Motor

DIR = Path(__file__).parent / "golden"


def _resumo(eventos: list[dict], log: list[dict]) -> dict:
    """O que não pode mudar sem intenção: tipos e sequência de eventos, textos do log, PV finais relevantes."""
    return {
        "tipos": [e["tipo"] for e in eventos],
        "log": [a["texto"] for a in log],
        "danos": [[e["alvo"], e["valor"]] for e in eventos if e["tipo"] == "dano"],
        "rejeitadas": [e["motivo"] for e in eventos if e["tipo"] == "intencao_rejeitada"],
    }


@pytest.mark.parametrize("caso", sorted(p.stem for p in DIR.glob("*.json")))
def test_rodada_gravada(caso, biblioteca, request):
    dados = json.loads((DIR / f"{caso}.json").read_text(encoding="utf-8"))
    sis = biblioteca.sistema(dados["sistema_id"])
    camp = biblioteca.campanha(dados["campanha_id"])
    motor = Motor(sis.config, sis.efeitos, camp.cenas, sis.plugin)
    rules_engine.usar_semente(dados["seed"])
    eventos, log = motor.resolver_rodada(dados["estado"], dados["acoes"], dados["plano"], dados.get("rolagens", {}))
    atual = _resumo(eventos, log)
    if request.config.getoption("--regravar"):
        dados["esperado"] = atual
        (DIR / f"{caso}.json").write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        pytest.skip("regravado")
    assert atual == dados["esperado"], f"golden '{caso}' divergiu; se a mudança foi intencional, rode com --regravar"
