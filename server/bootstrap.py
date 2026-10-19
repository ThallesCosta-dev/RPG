"""Monta store, motor, provedores, GPU Scheduler e salas (§4). Ponto único de configuração."""
from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from . import auth, map_engine, tts_engine  # noqa: E402
from .cartuchos import Biblioteca, montar_cena_inicial  # noqa: E402
from .events import EventStore  # noqa: E402
from .fichas import FichasSalvas, modelo_ficha, validar_ficha  # noqa: E402
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
        self.fichas = FichasSalvas(dir_dados / "fichas")
        self.voices = json.loads((self.raiz / "voices.json").read_text(encoding="utf-8")) if (self.raiz / "voices.json").exists() else {"NARRADOR": {}}
        self.gpu = GPUScheduler({})
        self.llm = CadeiaProvedores([GeminiProvider(), LocalProvider(), HeuristicoProvider()], GestorCota(), self.store)
        self.narracao = PipelineNarracao(self.gpu)
        self.salas: dict[str, Sala] = {}
        self._rags: dict[str, IndiceRAG] = {}

    # ---------------------------------------------------------------- ciclo de vida
    async def iniciar(self):
        handlers = {}
        tts = tts_engine.escolher_handler_tts(self.voices)
        if tts:
            handlers["tts"] = tts
        else:
            log.info("TTS: nenhum motor disponível; narração só com legenda")
        if os.getenv("COMFYUI_URL"):
            handlers["mapa"] = map_engine.gerar_imagem_comfyui
        if tts:
            handlers["amostra"] = lambda voz_id: tts_engine.amostra_de_voz(tts, self.voices, voz_id)
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
            fontes = list(s.manifest.get("fontes") or []) or ([s.manifest["fonte"]] if s.manifest.get("fonte") else [])
            for f in fontes:
                caminho = (s.caminho / f) if s.caminho else None
                if caminho and caminho.exists():
                    indexar_markdown(indice, f"{s.id}:{f}", caminho.read_text(encoding="utf-8"))
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

    def _disponiveis(self, sala_id: str, info: dict, estado: dict) -> dict[str, tuple[str, dict]]:
        """Personagens que um jogador pode assumir: modelos da campanha, fichas criadas nesta sala e fichas salvas do sistema."""
        campanha = self.biblioteca.campanha(info["campanha_id"])
        usados = {j.get("personagem_id") for j in estado["jogadores"].values()}
        out: dict[str, tuple[str, dict]] = {}
        for p in campanha.personagens.values():
            if p["id"] not in usados:
                out[p["id"]] = ("campanha", p)
        for p in estado["personagens"].values():
            if p.get("tipo") == "jogador" and p["id"] not in usados:
                out[p["id"]] = ("sala", p)
        for p in self.fichas.listar(info["sistema_id"]):
            if p["id"] not in usados and p["id"] not in estado["personagens"]:
                out[p["id"]] = ("salva", p)
        return out

    def lobby(self, sala_id: str) -> dict:
        info = self.store.info_sala(sala_id)
        if not info:
            raise KeyError("sala inexistente")
        campanha = self.biblioteca.campanha(info["campanha_id"])
        estado = self.store.estado_atual(sala_id)
        disponiveis = [{"id": p["id"], "nome": p["nome"], "classe": p.get("classe", ""), "icone": p.get("icone", ""), "cor": p.get("cor", ""),
                        "origem": origem} for origem, p in self._disponiveis(sala_id, info, estado).values()]
        return {"sala_id": sala_id, "campanha": campanha.nome, "sistema": info["sistema_id"], "tema": campanha.tema,
                "personagens_disponiveis": disponiveis,
                "jogadores": [{"nome": j["nome"], "papel": j["papel"], "personagem_id": j.get("personagem_id")} for j in estado["jogadores"].values()]}

    def _posicionar(self, estado: dict, info: dict, ficha: dict) -> dict:
        """Coloca a ficha numa célula livre perto da entrada da cena atual."""
        campanha = self.biblioteca.campanha(info["campanha_id"])
        cena = estado["cena"]
        if cena.get("tilemap"):
            from . import grid_math as gm
            sala = self.salas.get(estado["sala_id"])
            motor = sala.motor if sala else self._motor(info["sistema_id"], info["campanha_id"])
            mapa = motor.mapa_logico(estado)
            entrada = tuple(campanha.cenas.get(cena["id"], {}).get("entrada", [1, 1]))
            for c in sorted(gm.bfs_conectado(cena["tilemap"], entrada), key=lambda c: gm.distancia_quadrados(c, entrada)):
                if mapa.passavel(*c):
                    ficha["x"], ficha["y"] = c
                    break
        return ficha

    def criar_ficha(self, sala_id: str, dados: dict, player_id: str | None = None, convite: str | None = None) -> dict:
        info = self.store.info_sala(sala_id)
        if not info:
            raise KeyError("sala inexistente")
        if player_id is None and not (convite and self.store.convite_valido(sala_id, convite)):
            raise PermissionError("convite inválido")
        sistema = self.biblioteca.sistema(info["sistema_id"])
        ficha, erros = validar_ficha(dados, sistema, self.voices)
        if erros:
            raise ValueError("; ".join(erros))
        estado = self.store.estado_atual(sala_id)
        self._posicionar(estado, info, ficha)
        self.fichas.salvar(ficha)
        eventos = [{"tipo": "personagem_adicionado", "personagem": ficha}]
        self.store.anexar(sala_id, eventos)
        j = estado["jogadores"].get(player_id or "")
        if j and not j.get("personagem_id"):
            self.store.definir_personagem(sala_id, player_id, ficha["id"], "host" if j["papel"] == "host" else "jogador")
        sala = self.salas.get(sala_id)
        if sala:
            sala._sync()
            sala._broadcast_jogadores()
            if player_id and j:
                sala.enviar(player_id, sala._msg_room_state(player_id))
        return ficha

    def escolher_personagem(self, sala_id: str, player_id: str, personagem_id: str) -> dict:
        info = self.store.info_sala(sala_id)
        if not info:
            raise KeyError("sala inexistente")
        estado = self.store.estado_atual(sala_id)
        j = estado["jogadores"].get(player_id)
        if j is None:
            raise PermissionError("jogador não está na sala")
        if j.get("personagem_id"):
            raise ValueError("você já tem um personagem")
        disp = self._disponiveis(sala_id, info, estado)
        if personagem_id not in disp:
            raise ValueError("personagem indisponível")
        origem, ficha = disp[personagem_id]
        if origem != "sala":
            ficha = self._posicionar(estado, info, copy.deepcopy(ficha))
            ficha.setdefault("condicoes", [])
            ficha.setdefault("caido", False)
            self.store.anexar(sala_id, [{"tipo": "personagem_adicionado", "personagem": ficha}])
        self.store.definir_personagem(sala_id, player_id, personagem_id, "host" if j["papel"] == "host" else "jogador")
        sala = self.salas.get(sala_id)
        if sala:
            sala._sync()
            sala._broadcast_jogadores()
            sala.enviar(player_id, sala._msg_room_state(player_id))
        return ficha

    def entrar(self, sala_id: str, convite: str, nome: str, personagem_id: str | None) -> dict:
        info = self.store.info_sala(sala_id)
        if not info:
            raise KeyError("sala inexistente")
        if not self.store.convite_valido(sala_id, convite):
            raise PermissionError("convite inválido ou já usado")
        estado = self.store.estado_atual(sala_id)
        papel, ficha = "espectador", None
        if personagem_id:
            disp = self._disponiveis(sala_id, info, estado)
            if personagem_id not in disp:
                raise ValueError("personagem indisponível")
            origem, ficha = disp[personagem_id]
            papel = "jogador"
            if origem == "sala":
                ficha = None                                  # já está no estado; só vincula
            else:
                ficha = self._posicionar(estado, info, copy.deepcopy(ficha))
                ficha.setdefault("condicoes", [])
                ficha.setdefault("caido", False)
        player_id = auth.novo_player_id()
        self.store.adicionar_jogador(sala_id, player_id, nome[:40], papel, personagem_id if papel == "jogador" else None, ficha)
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

    def modelo_ficha(self, sistema_id: str) -> dict:
        m = modelo_ficha(self.biblioteca.sistema(sistema_id))
        m["vozes"] = self.vozes()
        return m

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

    def vozes(self) -> list[dict]:
        return tts_engine.vozes_escolhiveis(self.voices)

    async def amostra_de_voz(self, voz_id: str) -> str | None:
        if not self.gpu.tem_handler("tts") or voz_id not in self.voices or voz_id.startswith("_"):
            return None
        return await self.gpu.submeter(0, ("amostra", voz_id))
