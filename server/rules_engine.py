"""Motor de regras determinístico: dados, ataques, testes, dano, condições, iniciativa (§7).

Nada aqui altera o estado: as funções devolvem EVENTOS, que o Event Store aplica (events.py).
`_rng` é trocado por `random.Random(seed)` nos testes (ver `usar_semente`).
"""
from __future__ import annotations

import random
import re
import secrets
from typing import Any

_rng: Any = secrets.SystemRandom()
TERMO = re.compile(r"([+-]?)(?:(\d*)d(\d+)(?:(kh|kl)(\d+))?|(\d+))")

CONDICOES_INCAPACITANTES = {"inconsciente", "morrendo", "paralisado", "atordoado", "indefeso"}


def usar_semente(seed: int | None) -> None:
    """Testes e golden tests: resultados reprodutíveis."""
    global _rng
    _rng = random.Random(seed) if seed is not None else secrets.SystemRandom()


def rolar(expressao: str, mult_dados: int = 1) -> dict:
    """'1d20+8', '2d20kh1+5', '2d6+1d4+3'. mult_dados multiplica a quantidade de dados (crítico)."""
    expr = expressao.replace(" ", "").lower()
    pos, total, termos = 0, 0, []
    for m in TERMO.finditer(expr):
        if m.start() != pos:
            break
        pos = m.end()
        sinal = -1 if m.group(1) == "-" else 1
        if m.group(3):                                   # termo de dados
            qtd, faces = int(m.group(2) or 1) * mult_dados, int(m.group(3))
            if not (1 <= qtd <= 100 and 2 <= faces <= 1000):
                raise ValueError(f"dados fora dos limites: {m.group(0)}")
            dados = [_rng.randint(1, faces) for _ in range(qtd)]
            mantidos = dados
            if m.group(4):                               # kh = maiores, kl = menores
                mantidos = sorted(dados, reverse=m.group(4) == "kh")[: int(m.group(5))]
            total += sinal * sum(mantidos)
            termos.append({"termo": m.group(0), "dados": dados, "mantidos": mantidos})
        else:                                            # modificador fixo
            total += sinal * int(m.group(6))
            termos.append({"termo": m.group(0)})
    if pos != len(expr) or not termos:
        raise ValueError(f"expressão inválida: {expressao!r}")
    return {"expressao": expressao, "total": total, "termos": termos}


def expressao_valida(expressao: str) -> bool:
    if not isinstance(expressao, str) or len(expressao) > 64:
        return False
    expr = expressao.replace(" ", "").lower()
    pos, n = 0, 0
    for m in TERMO.finditer(expr):
        if m.start() != pos:
            return False
        pos = m.end()
        n += 1
        if m.group(3) and not (1 <= int(m.group(2) or 1) <= 100 and 2 <= int(m.group(3)) <= 1000):
            return False
    return pos == len(expr) and n > 0


def natural(teste: dict) -> int | None:
    """Valor natural do primeiro dado mantido (o d20 de um ataque)."""
    for t in teste["termos"]:
        if "mantidos" in t:
            return t["mantidos"][0]
    return None


def evento(tipo: str, **dados) -> dict:
    return {"tipo": tipo, **dados}       # id, rodada e seq são atribuídos pelo Event Store


# ------------------------------------------------------------------ estado auxiliar
def vivo(p: dict) -> bool:
    return not p.get("caido") and p["barras"].get("pv", {"atual": 1})["atual"] > 0


def incapacitado(p: dict) -> bool:
    return not vivo(p) or any(c["id"] in CONDICOES_INCAPACITANTES for c in p.get("condicoes", []))


def bonus_pericia(p: dict, pericia: str) -> int:
    return int(p.get("pericias", {}).get(pericia, 0))


def tem_condicao(p: dict, cond: str) -> bool:
    return any(c["id"] == cond for c in p.get("condicoes", []))


