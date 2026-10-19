"""Fachada do motor: validação de declarações, menu de opções válidas, validação do plano da IA
e resolução da rodada (§6.4, §7, §8.4, §9.3).

Tudo aqui é síncrono e determinístico (dado o RNG). Entrada: estado + ações + plano. Saída: eventos.
"""
from __future__ import annotations

import copy
import secrets
from typing import Any

from . import grid_math as gm
from . import heuristic_ai
from . import rules_engine as re_
from .events import aplicar
from .rules_engine import evento

FAIXAS = ("facil", "media", "dificil", "muito_dificil")
ACOES_NPC = ("atacar", "mover", "habilidade", "defender", "fugir", "render_se", "falar", "esperar")
MAX_FALA_NPC = 400
MAX_TEXTO = 500


def _pos(p: dict) -> tuple[int, int]:
    return (int(p["x"]), int(p["y"]))


def _frac_pv(p: dict) -> float:
    b = p["barras"].get("pv", {"atual": 1, "max": 1})
    return b["atual"] / b["max"] if b["max"] else 0.0


def _ids(xs: list[dict]) -> list[str]:
    return [x["id"] for x in xs]


class Motor:
    def __init__(self, cfg: dict, catalogo_efeitos: dict, cenas: dict[str, dict] | None = None, plugin: Any = None):
        self.cfg = cfg
        self.catalogo = catalogo_efeitos
        self.cenas = cenas or {}
        self.plugin = plugin

    # ================================================================== utilidades de estado
    @property
    def metrica(self) -> str:
        return self.cfg.get("grid", {}).get("metrica_diagonal", "1-2-1-2")

    def mapa_logico(self, estado: dict, excluir: set[str] | None = None) -> gm.MapaLogico:
        excluir = excluir or set()
        ocupados = {_pos(p) for pid, p in estado["personagens"].items() if pid not in excluir and re_.vivo(p)}
        obst = {(o["x"], o["y"]): o["tipo"] for o in estado.get("obstaculos", [])}
        return gm.MapaLogico(estado["cena"]["tilemap"], ocupados, obst)

    def personagem_de(self, estado: dict, player_id: str) -> dict | None:
        j = estado["jogadores"].get(player_id)
        if not j or not j.get("personagem_id"):
            return None
        return estado["personagens"].get(j["personagem_id"])

    def inimigos_de(self, estado: dict, p: dict) -> list[dict]:
        return [o for o in estado["personagens"].values()
                if o["id"] != p["id"] and re_.vivo(o) and o["faccao"] != p["faccao"] and o.get("postura") != "rendido"]

    def alcance(self, estado: dict, personagem_id: str) -> dict[tuple[int, int], int]:
        p = estado["personagens"][personagem_id]
        if re_.incapacitado(p):
            return {_pos(p): 0}
        mapa = self.mapa_logico(estado, {personagem_id})
        return gm.custos_de_movimento(_pos(p), mapa, self.metrica, int(p.get("deslocamento", 6)))

    def alcance_lista(self, estado: dict, personagem_id: str) -> list[list[int]]:
        return [[x, y, c] for (x, y), c in sorted(self.alcance(estado, personagem_id).items())]

    def em_alcance(self, estado: dict, origem: tuple[int, int], alvo: dict, ataque: dict,
                   mapa: gm.MapaLogico | None = None) -> bool:
        mapa = mapa or self.mapa_logico(estado)
        alc = int(ataque.get("alcance", 1))
        if gm.distancia_quadrados(origem, _pos(alvo), self.metrica) > alc:
            return False
        return alc <= 1 or gm.linha_de_visao(origem, _pos(alvo), mapa)

    # ================================================================== preview e validação do jogador
    def caminho_preview(self, estado: dict, player_id: str, destino: tuple[int, int]) -> dict | None:
        p = self.personagem_de(estado, player_id)
        if p is None or re_.incapacitado(p):
            return None
        mapa = self.mapa_logico(estado, {p["id"]})
        if not mapa.dentro(*destino) or not mapa.passavel(*destino):
            return None
        res = gm.caminho(_pos(p), tuple(destino), mapa, self.metrica, int(p.get("deslocamento", 6)))
        if res is None:
            return None
        caminho, custo = res
        return {"personagem_id": p["id"], "caminho": [list(c) for c in caminho], "custo": custo}

    def rolar_para_slot(self, rolagens: dict, player_id: str, slot_id: str, expressao: str) -> dict:
        """No máximo 1 rolagem por slot por rodada. `rolagens[player_id][slot_id]`."""
        if not isinstance(slot_id, str) or len(slot_id) > 40:
            raise ValueError("slot inválido")
        if not re_.expressao_valida(expressao):
            raise ValueError("expressão de dados inválida")
        por_jogador = rolagens.setdefault(player_id, {})
        if slot_id in por_jogador and not slot_id.startswith("livre_dado"):
            raise ValueError("este slot já foi rolado nesta rodada")
        r = re_.rolar(expressao)
        r["id"] = "r-" + secrets.token_hex(3)
        por_jogador[slot_id if not slot_id.startswith("livre_dado") else r["id"]] = r
        return r

    def validar_declaracao(self, estado: dict, player_id: str, acao: Any) -> list[str]:
        erros: list[str] = []
        p = self.personagem_de(estado, player_id)
        if p is None:
            return ["jogador sem personagem (espectador?)"]
        if not isinstance(acao, dict):
            return ["ação precisa ser um objeto"]
        slots_cfg = {s["id"]: s for s in self.cfg.get("slots_de_acao_por_turno", [])}
        mov = acao.get("movimento")
        if mov is not None:
            dest = mov.get("destino") if isinstance(mov, dict) else None
            if not (isinstance(dest, list) and len(dest) == 2 and all(isinstance(v, int) for v in dest)):
                erros.append("movimento.destino deve ser [x, y]")
            elif tuple(dest) not in self.alcance(estado, p["id"]):
                erros.append("destino fora do alcance de movimento")
        slots = acao.get("slots", {})
        if not isinstance(slots, dict):
            return erros + ["slots deve ser um objeto"]
        for sid, s in slots.items():
            cfg_slot = slots_cfg.get(sid)
            if cfg_slot is None:
                erros.append(f"slot desconhecido: {sid}")
                continue
            if not isinstance(s, dict) or "tipo" not in s:
                erros.append(f"slot {sid} sem tipo")
                continue
            tipo = s["tipo"]
            permitidos = set(cfg_slot.get("tipos_permitidos", [])) | {"defender", "esperar"}
            if cfg_slot.get("vinculado_ao_grid"):
                erros.append(f"slot {sid} é de movimento; use 'movimento'")
                continue
            if tipo not in permitidos:
                erros.append(f"tipo {tipo} não permitido no slot {sid}")
                continue
            if tipo == "ataque":
                atq = re_.ataque_de(p, s.get("ataque_id", ""))
                alvo = estado["personagens"].get(s.get("alvo_id", ""))
                if atq is None:
                    erros.append("ataque não pertence à ficha")
                elif alvo is None or not re_.vivo(alvo):
                    erros.append("alvo inexistente ou caído")
                elif alvo["faccao"] == p["faccao"]:
                    erros.append("não é possível atacar aliados")
                else:
                    origem = tuple(mov["destino"]) if mov and isinstance(mov, dict) and isinstance(mov.get("destino"), list) else _pos(p)
                    if not self.em_alcance(estado, origem, alvo, atq, self.mapa_logico(estado, {p["id"]})):
                        erros.append("alvo fora de alcance ou sem linha de visão")
            elif tipo == "pericia":
                if s.get("pericia") not in p.get("pericias", {}):
                    erros.append("perícia não está na ficha")
            elif tipo == "habilidade":
                erro = self._erro_habilidade(estado, p, s, sid, mov)
                if erro:
                    erros.append(erro)
            elif tipo in ("criativa", "fala"):
                texto = s.get("texto", "")
                if not isinstance(texto, str) or not texto.strip():
                    erros.append(f"slot {sid} precisa de texto")
                elif len(texto) > MAX_TEXTO:
                    erros.append(f"texto do slot {sid} excede {MAX_TEXTO} caracteres")
        return erros

    # ================================================================== opções válidas (menu do LLM)
    def opcoes_validas(self, estado: dict) -> dict[str, dict]:
        opcoes: dict[str, dict] = {}
        for nid, npc in estado["personagens"].items():
            if npc["tipo"] != "npc" or re_.incapacitado(npc) or npc.get("postura") == "rendido":
                continue
            inimigos = self.inimigos_de(estado, npc)
            mapa = self.mapa_logico(estado, {nid})
            alc = gm.custos_de_movimento(_pos(npc), mapa, self.metrica, int(npc.get("deslocamento", 6)))
            agora, movendo = [], []
            for atq in npc.get("ataques", []):
                for alvo in inimigos:
                    d = gm.distancia_quadrados(_pos(npc), _pos(alvo), self.metrica)
                    if self.em_alcance(estado, _pos(npc), alvo, atq, mapa):
                        agora.append({"alvo_id": alvo["id"], "ataque_id": atq["id"], "distancia": d, "pv_frac": _frac_pv(alvo)})
                        continue
                    melhor = None
                    for cel, custo in alc.items():
                        if cel == _pos(npc):
                            continue
                        if self.em_alcance(estado, cel, alvo, atq, mapa) and (melhor is None or custo < melhor[1]):
                            melhor = (cel, custo)
                    if melhor:
                        movendo.append({"alvo_id": alvo["id"], "ataque_id": atq["id"], "via": melhor[0],
                                        "custo": melhor[1], "distancia": d, "pv_frac": _frac_pv(alvo)})
            fuga = None
            if inimigos and len(alc) > 1:
                def dist_min(c):
                    return min(gm.distancia_quadrados(c, _pos(i), self.metrica) for i in inimigos)
                fuga = max(alc, key=lambda c: (dist_min(c), -alc[c]))
            opcoes[nid] = {"deslocamento": int(npc.get("deslocamento", 6)), "alcance": alc,
                           "ataques_agora": agora, "ataques_movendo": movendo, "fuga": fuga}
        return opcoes

    def opcoes_validas_texto(self, estado: dict, opcoes: dict) -> str:
        linhas = ["OPÇÕES VÁLIDAS (pré-calculadas pelo servidor)"]
        for nid, op in opcoes.items():
            npc = estado["personagens"][nid]
            partes = []
            por_ataque: dict[str, list[str]] = {}
            for a in op["ataques_agora"]:
                por_ataque.setdefault(a["ataque_id"], []).append(f"{a['alvo_id']} ({a['distancia']} q)")
            for aid, alvos in por_ataque.items():
                partes.append(f"{aid} agora em [{', '.join(alvos)}]")
            por_mov: dict[str, list[str]] = {}
            for a in op["ataques_movendo"]:
                por_mov.setdefault(a["ataque_id"], []).append(f"{a['alvo_id']} via ({a['via'][0]},{a['via'][1]}), custo {a['custo']}")
            for aid, alvos in por_mov.items():
                partes.append(f"movendo, {aid} alcança [{', '.join(alvos)}]")
            if op["fuga"]:
                partes.append(f"fuga possível para ({op['fuga'][0]},{op['fuga'][1]})")
            if not partes:
                partes.append("nenhum alvo alcançável; pode mover ou defender")
            nome = npc.get("postura") or "neutra"
            fala = "" if npc.get("voz") and npc.get("voz") != "NARRADOR" else ", NÃO FALA (animal/criatura)"
            linhas.append(f"- {nid} (deslocamento {op['deslocamento']}, postura {nome}{fala}): " + "; ".join(partes))
        return "\n".join(linhas)

    # ================================================================== validação do plano da IA
    def validar_plano(self, estado: dict, plano: dict, opcoes: dict) -> tuple[dict[str, dict], list[dict]]:
        """Devolve (intenções válidas por npc, eventos intencao_rejeitada). NPC sem intenção válida recebe a heurística."""
        validas: dict[str, dict] = {}
        rejeitadas: list[dict] = []
        vistas = set()
        for it in plano.get("intencoes_npcs", []) or []:
            nid = it.get("npc_id")
            if nid in vistas:
                continue
            vistas.add(nid)
            motivo = self._motivo_rejeicao(estado, it, opcoes)
            if motivo:
                rejeitadas.append(evento("intencao_rejeitada", npc=nid, motivo=motivo, intencao=it))
                if nid in opcoes:
                    validas[nid] = heuristic_ai.planejar_npc(nid, estado, opcoes, self.metrica,
                                                             it.get("se_alvo_invalido", "mais_proximo")
                                                             if it.get("se_alvo_invalido") in ("mais_proximo", "mais_ferido") else "mais_proximo")
            else:
                validas[nid] = it
        for nid in opcoes:
            if nid not in validas:
                validas[nid] = heuristic_ai.planejar_npc(nid, estado, opcoes, self.metrica)
        return validas, rejeitadas

    def _motivo_rejeicao(self, estado: dict, it: dict, opcoes: dict) -> str | None:
        nid = it.get("npc_id")
        if nid not in opcoes:
            return "NPC inexistente, caído ou rendido"
        npc = estado["personagens"][nid]
        acao = it.get("acao")
        if acao not in ACOES_NPC:
            return f"ação desconhecida: {acao}"
        op = opcoes[nid]
        dest = None
        if it.get("destino_x") is not None or it.get("destino_y") is not None:
            try:
                dest = (int(it["destino_x"]), int(it["destino_y"]))
            except (TypeError, ValueError):
                return "destino inválido"
            if dest not in op["alcance"]:
                return f"destino {dest} fora do alcance de movimento"
        if acao in ("mover", "fugir") and dest is None:
            return "mover/fugir exige destino"
        if acao == "falar" and not (isinstance(it.get("fala"), str) and it["fala"].strip()):
            return "falar exige o texto da fala"
        if acao in ("atacar", "habilidade"):
            aid = it.get("ataque_ou_habilidade_id")
            atq = re_.ataque_de(npc, aid or "")
            if atq is None:
                return f"ataque/habilidade '{aid}' não está na ficha"
            alvo = estado["personagens"].get(it.get("alvo_id") or "")
            if alvo is None or not re_.vivo(alvo):
                return "alvo inexistente ou caído"
            if alvo["faccao"] == npc["faccao"]:
                return "alvo é aliado do NPC"
            origem = dest or _pos(npc)
            if not self.em_alcance(estado, origem, alvo, atq, self.mapa_logico(estado, {nid})):
                return "alvo fora de alcance/visão a partir da posição escolhida"
        return None

    def validar_arbitragem(self, estado: dict, arb: dict) -> str | None:
        p = estado["personagens"].get(arb.get("personagem_id") or "")
        if p is None:
            return "personagem inexistente"
        if arb.get("pericia") not in (p.get("pericias") or {}):
            arb["pericia"] = self._melhor_pericia(p)           # o LLM escolheu uma perícia que a ficha não tem: usa a melhor
        if arb.get("dificuldade") not in FAIXAS:
            arb["dificuldade"] = "media"                       # tolerante: o LLM errou a faixa, não a ação
        for k in ("efeito_sucesso", "efeito_falha"):
            if arb.get(k) not in self.catalogo:
                arb[k] = "nenhum"                              # efeito fora do catálogo vira "só narrativa"
        for a in arb.get("alvos", []) or []:
            if a not in estado["personagens"]:
                return f"alvo '{a}' inexistente"
        return None

    @staticmethod
    def _melhor_pericia(p: dict) -> str:
        pericias = p.get("pericias") or {}
        return max(pericias, key=lambda k: pericias[k]) if pericias else "improviso"   # improviso = bônus 0

    # ================================================================== resolução da rodada
    def resolver_rodada(self, estado: dict, acoes: dict[str, dict], plano: dict | None,
                        rolagens: dict | None = None, opcoes: dict | None = None) -> tuple[list[dict], list[dict]]:
        """Devolve (eventos, acoes_log). Os eventos já carregam `grupo` (e1, e2…) quando pertencem a uma ação."""
        estado = copy.deepcopy(estado)
        plano = plano or {}
        rolagens = rolagens or {}
        opcoes = opcoes if opcoes is not None else self.opcoes_validas(estado)
        ctx = _Rodada(self, estado)
        rodada = estado["rodada"] + 1
        ctx.emitir([evento("rodada_iniciada", rodada=rodada)])

        intencoes, rejeitadas = self.validar_plano(estado, plano, opcoes)
        ctx.emitir(rejeitadas)
        arbitragens = {}
        for arb in plano.get("arbitragens", []) or []:
            motivo = self.validar_arbitragem(estado, arb)
            if motivo:
                ctx.emitir([evento("intencao_rejeitada", npc=arb.get("personagem_id"), motivo=f"arbitragem: {motivo}", intencao=arb)])
            else:
                arbitragens[arb["personagem_id"]] = arb

        # combate começa se o plano pedir, se alguém atacar ou se um NPC hostil pretender atacar
        ataque_declarado = any(s.get("tipo") == "ataque" for a in acoes.values() for s in (a.get("slots") or {}).values())
        npc_ataca = any(i.get("acao") in ("atacar", "habilidade") for i in intencoes.values())
        if estado["modo"] != "combate" and (plano.get("iniciar_combate") or ataque_declarado or npc_ataca):
            self._iniciar_combate(ctx)

        # ordem de resolução
        por_personagem = {}
        for pid, acao in acoes.items():
            p = self.personagem_de(estado, pid)
            if p:
                por_personagem[p["id"]] = (pid, acao)
        if estado["modo"] == "combate":
            ordem = [i for i in estado["iniciativa"] if i in estado["personagens"]]
        else:
            ordem = list(por_personagem) + [n for n in intencoes if n not in por_personagem]

        for cid in ordem:
            p = estado["personagens"].get(cid)
            if p is None or re_.incapacitado(p):
                continue
            self._inicio_turno(ctx, p)
            if re_.incapacitado(p):
                continue
            if cid in por_personagem:
                player_id, acao = por_personagem[cid]
                self._executar_jogador(ctx, p, acao, rolagens.get(player_id, {}), arbitragens.get(cid))
            elif cid in intencoes:
                self._executar_npc(ctx, p, intencoes[cid])
            ctx.emitir(re_.fim_de_turno(estado["personagens"][cid]))

        # NPCs que entraram na ordem só agora (ex.: exploração sem iniciativa) já foram cobertos; obstáculos envelhecem
        if estado.get("obstaculos"):
            ctx.emitir([evento("obstaculos_tick")])
        if estado["modo"] == "combate" and not any(re_.vivo(p) and p["faccao"] == "inimigo" and p.get("postura") not in ("rendido",)
                                                   for p in estado["personagens"].values()):
            ctx.emitir([evento("combate_encerrado")], texto="O combate termina", ator=None)
        destino_cena = plano.get("mudar_cena_para")
        if destino_cena and destino_cena in self.cenas and destino_cena != estado["cena"]["id"]:
            ctx.emitir([self.evento_mudar_cena(estado, destino_cena)], texto=f"O grupo segue para {self.cenas[destino_cena]['nome']}", ator=None)

        ctx.emitir([evento("log_rodada", rodada=rodada, acoes=[{"id": a["id"], "ator_id": a["ator_id"], "texto": a["texto"]} for a in ctx.acoes])])
        ctx.emitir([evento("rodada_concluida", rodada=rodada)])
        return ctx.eventos, ctx.acoes

    # ---------------------------------------------------------------- combate / turnos
    def _iniciar_combate(self, ctx: "_Rodada") -> None:
        estado = ctx.estado
        resultados = []
        for p in estado["personagens"].values():
            if not re_.vivo(p):
                continue
            fn = getattr(self.plugin, "rolar_iniciativa", None) or re_.rolar_iniciativa
            resultados.append(fn(p, self.cfg))
        ordem = re_.ordenar_iniciativa(resultados, estado["personagens"])
        nomes = ", ".join(estado["personagens"][i]["nome"] for i in ordem)
        ctx.emitir(resultados + [evento("combate_iniciado", ordem=ordem)], texto=f"Combate! Ordem de iniciativa: {nomes}", ator=None)

    def _inicio_turno(self, ctx: "_Rodada", p: dict) -> None:
        fn = getattr(self.plugin, "inicio_de_turno", None) or re_.inicio_de_turno
        evs = fn(p, self.cfg)
        if evs:
            total = sum(e["valor"] for e in evs if e["tipo"] == "dano")
            ctx.emitir(evs, texto=f"{p['nome']} sofre {total} de dano contínuo ({re_.resumo_barra(ctx.estado['personagens'][p['id']])})" if total else None, ator=p["id"])
            ctx.checar_queda(p["id"])

    # ---------------------------------------------------------------- jogador
    def _executar_jogador(self, ctx: "_Rodada", p: dict, acao: dict, rolagens: dict, arbitragem: dict | None) -> None:
        estado = ctx.estado
        mov = acao.get("movimento")
        if isinstance(mov, dict) and isinstance(mov.get("destino"), list):
            self._mover(ctx, p, tuple(mov["destino"]))
        slots_cfg = [s["id"] for s in self.cfg.get("slots_de_acao_por_turno", [])]
        slots = acao.get("slots", {}) or {}
        for sid in sorted(slots, key=lambda s: slots_cfg.index(s) if s in slots_cfg else 99):
            s = slots[sid]
            p = estado["personagens"][p["id"]]
            if re_.incapacitado(p):
                break
            tipo = s.get("tipo")
            if tipo == "ataque":
                self._ataque_jogador(ctx, p, s, rolagens.get(sid))
            elif tipo == "habilidade":
                self._habilidade(ctx, p, s, sid)
            elif tipo == "pericia":
                cd = re_.cd_por_faixa(arbitragem["dificuldade"], self.cfg) if arbitragem and arbitragem.get("pericia") == s.get("pericia") else re_.cd_por_faixa("media", self.cfg)
                ev = re_.resolver_teste(p, s["pericia"], cd, self.cfg, motivo=(s.get("texto") or "")[:MAX_TEXTO])
                res = "SUCESSO" if ev["sucesso"] else "FALHA"
                ctx.emitir([ev], texto=f"{p['nome']} testa {s['pericia']} (CD {cd}): {ev['rolagem']['total']} → {res}", ator=p["id"])
            elif tipo == "criativa":
                self._criativa(ctx, p, s.get("texto", ""), arbitragem)
            elif tipo == "fala":
                texto = (s.get("texto") or "")[:MAX_TEXTO]
                ctx.emitir([evento("fala", personagem=p["id"], texto=texto)], texto=f"{p['nome']} diz: \"{texto}\"", ator=p["id"], fala=True)
            elif tipo == "defender":
                self._defender(ctx, p)
            elif tipo == "esperar":
                ctx.emitir([evento("esperar", personagem=p["id"])])          # silencioso: não vira linha de narração

    def _ataque_jogador(self, ctx: "_Rodada", p: dict, s: dict, rolagem: dict | None) -> None:
        estado = ctx.estado
        atq = re_.ataque_de(p, s.get("ataque_id", ""))
        if atq is None:
            return
        mapa = self.mapa_logico(estado, {p["id"]})
        alvo = estado["personagens"].get(s.get("alvo_id", ""))
        valido = alvo is not None and re_.vivo(alvo) and alvo["faccao"] != p["faccao"] and self.em_alcance(estado, _pos(p), alvo, atq, mapa)
        if not valido:
            cands = [o for o in self.inimigos_de(estado, p) if self.em_alcance(estado, _pos(p), o, atq, mapa)]
            if not cands:
                motivo = "o alvo já caiu" if alvo is not None and not re_.vivo(alvo) else "o alvo saiu do alcance"
                ctx.emitir([evento("preparar", personagem=p["id"], motivo=motivo)],
                           texto=f"{p['nome']} prepara-se: {motivo} e não há outro ao alcance", ator=p["id"])
                return
            alvo = min(cands, key=lambda o: gm.distancia_quadrados(_pos(p), _pos(o), self.metrica))
        teste = None
        esperado = self.cfg["ataque"]["expressao"].format(bonus=re_.bonus_ataque_efetivo(p, atq, self.cfg))
        if rolagem and rolagem.get("expressao", "").replace(" ", "").lower() == esperado.replace(" ", "").lower():
            teste = {k: rolagem[k] for k in ("expressao", "total", "termos")}
        self._resolver_ataque(ctx, p, alvo, atq, teste, mapa)

    def _resolver_ataque(self, ctx: "_Rodada", atacante: dict, alvo: dict, atq: dict, teste: dict | None, mapa: gm.MapaLogico) -> None:
        em_cob = mapa.cobertura(*_pos(alvo)) and not gm.adjacentes(_pos(atacante), _pos(alvo))
        fn = getattr(self.plugin, "resolver_ataque", None)
        evs = fn(atacante, alvo, atq, self.cfg, teste) if fn else re_.resolver_ataque(atacante, alvo, atq, self.cfg, teste, em_cob)
        a = evs[0]
        res = "CRÍTICO" if a["critico"] else ("ACERTO" if a["acertou"] else "ERRO")
        texto = f"{atacante['nome']} ataca {alvo['nome']} com {atq.get('nome', atq['id'])}: {a['rolagem']['total']} contra Defesa {a['defesa']} → {res}"
        ctx.emitir(evs, texto=texto, ator=atacante["id"])
        alvo_atual = ctx.estado["personagens"][alvo["id"]]
        danos = [e for e in evs if e["tipo"] == "dano"]
        if danos:
            conds = [e["condicao"] for e in evs if e["tipo"] == "condicao"]
            extra = f" e condição {', '.join(conds)}" if conds else ""
            origens = [x["origem"] for x in danos[0].get("extras", []) if x.get("valor")]
            det = f" (+{', '.join(origens)})" if origens else ""
            ctx.acoes[-1]["texto"] += f"; {danos[0]['valor']} de dano{det}{extra} ({alvo['nome']} {re_.resumo_barra(alvo_atual)})"
        ctx.checar_queda(alvo["id"])

    # ---------------------------------------------------------------- habilidades de classe
    def habilidade_de(self, p: dict, hid: str) -> dict | None:
        return next((h for h in p.get("habilidades", []) or [] if h.get("id") == hid), None)

    def _pode_pagar(self, p: dict, hab: dict) -> str | None:
        custo = hab.get("custo")
        if custo:
            b = p["barras"].get(custo.get("barra", "pm"), {"atual": 0})
            if b["atual"] < int(custo.get("valor", 1)):
                return f"sem {custo.get('barra', 'pm')} suficiente para {hab['nome']}"
        if hab.get("usos") and int((p.get("usos") or {}).get(hab["id"], 0)) <= 0:
            return f"{hab['nome']} já foi usada; recupera com descanso {hab['usos'].get('recupera', 'longo')}"
        return None

    def _erro_habilidade(self, estado: dict, p: dict, s: dict, slot_id: str, mov) -> str | None:
        hab = self.habilidade_de(p, s.get("habilidade_id", ""))
        if hab is None:
            return "habilidade não está na ficha"
        if hab.get("tipo") != "ativa":
            return f"{hab['nome']} é passiva (já está valendo)"
        if hab.get("slot", "padrao") != slot_id:
            return f"{hab['nome']} usa o slot '{hab.get('slot', 'padrao')}'"
        erro = self._pode_pagar(p, hab)
        if erro:
            return erro
        origem = tuple(mov["destino"]) if mov and isinstance(mov, dict) and isinstance(mov.get("destino"), list) else _pos(p)
        alvo_tipo = hab.get("alvo", "self")
        if alvo_tipo in ("aliado", "inimigo", "area"):
            alvo = estado["personagens"].get(s.get("alvo_id") or "")
            if alvo_tipo == "self" or (alvo_tipo == "area" and int(hab.get("alcance", 0)) == 0):
                return None
            if alvo is None:
                return f"{hab['nome']} precisa de um alvo"
            if alvo_tipo == "aliado" and alvo["faccao"] != p["faccao"]:
                return "o alvo precisa ser um aliado"
            if alvo_tipo == "inimigo" and (alvo["faccao"] == p["faccao"] or not re_.vivo(alvo)):
                return "o alvo precisa ser um inimigo vivo"
            if gm.distancia_quadrados(origem, _pos(alvo), self.metrica) > int(hab.get("alcance", 1)):
                return f"{hab['nome']}: alvo fora de alcance ({hab.get('alcance', 1)} q)"
        if (hab.get("efeito") or {}).get("ataque"):
            atq = re_.ataque_de(p, s.get("ataque_id") or (p.get("ataques") or [{}])[0].get("id", ""))
            if atq is None:
                return "arma inválida para a habilidade"
        return None

    def _rolar_salvaguarda(self, alvo: dict, atributo: str | None, cd: int) -> dict | None:
        """d20 + modificador (atributo em 5e; perícia de resistência em T20) + mod_salvaguarda, contra a CD."""
        if not atributo:
            return None
        if atributo in (alvo.get("atributos") or {}):
            mod = int(alvo["atributos"][atributo])
        else:
            mod = int((alvo.get("pericias") or {}).get(atributo, 0))
        mod += re_.passivas(alvo)["mod_salvaguarda"] + sum(int(self.cfg.get("condicoes", {}).get(c["id"], {}).get("mod_salvaguarda", 0)) for c in alvo.get("condicoes", []))
        r = re_.rolar(f"1d20{mod:+d}" if mod else "1d20")
        return {"atributo": atributo, "cd": cd, "rolagem": r, "sucesso": r["total"] >= cd}

    def _alvos_em_area(self, estado: dict, origem: dict, centro: tuple[int, int], raio: int, aliados: bool) -> list[dict]:
        mapa = self.mapa_logico(estado)
        celulas = set(gm.area_raio(centro, raio, mapa, self.metrica))
        out = []
        for o in estado["personagens"].values():
            if not re_.vivo(o) or _pos(o) not in celulas:
                continue
            if aliados and o["faccao"] != origem["faccao"]:
                continue
            if not aliados and o["id"] == origem["id"]:
                continue
            out.append(o)
        return out

    def _habilidade(self, ctx: "_Rodada", p: dict, s: dict, slot_id: str) -> None:
        estado = ctx.estado
        hab = self.habilidade_de(p, s.get("habilidade_id", ""))
        if hab is None or self._pode_pagar(p, hab):
            return
        ef = hab.get("efeito") or {}
        alvo_tipo = hab.get("alvo", "self")
        alvo = estado["personagens"].get(s.get("alvo_id") or "") if alvo_tipo != "self" else p
        if alvo_tipo in ("aliado", "inimigo") and (alvo is None or not re_.vivo(alvo)):
            alvo = p if alvo_tipo == "aliado" else None
            if alvo is None:
                ctx.emitir([evento("preparar", personagem=p["id"], motivo="alvo da habilidade caiu")], texto=f"{p['nome']} prepara {hab['nome']}, mas o alvo já caiu", ator=p["id"])
                return
        # custo e usos
        pagamento = []
        if hab.get("custo"):
            pagamento.append(evento("recurso", personagem=p["id"], barra=hab["custo"].get("barra", "pm"), valor=int(hab["custo"].get("valor", 1))))
        if hab.get("usos"):
            pagamento.append(evento("uso_gasto", personagem=p["id"], habilidade=hab["id"]))
        cd = int((p.get("magia") or {}).get("cd", 12))
        nivel = int(p.get("nivel", 1))
        mag = p.get("magia") or {}
        texto = f"{p['nome']} usa {hab['nome']}"
        if alvo is not None and alvo["id"] != p["id"]:
            texto += f" em {alvo['nome']}"
        quedas: list[str] = []
        evs = [evento("habilidade", personagem=p["id"], habilidade=hab["id"], nome=hab["nome"], alvo=alvo["id"] if alvo else None)] + pagamento
        ctx.emitir(evs, texto=texto, ator=p["id"])
        detalhes = []

        # --- ataque com arma + extras
        if ef.get("ataque") and alvo is not None and alvo["id"] != p["id"]:
            base = re_.ataque_de(p, s.get("ataque_id") or (p.get("ataques") or [{}])[0].get("id", ""))
            if base:
                atq = {**base, "bonus": int(base.get("bonus", 0)) + int(ef["ataque"].get("bonus", 0)), "dano_extra": ef["ataque"].get("dano_extra"),
                       "origem_extra": hab["id"], "nome": f"{base.get('nome', base['id'])} ({hab['nome']})"}
                self._resolver_ataque(ctx, p, alvo, atq, None, self.mapa_logico(estado, {p["id"]}))
        # --- dano direto / área
        if ef.get("dano"):
            d = ef["dano"]
            expr = d.get("escala_nivel5") if nivel >= 5 and d.get("escala_nivel5") else d["expressao"]
            if d.get("mais_atributo"):
                m = int((p.get("atributos") or {}).get(d["mais_atributo"], 0))
                expr = f"{expr}{m:+d}" if m else expr
            if d.get("raio") is not None and alvo_tipo == "area":
                centro = _pos(alvo) if alvo is not None and s.get("alvo_id") else _pos(p)
                alvos = self._alvos_em_area(estado, p, centro, int(d["raio"]), False)
            else:
                alvos = [alvo] if alvo is not None and alvo["id"] != p["id"] else []
            for o in alvos:
                rol = re_.rolar(expr)
                valor = rol["total"]
                acertou = True
                nota = ""
                if d.get("automatico"):
                    pass
                elif d.get("salvaguarda"):
                    sv = self._rolar_salvaguarda(o, d["salvaguarda"], cd)
                    if sv and sv["sucesso"]:
                        valor = 0 if d.get("anula") else valor // 2
                        nota = " (resistiu)"
                elif d.get("bonus_ataque") is not None:
                    bonus = int(mag.get("bonus", 0)) if d["bonus_ataque"] == "magia" else (int((p.get("ataques") or [{}])[0].get("bonus", 0)) if d["bonus_ataque"] == "arma" else int(d["bonus_ataque"]))
                    teste = re_.rolar(f"1d20{bonus:+d}" if bonus else "1d20")
                    acertou = teste["total"] >= re_.defesa_efetiva(o, self.cfg) or (re_.natural(teste) == 20)
                    if re_.natural(teste) == 1:
                        acertou = False
                    nota = f" ({teste['total']} vs {re_.defesa_efetiva(o, self.cfg)})"
                if not acertou:
                    ctx.emitir([evento("habilidade_erro", personagem=p["id"], alvo=o["id"], habilidade=hab["id"])])
                    detalhes.append(f"erra {o['nome']}{nota}")
                    continue
                reducao = re_.passivas(o)["reducao_dano"] + sum(int(self.cfg.get("condicoes", {}).get(c["id"], {}).get("reducao_dano", 0)) for c in o.get("condicoes", []))
                valor = max(0, valor - reducao)
                ctx.emitir([evento("dano", alvo=o["id"], valor=valor, barra="pv", tipo_dano=d.get("tipo_dano", "energia"), rolagem=rol, origem=hab["id"])])
                detalhes.append(f"{valor} de dano em {o['nome']}{nota} ({re_.resumo_barra(estado['personagens'][o['id']])})")
                quedas.append(o["id"])
        # --- cura
        if ef.get("cura"):
            c = ef["cura"]
            expr = c["expressao"]
            if c.get("por_nivel"):
                expr = str(int(expr) * nivel)
            if c.get("mais_atributo"):
                m = int((p.get("atributos") or {}).get(c["mais_atributo"], 0))
                expr = f"{expr}{m:+d}" if m else expr
            if c.get("mais_nivel"):
                expr = f"{expr}+{nivel}"
            alvos = self._alvos_em_area(estado, p, _pos(p), int(c["raio"]), True) if c.get("raio") else [alvo or p]
            for o in alvos:
                rol = re_.rolar(expr) if "d" in expr else {"expressao": expr, "total": int(expr.replace("+", "")) if expr.lstrip("+-").isdigit() else 0, "termos": []}
                if not rol["termos"] and not expr.lstrip("+-").isdigit():
                    rol = re_.rolar(expr)
                ctx.emitir([evento("cura", alvo=o["id"], valor=max(0, rol["total"]), barra="pv", rolagem=rol, origem=hab["id"])])
                detalhes.append(f"{o['nome']} recupera {rol['total']} ({re_.resumo_barra(estado['personagens'][o['id']])})")
        # --- condição
        if ef.get("condicao"):
            c = ef["condicao"]
            em = c.get("em", "alvo")
            if em == "self":
                alvos = [p]
            elif em == "area":
                centro = _pos(alvo) if alvo is not None and s.get("alvo_id") and alvo["id"] != p["id"] else _pos(p)
                alvos = self._alvos_em_area(estado, p, centro, int(c.get("raio", 2)), bool(c.get("aliados")))
            else:
                alvos = [alvo] if alvo is not None else []
            for o in alvos:
                if c.get("salvaguarda") and o["id"] != p["id"]:
                    sv = self._rolar_salvaguarda(o, c["salvaguarda"], cd)
                    if sv and sv["sucesso"]:
                        detalhes.append(f"{o['nome']} resiste")
                        continue
                ev = evento("condicao", alvo=o["id"], condicao=c["id"], rodadas=int(c.get("rodadas", 1)))
                if c.get("bonus"):
                    ev["bonus"] = int(c["bonus"])
                ctx.emitir([ev])
                detalhes.append(f"{o['nome']} fica {self.cfg.get('condicoes', {}).get(c['id'], {}).get('nome', c['id'])}")
        if detalhes:
            ctx.acoes[-1]["texto"] += ": " + "; ".join(detalhes)
        for pid in quedas:
            ctx.checar_queda(pid)

    def _criativa(self, ctx: "_Rodada", p: dict, texto: str, arb: dict | None) -> None:
        estado = ctx.estado
        texto = texto[:MAX_TEXTO]
        if arb is None:   # sem Planejador (nível 4): teste com a melhor perícia, CD média, sem efeito mecânico
            pericia = self._melhor_pericia(p)
            arb = {"pericia": pericia, "dificuldade": "media", "efeito_sucesso": "nenhum", "efeito_falha": "nenhum",
                   "alvos": [], "motivo": texto}
        cd = re_.cd_por_faixa(arb["dificuldade"], self.cfg)
        ev = re_.resolver_teste(p, arb["pericia"], cd, self.cfg, motivo=texto)
        res = "SUCESSO" if ev["sucesso"] else "FALHA"
        alvos = [estado["personagens"][a] for a in arb.get("alvos", []) if a in estado["personagens"]]
        efeito = arb["efeito_sucesso"] if ev["sucesso"] else arb["efeito_falha"]
        evs = [ev] + re_.aplicar_efeito_catalogo(efeito, self.catalogo, p, alvos)
        evs = self._resolver_empurroes(estado, evs)
        desc = f"{p['nome']}, ação criativa \"{texto}\": {arb['pericia']} CD {cd} → {ev['rolagem']['total']}, {res}"
        ctx.emitir(evs, texto=desc, ator=p["id"])
        detalhes = []
        for e in evs[1:]:
            alvo = estado["personagens"].get(e.get("alvo", ""), {})
            if e["tipo"] == "dano":
                detalhes.append(f"{e['valor']} de dano em {alvo.get('nome', '?')} ({re_.resumo_barra(alvo)})")
            elif e["tipo"] == "cura":
                detalhes.append(f"{alvo.get('nome', '?')} recupera {e['valor']}")
            elif e["tipo"] == "condicao":
                detalhes.append(f"{alvo.get('nome', '?')} fica {e['condicao']}")
            elif e["tipo"] == "empurrado":
                detalhes.append(f"{alvo.get('nome', '?')} é empurrado para ({e['para'][0]},{e['para'][1]})")
        if detalhes:
            ctx.acoes[-1]["texto"] += "; " + "; ".join(detalhes)
        for e in evs:
            if e["tipo"] == "dano":
                ctx.checar_queda(e["alvo"])

    def _resolver_empurroes(self, estado: dict, evs: list[dict]) -> list[dict]:
        out = []
        for e in evs:
            if e["tipo"] != "empurrar_pedido":
                out.append(e)
                continue
            alvo, origem = estado["personagens"].get(e["alvo"]), estado["personagens"].get(e["origem"])
            if not alvo or not origem:
                continue
            mapa = self.mapa_logico(estado, {alvo["id"]})
            dx, dy = alvo["x"] - origem["x"], alvo["y"] - origem["y"]
            n = max(abs(dx), abs(dy)) or 1
            passo = (round(dx / n), round(dy / n))
            if passo == (0, 0):
                passo = (1, 0)
            atual = _pos(alvo)
            for _ in range(e["quadrados"]):
                prox = (atual[0] + passo[0], atual[1] + passo[1])
                if not mapa.passavel(*prox):
                    break
                atual = prox
            if atual != _pos(alvo):
                out.append(evento("empurrado", personagem=alvo["id"], alvo=alvo["id"], de=list(_pos(alvo)), para=list(atual)))
        return out

    def _defender(self, ctx: "_Rodada", p: dict) -> None:
        ctx.emitir([evento("condicao", alvo=p["id"], condicao="defendendo", rodadas=1)],
                   texto=f"{p['nome']} assume postura defensiva", ator=p["id"])

    def _mover(self, ctx: "_Rodada", p: dict, destino: tuple[int, int], rotulo: str = "se move") -> bool:
        estado = ctx.estado
        p = estado["personagens"][p["id"]]
        mapa = self.mapa_logico(estado, {p["id"]})
        limite = int(p.get("deslocamento", 6))
        res = gm.caminho(_pos(p), destino, mapa, self.metrica, limite) if mapa.dentro(*destino) and mapa.passavel(*destino) else None
        if res is None:                      # caminho bloqueado durante a rodada: chega o mais perto possível
            alc = gm.custos_de_movimento(_pos(p), mapa, self.metrica, limite)
            if len(alc) <= 1:
                return False
            destino = min(alc, key=lambda c: (gm.distancia_quadrados(c, destino, self.metrica), alc[c]))
            res = gm.caminho(_pos(p), destino, mapa, self.metrica, limite)
            if res is None:
                return False
        caminho, custo = res
        if custo == 0:
            return False
        ctx.emitir([evento("movimento", personagem=p["id"], de=list(_pos(p)), para=list(destino),
                           caminho=[list(c) for c in caminho], custo=custo)],
                   texto=f"{p['nome']} {rotulo} para ({destino[0]},{destino[1]})", ator=p["id"])
        return True

    # ---------------------------------------------------------------- NPC
    def _falar_npc(self, ctx: "_Rodada", npc: dict, fala: str) -> None:
        fala = " ".join(str(fala).split())[:MAX_FALA_NPC]
        if fala:
            ctx.emitir([evento("fala", personagem=npc["id"], texto=fala)], texto=f"{npc['nome']} diz: \"{fala}\"", ator=npc["id"], fala=True)

    def _executar_npc(self, ctx: "_Rodada", npc: dict, it: dict) -> None:
        estado = ctx.estado
        acao = it.get("acao")
        postura = it.get("postura")
        if postura and postura != npc.get("postura"):
            ctx.emitir([evento("postura", personagem=npc["id"], postura=postura)])
        dest = None
        if it.get("destino_x") is not None and it.get("destino_y") is not None:
            dest = (int(it["destino_x"]), int(it["destino_y"]))
        fala = it.get("fala") if isinstance(it.get("fala"), str) else None
        if not npc.get("voz") or npc.get("voz") == "NARRADOR":          # animais e criaturas sem voz própria não falam
            fala = None
            if acao == "falar":
                acao = "esperar"
        if acao == "falar":
            self._falar_npc(ctx, npc, fala or "")
            return
        if acao == "esperar":
            return
        if fala and acao in ("atacar", "habilidade", "mover", "fugir", "defender", "render_se"):
            self._falar_npc(ctx, npc, fala)                        # fala antes de agir (provocação, ordem, súplica)
        if acao == "render_se":
            ctx.emitir([evento("postura", personagem=npc["id"], postura="rendido")], texto=f"{npc['nome']} se rende", ator=npc["id"])
            return
        if acao == "defender":
            if not self.inimigos_de(estado, npc) or estado["modo"] != "combate":
                return                                             # sem ameaça, "defender" é só esperar: nada a narrar
            self._defender(ctx, npc)
            return
        if acao in ("mover", "fugir") and dest:
            self._mover(ctx, npc, dest, "foge" if acao == "fugir" else "se move")
            return
        if acao in ("atacar", "habilidade"):
            atq = re_.ataque_de(npc, it.get("ataque_ou_habilidade_id") or "")
            if atq is None:
                return
            if dest:
                self._mover(ctx, npc, dest)
            npc = estado["personagens"][npc["id"]]
            mapa = self.mapa_logico(estado, {npc["id"]})
            alvo = estado["personagens"].get(it.get("alvo_id") or "")
            if alvo is None or not re_.vivo(alvo) or not self.em_alcance(estado, _pos(npc), alvo, atq, mapa):
                alvo = self._fallback_alvo(estado, npc, atq, mapa, it.get("se_alvo_invalido", "mais_proximo"))
                if alvo is None:
                    # ninguém ao alcance: aproxima-se do inimigo mais próximo (se ainda não moveu) ou defende
                    inimigos = self.inimigos_de(estado, npc)
                    if inimigos and not dest:
                        alc = gm.custos_de_movimento(_pos(npc), mapa, self.metrica, int(npc.get("deslocamento", 6)))
                        perto = min(inimigos, key=lambda o: gm.distancia_quadrados(_pos(npc), _pos(o), self.metrica))
                        cel = min(alc, key=lambda c: (gm.distancia_quadrados(c, _pos(perto), self.metrica), alc[c]))
                        if cel != _pos(npc) and self._mover(ctx, npc, cel, "avança"):
                            return
                    self._defender(ctx, npc)
                    return
            self._resolver_ataque(ctx, npc, alvo, atq, None, mapa)

    def _fallback_alvo(self, estado: dict, npc: dict, atq: dict, mapa: gm.MapaLogico, politica: str) -> dict | None:
        if politica == "defender":
            return None
        cands = [o for o in self.inimigos_de(estado, npc) if self.em_alcance(estado, _pos(npc), o, atq, mapa)]
        if not cands:
            return None
        if politica == "mais_ferido":
            return min(cands, key=lambda o: (_frac_pv(o), gm.distancia_quadrados(_pos(npc), _pos(o), self.metrica)))
        return min(cands, key=lambda o: (gm.distancia_quadrados(_pos(npc), _pos(o), self.metrica), _frac_pv(o)))

    # ---------------------------------------------------------------- cenas
    def evento_mudar_cena(self, estado: dict, cena_id: str) -> dict:
        """Evento `cena_mudou`: carrega o tilemap da cena, posiciona o grupo na entrada e instancia os NPCs do encontro."""
        cena = self.cenas[cena_id]
        tilemap = cena["tilemap"]
        entrada = cena.get("entrada", [1, 1])
        mapa = gm.MapaLogico(tilemap)
        livres = sorted(gm.bfs_conectado(tilemap, tuple(entrada)),
                        key=lambda c: gm.distancia_quadrados(c, tuple(entrada), self.metrica))
        posicoes = {}
        usados = set()
        for pid, p in estado["personagens"].items():
            if p["tipo"] != "jogador":
                continue
            for c in livres:
                if c not in usados and mapa.passavel(*c):
                    posicoes[pid] = list(c)
                    usados.add(c)
                    break
        remover = [pid for pid, p in estado["personagens"].items() if p["tipo"] == "npc"]
        adicionar = []
        for npc in cena.get("npcs", []):
            npc = copy.deepcopy(npc)
            if (npc["x"], npc["y"]) in usados or not mapa.passavel(npc["x"], npc["y"]):
                for c in reversed(livres):
                    if c not in usados:
                        npc["x"], npc["y"] = c
                        break
            usados.add((npc["x"], npc["y"]))
            adicionar.append(npc)
        nova = {"id": cena_id, "nome": cena["nome"], "descricao": cena.get("descricao", ""),
                "tema": cena.get("tema", estado["cena"].get("tema", "medieval")), "tilemap": tilemap,
                "largura": len(tilemap[0]), "altura": len(tilemap), "imagem_url": cena.get("imagem_url")}
        return evento("cena_mudou", cena_id=cena_id, cena=nova, posicoes=posicoes, remover=remover, adicionar=adicionar)


