"""Convites e tokens assinados (§14.2). O player_id sai sempre do token, nunca da URL."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

VALIDADE_S = int(os.getenv("TOKEN_VALIDADE_S", str(7 * 24 * 3600)))


@dataclass(frozen=True)
class Identidade:
    sala_id: str
    player_id: str
    papel: str


def _serializador() -> URLSafeTimedSerializer:
    chave = os.getenv("CHAVE_TOKENS") or "chave-de-desenvolvimento-troque-no-env"
    return URLSafeTimedSerializer(chave, salt="ai-vtt-sessao")


def criar_token(sala_id: str, player_id: str, papel: str) -> str:
    return _serializador().dumps({"s": sala_id, "p": player_id, "r": papel})


def validar_token(token: str | None, sala_id: str | None = None) -> Identidade | None:
    if not token:
        return None
    try:
        d = _serializador().loads(token, max_age=VALIDADE_S)
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None
    if sala_id is not None and d.get("s") != sala_id:
        return None
    return Identidade(d["s"], d["p"], d.get("r", "jogador"))


def novo_player_id() -> str:
    return "p_" + secrets.token_hex(6)


def novo_codigo_convite() -> str:
    return secrets.token_urlsafe(9)


def nova_sala_id() -> str:
    return secrets.token_hex(4)
