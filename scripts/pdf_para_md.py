"""Converte um PDF de livro de regras em Markdown para o compilador/RAG.

    python scripts/pdf_para_md.py "../dnd 5e/livro.pdf" cartuchos/sistemas/dnd5e/sistema.md --titulo "Livro do Jogador"

Cada página vira uma seção `## <Título> — p. N` (o fatiador do RAG subdivide em ~600 tokens). Linhas de cabeçalho/rodapé
repetidas e números de página soltos são removidos; hifenização de fim de linha é desfeita.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path


def limpar_pagina(texto: str, repetidas: set[str]) -> str:
    linhas = []
    for l in texto.splitlines():
        s = " ".join(l.split())
        if not s or s in repetidas or re.fullmatch(r"\d{1,3}", s):
            continue
        linhas.append(s)
    corpo = "\n".join(linhas)
    corpo = re.sub(r"(\w)-\n(\w)", r"\1\2", corpo)          # hifenização
    corpo = re.sub(r"(?<![.:!?])\n(?=[a-záéíóúâêôãõç])", " ", corpo)   # quebra no meio da frase
    return corpo.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("saida")
    ap.add_argument("--titulo", default=None)
    ap.add_argument("--inicio", type=int, default=1, help="primeira página (1-based)")
    ap.add_argument("--fim", type=int, default=None)
    ap.add_argument("--anexar", action="store_true", help="acrescenta ao arquivo de saída em vez de sobrescrever")
    args = ap.parse_args()
    from pypdf import PdfReader
    r = PdfReader(args.pdf)
    titulo = args.titulo or Path(args.pdf).stem
    paginas = [(i + 1, (p.extract_text() or "")) for i, p in enumerate(r.pages)]
    paginas = [(n, t) for n, t in paginas if args.inicio <= n <= (args.fim or 10**6)]
    # cabeçalhos/rodapés: linhas curtas que se repetem em muitas páginas
    cont: Counter = Counter()
    for _, t in paginas:
        for l in set(" ".join(x.split()) for x in t.splitlines()[:3] + t.splitlines()[-3:]):
            if 0 < len(l) < 60:
                cont[l] += 1
    repetidas = {l for l, c in cont.items() if c >= max(5, len(paginas) // 20)}
    partes = [f"# {titulo}\n"]
    vazias = 0
    for n, t in paginas:
        corpo = limpar_pagina(t, repetidas)
        if len(corpo) < 80:
            vazias += 1
            continue
        partes.append(f"\n## {titulo} — p. {n}\n\n{corpo}\n")
    saida = Path(args.saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    texto = "".join(partes)
    if args.anexar and saida.exists():
        saida.write_text(saida.read_text(encoding="utf-8") + "\n" + texto, encoding="utf-8")
    else:
        saida.write_text(texto, encoding="utf-8")
    print(f"{len(paginas) - vazias} páginas com texto ({vazias} vazias/imagens) → {saida} ({len(texto) // 1024} KB, ~{len(texto) // 4} tokens)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
