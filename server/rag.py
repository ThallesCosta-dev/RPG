"""RAG local: fatiamento por cabeçalhos, índice em SQLite e busca (§5.1, §10.1).

Sem dependências pesadas por padrão: BM25 puro em Python. Se `sentence-transformers` estiver instalado
e `RAG_EMBEDDINGS=1`, os trechos também recebem embeddings (bge-m3) e a busca combina os dois.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import unicodedata
from collections import Counter
from pathlib import Path

TOKEN = re.compile(r"[a-z0-9]+")
STOP = set("a o e de da do das dos em um uma uns umas que para com por no na nos nas se ao à os as é ou não como mais".split())


def _normalizar(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()


def tokenizar(texto: str) -> list[str]:
    return [t for t in TOKEN.findall(_normalizar(texto)) if t not in STOP and len(t) > 1]


def estimar_tokens(texto: str) -> int:
    return max(1, len(texto) // 4)


# ---------------------------------------------------------------- fatiamento
def fatiar_markdown(texto: str, alvo_tokens: int = 600, sobreposicao: int = 80) -> list[dict]:
    """Divide por cabeçalhos (##, ###) preservando o caminho; trechos grandes são subdivididos com sobreposição."""
    trechos: list[dict] = []
    caminho: list[str] = []
    buffer: list[str] = []

    def fechar():
        corpo = "\n".join(buffer).strip()
        buffer.clear()
        if not corpo:
            return
        titulo = " > ".join(caminho) or "(raiz)"
        palavras = corpo.split()
        passo = max(1, alvo_tokens * 3 // 4)         # ~4 chars/token ≈ 0,75 palavra/token
        i = 0
        while i < len(palavras):
            pedaco = " ".join(palavras[i:i + passo])
            trechos.append({"caminho": titulo, "texto": pedaco})
            if i + passo >= len(palavras):
                break
            i += passo - sobreposicao * 3 // 4
    for linha in texto.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)", linha)
        if m:
            fechar()
            nivel = len(m.group(1))
            caminho[:] = caminho[: nivel - 1] + [m.group(2).strip()]
        else:
            buffer.append(linha)
    fechar()
    return trechos


# ---------------------------------------------------------------- índice
class IndiceRAG:
    def __init__(self, caminho: str | Path = ":memory:"):
        self.caminho = str(caminho)
        self.con = sqlite3.connect(self.caminho, check_same_thread=False)
        self.con.execute("CREATE TABLE IF NOT EXISTS trechos (id INTEGER PRIMARY KEY, fonte TEXT, caminho TEXT, texto TEXT, embedding BLOB)")
        self.con.execute("CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT)")
        self._docs: list[dict] = []
        self._df: Counter = Counter()
        self._tf: list[Counter] = []
        self._len: list[int] = []
        self._embedder = None
        self._carregar()

    # ---- embeddings opcionais
    def _modelo(self):
        if self._embedder is None and os.getenv("RAG_EMBEDDINGS") == "1":
            try:
                from sentence_transformers import SentenceTransformer  # type: ignore
                self._embedder = SentenceTransformer(os.getenv("RAG_MODELO", "BAAI/bge-m3"))
            except Exception:
                self._embedder = False
        return self._embedder or None

    def _carregar(self) -> None:
        rows = self.con.execute("SELECT id, fonte, caminho, texto, embedding FROM trechos ORDER BY id").fetchall()
        self._docs = [{"id": r[0], "fonte": r[1], "caminho": r[2], "texto": r[3],
                       "embedding": json.loads(r[4]) if r[4] else None} for r in rows]
        self._tf, self._len, self._df = [], [], Counter()
        for d in self._docs:
            toks = tokenizar(d["caminho"] + " " + d["texto"])
            tf = Counter(toks)
            self._tf.append(tf)
            self._len.append(len(toks))
            self._df.update(tf.keys())

    def limpar(self, fonte: str | None = None) -> None:
        if fonte:
            self.con.execute("DELETE FROM trechos WHERE fonte=?", (fonte,))
        else:
            self.con.execute("DELETE FROM trechos")
        self.con.commit()
        self._carregar()

    def indexar(self, fonte: str, trechos: list[dict]) -> int:
        modelo = self._modelo()
        embs = None
        if modelo is not None and trechos:
            embs = modelo.encode([t["caminho"] + "\n" + t["texto"] for t in trechos], normalize_embeddings=True).tolist()
        self.con.executemany("INSERT INTO trechos (fonte, caminho, texto, embedding) VALUES (?,?,?,?)",
                             [(fonte, t["caminho"], t["texto"], json.dumps(embs[i]) if embs else None) for i, t in enumerate(trechos)])
        self.con.commit()
        self._carregar()
        return len(trechos)

    def meta(self, chave: str, valor: str | None = None) -> str | None:
        if valor is not None:
            self.con.execute("INSERT OR REPLACE INTO meta (chave, valor) VALUES (?,?)", (chave, valor))
            self.con.commit()
            return valor
        r = self.con.execute("SELECT valor FROM meta WHERE chave=?", (chave,)).fetchone()
        return r[0] if r else None

    def __len__(self) -> int:
        return len(self._docs)

    # ---- busca
    def buscar(self, consulta: str, k: int = 5, max_tokens: int = 3000) -> list[dict]:
        if not self._docs:
            return []
        q = tokenizar(consulta)
        n = len(self._docs)
        avg = sum(self._len) / n if n else 1
        k1, b = 1.5, 0.75
        pont = []
        for i, tf in enumerate(self._tf):
            s = 0.0
            for t in q:
                if t not in tf:
                    continue
                idf = math.log(1 + (n - self._df[t] + 0.5) / (self._df[t] + 0.5))
                f = tf[t]
                s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * self._len[i] / avg))
            pont.append(s)
        modelo = self._modelo()
        if modelo is not None and self._docs[0]["embedding"]:
            qe = modelo.encode([consulta], normalize_embeddings=True)[0].tolist()
            maxbm = max(pont) or 1.0
            for i, d in enumerate(self._docs):
                cos = sum(a * b_ for a, b_ in zip(qe, d["embedding"])) if d["embedding"] else 0.0
                pont[i] = 0.5 * pont[i] / maxbm + 0.5 * cos
        ordem = sorted(range(n), key=lambda i: -pont[i])
        out, usados = [], 0
        for i in ordem:
            if pont[i] <= 0 or len(out) >= k:
                break
            t = estimar_tokens(self._docs[i]["texto"])
            if usados + t > max_tokens:
                continue
            usados += t
            out.append({"caminho": self._docs[i]["caminho"], "texto": self._docs[i]["texto"], "pontuacao": round(pont[i], 3)})
        return out


def indexar_markdown(indice: IndiceRAG, fonte: str, texto: str) -> int:
    indice.limpar(fonte)
    return indice.indexar(fonte, fatiar_markdown(texto))
