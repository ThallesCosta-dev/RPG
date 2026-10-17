"""Fichas de personagem criadas pelos jogadores, validadas contra o system_config do cartucho.

O formulário é gerado a partir de `modelo_ficha(sistema)`; `validar_ficha` devolve (ficha normalizada, erros).
Fichas salvas ficam em data/fichas/<sistema_id>/<id>.json e podem ser reaproveitadas em outras mesas.
"""
from __future__ import annotations

import json
import re
import secrets
import unicodedata
from pathlib import Path

from .rules_engine import expressao_valida

LIMITES = {"atributo": (-5, 15), "pv": (1, 999), "barra": (0, 999), "defesa": (1, 60), "deslocamento": (1, 30),
           "iniciativa_bonus": (-5, 30), "pericia": (-5, 40), "bonus_ataque": (-5, 40), "alcance": (1, 40),
           "max_ataques": 6, "max_pericias": 30, "nome": 40, "classe": 60, "icone": 4, "historia": 1500}
TIPOS_DANO = ["corte", "perfuracao", "impacto", "fogo", "frio", "eletricidade", "acido", "energia", "luz", "trevas", "veneno", "psiquico"]
ICONES = ["⚔️", "🛡️", "🏹", "🔮", "✨", "🗡️", "🪓", "🔥", "🌿", "🎭", "📖", "🐾", "💀", "🎵", "🧪", "🪄"]


def _slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:24] or "pc"


def modelo_ficha(sistema) -> dict:
    cfg = sistema.config
    return {
        "sistema_id": sistema.id,
        "sistema_nome": cfg.get("sistema_nome", sistema.nome),
        "atributos": cfg.get("atributos_principais", []),
        "pericias": cfg.get("pericias", []),
        "barras": cfg.get("barras_status", [{"id": "pv", "nome": "Pontos de Vida"}]),
        "campo_defesa": cfg.get("campo_defesa", "defesa"),
        "tipos_dano": TIPOS_DANO,
        "icones": ICONES,
        "limites": LIMITES,
        "expressao_ataque": cfg.get("ataque", {}).get("expressao", "1d20+{bonus}"),
        "exemplo_dano": "1d8+3",
        "monstros_modelo": [{"id": k, "nome": v.get("nome", k)} for k, v in sistema.monstros.items()],
    }


def _int(v, nome: str, lim: tuple[int, int], erros: list[str], padrao: int = 0) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        erros.append(f"{nome} deve ser um número inteiro")
        return padrao
    if not (lim[0] <= n <= lim[1]):
        erros.append(f"{nome} fora dos limites ({lim[0]} a {lim[1]})")
        return max(lim[0], min(lim[1], n))
    return n


