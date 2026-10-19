"""GPU Scheduler: duas faixas na mesma GPU (§13).

- tempo real (0 = TTS, 1 = embeddings): modelos pequenos, sempre residentes;
- pesada (2 = mapas): um job por vez e só quando nenhuma sala está narrando.
O LLM local roda em processo próprio (llama.cpp/Ollama); no nível 3 a faixa pesada é desligada.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
from collections.abc import Callable

log = logging.getLogger("ai_vtt.gpu")


class GPUScheduler:
    def __init__(self, handlers: dict[str, Callable] | None = None):
        self.handlers: dict[str, Callable] = {k: v for k, v in (handlers or {}).items() if v is not None}
        self.filas = {"tempo_real": asyncio.PriorityQueue(), "pesada": asyncio.PriorityQueue()}
        self.sem_narracao = asyncio.Event()
        self.sem_narracao.set()
        self.pesada_ligada = asyncio.Event()
        self.pesada_ligada.set()
        self._narracoes = 0
        self._ordem = itertools.count()
        self._tarefas: list[asyncio.Task] = []

    def tem_handler(self, tipo: str) -> bool:
        return tipo in self.handlers

    def submeter(self, prioridade: int, job: tuple) -> asyncio.Future:
        futuro = asyncio.get_running_loop().create_future()
        if job[0] not in self.handlers:
            futuro.set_exception(KeyError(f"sem handler para {job[0]}"))
            return futuro
        faixa = "tempo_real" if prioridade <= 1 else "pesada"
        self.filas[faixa].put_nowait((prioridade, next(self._ordem), job, futuro))
        return futuro

    def narracao_iniciada(self) -> None:
        self._narracoes += 1
        self.sem_narracao.clear()

    def narracao_terminada(self) -> None:
        self._narracoes = max(0, self._narracoes - 1)
        if self._narracoes == 0:
            self.sem_narracao.set()

    def desligar_pesada(self, desligar: bool = True) -> None:
        """Nível 3: a VRAM vai para o LLM local; mapas esperam."""
        if desligar:
            self.pesada_ligada.clear()
        else:
            self.pesada_ligada.set()

    async def _worker(self, faixa: str) -> None:
        fila = self.filas[faixa]
        while True:
            _, _, (tipo, *args), futuro = await fila.get()
            if faixa == "pesada":
                await self.sem_narracao.wait()       # mapa espera a narração terminar
                await self.pesada_ligada.wait()
            if futuro.done():                        # cancelado por quem pediu
                continue
            try:
                resultado = await asyncio.to_thread(self.handlers[tipo], *args)
            except Exception as exc:
                log.warning("job %s falhou: %s", tipo, exc)
                if not futuro.done():
                    futuro.set_exception(exc)
            else:
                if not futuro.done():
                    futuro.set_result(resultado)

    def iniciar(self, workers_tempo_real: int | None = None) -> None:
        if not self._tarefas:
            import os
            n = workers_tempo_real or int(os.getenv("TTS_PARALELO", "3"))
            self._tarefas = [asyncio.create_task(self._worker("tempo_real")) for _ in range(max(1, n))]
            self._tarefas.append(asyncio.create_task(self._worker("pesada")))

    async def rodar(self) -> None:
        await asyncio.gather(self._worker("tempo_real"), self._worker("pesada"))

    def parar(self) -> None:
        for t in self._tarefas:
            t.cancel()
        self._tarefas = []
