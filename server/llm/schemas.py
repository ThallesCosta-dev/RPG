"""Saída estruturada dos LLMs (§9.2, §10.3) e o objeto de contexto que vai para cada provedor.

Sem valores default nos modelos de saída: o Gemini exige todos os campos; "não se aplica" = null.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel


class IntencaoNPC(BaseModel):
    npc_id: str
    acao: Literal["atacar", "mover", "habilidade", "defender", "fugir", "render_se"]
    alvo_id: str | None              # obrigatório em atacar/habilidade
    ataque_ou_habilidade_id: str | None
    destino_x: int | None            # obrigatório em mover/fugir
    destino_y: int | None
    se_alvo_invalido: Literal["mais_proximo", "mais_ferido", "defender"]
    postura: Literal["agressivo", "cauteloso", "fugindo", "rendido"]


class Arbitragem(BaseModel):
    personagem_id: str
    pericia: str                     # precisa existir na ficha / system_config
    dificuldade: Literal["facil", "media", "dificil", "muito_dificil"]
    motivo: str
    efeito_sucesso: str              # id do CATÁLOGO DE EFEITOS
    efeito_falha: str
    alvos: list[str]


class PlanoRodada(BaseModel):
    intencoes_npcs: list[IntencaoNPC]
    arbitragens: list[Arbitragem]
    iniciar_combate: bool
    mudar_cena_para: str | None      # id de cenas.json ou null


class Memoria(BaseModel):
    resumo: str
    fatos: list[str]
    npcs_conhecidos: dict[str, str]
    missoes_abertas: list[str]


class LayoutMapa(BaseModel):
    tipo: Literal["masmorra", "caverna", "taverna", "rua", "floresta", "salao"]
    largura: int
    altura: int
    descricao_visual: str            # vai para o prompt da imagem
    elementos: list[Literal["agua", "pilastras", "terreno_dificil", "cobertura", "varias_entradas"]]


# ---------------------------------------------------------------- extração de cartuchos (§5.1)
class AtaqueExtraido(BaseModel):
    id: str
    nome: str
    bonus: int
    dano: str
    tipo_dano: str
    alcance: int
    condicoes_ao_acertar: list[str]


class MonstroExtraido(BaseModel):
    id: str
    nome: str
    pv: int
    defesa: int
    deslocamento: int
    iniciativa_bonus: int
    ataques: list[AtaqueExtraido]
    pericias: dict[str, int]
    descricao: str


class CondicaoExtraida(BaseModel):
    id: str
    nome: str
    descricao: str
    mod_defesa: int
    mod_ataque: int
    dano_por_turno: str | None
    duracao_padrao: int


class ExtracaoSecao(BaseModel):
    monstros: list[MonstroExtraido]
    condicoes: list[CondicaoExtraida]


class NPCExtraido(BaseModel):
    id: str
    nome: str
    faccao: Literal["aliado", "inimigo", "neutro"]
    personalidade: str
    voz: Literal["NARRADOR", "grave", "agudo", "feminina", "sussurro"]
    postura: Literal["agressivo", "cauteloso", "fugindo", "rendido"]
    modelo_monstro: str | None       # id em monstros.json, se for uma criatura do sistema
    pv: int
    defesa: int


class CenaExtraida(BaseModel):
    id: str
    nome: str
    descricao: str
    tipo_mapa: Literal["masmorra", "caverna", "taverna", "rua", "floresta", "salao"]
    npcs: list[str]                  # ids de NPCs presentes
    transicoes: list[str]            # ids de cenas vizinhas


class ExtracaoCampanha(BaseModel):
    npcs: list[NPCExtraido]
    cenas: list[CenaExtraida]
    cena_inicial: str


# ---------------------------------------------------------------- contexto
@dataclass
class Contexto:
    """O que um provedor recebe. `dados` carrega estado/opções para o provedor heurístico."""
    tipo: Literal["planejar", "narrar", "memoria", "mapa", "extrair"]
    system_prompt: str
    conteudo: str
    sala_id: str | None = None
    rodada: int | None = None
    economico: bool = False
    max_palavras: int = 220
    schema: Any = None                       # modelo Pydantic esperado (planejar/memoria/mapa/extrair)
    dados: dict = field(default_factory=dict)
