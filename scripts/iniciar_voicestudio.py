"""Sobe o backend do VoiceStudio (debpalash/VoiceStudio) sem a interface Electron, na porta 3900.

Usa o `uv` e o `pyproject` empacotados pelo instalador do app (instalação por usuário em
%LOCALAPPDATA%\\Programs\\VoiceStudio) e o ambiente criado em %LOCALAPPDATA%\\VoiceStudio\\venv.

    python scripts/iniciar_voicestudio.py            # inicia e espera /health
    python scripts/iniciar_voicestudio.py --sync     # (re)cria o ambiente antes (download grande: torch CUDA + modelos)
    python scripts/iniciar_voicestudio.py --parar
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

LOCAL = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
INSTALACAO = Path(os.environ.get("VOICESTUDIO_DIR", LOCAL / "Programs" / "VoiceStudio" / "resources"))
DADOS = Path(os.environ.get("VOICESTUDIO_DADOS", LOCAL / "VoiceStudio"))
PORTA = int(os.environ.get("OMNIVOICE_PORT", "3900"))
PID_FILE = DADOS / "backend.pid"


def ambiente() -> dict:
    env = dict(os.environ)
    env.update({"UV_PROJECT_ENVIRONMENT": str(DADOS / "venv"), "UV_CACHE_DIR": str(DADOS / "uv-cache"),
                "UV_PYTHON_INSTALL_DIR": str(DADOS / "python"), "OMNIVOICE_PORT": str(PORTA), "PYTHONUTF8": "1"})
    return env


def saudavel() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORTA}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def sync() -> int:
    print("criando/atualizando o ambiente do VoiceStudio (pode levar muitos minutos)…")
    return subprocess.call([str(INSTALACAO / "tools" / "uv.exe"), "sync", "--python", "3.11", "--no-dev"], cwd=INSTALACAO, env=ambiente())


def iniciar(espera_s: int = 600) -> int:
    if saudavel():
        print(f"backend já está no ar em http://127.0.0.1:{PORTA}")
        return 0
    uv = INSTALACAO / "tools" / "uv.exe"
    if not uv.exists():
        print("VoiceStudio não encontrado em", INSTALACAO)
        return 1
    DADOS.mkdir(parents=True, exist_ok=True)
    log = open(DADOS / "backend.log", "ab")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0) if os.name == "nt" else 0
    proc = subprocess.Popen([str(uv), "run", "--project", str(INSTALACAO), "python", "main.py"], cwd=INSTALACAO / "backend",
                            env=ambiente(), stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
    PID_FILE.write_text(str(proc.pid))
    print(f"backend iniciado (pid {proc.pid}); esperando /health… (1ª vez baixa o modelo OmniVoice)")
    t0 = time.time()
    while time.time() - t0 < espera_s:
        if saudavel():
            print(f"pronto em {time.time() - t0:.0f}s: http://127.0.0.1:{PORTA}")
            return 0
        if proc.poll() is not None:
            print("o backend terminou com código", proc.returncode, "— veja", DADOS / "backend.log")
            return 1
        time.sleep(3)
    print("tempo esgotado esperando o backend; veja", DADOS / "backend.log")
    return 1


def parar() -> int:
    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        subprocess.call(["taskkill", "/PID", pid, "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        PID_FILE.unlink(missing_ok=True)
        print("backend parado")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sync", action="store_true")
    ap.add_argument("--parar", action="store_true")
    ap.add_argument("--espera", type=int, default=600)
    a = ap.parse_args()
    if a.parar:
        sys.exit(parar())
    if a.sync and sync() != 0:
        sys.exit(1)
    sys.exit(iniciar(a.espera))