def defesa_efetiva(alvo: dict, cfg: dict, em_cobertura: bool = False) -> int:
    base = int(alvo[cfg.get("campo_defesa", "defesa")])
    for c in alvo.get("condicoes", []):
        base += int(cfg.get("condicoes", {}).get(c["id"], {}).get("mod_defesa", 0))
    if em_cobertura:
        base += int(cfg.get("bonus_cobertura", 2))
    return base


def bonus_ataque_efetivo(atacante: dict, ataque: dict, cfg: dict) -> int:
    bonus = int(ataque.get("bonus", 0))
    for c in atacante.get("condicoes", []):
        regra = cfg.get("condicoes", {}).get(c["id"], {})
        bonus += int(regra.get("mod_ataque", 0)) + int(c.get("bonus", 0) if c["id"] == "inspirado" else 0)
    return bonus


# ------------------------------------------------------------------ ataque
def resolver_ataque(atacante: dict, alvo: dict, ataque: dict, cfg: dict,
                    teste: dict | None = None, em_cobertura: bool = False) -> list[dict]:
    """Ataque genérico 'd20 + bônus vs defesa'. Sistemas com graus de sucesso (PF2e) sobrescrevem no plugin."""
    bonus = bonus_ataque_efetivo(atacante, ataque, cfg)
    teste = teste or rolar(cfg["ataque"]["expressao"].format(bonus=bonus))
    nat = natural(teste) or 0
    defesa = defesa_efetiva(alvo, cfg, em_cobertura)
    crit_cfg = cfg["critico"]

    acertou = teste["total"] >= defesa
    if nat == 20 and crit_cfg.get("natural_20_acerta", True):
        acertou = True
    if nat == 1 and crit_cfg.get("natural_1_erra", True):
        acertou = False
    critico = acertou and nat >= ataque.get("margem_critico", crit_cfg["margem_padrao"])

    eventos = [evento("ataque", atacante=atacante["id"], alvo=alvo["id"], ataque=ataque["id"],
                      ataque_nome=ataque.get("nome", ataque["id"]), rolagem=teste, defesa=defesa,
                      acertou=acertou, critico=critico)]
    if acertou:
        mult = ataque.get("mult_critico", crit_cfg["multiplicador_padrao"]) if critico else 1
        dano = rolar(ataque["dano"], mult_dados=mult)
        valor = max(0, dano["total"] - int(alvo.get("reducao_dano", 0)))
        eventos.append(evento("dano", alvo=alvo["id"], valor=valor, barra="pv",
                              tipo_dano=ataque.get("tipo_dano", "fisico"), rolagem=dano))
        for cond in ataque.get("condicoes_ao_acertar", []):
            eventos.append(evento("condicao", alvo=alvo["id"], condicao=cond,
                                  rodadas=int(cfg.get("condicoes", {}).get(cond, {}).get("duracao_padrao", 3))))
    return eventos


# ------------------------------------------------------------------ testes de perícia / arbitragem
def resolver_teste(personagem: dict, pericia: str, cd: int, cfg: dict, teste: dict | None = None,
                   motivo: str = "") -> dict:
    expr = cfg.get("teste", {}).get("expressao", "1d20+{bonus}").format(bonus=bonus_pericia(personagem, pericia))
    teste = teste or rolar(expr)
    return evento("teste", personagem=personagem["id"], pericia=pericia, cd=cd, rolagem=teste,
                  sucesso=teste["total"] >= cd, motivo=motivo)


