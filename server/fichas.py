"""Fichas de personagem construídas a partir do sistema: classe, nível, atributos, perícias, equipamento → números derivados.

`construir_ficha` (padrão, quando o sistema tem classes.json): o servidor calcula PV, recurso de classe, Defesa/CA, bônus de
ataque e de perícia, CD de habilidades e a lista de habilidades da classe até o nível. O jogador só escolhe.
`validar_ficha` (legado, "ficha livre"): aceita números digitados, com limites, para sistemas sem classes.
Fichas salvas ficam em data/fichas/<sistema_id>/<id>.json e podem ser reaproveitadas em outras mesas.
"""
from __future__ import annotations

import json
import re
import secrets
import unicodedata
from pathlib import Path

from .rules_engine import expressao_valida

LIMITES = {"atributo": (-5, 12), "pv": (1, 400), "barra": (0, 400), "defesa": (5, 35), "deslocamento": (1, 20),
           "iniciativa_bonus": (-5, 20), "pericia": (-5, 25), "bonus_ataque": (-5, 25), "alcance": (1, 30),
           "max_ataques": 6, "max_pericias": 30, "nome": 40, "classe": 60, "icone": 4, "historia": 1500,
           "nivel": (1, 20), "max_armas": 3, "pericias_extras": 2, "soma_atributos": 12}
TIPOS_DANO = ["corte", "perfuracao", "impacto", "fogo", "frio", "eletricidade", "acido", "energia", "luz", "trevas", "veneno", "psiquico"]
ICONES = ["⚔️", "🛡️", "🏹", "🔮", "✨", "🗡️", "🪓", "🔥", "🌿", "🎭", "📖", "🐾", "💀", "🎵", "🧪", "🪄"]


def _slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:24] or "pc"


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


# ====================================================================== modelo para o formulário
def modelo_ficha(sistema) -> dict:
    cfg = sistema.config
    classes = {k: v for k, v in (sistema.classes or {}).items() if not k.startswith("_")}
    return {
        "sistema_id": sistema.id,
        "sistema_nome": cfg.get("sistema_nome", sistema.nome),
        "modo": "classes" if classes else "livre",
        "atributos": cfg.get("atributos_principais", []),
        "pericias": cfg.get("pericias", []),
        "pericia_atributo": cfg.get("pericia_atributo", {}),
        "barras": cfg.get("barras_status", [{"id": "pv", "nome": "Pontos de Vida"}]),
        "campo_defesa": cfg.get("campo_defesa", "defesa"),
        "nome_defesa": cfg.get("nome_defesa", "Defesa"),
        "tipos_dano": TIPOS_DANO,
        "icones": ICONES,
        "limites": LIMITES,
        "expressao_ataque": cfg.get("ataque", {}).get("expressao", "1d20+{bonus}"),
        "exemplo_dano": "1d8+3",
        "progressao": cfg.get("progressao", {}),
        "armas": cfg.get("armas", []),
        "armaduras": cfg.get("armaduras", []),
        "escudo": cfg.get("escudo", {"bonus": 2}),
        "classes": [{"id": k, "nome": c["nome"], "descricao": c.get("descricao", ""), "dado_vida": c.get("dado_vida"),
                     "pv_nivel1": c.get("pv_nivel1"), "pv_por_nivel": c.get("pv_por_nivel"), "pm_por_nivel": c.get("pm_por_nivel"),
                     "atributo_principal": c.get("atributo_principal"), "conjurador": bool(c.get("conjurador")),
                     "pericias_de_classe": c.get("pericias_de_classe", []), "quantidade_pericias": c.get("quantidade_pericias", 2),
                     "pericias_fixas": c.get("pericias_fixas", []), "armas_iniciais": c.get("armas_iniciais", []),
                     "armadura_inicial": c.get("armadura_inicial", "nenhuma"), "escudo": bool(c.get("escudo")),
                     "habilidades": c.get("habilidades", [])} for k, c in classes.items()],
        "monstros_modelo": [{"id": k, "nome": v.get("nome", k)} for k, v in sistema.monstros.items()],
    }


