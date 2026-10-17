"""Backup do Event Store ao fim da sessão (§14.1): data/backup-AAAAMMDD-HHMM.db. Mantém os 14 mais recentes."""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def main() -> int:
    origem = RAIZ / "data" / "sessions.db"
    if not origem.exists():
        print("nada para copiar:", origem)
        return 1
    destino = RAIZ / "data" / f"backup-{datetime.now():%Y%m%d-%H%M}.db"
    src, dst = sqlite3.connect(origem), sqlite3.connect(destino)
    src.backup(dst)
    src.close(), dst.close()
    antigos = sorted((RAIZ / "data").glob("backup-*.db"))[:-14]
    for a in antigos:
        a.unlink()
    print("backup salvo em", destino)
    return 0


if __name__ == "__main__":
    sys.exit(main())