class _Rodada:
    """Acumula eventos, aplica-os ao estado de trabalho e agrupa em ações (e1, e2…) para o Narrador."""

    def __init__(self, motor: Motor, estado: dict):
        self.motor = motor
        self.estado = estado
        self.eventos: list[dict] = []
        self.acoes: list[dict] = []
        self._n = 0

    def emitir(self, evs: list[dict], texto: str | None = None, ator: str | None = None, fala: bool = False) -> str | None:
        grupo = None
        if texto is not None:
            self._n += 1
            grupo = f"e{self._n}"
            self.acoes.append({"id": grupo, "ator_id": ator, "texto": texto, "eventos": [], "fala": fala})
        for ev in evs:
            if grupo:
                ev["grupo"] = grupo
                self.acoes[-1]["eventos"].append(ev)
            aplicar(self.estado, ev)
            self.eventos.append(ev)
        return grupo

    def checar_queda(self, pid: str) -> None:
        p = self.estado["personagens"].get(pid)
        if p and not p.get("caido") and p["barras"].get("pv", {"atual": 1})["atual"] <= 0:
            ev = evento("caiu", personagem=pid)
            if self.acoes:
                ev["grupo"] = self.acoes[-1]["id"]
                self.acoes[-1]["eventos"].append(ev)
                self.acoes[-1]["texto"] += f"; {p['nome']} CAI"
            aplicar(self.estado, ev)
            self.eventos.append(ev)