# ====================================================================== números derivados
def _progressao(cfg: dict, classe: dict, nivel: int, atributos: dict) -> dict:
    """Proficiência/treino, meio nível e fórmulas do sistema."""
    prog = cfg.get("progressao", {"tipo": "5e"})
    tipo = prog.get("tipo", "5e")
    con = int(atributos.get("CON", 0))
    principal = classe.get("atributo_principal", "FOR")
    mod_principal = int(atributos.get(principal, 0))
    if tipo == "t20":
        meio = nivel // 2
        treino = int(prog.get("treino", 2)) if nivel < 7 else 4
        pv = int(classe.get("pv_nivel1", 12)) + con + (nivel - 1) * (int(classe.get("pv_por_nivel", 3)) + con)
        recurso = int(classe.get("pm_por_nivel", 3)) * nivel
        bonus_pericia_treinada = lambda mod: meio + mod + treino           # noqa: E731
        bonus_pericia_destreinada = lambda mod: meio + mod                  # noqa: E731
        bonus_ataque = lambda mod: meio + mod                               # noqa: E731
        cd = 10 + meio + mod_principal
        bonus_magia = meio + mod_principal
        prof = treino
    else:
        tabela = prog.get("proficiencia", [2, 2, 2, 2, 3, 3, 3, 3, 4, 4])
        prof = int(tabela[min(nivel, len(tabela)) - 1])
        dv = int(classe.get("dado_vida", 8))
        pv = dv + con + (nivel - 1) * (dv // 2 + 1 + con)
        esp = prog.get("espacos_conjurador", [2, 3, 4, 4, 4])
        if classe.get("conjurador"):
            recurso = int(esp[min(nivel, len(esp)) - 1])
        elif classe.get("recurso_por_nivel"):
            recurso = nivel
        else:
            recurso = nivel if any(h.get("custo") for h in classe.get("habilidades", [])) else 0
        bonus_pericia_treinada = lambda mod: prof + mod                     # noqa: E731
        bonus_pericia_destreinada = lambda mod: mod                         # noqa: E731
        bonus_ataque = lambda mod: prof + mod                               # noqa: E731
        cd = 8 + prof + mod_principal
        bonus_magia = prof + mod_principal
        meio = nivel // 2
    return {"tipo": tipo, "prof": prof, "meio_nivel": meio, "pv": max(1, pv), "recurso": max(0, recurso),
            "pericia_treinada": bonus_pericia_treinada, "pericia_destreinada": bonus_pericia_destreinada,
            "ataque": bonus_ataque, "cd": cd, "bonus_magia": bonus_magia, "mod_principal": mod_principal}


def _mod_arma(arma: dict, atributos: dict) -> int:
    regra = arma.get("atributo", "FOR")
    if regra == "melhor":
        return max(int(atributos.get("FOR", 0)), int(atributos.get("DES", 0)))
    return int(atributos.get(regra, 0))


def construir_ficha(dados: dict, sistema, voices: dict | None = None) -> tuple[dict, list[str]]:
    """Ficha a partir de classe + nível + atributos + escolhas. Devolve (ficha, erros)."""
    erros: list[str] = []
    cfg = sistema.config
    classes = {k: v for k, v in (sistema.classes or {}).items() if not k.startswith("_")}
    if not isinstance(dados, dict):
        return {}, ["ficha deve ser um objeto"]
    classe_id = str(dados.get("classe_id") or "")
    classe = classes.get(classe_id)
    if classe is None:
        return {}, [f"classe inválida: escolha uma de {', '.join(classes)}"]
    nivel_max = int(cfg.get("progressao", {}).get("nivel_max", 5))
    nivel = _int(dados.get("nivel", 1), "nível", (1, nivel_max), erros, 1)

    nome = str(dados.get("nome") or "").strip()[:LIMITES["nome"]]
    if not nome:
        erros.append("nome é obrigatório")
    icone = str(dados.get("icone") or "⚔️")[:LIMITES["icone"]]
    cor = str(dados.get("cor") or "#2563eb")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", cor):
        erros.append("cor deve ser #rrggbb")
        cor = "#2563eb"
    historia = str(dados.get("historia") or "")[:LIMITES["historia"]]
    voz = dados.get("voz") or None
    if voz is not None and voices is not None and (voz not in voices or voz.startswith("_") or voz == "NARRADOR"):
        erros.append("voz desconhecida")
        voz = None

    # atributos: modificadores (ex.: FOR +3). Soma limitada para evitar fichas absurdas.
    atributos = {}
    for a in cfg.get("atributos_principais", []):
        atributos[a] = _int((dados.get("atributos") or {}).get(a, 0), f"atributo {a}", LIMITES["atributo"], erros)
    soma_max = LIMITES["soma_atributos"] + (nivel - 1) // 4 * 2
    if sum(atributos.values()) > soma_max:
        erros.append(f"a soma dos modificadores de atributo não pode passar de +{soma_max} no nível {nivel}")

    P = _progressao(cfg, classe, nivel, atributos)

    # perícias: fixas da classe + escolhidas da lista da classe (quantidade) + extras livres (antecedente/origem)
    pericia_atr = cfg.get("pericia_atributo", {})
    todas = list(cfg.get("pericias", []))
    fixas = [p for p in classe.get("pericias_fixas", []) if p in todas]
    escolhidas = [str(p) for p in (dados.get("pericias") or []) if str(p) in todas and str(p) not in fixas]
    de_classe = [p for p in escolhidas if p in classe.get("pericias_de_classe", [])]
    livres = [p for p in escolhidas if p not in classe.get("pericias_de_classe", [])]
    if len(de_classe) > int(classe.get("quantidade_pericias", 2)):
        erros.append(f"a classe {classe['nome']} permite {classe.get('quantidade_pericias', 2)} perícias de classe (escolheu {len(de_classe)})")
    if len(livres) > LIMITES["pericias_extras"]:
        erros.append(f"no máximo {LIMITES['pericias_extras']} perícias fora da lista da classe (antecedente)")
    treinadas = sorted(set(fixas) | set(escolhidas))
    pericias = {}
    for p in todas:
        mod = int(atributos.get(pericia_atr.get(p, "DES"), 0))
        pericias[p] = int(P["pericia_treinada"](mod) if p in treinadas else P["pericia_destreinada"](mod))

    # equipamento
    armas_cfg = {a["id"]: a for a in cfg.get("armas", [])}
    armaduras_cfg = {a["id"]: a for a in cfg.get("armaduras", [])}
    ids_armas = [str(a) for a in (dados.get("armas") or classe.get("armas_iniciais", []))][: LIMITES["max_armas"]]
    ataques = []
    for aid in ids_armas:
        arma = armas_cfg.get(aid)
        if arma is None:
            erros.append(f"arma desconhecida: {aid}")
            continue
        mod = _mod_arma(arma, atributos)
        dano = f"{arma['dano']}{mod:+d}" if mod else arma["dano"]
        ataques.append({"id": arma["id"], "nome": arma["nome"], "bonus": int(P["ataque"](mod)), "dano": dano,
                        "tipo_dano": arma.get("tipo_dano", "impacto"), "alcance": int(arma.get("alcance", 1)),
                        "atributo": arma.get("atributo", "FOR")})
        if arma.get("arremesso"):
            ataques.append({"id": f"{arma['id']}_arremesso", "nome": f"{arma['nome']} (arremesso)", "bonus": int(P["ataque"](mod)),
                            "dano": dano, "tipo_dano": arma.get("tipo_dano", "impacto"), "alcance": int(arma["arremesso"]), "atributo": arma.get("atributo", "FOR")})
    if not ataques:
        erros.append("escolha pelo menos uma arma")

    armadura_id = str(dados.get("armadura_id") or classe.get("armadura_inicial", "nenhuma"))
    armadura = armaduras_cfg.get(armadura_id)
    if armadura is None:
        erros.append(f"armadura desconhecida: {armadura_id}")
        armadura = armaduras_cfg.get("nenhuma", {"id": "nenhuma", "nome": "Sem armadura", "defesa_base": 10, "max_des": None})
    escudo = bool(dados.get("escudo", classe.get("escudo", False)))
    des = int(atributos.get("DES", 0))
    max_des = armadura.get("max_des")
    defesa = int(armadura.get("defesa_base", 10)) + (des if max_des is None else min(des, int(max_des)))
    if escudo:
        defesa += int(cfg.get("escudo", {"bonus": 2}).get("bonus", 2))

    # habilidades da classe até o nível (+ passivas aplicadas na defesa)
    habilidades = []
    for h in classe.get("habilidades", []):
        if int(h.get("nivel", 1)) > nivel:
            continue
        hab = dict(h)
        if hab.get("usos"):
            hab["usos_restantes"] = int(hab["usos"].get("max", 1))
        habilidades.append(hab)
        pas = (h.get("efeito") or {}).get("passiva") or {}
        if pas.get("mod_defesa"):
            defesa += int(pas["mod_defesa"])
        if pas.get("defesa_sem_armadura") and armadura_id == "nenhuma" and not escudo:
            defesa = 10 + sum(int(atributos.get(a, 0)) for a in pas["defesa_sem_armadura"])

    barras = {"pv": {"atual": P["pv"], "max": P["pv"]}}
    for b in cfg.get("barras_status", []):
        if b["id"] != "pv":
            barras[b["id"]] = {"atual": P["recurso"], "max": P["recurso"]}

    pid = f"pc_{_slug(nome)}_{secrets.token_hex(2)}"
    ficha = {"id": pid, "nome": nome, "tipo": "jogador", "faccao": "aliado", "classe": f"{classe['nome']} (nível {nivel})",
             "classe_id": classe_id, "nivel": nivel, "cor": cor, "icone": icone, "x": 0, "y": 0, "barras": barras,
             "defesa": max(1, defesa), "deslocamento": int(classe.get("deslocamento", 6)), "iniciativa_bonus": des,
             "atributos": atributos, "ataques": ataques, "pericias": pericias, "pericias_treinadas": treinadas,
             "armadura": armadura_id, "escudo": escudo, "habilidades": habilidades, "usos": {h["id"]: h["usos_restantes"] for h in habilidades if "usos_restantes" in h},
             "magia": {"bonus": P["bonus_magia"], "cd": P["cd"], "atributo": classe.get("atributo_principal", "FOR")},
             "proficiencia": P["prof"], "condicoes": [], "caido": False, "voz": voz, "postura": None, "historia": historia,
             "sistema_id": sistema.id, "personalizada": True}
    return ficha, erros


# ====================================================================== ficha livre (sistemas sem classes)
def validar_ficha(dados: dict, sistema, voices: dict | None = None) -> tuple[dict, list[str]]:
    """Normaliza e valida uma ficha livre. Devolve (ficha no formato do estado, lista de erros)."""
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
    voz = dados.get("voz") or None
    if voz is not None:
        validas_voz = {k for k in (voices or {}) if not k.startswith("_") and k != "NARRADOR"}
        if voices is not None and voz not in validas_voz:
            erros.append("voz desconhecida")
            voz = None

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
    for i, a in enumerate(ataques):
        if ids.count(a["id"]) > 1:
            a["id"] = f"{a['id']}_{i + 1}"
    if len(lista) > LIMITES["max_ataques"]:
        erros.append(f"no máximo {LIMITES['max_ataques']} ataques")

    pid = f"pc_{_slug(nome)}_{secrets.token_hex(2)}"
    ficha = {"id": pid, "nome": nome, "tipo": "jogador", "faccao": "aliado", "classe": classe, "cor": cor, "icone": icone,
             "x": 0, "y": 0, "barras": barras, "defesa": defesa, "deslocamento": deslocamento, "iniciativa_bonus": iniciativa,
             "atributos": atributos, "ataques": ataques, "pericias": pericias, "condicoes": [], "caido": False,
             "voz": voz, "postura": None, "historia": historia, "sistema_id": sistema.id, "personalizada": True}
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