def validar_ficha(dados: dict, sistema) -> tuple[dict, list[str]]:
    """Normaliza e valida. Devolve (ficha no formato do estado, lista de erros)."""
    erros: list[str] = []
    cfg = sistema.config
    if not isinstance(dados, dict):
        return {}, ["ficha deve ser um objeto"]
    nome = str(dados.get("nome") or "").strip()
    if not nome:
        erros.append("nome é obrigatório")
    nome = nome[:LIMITES["nome"]]
    classe = str(dados.get("classe") or "").strip()[:LIMITES["classe"]]
    icone = str(dados.get("icone") or "⚔️")[:LIMITES["icone"]]
    cor = str(dados.get("cor") or "#2563eb")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", cor):
        erros.append("cor deve ser #rrggbb")
        cor = "#2563eb"
    historia = str(dados.get("historia") or "")[:LIMITES["historia"]]

    atributos = {}
    for a in cfg.get("atributos_principais", []):
        atributos[a] = _int((dados.get("atributos") or {}).get(a, 0), f"atributo {a}", LIMITES["atributo"], erros)

    barras = {}
    for b in cfg.get("barras_status", [{"id": "pv", "nome": "Pontos de Vida"}]):
        bid = b["id"]
        lim = LIMITES["pv"] if bid == "pv" else LIMITES["barra"]
        maximo = _int((dados.get("barras") or {}).get(bid, 10 if bid == "pv" else 0), f"barra {b.get('nome', bid)}", lim, erros, 10)
        barras[bid] = {"atual": maximo, "max": maximo}
    if "pv" not in barras:
        barras["pv"] = {"atual": 10, "max": 10}

    defesa = _int(dados.get("defesa", 10), "defesa", LIMITES["defesa"], erros, 10)
    deslocamento = _int(dados.get("deslocamento", 6), "deslocamento", LIMITES["deslocamento"], erros, 6)
    iniciativa = _int(dados.get("iniciativa_bonus", 0), "iniciativa", LIMITES["iniciativa_bonus"], erros, 0)

    validas = set(cfg.get("pericias", []))
    pericias = {}
    for k, v in (dados.get("pericias") or {}).items():
        if validas and k not in validas:
            erros.append(f"perícia desconhecida no sistema: {k}")
            continue
        pericias[k] = _int(v, f"perícia {k}", LIMITES["pericia"], erros)
    if len(pericias) > LIMITES["max_pericias"]:
        erros.append("perícias demais")

    ataques = []
    lista = dados.get("ataques") or []
    if not isinstance(lista, list) or not lista:
        erros.append("inclua pelo menos um ataque")
        lista = []
    for i, a in enumerate(lista[: LIMITES["max_ataques"]]):
        if not isinstance(a, dict):
            erros.append(f"ataque {i + 1} inválido")
            continue
        anome = str(a.get("nome") or f"Ataque {i + 1}").strip()[:40]
        dano = str(a.get("dano") or "").replace(" ", "")
        if not expressao_valida(dano):
            erros.append(f"ataque '{anome}': expressão de dano inválida (ex.: 1d8+3)")
        tipo = a.get("tipo_dano") if a.get("tipo_dano") in TIPOS_DANO else "impacto"
        ataques.append({"id": _slug(anome) or f"ataque_{i + 1}", "nome": anome,
                        "bonus": _int(a.get("bonus", 0), f"bônus de '{anome}'", LIMITES["bonus_ataque"], erros),
                        "dano": dano or "1d4", "tipo_dano": tipo,
                        "alcance": _int(a.get("alcance", 1), f"alcance de '{anome}'", LIMITES["alcance"], erros, 1)})
    ids = [a["id"] for a in ataques]
    for i, a in enumerate(ataques):                      # ids únicos
        if ids.count(a["id"]) > 1:
            a["id"] = f"{a['id']}_{i + 1}"
    if len(lista) > LIMITES["max_ataques"]:
        erros.append(f"no máximo {LIMITES['max_ataques']} ataques")

    pid = f"pc_{_slug(nome)}_{secrets.token_hex(2)}"
    ficha = {"id": pid, "nome": nome, "tipo": "jogador", "faccao": "aliado", "classe": classe, "cor": cor, "icone": icone,
             "x": 0, "y": 0, "barras": barras, "defesa": defesa, "deslocamento": deslocamento, "iniciativa_bonus": iniciativa,
             "atributos": atributos, "ataques": ataques, "pericias": pericias, "condicoes": [], "caido": False,
             "voz": None, "postura": None, "historia": historia, "sistema_id": sistema.id, "personalizada": True}
    return ficha, erros


class FichasSalvas:
    def __init__(self, raiz: str | Path):
        self.raiz = Path(raiz)

    def _dir(self, sistema_id: str) -> Path:
        d = self.raiz / sistema_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def salvar(self, ficha: dict) -> None:
        (self._dir(ficha["sistema_id"]) / f"{ficha['id']}.json").write_text(json.dumps(ficha, ensure_ascii=False, indent=2), encoding="utf-8")

    def listar(self, sistema_id: str) -> list[dict]:
        out = []
        for f in sorted(self._dir(sistema_id).glob("*.json")):
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except ValueError:
                continue
        return out

    def obter(self, sistema_id: str, ficha_id: str) -> dict | None:
        if not re.fullmatch(r"pc_[a-z0-9_]+", ficha_id or ""):
            return None
        f = self._dir(sistema_id) / f"{ficha_id}.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None

    def apagar(self, sistema_id: str, ficha_id: str) -> bool:
        f = self._dir(sistema_id) / f"{ficha_id}.json"
        if re.fullmatch(r"pc_[a-z0-9_]+", ficha_id or "") and f.exists():
            f.unlink()
            return True
        return False
