"""Cria os perfis de voz do AI-VTT no VoiceStudio (clonagem a partir de clipes de referência) e escreve voices.json.

Referências: arquivos em data/vozes_ref/<ator>.(mp3|wav|ogg) com o texto falado em data/vozes_ref/<ator>.txt
(opcional; sem ele usa a frase de amostra padrão). Os clipes pt-BR gerados antes pelo Edge-TTS servem bem.

    python scripts/criar_vozes_voicestudio.py            # cria o que faltar e atualiza voices.json
    python scripts/criar_vozes_voicestudio.py --testar   # além disso, sintetiza uma frase com cada perfil e mede o tempo
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parents[1]
URL = os.environ.get("VOICESTUDIO_URL", "http://127.0.0.1:3900").rstrip("/")
REF = RAIZ / "data" / "vozes_ref"
FRASE_REF = "Que os deuses guiem a sua lâmina, viajante. A estrada para Valkar é longa e cheia de sombras."
ATORES = {
    # ator → (descrição para a UI, velocidade, reserva)
    "NARRADOR": ("Narrador (VoiceStudio, clonado)", 1.0),
    "grave":    ("Masculina grave (chefes, guerreiros)", 0.95),
    "masculina":("Masculina neutra", 1.0),
    "agudo":    ("Masculina aguda e rápida (goblins, trapaceiros)", 1.15),
    "feminina": ("Feminina", 1.0),
    "jovem":    ("Feminina jovem", 1.05),
    "anciao":   ("Masculina lenta e cansada (anciãos, eruditos)", 0.9),
    "sussurro": ("Sussurrada e grave (cultistas, espíritos)", 0.9),
}
# ator → arquivo de referência (se não houver um próprio)
FALLBACK_REF = {"masculina": "NARRADOR", "agudo": "jovem"}


def perfis_existentes(cli: httpx.Client) -> dict[str, dict]:
    r = cli.get(f"{URL}/profiles")
    r.raise_for_status()
    dados = r.json()
    lista = dados if isinstance(dados, list) else dados.get("profiles") or dados.get("items") or []
    return {p.get("name"): p for p in lista if isinstance(p, dict)}


def criar_perfil(cli: httpx.Client, nome: str, clipe: Path, texto: str) -> dict:
    with clipe.open("rb") as f:
        r = cli.post(f"{URL}/profiles", data={"name": nome, "ref_text": texto, "language": "pt", "kind": "clone"},
                     files={"ref_audio": (clipe.name, f, "audio/mpeg" if clipe.suffix == ".mp3" else "audio/wav")}, timeout=300)
    if r.status_code >= 400:
        raise RuntimeError(f"{r.status_code}: {r.text[:300]}")
    return r.json()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--testar", action="store_true")
    ap.add_argument("--prefixo", default="aivtt_")
    a = ap.parse_args()
    REF.mkdir(parents=True, exist_ok=True)
    cache = RAIZ / "data" / "audio_cache"
    for ator in ATORES:                                        # aproveita amostras antigas do Edge-TTS como referência
        if not any((REF / f"{ator}{ext}").exists() for ext in (".mp3", ".wav", ".ogg")):
            fonte = cache / f"amostra_{ator}.mp3"
            if fonte.exists():
                (REF / f"{ator}.mp3").write_bytes(fonte.read_bytes())
    with httpx.Client(timeout=60) as cli:
        try:
            cli.get(f"{URL}/health").raise_for_status()
        except Exception as exc:
            print("VoiceStudio não está no ar em", URL, "—", exc)
            return 1
        existentes = perfis_existentes(cli)
        vozes_path = RAIZ / "voices.json"
        vozes = json.loads(vozes_path.read_text(encoding="utf-8")) if vozes_path.exists() else {}
        for ator, (descricao, vel) in ATORES.items():
            nome = a.prefixo + ator
            clipe = next((REF / f"{ator}{ext}" for ext in (".mp3", ".wav", ".ogg") if (REF / f"{ator}{ext}").exists()), None)
            if clipe is None and ator in FALLBACK_REF:
                clipe = next((REF / f"{FALLBACK_REF[ator]}{ext}" for ext in (".mp3", ".wav", ".ogg") if (REF / f"{FALLBACK_REF[ator]}{ext}").exists()), None)
            if nome in existentes:
                perfil = existentes[nome]
                print(f"  {ator:<10} já existe → {perfil.get('id')}")
            elif clipe is None:
                print(f"  {ator:<10} sem clipe de referência em {REF}; pulando")
                continue
            else:
                texto = (REF / f"{clipe.stem}.txt").read_text(encoding="utf-8").strip() if (REF / f"{clipe.stem}.txt").exists() else FRASE_REF
                perfil = criar_perfil(cli, nome, clipe, texto)
                print(f"  {ator:<10} criado a partir de {clipe.name} → {perfil.get('id')}")
            vozes[ator] = {"motor": "voicestudio", "voz": perfil.get("id"), "perfil": nome, "velocidade": vel, "pitch_semitons": 0,
                           "idioma": "pt", "descricao": descricao, "reserva": vozes.get(ator, {}).get("reserva")}
        vozes_path.write_text(json.dumps(vozes, ensure_ascii=False, indent=2), encoding="utf-8")
        print("voices.json atualizado")
        if a.testar:
            for ator, cfg in vozes.items():
                if cfg.get("motor") != "voicestudio":
                    continue
                t = time.time()
                r = cli.post(f"{URL}/v1/audio/speech", json={"model": os.environ.get("VOICESTUDIO_MODELO", "omnivoice"), "voice": cfg["voz"],
                             "input": "Thorin avança e o machado encontra o flanco de Kargath, abrindo um corte fundo na armadura.",
                             "response_format": "wav", "language": "pt", "speed": cfg.get("velocidade", 1.0)}, timeout=300)
                ok = r.status_code == 200 and len(r.content) > 1000
                saida = cache / f"vs_teste_{ator}.wav"
                if ok:
                    saida.write_bytes(r.content)
                print(f"  {ator:<10} {'OK' if ok else 'FALHOU ' + r.text[:120]}  {time.time() - t:5.1f}s  {saida if ok else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