def aplicar_efeito_catalogo(efeito_id: str, catalogo: dict, ator: dict, alvos: list[dict]) -> list[dict]:
    """Converte um efeito do catálogo (§7.4) em eventos, com valores limitados pelo próprio catálogo."""
    ef = catalogo.get(efeito_id)
    if not ef or efeito_id == "nenhum":
        return []
    eventos: list[dict] = []
    if "dano" in ef:
        for alvo in alvos:
            dano = rolar(ef["dano"])
            eventos.append(evento("dano", alvo=alvo["id"], valor=max(0, dano["total"]), barra="pv",
                                  tipo_dano=ef.get("tipo_dano", "impacto"), rolagem=dano, origem="ambiente"))
    if "cura" in ef:
        for alvo in alvos:
            cura = rolar(ef["cura"])
            eventos.append(evento("cura", alvo=alvo["id"], valor=cura["total"], barra="pv", rolagem=cura))
    if "condicoes_permitidas" in ef:
        cond = ef.get("condicao") or ef["condicoes_permitidas"][0]
        if cond in ef["condicoes_permitidas"]:
            for alvo in alvos:
                eventos.append(evento("condicao", alvo=alvo["id"], condicao=cond,
                                      rodadas=int(ef.get("duracao_rodadas", 1))))
    if "bonus" in ef:
        for alvo in alvos:
            eventos.append(evento("condicao", alvo=alvo["id"], condicao="inspirado",
                                  rodadas=int(ef.get("duracao_rodadas", 1)), bonus=int(ef["bonus"])))
    if "quadrados_max" in ef:
        # empurrar: o motor calcula o destino com grid_math; aqui só o pedido
        for alvo in alvos:
            eventos.append(evento("empurrar_pedido", alvo=alvo["id"], origem=ator["id"],
                                  quadrados=int(ef["quadrados_max"])))
    if efeito_id == "revelar_informacao":
        eventos.append(evento("informacao_revelada", personagem=ator["id"]))
    return eventos


# ------------------------------------------------------------------ iniciativa e turnos
def rolar_iniciativa(personagem: dict, cfg: dict) -> dict:
    expr = cfg.get("iniciativa", {}).get("expressao", "1d20+{iniciativa}")
    teste = rolar(expr.format(iniciativa=int(personagem.get("iniciativa_bonus", 0))))
    return evento("iniciativa", personagem=personagem["id"], rolagem=teste, total=teste["total"])


def ordenar_iniciativa(resultados: list[dict], personagens: dict[str, dict]) -> list[str]:
    """Maior total primeiro; empate: maior bônus; depois jogadores antes de NPCs; depois id."""
    def chave(r):
        p = personagens[r["personagem"]]
        return (-r["total"], -int(p.get("iniciativa_bonus", 0)), 0 if p["tipo"] == "jogador" else 1, p["id"])
    return [r["personagem"] for r in sorted(resultados, key=chave)]


def inicio_de_turno(personagem: dict, cfg: dict) -> list[dict]:
    """Efeitos contínuos no início do turno (ex.: Sangrando)."""
    eventos: list[dict] = []
    for c in personagem.get("condicoes", []):
        regra = cfg.get("condicoes", {}).get(c["id"], {})
        if regra.get("dano_por_turno"):
            dano = rolar(regra["dano_por_turno"])
            eventos.append(evento("dano", alvo=personagem["id"], valor=dano["total"], barra="pv",
                                  tipo_dano=regra.get("tipo_dano", "sangramento"), rolagem=dano, origem=c["id"]))
    return eventos


def fim_de_turno(personagem: dict) -> list[dict]:
    """Decrementa durações; condição que chega a zero é removida."""
    eventos: list[dict] = []
    for c in personagem.get("condicoes", []):
        if c.get("rodadas_restantes") is None:
            continue
        if c["rodadas_restantes"] - 1 <= 0:
            eventos.append(evento("condicao_removida", alvo=personagem["id"], condicao=c["id"]))
        else:
            eventos.append(evento("condicao_tick", alvo=personagem["id"], condicao=c["id"]))
    return eventos


def cd_por_faixa(faixa: str, cfg: dict) -> int:
    tabela = cfg.get("tabela_dificuldade", {"facil": 10, "media": 15, "dificil": 20, "muito_dificil": 25})
    return int(tabela.get(faixa, tabela.get("media", 15)))


def ataque_de(personagem: dict, ataque_id: str) -> dict | None:
    for a in personagem.get("ataques", []):
        if a["id"] == ataque_id:
            return a
    return None


def resumo_barra(p: dict, barra: str = "pv") -> str:
    b = p["barras"].get(barra)
    return f"{b['atual']}/{b['max']}" if b else "?"
