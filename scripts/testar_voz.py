"""Testa o motor de voz instalado (Kokoro ou Piper) fora do servidor: sintetiza uma frase por "ator" de voices.json
e grava em data/audio_cache. Útil depois de `pip install kokoro soundfile`.

    python scripts/testar_voz.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import tts_engine  # noqa: E402

FRASE = "Thorin avança e o machado encontra o flanco de Kargath, abrindo um corte fundo na armadura de couro."


def main() -> int:
    try:
        import torch
        print("torch", torch.__version__, "| CUDA:", torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")
    except Exception as exc:
        print("torch indisponível:", exc)
    handler = tts_engine.escolher_handler_tts()
    if handler is None:
        print("nenhum motor de TTS disponível (TTS_MOTOR=%s)" % __import__("os").getenv("TTS_MOTOR", "auto"))
        return 1
    vozes = json.loads((Path(__file__).resolve().parents[1] / "voices.json").read_text(encoding="utf-8"))
    for nome, cfg in vozes.items():
        if cfg.get("motor", "kokoro") != __import__("os").getenv("TTS_MOTOR_ATIVO", "kokoro"):
            continue                                     # ator de outro motor (ex.: _reserva do Piper)
        t = time.time()
        try:
            audio_id = handler(FRASE, cfg)
        except Exception as exc:
            print(f"{nome:<10} FALHOU: {exc}")
            continue
        caminho = tts_engine.DIR_AUDIO / f"{audio_id}.ogg"
        print(f"{nome:<10} {time.time() - t:5.2f}s  → {caminho} ({caminho.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
