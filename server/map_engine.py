"""Battlemaps alinhados ao grid (§12): tilemap lógico primeiro, imagem depois.

1. gerador procedural (BSP para masmorras, autômato celular para cavernas, modelos para taverna/rua/floresta/salão);
2. validação (dimensões, entradas conectadas por BFS, área de chegada livre);
3. imagem de controle (mapa de segmentação por tipo de tile, 64 px por quadrado);
4. ComfyUI headless (opcional; `COMFYUI_URL`) com um workflow carregado de `comfyui_workflow.json`;
5. cache por hash(tilemap + prompt + seed).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import struct
import zlib
from pathlib import Path

from . import grid_math as gm

log = logging.getLogger("ai_vtt.mapas")
DIR_MAPAS = Path(os.getenv("DIR_DADOS", "data")) / "mapas_cache"

CORES_CONTROLE = {"#": (40, 40, 40), ".": (200, 190, 160), "P": (90, 90, 90), "~": (60, 100, 200), "w": (120, 170, 220),
                  "^": (120, 140, 80), "C": (150, 110, 70), "D": (170, 120, 60)}
ESTILO_TEMA = {"medieval": "fantasy medieval, hand painted, parchment tones",
               "cyberpunk": "neon lit sci-fi interior, metal floor panels, holographic accents",
               "terror": "gloomy, desaturated, 1920s, cracked wood and stone, fog"}


# ====================================================================== geração procedural
def _vazio(largura: int, altura: int, preencher: str = "#") -> list[list[str]]:
    return [[preencher] * largura for _ in range(altura)]


def _para_strings(grade: list[list[str]]) -> list[str]:
    return ["".join(l) for l in grade]


def _bsp(largura: int, altura: int, rng: random.Random, elementos: set[str]) -> list[list[str]]:
    g = _vazio(largura, altura)
    salas: list[tuple[int, int, int, int]] = []

    def dividir(x, y, w, h, prof):
        if prof == 0 or (w < 9 and h < 9) or rng.random() < 0.2 and prof < 3:
            sw, sh = rng.randint(max(3, w // 2), max(3, w - 2)), rng.randint(max(3, h // 2), max(3, h - 2))
            sx, sy = x + rng.randint(1, max(1, w - sw - 1)), y + rng.randint(1, max(1, h - sh - 1))
            for yy in range(sy, min(sy + sh, altura - 1)):
                for xx in range(sx, min(sx + sw, largura - 1)):
                    g[yy][xx] = "."
            salas.append((sx, sy, sw, sh))
            return
        if w >= h:
            corte = rng.randint(w // 3, 2 * w // 3)
            dividir(x, y, corte, h, prof - 1)
            dividir(x + corte, y, w - corte, h, prof - 1)
        else:
            corte = rng.randint(h // 3, 2 * h // 3)
            dividir(x, y, w, corte, prof - 1)
            dividir(x, y + corte, w, h - corte, prof - 1)

    dividir(1, 1, largura - 2, altura - 2, 3)
    # corredores ligando centros consecutivos
    for (ax, ay, aw, ah), (bx, by, bw, bh) in zip(salas, salas[1:]):
        x1, y1, x2, y2 = ax + aw // 2, ay + ah // 2, bx + bw // 2, by + bh // 2
        for xx in range(min(x1, x2), max(x1, x2) + 1):
            g[y1][xx] = "." if g[y1][xx] == "#" else g[y1][xx]
        for yy in range(min(y1, y2), max(y1, y2) + 1):
            g[yy][x2] = "." if g[yy][x2] == "#" else g[yy][x2]
    for sx, sy, sw, sh in salas:
        if "pilastras" in elementos and sw >= 6 and sh >= 5:
            for xx, yy in ((sx + 1, sy + 1), (sx + sw - 2, sy + 1), (sx + 1, sy + sh - 2), (sx + sw - 2, sy + sh - 2)):
                if 0 < xx < largura - 1 and 0 < yy < altura - 1:
                    g[yy][xx] = "P"
        if "cobertura" in elementos and sw >= 5:
            g[sy + sh // 2][sx + sw // 2] = "C"
        if "agua" in elementos and sw >= 7 and sh >= 5 and rng.random() < 0.6:
            for yy in range(sy + 1, sy + 3):
                for xx in range(sx + sw - 4, sx + sw - 2):
                    g[yy][xx] = "~"
        if "terreno_dificil" in elementos and rng.random() < 0.5:
            for yy in range(sy, min(sy + 2, altura - 1)):
                for xx in range(sx, min(sx + 3, largura - 1)):
                    if g[yy][xx] == ".":
                        g[yy][xx] = "^"
    return g


def _caverna(largura: int, altura: int, rng: random.Random, elementos: set[str]) -> list[list[str]]:
    g = [["#" if (x in (0, largura - 1) or y in (0, altura - 1) or rng.random() < 0.42) else "." for x in range(largura)] for y in range(altura)]
    for _ in range(5):
        novo = [l[:] for l in g]
        for y in range(1, altura - 1):
            for x in range(1, largura - 1):
                n = sum(g[y + dy][x + dx] == "#" for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0))
                novo[y][x] = "#" if n >= 5 else "."
        g = novo
    # fica só o maior componente de chão
    melhor: set = set()
    vistos: set = set()
    for y in range(altura):
        for x in range(largura):
            if g[y][x] == "." and (x, y) not in vistos:
                comp = gm.bfs_conectado(_para_strings(g), (x, y))
                vistos |= comp
                if len(comp) > len(melhor):
                    melhor = comp
    for y in range(altura):
        for x in range(largura):
            if g[y][x] == "." and (x, y) not in melhor:
                g[y][x] = "#"
    chao = sorted(melhor)
    if "agua" in elementos and chao:
        cx, cy = rng.choice(chao)
        for (x, y) in chao:
            if abs(x - cx) <= 2 and abs(y - cy) <= 1:
                g[y][x] = "~"
    if "terreno_dificil" in elementos:
        for (x, y) in chao:
            if g[y][x] == "." and rng.random() < 0.12:
                g[y][x] = "^"
    if "pilastras" in elementos:
        for (x, y) in chao:
            if g[y][x] == "." and rng.random() < 0.03:
                g[y][x] = "P"
    return g


def _modelo(tipo: str, largura: int, altura: int, rng: random.Random, elementos: set[str]) -> list[list[str]]:
    if tipo == "floresta":
        g = [["." for _ in range(largura)] for _ in range(altura)]
        for y in range(altura):
            for x in range(largura):
                borda = min(x, y, largura - 1 - x, altura - 1 - y)
                r = rng.random()
                if borda <= 1 and r < 0.6:
                    g[y][x] = "P"                         # árvores
                elif borda <= 3 and r < 0.35:
                    g[y][x] = "^"
                elif r < 0.05:
                    g[y][x] = "P"
                elif r < 0.12:
                    g[y][x] = "^"
        if "agua" in elementos:
            for y in range(altura):
                x = largura // 2 + int(2 * ((y % 4) - 1.5))
                g[y][x] = "~"
        return g
    g = _vazio(largura, altura)
    for y in range(1, altura - 1):
        for x in range(1, largura - 1):
            g[y][x] = "."
    if tipo == "taverna":
        for y in range(2, altura - 3, 3):
            for x in range(2, largura - 3, 5):
                g[y][x] = g[y][x + 1] = "C"               # mesas
        for x in range(largura - 5, largura - 1):
            g[1][x] = "C"                                 # balcão
        g[altura - 1][largura // 2] = g[altura - 1][largura // 2 + 1] = "D"
    elif tipo == "rua":
        for y in range(1, altura - 1):
            for x in range(1, largura - 1):
                if y < 3 or y > altura - 4:
                    g[y][x] = "#" if rng.random() < 0.8 else "D"
        for x in range(3, largura - 3, 6):
            g[altura // 2][x] = "C"
        g[altura // 2][0] = g[altura // 2][largura - 1] = "D"
    else:  # salao
        for y in (2, altura - 3):
            for x in range(3, largura - 3, 5):
                g[y][x] = "P"
        if "cobertura" in elementos:
            g[altura // 2][largura // 2] = g[altura // 2][largura // 2 + 1] = "C"
        if "agua" in elementos:
            for y in range(altura - 6, altura - 2):
                g[y][largura // 2 + 2] = g[y][largura // 2 + 3] = "~"
        g[altura - 1][largura // 2] = g[altura - 1][largura // 2 + 1] = "D"
        g[altura // 2][0] = "D"
    return g


def gerar_tilemap(tipo: str, largura: int = 20, altura: int = 15, elementos: list[str] | None = None,
                  seed: int | str | None = None) -> tuple[list[str], tuple[int, int]]:
    """Devolve (tilemap, entrada). Sempre jogável: tenta até 20 sementes e valida conectividade."""
    largura, altura = max(10, min(40, int(largura))), max(8, min(30, int(altura)))
    el = set(elementos or [])
    base = seed if isinstance(seed, int) else int(hashlib.sha1(str(seed or tipo).encode()).hexdigest(), 16) % (2 ** 31)
    for tentativa in range(20):
        rng = random.Random(base + tentativa)
        if tipo == "masmorra":
            g = _bsp(largura, altura, rng, el)
        elif tipo == "caverna":
            g = _caverna(largura, altura, rng, el)
        else:
            g = _modelo(tipo, largura, altura, rng, el)
        tilemap = _para_strings(g)
        entrada = _escolher_entrada(tilemap)
        if entrada and _validar(tilemap, entrada, "varias_entradas" in el):
            if tipo in ("masmorra", "caverna"):
                _abrir_porta(g, entrada)
                tilemap = _para_strings(g)
            return tilemap, entrada
    # fallback: salão vazio
    g = _modelo("salao", largura, altura, random.Random(base), set())
    tilemap = _para_strings(g)
    return tilemap, _escolher_entrada(tilemap) or (1, 1)


def _escolher_entrada(tilemap: list[str]) -> tuple[int, int] | None:
    altura, largura = len(tilemap), len(tilemap[0])
    mapa = gm.MapaLogico(tilemap)
    for y in range(altura - 2, 0, -1):                  # perto da borda inferior, centro
        for dx in range(largura // 2):
            for x in (largura // 2 - dx, largura // 2 + dx):
                if 0 < x < largura - 1 and mapa.passavel(x, y) and tilemap[y][x] == ".":
                    return (x, y)
    return None


def _abrir_porta(g: list[list[str]], entrada: tuple[int, int]) -> None:
    x, y = entrada
    altura = len(g)
    for yy in range(y + 1, altura):
        if g[yy][x] == "#":
            g[yy][x] = "D"
            break
        if yy == altura - 1:
            g[yy][x] = "D"


def _validar(tilemap: list[str], entrada: tuple[int, int], varias: bool) -> bool:
    if gm.validar_tilemap(tilemap):
        return False
    chao = sum(l.count(".") for l in tilemap)
    if chao < len(tilemap) * len(tilemap[0]) * 0.25:
        return False
    comp = gm.bfs_conectado(tilemap, entrada)
    if len(comp) < chao * 0.8:
        return False
    livres = [c for c in comp if gm.distancia_quadrados(c, entrada) <= 3]
    return len(livres) >= 6


# ====================================================================== imagem de controle e PNG
def _png(largura: int, altura: int, linhas_rgb: list[bytes]) -> bytes:
    def chunk(tipo: bytes, dados: bytes) -> bytes:
        return struct.pack(">I", len(dados)) + tipo + dados + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + l for l in linhas_rgb)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", largura, altura, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def imagem_controle(tilemap: list[str], px: int = 64) -> bytes:
    """Mapa de segmentação por tipo de tile (PNG), para o ControlNet."""
    largura, altura = len(tilemap[0]) * px, len(tilemap) * px
    linhas = []
    for y in range(altura):
        linha = bytearray()
        fila = tilemap[y // px]
        for x in range(largura):
            r, g, b = CORES_CONTROLE.get(fila[x // px], (0, 0, 0))
            linha += bytes((r, g, b))
        linhas.append(bytes(linha))
    return _png(largura, altura, linhas)


def chave_cache(tilemap: list[str], prompt: str, seed: int) -> str:
    return hashlib.sha256(("\n".join(tilemap) + "|" + prompt + "|" + str(seed)).encode()).hexdigest()[:24]


def prompt_imagem(descricao: str, tema: str) -> str:
    return f"top-down battlemap, {descricao}, {ESTILO_TEMA.get(tema, ESTILO_TEMA['medieval'])}, no text, no grid, uniform lighting"


# ====================================================================== ComfyUI
def gerar_imagem_comfyui(tilemap: list[str], descricao: str, tema: str, seed: int = 0) -> str | None:
    """Executado em thread pelo GPU Scheduler (faixa pesada). Devolve a URL pública da imagem ou None."""
    url = os.getenv("COMFYUI_URL", "").rstrip("/")
    if not url:
        return None
    import httpx
    DIR_MAPAS.mkdir(parents=True, exist_ok=True)
    prompt = prompt_imagem(descricao, tema)
    chave = chave_cache(tilemap, prompt, seed)
    destino = DIR_MAPAS / f"{chave}.png"
    if destino.exists():
        return f"/mapas/{chave}.png"
    wf_path = Path(os.getenv("COMFYUI_WORKFLOW", "comfyui_workflow.json"))
    if not wf_path.exists():
        log.warning("COMFYUI_WORKFLOW não encontrado: %s", wf_path)
        return None
    controle = imagem_controle(tilemap)
    with httpx.Client(timeout=600) as cli:
        up = cli.post(f"{url}/upload/image", files={"image": (f"controle_{chave}.png", controle, "image/png")}, data={"overwrite": "true"})
        up.raise_for_status()
        nome_controle = up.json()["name"]
        wf = wf_path.read_text(encoding="utf-8")
        wf = (wf.replace("{{PROMPT}}", json.dumps(prompt)[1:-1]).replace("{{CONTROLE}}", nome_controle)
                .replace("{{SEED}}", str(seed)).replace("{{LARGURA}}", str(len(tilemap[0]) * 64)).replace("{{ALTURA}}", str(len(tilemap) * 64)))
        r = cli.post(f"{url}/prompt", json={"prompt": json.loads(wf)})
        r.raise_for_status()
        pid = r.json()["prompt_id"]
        import time
        for _ in range(600):
            time.sleep(1)
            h = cli.get(f"{url}/history/{pid}").json()
            if pid in h:
                saidas = h[pid].get("outputs", {})
                for no in saidas.values():
                    for img in no.get("images", []):
                        dados = cli.get(f"{url}/view", params={"filename": img["filename"], "subfolder": img.get("subfolder", ""), "type": img.get("type", "output")}).content
                        destino.write_bytes(dados)
                        return f"/mapas/{chave}.png"
                return None
    return None
