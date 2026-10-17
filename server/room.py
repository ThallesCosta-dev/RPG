"""Orquestrador de sala / máquina de estados (§8, §17.2).

LOBBY → PLANEJAMENTO → RESOLVENDO → NARRANDO → PLANEJAMENTO … ; PAUSADO a qualquer momento pelo Host.
Cada cliente tem a própria fila de envio: um navegador lento não atrasa os outros.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from . import context_builder as cb
from .llm.schemas import Contexto, LayoutMapa, Memoria
from .rules_engine import vivo
from .tts_engine import TAG_FALA, resolver_vozes
import secrets

log = logging.getLogger("ai_vtt.sala")

ACAO_AUSENTE = {"slots": {"padrao": {"tipo": "defender"}}}
MAX_MSGS_POR_S = 20


class Fase(str, Enum):
    LOBBY = "lobby"
    PLANEJAMENTO = "planejamento"
    RESOLVENDO = "resolvendo"
    NARRANDO = "narrando"
    PAUSADO = "pausado"


@dataclass
class Cliente:
    player_id: str
    ws: Any
    fila: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=256))
    tarefa: asyncio.Task | None = None
    janela: list[float] = field(default_factory=list)

    async def loop_envio(self):
        while True:
            await self.ws.send_json(await self.fila.get())

    def dentro_do_limite(self) -> bool:
        agora = time.time()
        self.janela = [t for t in self.janela if t > agora - 1]
        self.janela.append(agora)
        return len(self.janela) <= MAX_MSGS_POR_S


class Sala:
    def __init__(self, sala_id: str, store, motor, llm, narracao, gpu, sistema, campanha, rag=None,
                 voices: dict | None = None, timeout_combate: float | None = None, timeout_exploracao: float | None = None):
        self.sala_id = sala_id
        self.store, self.motor, self.llm = store, motor, llm
        self.narracao, self.gpu = narracao, gpu
        self.sistema, self.campanha, self.rag = sistema, campanha, rag
        self.voices = voices or {"NARRADOR": {}}
        self.timeout_combate = timeout_combate or float(os.getenv("TIMEOUT_COMBATE", "90"))
        self.timeout_exploracao = timeout_exploracao or float(os.getenv("TIMEOUT_EXPLORACAO", "180"))
        self.clientes: dict[str, Cliente] = {}
        self.acoes: dict[str, dict] = {}
        self.rolagens: dict[str, dict] = {}
        self.fase = Fase.LOBBY
        self.fase_anterior = Fase.LOBBY
        self.prazo: float | None = None
        self.pausa_pendente = False
        self.lock = asyncio.Lock()
        self._timer: asyncio.Task | None = None
        self._rodada: asyncio.Task | None = None
        self._tarefas_fundo: set[asyncio.Task] = set()
        self.ultimo_log: list[dict] = []
        self._dialogo_em_curso: str | None = None
        self.revisar_arbitragens = False                 # §7.4: Host pode alterar a arbitragem antes da resolução
        self.prazo_revisao_s = float(os.getenv("TIMEOUT_REVISAO_ARBITRAGEM", "45"))
        self._revisao: asyncio.Future | None = None
        self.ultima_narracao_rodada: int | None = None
        self.ultima_memoria_rodada = 0

    # ------------------------------------------------------------------ estado para o cliente
    def estado_cliente(self) -> dict:
        estado = self.store.estado_atual(self.sala_id)
        for pid, j in estado["jogadores"].items():
            j["conectado"] = pid in self.clientes
        return estado

    def _timeout(self, estado: dict | None = None) -> float:
        estado = estado or self.store.estado_atual(self.sala_id)
        return self.timeout_combate if estado["modo"] == "combate" else self.timeout_exploracao

    def _msg_room_state(self, player_id: str) -> dict:
        estado = self.estado_cliente()
        j = estado["jogadores"].get(player_id, {})
        return {"type": "room_state", "fase": self.fase, "prazo": self.prazo, "state": estado, "config": self.sistema.config,
                "revisar_arbitragens": self.revisar_arbitragens,
                "campanha": {"id": self.campanha.id, "nome": self.campanha.nome, "tema": self.campanha.tema},
                "eu": {"player_id": player_id, "papel": j.get("papel", "espectador"), "personagem_id": j.get("personagem_id")},
                "nivel_ia": self.llm.nivel() if hasattr(self.llm, "nivel") else 4, "prontos": sorted(self.acoes)}

    # ------------------------------------------------------------------ conexões
    async def conectar(self, player_id: str, ws):
        antigo = self.clientes.pop(player_id, None)
        if antigo:                                   # mesma pessoa reconectando (outra aba, queda)
            if antigo.tarefa:
                antigo.tarefa.cancel()
            asyncio.create_task(self._fechar(antigo.ws, 4009))
        cli = Cliente(player_id, ws)
        cli.tarefa = asyncio.create_task(cli.loop_envio())
        self.clientes[player_id] = cli
        self.enviar(player_id, self._msg_room_state(player_id))
        if self.fase is Fase.PLANEJAMENTO:
            self._enviar_alcance(player_id)
        async with self.lock:
            self._avaliar_prontidao()
        self._broadcast_jogadores()

    async def desconectar(self, player_id: str, ws):
        cli = self.clientes.get(player_id)
        if cli is None or cli.ws is not ws:
            return                                   # já substituído por uma conexão nova
        if cli.tarefa:
            cli.tarefa.cancel()
        del self.clientes[player_id]
        async with self.lock:
            self.acoes.pop(player_id, None)
            self._avaliar_prontidao()                # quem faltava saiu? a rodada dispara
        self._broadcast_jogadores()

    async def _fechar(self, ws, codigo: int):
        try:
            await ws.close(code=codigo)
        except Exception:
            pass

    def enviar(self, player_id: str, msg: dict):
        cli = self.clientes.get(player_id)
        if cli is None:
            return
        try:
            cli.fila.put_nowait(msg)
        except asyncio.QueueFull:                    # cliente travado: fecha; ele reconecta e ressincroniza
            if cli.tarefa:
                cli.tarefa.cancel()
            self.clientes.pop(player_id, None)
            asyncio.create_task(self._fechar(cli.ws, 4008))

    def broadcast(self, msg: dict):
        for pid in list(self.clientes):
            self.enviar(pid, msg)

    def _broadcast_jogadores(self):
        estado = self.estado_cliente()
        self.broadcast({"type": "players", "jogadores": estado["jogadores"]})

    def aceita_mensagem(self, player_id: str) -> bool:
        cli = self.clientes.get(player_id)
        return bool(cli and cli.dentro_do_limite())

    # ------------------------------------------------------------------ planejamento
    def _jogadores_ativos(self, estado: dict) -> set[str]:
        """Quem precisa confirmar: conectados, com personagem vivo."""
        out = set()
        for pid in self.clientes:
            j = estado["jogadores"].get(pid)
            if not j or not j.get("personagem_id") or j.get("papel") == "espectador":
                continue
            p = estado["personagens"].get(j["personagem_id"])
            if p and vivo(p):
                out.add(pid)
        return out

    def _enviar_alcance(self, player_id: str, estado: dict | None = None):
        estado = estado or self.store.estado_atual(self.sala_id)
        j = estado["jogadores"].get(player_id)
        if j and j.get("personagem_id") in estado["personagens"]:
            self.enviar(player_id, {"type": "alcance", "personagem_id": j["personagem_id"],
                                    "celulas": self.motor.alcance_lista(estado, j["personagem_id"])})

    def iniciar_planejamento(self):                  # chamar com self.lock adquirido
        if self._timer and self._timer is not asyncio.current_task():
            self._timer.cancel()
        estado = self.store.estado_atual(self.sala_id)
        self.fase = Fase.PLANEJAMENTO
        self.acoes = {}
        self.rolagens = {}
        self.prazo = time.time() + self._timeout(estado)
        self._timer = asyncio.create_task(self._expirar(self.prazo))
        self.broadcast({"type": "phase", "fase": self.fase, "prazo": self.prazo, "modo": estado["modo"]})
        for pid in list(self.clientes):
            self._enviar_alcance(pid, estado)
        self._avaliar_prontidao()

    async def _expirar(self, prazo: float):
        await asyncio.sleep(max(0.0, prazo - time.time()))
        async with self.lock:
            if self.fase is Fase.PLANEJAMENTO and self.prazo == prazo:
                self._disparar_rodada()              # quem não confirmou recebe a ação padrão

    async def preview(self, player_id: str, destino):
        if self.fase is not Fase.PLANEJAMENTO:
            return
        try:
            destino = (int(destino[0]), int(destino[1]))
        except (TypeError, ValueError, IndexError):
            self.enviar(player_id, {"type": "error", "code": "mensagem_invalida"})
            return
        caminho = self.motor.caminho_preview(self.store.estado_atual(self.sala_id), player_id, destino)
        if caminho:                                  # só repassa previews válidos
            self.broadcast({"type": "player_preview", "player_id": player_id, **caminho})
        else:
            self.enviar(player_id, {"type": "error", "code": "destino_invalido"})

    async def rolar(self, player_id: str, slot_id: str, expressao: str):
        async with self.lock:
            if self.fase is not Fase.PLANEJAMENTO:
                self.enviar(player_id, {"type": "error", "code": "fora_de_fase"})
                return
            try:                                     # no máximo 1 rolagem por slot
                rolagem = self.motor.rolar_para_slot(self.rolagens, player_id, slot_id, expressao)
            except ValueError as exc:
                self.enviar(player_id, {"type": "error", "code": "rolagem_invalida", "msg": str(exc)})
                return
            self.broadcast({"type": "dice_result", "player_id": player_id, "slot_id": slot_id, "rolagem": rolagem})

    async def confirmar(self, player_id: str, acao: dict):
        async with self.lock:
            if self.fase is not Fase.PLANEJAMENTO:
                self.enviar(player_id, {"type": "error", "code": "fora_de_fase"})
                return
            estado = self.store.estado_atual(self.sala_id)
            if player_id not in self._jogadores_ativos(estado):
                self.enviar(player_id, {"type": "error", "code": "sem_personagem"})
                return
            erros = self.motor.validar_declaracao(estado, player_id, acao)
            if erros:
                self.enviar(player_id, {"type": "error", "code": "acao_invalida", "detalhes": erros})
                return
            self.acoes[player_id] = acao
            self._avaliar_prontidao()

    async def desconfirmar(self, player_id: str):
        async with self.lock:
            if self.fase is Fase.PLANEJAMENTO and self.acoes.pop(player_id, None) is not None:
                self._avaliar_prontidao()

    def _avaliar_prontidao(self):                    # chamar com self.lock adquirido
        if self.fase is not Fase.PLANEJAMENTO:
            return
        ativos = self._jogadores_ativos(self.store.estado_atual(self.sala_id))
        self.broadcast({"type": "ready_status", "prontos": sorted(self.acoes), "total": len(ativos), "prazo": self.prazo})
        if ativos and ativos <= set(self.acoes):
            self._disparar_rodada()

    def _disparar_rodada(self):                      # chamar com self.lock adquirido
        self.fase = Fase.RESOLVENDO
        if self._timer and self._timer is not asyncio.current_task():
            self._timer.cancel()
        estado = self.store.estado_atual(self.sala_id)
        acoes = dict(self.acoes)
        for pid, j in estado["jogadores"].items():   # ausentes e quem não confirmou: ação padrão
            p = estado["personagens"].get(j.get("personagem_id") or "")
            if p and vivo(p) and pid not in acoes and j.get("papel") != "espectador":
                acoes[pid] = ACAO_AUSENTE
        rolagens, self.acoes, self.rolagens = self.rolagens, {}, {}
        self._rodada = asyncio.create_task(self._processar_rodada(acoes, rolagens))

    # ------------------------------------------------------------------ rodada
    async def _processar_rodada(self, acoes: dict[str, dict], rolagens: dict):
        narrando = False
        try:
            self.broadcast({"type": "phase", "fase": Fase.RESOLVENDO})
            estado = self.store.estado_atual(self.sala_id)
            opcoes = self.motor.opcoes_validas(estado)
            ultimas = self.store.ultimas_rodadas(self.sala_id, 4)

            # 1) A IA decide intenções dos NPCs (JSON validado; nunca altera o estado direto)
            ctx = cb.montar_contexto_planejamento(estado, acoes, rolagens, opcoes, self.motor, self.sistema, self.campanha, self.rag, ultimas)
            plano = await self.llm.planejar(ctx)
            plano = plano.model_dump() if hasattr(plano, "model_dump") else plano
            if self.revisar_arbitragens and plano.get("arbitragens"):
                plano["arbitragens"] = await self._revisao_do_host(estado, plano["arbitragens"])

            # 2) O motor resolve tudo em ordem de iniciativa → eventos → Event Store
            eventos, log_acoes = self.motor.resolver_rodada(estado, acoes, plano, rolagens, opcoes)
            self.store.anexar(self.sala_id, eventos, rodada=estado["rodada"] + 1)
            self.ultimo_log = log_acoes
            novo = self.store.estado_atual(self.sala_id)
            self.broadcast({"type": "round_log", "rodada": novo["rodada"], "modo": novo["modo"],
                            "acoes": [{"id": a["id"], "ator_id": a["ator_id"], "texto": a["texto"], "eventos": a["eventos"]} for a in log_acoes]})

            # 3) Narração em stream sobre o que JÁ foi resolvido
            self.fase = Fase.NARRANDO
            self.broadcast({"type": "phase", "fase": Fase.NARRANDO, "modo": novo["modo"]})
            self.gpu.narracao_iniciada()
            narrando = True
            await self._narrar(novo, log_acoes, ultimas)

            # 4) tarefas de fundo: memória, mapa da nova cena
            self._fundo(self._atualizar_memoria(novo))
            if any(e["tipo"] == "cena_mudou" for e in eventos):
                self._fundo(self._gerar_mapa(novo))
        except Exception:
            log.exception("rodada falhou na sala %s", self.sala_id)
            self.broadcast({"type": "error", "code": "rodada_falhou"})
        finally:
            if narrando:
                self.gpu.narracao_terminada()
            # 5) Sincronização final: o tabuleiro fica certo mesmo se a IA esquecer um [EVENTO]
            self.broadcast({"type": "state_sync", "state": self.estado_cliente()})
            self.broadcast({"type": "nivel_ia", "nivel": self.llm.nivel(), "provedor": getattr(self.llm, "ultimo_provedor", "-")})
            async with self.lock:
                if self.pausa_pendente:
                    self._pausar()
                else:
                    self.iniciar_planejamento()

    async def _revisao_do_host(self, estado: dict, arbitragens: list[dict]) -> list[dict]:
        """Mostra as arbitragens ao Host e espera `editar_arbitragem`/`aprovar_arbitragens` (ou o prazo)."""
        host = next((pid for pid, j in estado["jogadores"].items() if j.get("papel") == "host" and pid in self.clientes), None)
        if host is None:
            return arbitragens
        self._revisao = asyncio.get_running_loop().create_future()
        prazo = time.time() + self.prazo_revisao_s
        self.enviar(host, {"type": "arbitragens", "rodada": estado["rodada"] + 1, "prazo": prazo, "arbitragens": arbitragens,
                           "catalogo": sorted(self.motor.catalogo), "faixas": ["facil", "media", "dificil", "muito_dificil"]})
        self.broadcast({"type": "phase", "fase": Fase.RESOLVENDO, "aguardando_host": True, "prazo": prazo})
        try:
            editadas = await asyncio.wait_for(self._revisao, timeout=self.prazo_revisao_s)
        except asyncio.TimeoutError:
            editadas = None
        finally:
            self._revisao = None
        if not editadas:
            return arbitragens
        por_personagem = {a.get("personagem_id"): a for a in arbitragens}
        out = []
        for e in editadas:
            base = por_personagem.get(e.get("personagem_id"))
            if base is None:
                continue
            nova = dict(base)
            for k in ("pericia", "dificuldade", "efeito_sucesso", "efeito_falha", "motivo"):
                if isinstance(e.get(k), str):
                    nova[k] = e[k][:200]
            if isinstance(e.get("alvos"), list):
                nova["alvos"] = [str(a) for a in e["alvos"]][:8]
            if e.get("remover"):
                continue
            out.append(nova)
        return out

    async def _narrar(self, estado: dict, log_acoes: list[dict], ultimas: list[dict]):
        ctx = cb.montar_contexto_narracao(estado, log_acoes, self.sistema, self.campanha, ultimas, rag=self.rag)
        vozes = resolver_vozes(self.voices, estado)
        async for segmento in self.narracao.narrar(self.llm.narrar_stream(ctx), vozes):
            self.broadcast({"type": "narration_segment", **segmento})
        self.ultima_narracao_rodada = estado["rodada"]
        self.broadcast({"type": "narration_end", "rodada": estado["rodada"]})

    def _fundo(self, coro):
        t = asyncio.create_task(coro)
        self._tarefas_fundo.add(t)
        t.add_done_callback(self._tarefas_fundo.discard)

    async def _atualizar_memoria(self, estado: dict):
        if estado["rodada"] - self.ultima_memoria_rodada < 10:
            return
        try:
            ultimas = self.store.ultimas_rodadas(self.sala_id, 10)
            ctx = cb.montar_contexto_memoria(estado, ultimas, self.sistema)
            mem = await self.llm.estruturado(ctx)
            if isinstance(mem, Memoria) and (mem.resumo or mem.fatos):
                self.store.anexar(self.sala_id, [{"tipo": "memoria", "memoria": {**mem.model_dump(), "atualizado_na_rodada": estado["rodada"]}}])
            self.ultima_memoria_rodada = estado["rodada"]
        except Exception:
            log.exception("memória falhou")

    async def _gerar_mapa(self, estado: dict):
        """Battlemap da cena atual (faixa pesada do GPU Scheduler). Só se houver ComfyUI e a cena não tiver imagem."""
        from . import map_engine
        cena = estado["cena"]
        if cena.get("imagem_url") or not os.getenv("COMFYUI_URL") or not self.gpu.tem_handler("mapa"):
            return
        try:
            tema = cena.get("tema") or self.campanha.tema
            futuro = self.gpu.submeter(2, ("mapa", cena["tilemap"], cena.get("descricao", cena["nome"]), tema, 0))
            url = await futuro
            if url:
                self.store.anexar(self.sala_id, [{"tipo": "imagem_cena", "cena_id": cena["id"], "imagem_url": url}])
                self.broadcast({"type": "scene_image", "cena_id": cena["id"], "imagem_url": url})
        except Exception:
            log.exception("geração de mapa falhou")

    # ------------------------------------------------------------------ chat
    async def chat(self, player_id: str, texto: str, para: str | None = None):
        texto = " ".join(str(texto or "").split())[:500]
        if not texto:
            self.enviar(player_id, {"type": "error", "code": "mensagem_invalida", "msg": "texto vazio"})
            return
        estado = self.store.estado_atual(self.sala_id)
        j = estado["jogadores"].get(player_id)
        if j is None:
            return
        pid = j.get("personagem_id")
        falante = estado["personagens"].get(pid or "") or {"nome": j["nome"], "id": None}
        npc = None
        if para:
            npc = estado["personagens"].get(str(para))
            if npc is None or npc.get("tipo") != "npc":
                self.enviar(player_id, {"type": "error", "code": "npc_invalido"})
                return
            if not pid:
                self.enviar(player_id, {"type": "error", "code": "sem_personagem", "msg": "espectadores falam só com a mesa"})
                return
        ev = {"tipo": "chat", "id": "c-" + secrets.token_hex(4), "de": player_id, "nome": falante["nome"], "personagem_id": pid,
              "texto": texto, "para": npc["id"] if npc else None, "npc": False, "ts": time.time()}
        self.store.anexar(self.sala_id, [ev], snapshot=False)
        self.broadcast({"type": "chat_message", **{k: v for k, v in ev.items() if k != "tipo"}})
        if npc is None:
            return
        if self.fase in (Fase.RESOLVENDO, Fase.NARRANDO):
            self.enviar(player_id, {"type": "error", "code": "npc_ocupado", "msg": "espere a rodada terminar"})
            return
        if self._dialogo_em_curso:
            self.enviar(player_id, {"type": "error", "code": "npc_ocupado", "msg": f"{self._dialogo_em_curso} ainda está respondendo"})
            return
        self._dialogo_em_curso = npc["nome"]
        self.broadcast({"type": "chat_typing", "personagem_id": npc["id"], "nome": npc["nome"]})
        self._fundo(self._responder_npc(estado, npc, falante, texto))

    async def _responder_npc(self, estado: dict, npc: dict, falante: dict, texto: str):
        try:
            ctx = cb.montar_contexto_dialogo(estado, npc, falante, texto, self.sistema, self.campanha, self.rag,
                                             self.store.ultimas_rodadas(self.sala_id, 2))
            resposta = await asyncio.wait_for(self.llm.responder(ctx), timeout=60)
            resposta = " ".join(TAG_FALA.sub("", resposta).replace("[VOZ:NARRADOR]", "").split())[:600] or "..."
            await self._falar_npc(npc, resposta, para=falante.get("id"))
        except Exception:
            log.exception("diálogo com NPC falhou")
            self.broadcast({"type": "chat_typing", "personagem_id": npc["id"], "nome": npc["nome"], "fim": True})
        finally:
            self._dialogo_em_curso = None

    async def _falar_npc(self, npc: dict, texto: str, para: str | None = None, por_host: bool = False):
        audio_url = None
        if self.gpu.tem_handler("tts"):
            vozes = resolver_vozes(self.voices, self.store.estado_atual(self.sala_id))
            try:
                audio_id = await self.gpu.submeter(0, ("tts", texto, vozes.get(npc["id"]) or vozes["NARRADOR"]))
                audio_url = f"/audio/{audio_id}" if audio_id else None
            except Exception:
                log.warning("TTS do diálogo falhou", exc_info=True)
        ev = {"tipo": "chat", "id": "c-" + secrets.token_hex(4), "de": npc["id"], "nome": npc["nome"], "personagem_id": npc["id"],
              "texto": texto, "para": para, "npc": True, "ts": time.time()}
        self.store.anexar(self.sala_id, [ev], snapshot=False)
        self.broadcast({"type": "chat_message", **{k: v for k, v in ev.items() if k != "tipo"}, "audio_url": audio_url,
                        "voz": npc.get("voz"), "por_host": por_host})

    # ------------------------------------------------------------------ Host
    def _pausar(self):                               # chamar com self.lock adquirido
        if self.fase is not Fase.PAUSADO:
            self.fase_anterior = self.fase
        self.fase, self.prazo = Fase.PAUSADO, None
        if self._timer:
            self._timer.cancel()
        self.broadcast({"type": "phase", "fase": self.fase})

    async def comando_host(self, player_id: str, cmd: dict):
        if not self.store.eh_host(self.sala_id, player_id):
            self.enviar(player_id, {"type": "error", "code": "sem_permissao"})
            return
        async with self.lock:
            comando = cmd.get("comando")
            try:
                await self._executar_comando(player_id, comando, cmd)
            except Exception as exc:
                log.exception("comando do host falhou: %s", comando)
                self.enviar(player_id, {"type": "error", "code": "comando_falhou", "msg": str(exc)[:200]})

    async def _executar_comando(self, player_id: str, comando: str | None, cmd: dict):
        match comando:
            case "iniciar" if self.fase is Fase.LOBBY:
                self._garantir_cena()
                self.iniciar_planejamento()
            case "resolver_agora" if self.fase is Fase.PLANEJAMENTO:
                self._disparar_rodada()
            case "pausar":
                self.pausa_pendente = True       # no meio da rodada, vale quando ela terminar
                if self.fase in (Fase.PLANEJAMENTO, Fase.LOBBY):
                    self._pausar()
            case "retomar" if self.fase is Fase.PAUSADO:
                self.pausa_pendente = False
                if self.fase_anterior is Fase.LOBBY:
                    self.fase = Fase.LOBBY
                    self.broadcast({"type": "phase", "fase": self.fase})
                else:
                    self.iniciar_planejamento()
            case "desfazer_rodada" if self.fase in (Fase.PLANEJAMENTO, Fase.PAUSADO):
                self.store.reverter_ultima_rodada(self.sala_id)
                self._sync()
                if self.fase is Fase.PLANEJAMENTO:
                    self.iniciar_planejamento()  # ações declaradas sobre o estado antigo caem
            case "iniciar_combate" if self.fase in (Fase.PLANEJAMENTO, Fase.PAUSADO, Fase.LOBBY):
                estado = self.store.estado_atual(self.sala_id)
                if estado["modo"] != "combate":
                    from .motor import _Rodada
                    ctx = _Rodada(self.motor, estado)
                    self.motor._iniciar_combate(ctx)
                    self.store.anexar(self.sala_id, ctx.eventos)
                    self._sync()
                    if self.fase is Fase.PLANEJAMENTO:
                        self.iniciar_planejamento()
            case "encerrar_combate":
                self.store.anexar(self.sala_id, [{"tipo": "combate_encerrado"}])
                self._sync()
            case "mudar_cena" if self.fase in (Fase.PLANEJAMENTO, Fase.PAUSADO, Fase.LOBBY):
                cena_id = cmd.get("cena_id")
                if cena_id not in self.campanha.cenas:
                    raise ValueError("cena desconhecida")
                estado = self.store.estado_atual(self.sala_id)
                self.store.anexar(self.sala_id, [self.motor.evento_mudar_cena(estado, cena_id)])
                self._sync()
                self._fundo(self._gerar_mapa(self.store.estado_atual(self.sala_id)))
                if self.fase is Fase.PLANEJAMENTO:
                    self.iniciar_planejamento()
            case "editar_personagem":
                pid, campos = cmd.get("personagem_id"), cmd.get("campos") or {}
                estado = self.store.estado_atual(self.sala_id)
                if pid not in estado["personagens"] or not isinstance(campos, dict):
                    raise ValueError("personagem ou campos inválidos")
                permitidos = {"x", "y", "barras", "condicoes", "caido", "postura", "defesa", "deslocamento"}
                campos = {k: v for k, v in campos.items() if k in permitidos}
                if "x" in campos or "y" in campos:
                    mapa = self.motor.mapa_logico(estado, {pid})
                    x, y = int(campos.get("x", estado["personagens"][pid]["x"])), int(campos.get("y", estado["personagens"][pid]["y"]))
                    if not mapa.passavel(x, y):
                        raise ValueError("célula bloqueada")
                self.store.anexar(self.sala_id, [{"tipo": "personagem_editado", "personagem_id": pid, "campos": campos, "por": player_id}])
                self._sync()
                if self.fase is Fase.PLANEJAMENTO:
                    for cid in list(self.clientes):
                        self._enviar_alcance(cid)
            case "mudar_nivel_ia":
                nivel = cmd.get("nivel")
                self.llm.nivel_forcado = int(nivel) if nivel in (1, 2, 3, 4) else None
                if hasattr(self.gpu, "desligar_pesada"):
                    self.gpu.desligar_pesada(self.llm.nivel() == 3)
                self.broadcast({"type": "nivel_ia", "nivel": self.llm.nivel(), "provedor": getattr(self.llm, "ultimo_provedor", "-")})
            case "nova_narracao" if self.fase in (Fase.PLANEJAMENTO, Fase.PAUSADO) and self.ultimo_log:
                self._fundo(self._renarrar())
            case "revisar_arbitragens":
                self.revisar_arbitragens = bool(cmd.get("ativo"))
                self.enviar(player_id, {"type": "config_sala", "revisar_arbitragens": self.revisar_arbitragens})
            case "editar_arbitragem" | "aprovar_arbitragens":
                if self._revisao is not None and not self._revisao.done():
                    self._revisao.set_result(cmd.get("arbitragens") if comando == "editar_arbitragem" else None)
                else:
                    self.enviar(player_id, {"type": "error", "code": "sem_revisao_pendente"})
            case "falar_como_npc":
                estado = self.store.estado_atual(self.sala_id)
                npc = estado["personagens"].get(str(cmd.get("personagem_id") or ""))
                texto = " ".join(str(cmd.get("texto") or "").split())[:500]
                if npc is None or npc.get("tipo") != "npc" or not texto:
                    raise ValueError("NPC ou texto inválido")
                self._fundo(self._falar_npc(npc, texto, por_host=True))
            case "kick":
                alvo = cmd.get("player_id")
                cli = self.clientes.get(alvo or "")
                if cli and alvo != player_id:
                    await self._fechar(cli.ws, 4003)
            case _:
                self.enviar(player_id, {"type": "error", "code": "comando_invalido"})

    async def _renarrar(self):
        estado = self.store.estado_atual(self.sala_id)
        self.gpu.narracao_iniciada()
        try:
            self.broadcast({"type": "round_log", "rodada": estado["rodada"], "modo": estado["modo"], "renarracao": True,
                            "acoes": [{"id": a["id"], "ator_id": a["ator_id"], "texto": a["texto"], "eventos": []} for a in self.ultimo_log]})
            await self._narrar(estado, self.ultimo_log, self.store.ultimas_rodadas(self.sala_id, 4)[:-1])
        finally:
            self.gpu.narracao_terminada()

    def _garantir_cena(self):
        """Primeira vez que a mesa abre: posiciona o grupo na cena inicial e instancia os NPCs."""
        estado = self.store.estado_atual(self.sala_id)
        if estado["rodada"] == 0 and not any(p["tipo"] == "npc" for p in estado["personagens"].values()):
            cena_id = estado["cena"]["id"] or self.campanha.cena_inicial
            if cena_id in self.campanha.cenas:
                self.store.anexar(self.sala_id, [self.motor.evento_mudar_cena(estado, cena_id)])
                self._sync()
                self._fundo(self._gerar_mapa(self.store.estado_atual(self.sala_id)))

    def _sync(self):
        self.broadcast({"type": "state_sync", "state": self.estado_cliente()})

    def debug(self) -> dict:
        return {"fase": self.fase, "prazo": self.prazo, "conectados": sorted(self.clientes), "prontos": sorted(self.acoes),
                "ia": self.llm.status() if hasattr(self.llm, "status") else {},
                "chamadas": self.store.ultimas_chamadas(self.sala_id, 20),
                "intencoes_rejeitadas": self.store.intencoes_rejeitadas(self.sala_id, 20)}

    async def encerrar(self):
        for t in (self._timer, self._rodada, *self._tarefas_fundo):
            if t:
                t.cancel()
        for cli in list(self.clientes.values()):
            if cli.tarefa:
                cli.tarefa.cancel()
            await self._fechar(cli.ws, 1001)
        self.clientes.clear()
