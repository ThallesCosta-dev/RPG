"""Event Store (SQLite em modo WAL) + projeção do estado (§14.1).

Estado atual = último snapshot + eventos posteriores não revertidos.
`aplicar(estado, evento)` é a única forma de mudar o estado; o motor só produz eventos.
"""
from __future__ import annotations

import copy
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS salas (
  id          TEXT PRIMARY KEY,
  sistema_id  TEXT NOT NULL,
  campanha_id TEXT NOT NULL,
  host_id     TEXT NOT NULL,
  criada_em   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS jogadores (
  sala_id    TEXT NOT NULL REFERENCES salas(id),
  player_id  TEXT NOT NULL,
  nome       TEXT NOT NULL,
  papel      TEXT NOT NULL CHECK (papel IN ('host', 'jogador', 'espectador')),
  personagem TEXT,
  PRIMARY KEY (sala_id, player_id)
);

CREATE TABLE IF NOT EXISTS convites (
  codigo    TEXT PRIMARY KEY,
  sala_id   TEXT NOT NULL REFERENCES salas(id),
  usado_por TEXT,
  criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS eventos (
  id        INTEGER PRIMARY KEY,
  sala_id   TEXT NOT NULL REFERENCES salas(id),
  rodada    INTEGER NOT NULL,
  seq       INTEGER NOT NULL,
  tipo      TEXT NOT NULL,
  dados     TEXT NOT NULL,
  revertido INTEGER NOT NULL DEFAULT 0,
  criado_em TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (sala_id, seq)
);

CREATE TABLE IF NOT EXISTS snapshots (
  sala_id TEXT NOT NULL REFERENCES salas(id),
  ate_seq INTEGER NOT NULL,
  estado  TEXT NOT NULL,
  PRIMARY KEY (sala_id, ate_seq)
);

CREATE TABLE IF NOT EXISTS chamadas_llm (
  id          INTEGER PRIMARY KEY,
  sala_id     TEXT,
  rodada      INTEGER,
  tipo        TEXT NOT NULL,
  provedor    TEXT NOT NULL,
  modelo      TEXT NOT NULL,
  tokens_in   INTEGER,
  tokens_out  INTEGER,
  latencia_ms INTEGER,
  prompt      TEXT,
  resposta    TEXT,
  erro        TEXT,
  criado_em   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CRONICA_MAX_RODADAS = 6


# ====================================================================== projeção
def estado_inicial(sala_id: str, sistema_id: str, campanha_id: str) -> dict:
    return {
        "sala_id": sala_id,
        "sistema_id": sistema_id,
        "campanha_id": campanha_id,
        "rodada": 0,
        "modo": "exploracao",
        "cena": {"id": "", "nome": "", "descricao": "", "tema": "medieval",
                 "tilemap": [], "largura": 0, "altura": 0, "imagem_url": None},
        "obstaculos": [],
        "personagens": {},
        "iniciativa": [],
        "jogadores": {},
        "memoria": None,
        "cronica": [],
    }


def _p(estado: dict, pid: str) -> dict | None:
    return estado["personagens"].get(pid)


def _ajustar_barra(p: dict, barra: str, delta: int) -> None:
    b = p["barras"].setdefault(barra, {"atual": 0, "max": 0})
    b["atual"] = max(0, min(b["max"], b["atual"] + delta))


def aplicar(estado: dict, ev: dict) -> dict:
    """Aplica um evento e devolve o MESMO dicionário (mutação controlada). Eventos desconhecidos são ignorados."""
    t = ev["tipo"]
    pers = estado["personagens"]

    if t == "sala_criada":
        estado["cena"] = copy.deepcopy(ev["cena"])
        estado["personagens"] = copy.deepcopy(ev.get("personagens", {}))
        estado["jogadores"] = copy.deepcopy(ev.get("jogadores", {}))
    elif t == "jogador_entrou":
        estado["jogadores"][ev["player_id"]] = {"player_id": ev["player_id"], "nome": ev["nome"],
                                                "papel": ev["papel"], "personagem_id": ev.get("personagem_id"),
                                                "conectado": False}
        if ev.get("personagem") and ev.get("personagem_id"):
            pers[ev["personagem_id"]] = copy.deepcopy(ev["personagem"])
    elif t == "personagem_adicionado":
        pers[ev["personagem"]["id"]] = copy.deepcopy(ev["personagem"])
    elif t == "personagem_removido":
        pers.pop(ev["personagem_id"], None)
        estado["iniciativa"] = [i for i in estado["iniciativa"] if i != ev["personagem_id"]]
    elif t == "personagem_editado":
        p = _p(estado, ev["personagem_id"])
        if p:
            for k, v in ev["campos"].items():
                if k == "barras":
                    for bid, bv in v.items():
                        b = p["barras"].setdefault(bid, {"atual": 0, "max": 0})
                        b.update({kk: int(vv) for kk, vv in bv.items() if kk in ("atual", "max")})
                        b["atual"] = max(0, min(b["max"], b["atual"]))
                elif k in ("x", "y", "defesa", "deslocamento", "iniciativa_bonus"):
                    p[k] = int(v)
                elif k in ("condicoes", "caido", "postura", "nome", "voz", "faccao"):
                    p[k] = copy.deepcopy(v)
            if p["barras"].get("pv", {}).get("atual", 1) > 0 and "caido" in ev["campos"] and not ev["campos"]["caido"]:
                p["caido"] = False
    elif t == "rodada_iniciada":
        estado["rodada"] = ev["rodada"]
    elif t == "movimento" or t == "empurrado":
        p = _p(estado, ev["personagem"])
        if p:
            p["x"], p["y"] = int(ev["para"][0]), int(ev["para"][1])
    elif t == "dano":
        p = _p(estado, ev["alvo"])
        if p:
            _ajustar_barra(p, ev.get("barra", "pv"), -int(ev["valor"]))
    elif t == "cura":
        p = _p(estado, ev["alvo"])
        if p:
            _ajustar_barra(p, ev.get("barra", "pv"), int(ev["valor"]))
            if p["barras"].get("pv", {}).get("atual", 0) > 0:
                p["caido"] = False
    elif t == "condicao":
        p = _p(estado, ev["alvo"])
        if p:
            conds = p.setdefault("condicoes", [])
            nova = {"id": ev["condicao"], "rodadas_restantes": ev.get("rodadas")}
            if "bonus" in ev:
                nova["bonus"] = ev["bonus"]
            for c in conds:
                if c["id"] == ev["condicao"]:
                    c.update(nova)
                    break
            else:
                conds.append(nova)
    elif t == "condicao_removida":
        p = _p(estado, ev["alvo"])
        if p:
            p["condicoes"] = [c for c in p.get("condicoes", []) if c["id"] != ev["condicao"]]
    elif t == "condicao_tick":
        p = _p(estado, ev["alvo"])
        if p:
            for c in p.get("condicoes", []):
                if c["id"] == ev["condicao"] and c.get("rodadas_restantes") is not None:
                    c["rodadas_restantes"] -= 1
    elif t == "caiu":
        p = _p(estado, ev["personagem"])
        if p:
            p["caido"] = True
    elif t == "levantou":
        p = _p(estado, ev["personagem"])
        if p:
            p["caido"] = False
    elif t == "postura":
        p = _p(estado, ev["personagem"])
        if p:
            p["postura"] = ev["postura"]
    elif t == "obstaculo_adicionado":
        estado["obstaculos"] = [o for o in estado["obstaculos"] if (o["x"], o["y"]) != (ev["x"], ev["y"])]
        estado["obstaculos"].append({"x": ev["x"], "y": ev["y"], "tipo": ev["tipo_obstaculo"],
                                     "rodadas_restantes": ev.get("duracao_rodadas", 1)})
    elif t == "obstaculo_removido":
        estado["obstaculos"] = [o for o in estado["obstaculos"] if (o["x"], o["y"]) != (ev["x"], ev["y"])]
    elif t == "obstaculos_tick":
        for o in estado["obstaculos"]:
            o["rodadas_restantes"] -= 1
        estado["obstaculos"] = [o for o in estado["obstaculos"] if o["rodadas_restantes"] > 0]
    elif t == "combate_iniciado":
        estado["modo"] = "combate"
        estado["iniciativa"] = list(ev["ordem"])
    elif t == "combate_encerrado":
        estado["modo"] = "exploracao"
        estado["iniciativa"] = []
    elif t == "cena_mudou":
        estado["cena"] = copy.deepcopy(ev["cena"])
        estado["obstaculos"] = []
        estado["modo"] = "exploracao"
        estado["iniciativa"] = []
        for pid, pos in ev.get("posicoes", {}).items():
            p = _p(estado, pid)
            if p:
                p["x"], p["y"] = int(pos[0]), int(pos[1])
        for pid in ev.get("remover", []):
            pers.pop(pid, None)
        for np_ in ev.get("adicionar", []):
            pers[np_["id"]] = copy.deepcopy(np_)
    elif t == "imagem_cena":
        if estado["cena"].get("id") == ev["cena_id"]:
            estado["cena"]["imagem_url"] = ev["imagem_url"]
    elif t == "memoria":
        estado["memoria"] = copy.deepcopy(ev["memoria"])
    elif t == "log_rodada":
        estado["cronica"].extend({"rodada": ev["rodada"], "id": a["id"], "texto": a["texto"]} for a in ev["acoes"])
        corte = ev["rodada"] - CRONICA_MAX_RODADAS
        estado["cronica"] = [l for l in estado["cronica"] if l["rodada"] > corte]
    # ataque, teste, fala, iniciativa, intencao_rejeitada, informacao_revelada, rodada_concluida: só log
    return estado


def projetar(estado: dict, eventos: list[dict]) -> dict:
    for ev in eventos:
        aplicar(estado, ev)
    return estado


# ====================================================================== store
class EventStore:
    """Thread-safe (um lock) e com cache do estado projetado por sala."""

    def __init__(self, caminho: str | Path = ":memory:"):
        self.caminho = str(caminho)
        self._con = sqlite3.connect(self.caminho, check_same_thread=False, isolation_level=None)
        self._con.row_factory = sqlite3.Row
        self._con.executescript(SCHEMA)
        self._lock = threading.RLock()
        self._estados: dict[str, dict] = {}
        self._seq: dict[str, int] = {}

    # ---------------------------------------------------------------- salas e jogadores
    def criar_sala(self, sala_id: str, sistema_id: str, campanha_id: str, host_id: str,
                   cena: dict, personagens: dict, jogadores: dict | None = None) -> dict:
        with self._lock:
            self._con.execute("INSERT INTO salas (id, sistema_id, campanha_id, host_id) VALUES (?,?,?,?)",
                              (sala_id, sistema_id, campanha_id, host_id))
            self._estados[sala_id] = estado_inicial(sala_id, sistema_id, campanha_id)
            self._seq[sala_id] = 0
            self.anexar(sala_id, [{"tipo": "sala_criada", "cena": cena, "personagens": personagens,
                                   "jogadores": jogadores or {}}])
            return self.estado_atual(sala_id)

    def sala_existe(self, sala_id: str) -> bool:
        with self._lock:
            return self._con.execute("SELECT 1 FROM salas WHERE id=?", (sala_id,)).fetchone() is not None

    def info_sala(self, sala_id: str) -> dict | None:
        with self._lock:
            r = self._con.execute("SELECT * FROM salas WHERE id=?", (sala_id,)).fetchone()
            return dict(r) if r else None

    def listar_salas(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._con.execute("SELECT * FROM salas ORDER BY criada_em DESC")]

    def adicionar_jogador(self, sala_id: str, player_id: str, nome: str, papel: str,
                          personagem_id: str | None, personagem: dict | None = None) -> None:
        with self._lock:
            self._con.execute(
                "INSERT OR REPLACE INTO jogadores (sala_id, player_id, nome, papel, personagem) VALUES (?,?,?,?,?)",
                (sala_id, player_id, nome, papel, json.dumps(personagem) if personagem else None))
            ev = {"tipo": "jogador_entrou", "player_id": player_id, "nome": nome, "papel": papel,
                  "personagem_id": personagem_id}
            if personagem:
                ev["personagem"] = personagem
            self.anexar(sala_id, [ev])

    def jogadores(self, sala_id: str) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._con.execute("SELECT * FROM jogadores WHERE sala_id=?", (sala_id,))]

    def eh_host(self, sala_id: str, player_id: str) -> bool:
        with self._lock:
            r = self._con.execute("SELECT 1 FROM jogadores WHERE sala_id=? AND player_id=? AND papel='host'",
                                  (sala_id, player_id)).fetchone()
            return r is not None

    def criar_convite(self, sala_id: str, codigo: str) -> None:
        with self._lock:
            self._con.execute("INSERT INTO convites (codigo, sala_id) VALUES (?,?)", (codigo, sala_id))

    def convite_valido(self, sala_id: str, codigo: str) -> bool:
        with self._lock:
            r = self._con.execute("SELECT usado_por FROM convites WHERE codigo=? AND sala_id=?",
                                  (codigo, sala_id)).fetchone()
            return r is not None and r["usado_por"] is None

    def usar_convite(self, codigo: str, player_id: str) -> None:
        with self._lock:
            self._con.execute("UPDATE convites SET usado_por=? WHERE codigo=?", (player_id, codigo))

    # ---------------------------------------------------------------- eventos
    def _carregar(self, sala_id: str) -> dict:
        info = self.info_sala(sala_id)
        if info is None:
            raise KeyError(f"sala desconhecida: {sala_id}")
        snap = self._con.execute("SELECT ate_seq, estado FROM snapshots WHERE sala_id=? ORDER BY ate_seq DESC LIMIT 1",
                                 (sala_id,)).fetchone()
        if snap:
            estado, desde = json.loads(snap["estado"]), snap["ate_seq"]
        else:
            estado, desde = estado_inicial(sala_id, info["sistema_id"], info["campanha_id"]), 0
        rows = self._con.execute("SELECT seq, dados FROM eventos WHERE sala_id=? AND seq>? AND revertido=0 ORDER BY seq",
                                 (sala_id, desde)).fetchall()
        projetar(estado, [json.loads(r["dados"]) for r in rows])
        ultimo = self._con.execute("SELECT COALESCE(MAX(seq),0) AS s FROM eventos WHERE sala_id=?", (sala_id,)).fetchone()
        self._estados[sala_id] = estado
        self._seq[sala_id] = int(ultimo["s"])
        return estado

    def estado_atual(self, sala_id: str) -> dict:
        """Cópia profunda: quem recebe pode mexer sem corromper o cache."""
        with self._lock:
            if sala_id not in self._estados:
                self._carregar(sala_id)
            return copy.deepcopy(self._estados[sala_id])

    def anexar(self, sala_id: str, eventos: list[dict], rodada: int | None = None, snapshot: bool = True) -> list[dict]:
        """Atribui id/seq/rodada, grava, aplica ao estado em cache e salva snapshot. Devolve os eventos gravados."""
        with self._lock:
            if sala_id not in self._estados:
                self._carregar(sala_id)
            estado = self._estados[sala_id]
            rodada = estado["rodada"] if rodada is None else rodada
            gravados = []
            self._con.execute("BEGIN")
            try:
                for ev in eventos:
                    self._seq[sala_id] += 1
                    seq = self._seq[sala_id]
                    ev = {**ev, "seq": seq, "rodada": ev.get("rodada", rodada)}
                    ev.setdefault("id", f"ev{seq}")
                    self._con.execute("INSERT INTO eventos (sala_id, rodada, seq, tipo, dados) VALUES (?,?,?,?,?)",
                                      (sala_id, ev["rodada"], seq, ev["tipo"], json.dumps(ev, ensure_ascii=False)))
                    aplicar(estado, ev)
                    gravados.append(ev)
                if snapshot and gravados:
                    self._con.execute("INSERT OR REPLACE INTO snapshots (sala_id, ate_seq, estado) VALUES (?,?,?)",
                                      (sala_id, self._seq[sala_id], json.dumps(estado, ensure_ascii=False)))
                self._con.execute("COMMIT")
            except Exception:
                self._con.execute("ROLLBACK")
                self._carregar(sala_id)
                raise
            return gravados

    def eventos_da_rodada(self, sala_id: str, rodada: int) -> list[dict]:
        with self._lock:
            rows = self._con.execute("SELECT dados FROM eventos WHERE sala_id=? AND rodada=? AND revertido=0 ORDER BY seq",
                                     (sala_id, rodada)).fetchall()
            return [json.loads(r["dados"]) for r in rows]

    def ultimas_rodadas(self, sala_id: str, n: int = 4) -> list[dict]:
        """Eventos `log_rodada` das últimas n rodadas (para o contexto do LLM)."""
        with self._lock:
            rows = self._con.execute(
                "SELECT dados FROM eventos WHERE sala_id=? AND tipo='log_rodada' AND revertido=0 ORDER BY seq DESC LIMIT ?",
                (sala_id, n)).fetchall()
            return [json.loads(r["dados"]) for r in reversed(rows)]

    def reverter_ultima_rodada(self, sala_id: str) -> int:
        """Marca os eventos da última rodada jogada como revertidos e reprojeta. Devolve a rodada revertida (0 = nada)."""
        with self._lock:
            if sala_id not in self._estados:
                self._carregar(sala_id)
            r = self._con.execute(
                "SELECT MAX(rodada) AS r FROM eventos WHERE sala_id=? AND revertido=0 AND tipo='rodada_iniciada'",
                (sala_id,)).fetchone()
            rodada = r["r"]
            if not rodada:
                return 0
            self._con.execute("BEGIN")
            self._con.execute("UPDATE eventos SET revertido=1 WHERE sala_id=? AND rodada=? AND revertido=0",
                              (sala_id, rodada))
            self._con.execute("DELETE FROM snapshots WHERE sala_id=? AND ate_seq >= "
                              "(SELECT MIN(seq) FROM eventos WHERE sala_id=? AND rodada=?)", (sala_id, sala_id, rodada))
            self._con.execute("COMMIT")
            self._carregar(sala_id)
            return int(rodada)

    # ---------------------------------------------------------------- observabilidade
    def registrar_chamada_llm(self, sala_id: str | None, rodada: int | None, tipo: str, provedor: str, modelo: str,
                              tokens_in: int | None = None, tokens_out: int | None = None,
                              latencia_ms: int | None = None, prompt: str | None = None,
                              resposta: str | None = None, erro: str | None = None) -> None:
        with self._lock:
            self._con.execute(
                "INSERT INTO chamadas_llm (sala_id, rodada, tipo, provedor, modelo, tokens_in, tokens_out, latencia_ms, "
                "prompt, resposta, erro) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (sala_id, rodada, tipo, provedor, modelo, tokens_in, tokens_out, latencia_ms,
                 (prompt or "")[:20000] or None, (resposta or "")[:20000] or None, erro))

    def ultimas_chamadas(self, sala_id: str | None = None, n: int = 30) -> list[dict]:
        with self._lock:
            if sala_id:
                rows = self._con.execute("SELECT * FROM chamadas_llm WHERE sala_id=? ORDER BY id DESC LIMIT ?",
                                         (sala_id, n)).fetchall()
            else:
                rows = self._con.execute("SELECT * FROM chamadas_llm ORDER BY id DESC LIMIT ?", (n,)).fetchall()
            return [dict(r) for r in rows]

    def intencoes_rejeitadas(self, sala_id: str, n: int = 30) -> list[dict]:
        with self._lock:
            rows = self._con.execute(
                "SELECT dados FROM eventos WHERE sala_id=? AND tipo='intencao_rejeitada' ORDER BY seq DESC LIMIT ?",
                (sala_id, n)).fetchall()
            return [json.loads(r["dados"]) for r in rows]

    def backup(self, destino: str | Path) -> None:
        with self._lock:
            alvo = sqlite3.connect(str(destino))
            self._con.backup(alvo)
            alvo.close()

    def fechar(self) -> None:
        with self._lock:
            self._con.close()
