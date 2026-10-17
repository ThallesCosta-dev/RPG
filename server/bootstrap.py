"""Monta store, motor, provedores, GPU Scheduler e salas (§4). Ponto único de configuração."""
from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from . import auth, map_engine, tts_engine  # noqa: E402
from .cartuchos import Biblioteca, montar_cena_inicial  # noqa: E402
from .events import EventStore  # noqa: E402
from .gpu_scheduler import GPUScheduler  # noqa: E402
from .llm.gemini import GeminiProvider  # noqa: E402
from .llm.heuristico import HeuristicoProvider  # noqa: E402
from .llm.local import LocalProvider  # noqa: E402
from .llm.provider import CadeiaProvedores, GestorCota  # noqa: E402
from .motor import Motor  # noqa: E402
from .rag import IndiceRAG, indexar_markdown  # noqa: E402
from .room import Sala  # noqa: E402
from .tts_engine import PipelineNarracao  # noqa: E402

log = logging.getLogger("ai_vtt")
RAIZ = Path(__file__).resolve().parents[1]


class App:
    def __init__(self, raiz: Path | None = None, em_memoria: bool = False):
        self.raiz = raiz or RAIZ
        dir_dados = self.raiz / os.getenv("DIR_DADOS", "data")
        dir_dados.mkdir(parents=True, exist_ok=True)
        self.biblioteca = Biblioteca(self.raiz / os.getenv("DIR_CARTUCHOS", "cartuchos"))
        self.store = EventStore(":memory:" if em_memoria else dir_dados / "sessions.db")
        self.voices = json.loads((self.raiz / "voices.json").read_text(encoding="utf-8")) if (self.raiz / "voices.json").exists() else {"NARRADOR": {}}
        self.gpu = GPUScheduler({})
        self.llm = CadeiaProvedores([GeminiProvider(), LocalProvider(), HeuristicoProvider()], GestorCota(), self.store)
        self.narracao = PipelineNarracao(self.gpu)
        self.salas: dict[str, Sala] = {}
        self._rags: dict[str, IndiceRAG] = {}

    # ---------------------------------------------------------------- ciclo de vida
    async def iniciar(self):
        handlers = {}
        tts = tts_engine.escolher_handler_tts()
        if tts:
            handlers["tts"] = tts
        else:
            log.info("TTS: nenhum motor disponível; narração só com legenda")
        if os.getenv("COMFYUI_URL"):
            handlers["mapa"] = map_engine.gerar_imagem_comfyui
        self.gpu.handlers.update(handlers)
        self.gpu.iniciar()
        tts_engine.limpar_audio_antigo(float(os.getenv("AUDIO_MAX_IDADE_H", "48")))
        log.info("IA: nível %s (%s)", self.llm.nivel(), self.llm.status()["nome"])

    async def parar(self):
        for sala in list(self.salas.values()):
            await sala.encerrar()
        self.gpu.parar()
        self.store.fechar()

    # ---------------------------------------------------------------- RAG por cartucho
    def rag_para(self, sistema, campanha) -> IndiceRAG:
        chave = f"{sistema.id}|{campanha.id}"
        if chave in self._rags:
            return self._rags[chave]
        indice = IndiceRAG()
        for s in (sistema, campanha):
            idx = (s.caminho / "compilado" / "rag_index.db") if s.caminho else None
            if idx and idx.exists():
                sub = IndiceRAG(idx)
                if len(sub):
                    indice.indexar(s.id, [{"caminho": d["caminho"], "texto": d["texto"]} for d in sub._docs])
                    continue
            fonte = (s.caminho / s.manifest.get("fonte", "")) if s.caminho and s.manifest.get("fonte") else None
            if fonte and fonte.exists():
                indexar_markdown(indice, s.id, fonte.read_text(encoding="utf-8"))
        self._rags[chave] = indice
        return indice

    # ---------------------------------------------------------------- salas
    def criar_sala(self, nome_host: str, sistema_id: str, campanha_id: str, personagem_id: str | None = None) -> dict:
        sistema = self.biblioteca.sistema(sistema_id)
        campanha = self.biblioteca.campanha(campanha_id)
        if campanha.sistema_id != sistema_id:
            raise ValueError(f"a campanha exige o sistema {campanha.sistema_id}")
        if not (sistema.revisado and campanha.revisado):
            raise ValueError("cartucho ainda não revisado pelo Host")
        sala_id = auth.nova_sala_id()
        host_id = auth.novo_player_id()
        personagens = {}
        if personagem_id and personagem_id in campanha.personagens:
            personagens[personagem_id] = copy.deepcopy(campanha.personagens[personagem_id])
        jogadores = {host_id: {"player_id": host_id, "nome": nome_host[:40], "papel": "host",
                               "personagem_id": personagem_id if personagem_id in personagens else None, "conectado": False}}
        self.store.criar_sala(sala_id, sistema_id, campanha_id, host_id, montar_cena_inicial(campanha), personagens, jogadores)
        self.store.adicionar_jogador(sala_id, host_id, nome_host[:40], "host", jogadores[host_id]["personagem_id"])
        convite = auth.novo_codigo_convite()
        self.store.criar_convite(sala_id, convite)
        return {"sala_id": sala_id, "player_id": host_id, "token": auth.criar_token(sala_id, host_id, "host"), "convite": convite}

    def lobby(self, sala_id: str) -> dict:
        info = self.store.info_sala(sala_id)
        if not info:
            raise KeyError("sala inexistente")
        campanha = self.biblioteca.campanha(info["campanha_id"])
        estado = self.store.estado_atual(sala_id)
        usados = {j.get("personagem_id") for j in estado["jogadores"].values()}
        disponiveis = [{"id": p["id"], "nome": p["nome"], "classe": p.get("classe", ""), "icone": p.get("icone", ""), "cor": p.get("cor", "")}
                       for p in campanha.personagens.values() if p["id"] not in usados]
        return {"sala_id": sala_id, "campanha": campanha.nome, "sistema": info["sistema_id"], "tema": campanha.tema,
                "personagens_disponiveis": disponiveis,
                "jogadores": [{"nome": j["nome"], "papel": j["papel"], "personagem_id": j.get("personagem_id")} for j in estado["jogadores"].values()]}

    def entrar(self, sala_id: str, convite: str, nome: str, personagem_id: str | None) -> dict:
        info = self.store.info_sala(sala_id)
        if not info:
            raise KeyError("sala inexistente")
        if not self.store.convite_valido(sala_id, convite):
            raise PermissionError("convite inválido ou já usado")
        campanha = self.biblioteca.campanha(info["campanha_id"])
        estado = self.store.estado_atual(sala_id)
        usados = {j.get("personagem_id") for j in estado["jogadores"].values()}
        papel, ficha = "espectador", None
        if personagem_id:
            if personagem_id not in campanha.personagens or personagem_id in usados:
                raise ValueError("personagem indisponível")
            papel = "jogador"
            ficha = copy.deepcopy(campanha.personagens[personagem_id])
            cena = estado["cena"]
            if cena.get("tilemap"):
                sala = self.salas.get(sala_id)
                motor = sala.motor if sala else self._motor(info["sistema_id"], info["campanha_id"])
                from . import grid_math as gm
                mapa = motor.mapa_logico(estado)
                cfg_cena = campanha.cenas.get(cena["id"], {})
                entrada = tuple(cfg_cena.get("entrada", [1, 1]))
                livres = sorted(gm.bfs_conectado(cena["tilemap"], entrada), key=lambda c: gm.distancia_quadrados(c, entrada))
                for c in livres:
                    if mapa.passavel(*c):
                        ficha["x"], ficha["y"] = c
                        break
        player_id = auth.novo_player_id()
        self.store.adicionar_jogador(sala_id, player_id, nome[:40], papel, personagem_id if ficha else None, ficha)
        self.store.usar_convite(convite, player_id)
        sala = self.salas.get(sala_id)
        if sala:
            sala._sync()
            sala._broadcast_jogadores()
        return {"token": auth.criar_token(sala_id, player_id, papel), "player_id": player_id, "papel": papel}

    def novo_convite(self, sala_id: str) -> str:
        convite = auth.novo_codigo_convite()
        self.store.criar_convite(sala_id, convite)
        return convite

    def _motor(self, sistema_id: str, campanha_id: str) -> Motor:
        sistema = self.biblioteca.sistema(sistema_id)
        campanha = self.biblioteca.campanha(campanha_id)
        return Motor(sistema.config, sistema.efeitos, campanha.cenas, sistema.plugin)

    def obter_sala(self, sala_id: str) -> Sala:
        if sala_id in self.salas:
            return self.salas[sala_id]
        info = self.store.info_sala(sala_id)
        if not info:
            raise KeyError("sala inexistente")
        sistema = self.biblioteca.sistema(info["sistema_id"])
        campanha = self.biblioteca.campanha(info["campanha_id"])
        motor = Motor(sistema.config, sistema.efeitos, campanha.cenas, sistema.plugin)
        sala = Sala(sala_id, self.store, motor, self.llm, self.narracao, self.gpu, sistema, campanha,
                    self.rag_para(sistema, campanha), self.voices)
        self.salas[sala_id] = sala
        return sala

    def caminho_audio(self, audio_id: str):
        return tts_engine.caminho_audio(audio_id)
