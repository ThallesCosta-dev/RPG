"""Narração por template (nível 4 da escada de degradação, §10.4).

Transforma o log da rodada em texto com as mesmas tags que o LLM usaria ([VOZ:...] [EVENTO:...]),
para que o pipeline de TTS e as animações funcionem igual.
"""
from __future__ import annotations

from collections.abc import AsyncIterator


def narrar_rodada(acoes: list[dict], falas: list[dict] | None = None) -> str:
    partes = []
    for a in acoes:
        partes.append(f"[VOZ:NARRADOR] [EVENTO:{a['id']}] {a['texto']}.")
    for f in falas or []:
        marcador = f"[EVENTO:{f['id']}] " if f.get("id") else ""
        partes.append(f"[VOZ:{f['voz']}] {marcador}\"{f['texto']}\"")
    if not partes:
        partes.append("[VOZ:NARRADOR] A rodada passa sem incidentes.")
    partes.append("[VOZ:NARRADOR] O que vocês fazem?")
    return "\n".join(partes)


async def stream_de_texto(texto: str, tamanho: int = 40) -> AsyncIterator[str]:
    """Simula o stream do LLM (pedaços de texto) para reaproveitar o segmentador."""
    for i in range(0, len(texto), tamanho):
        yield texto[i:i + tamanho]
