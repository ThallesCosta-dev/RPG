"""Grid tático 2D: distâncias, custo de movimento (Dijkstra), linha de visão e áreas.

Fonte da verdade para movimento e visão (§6). Funções puras; o estado chega por `MapaLogico`.
Coordenadas: X = coluna, Y = linha, `tilemap[y][x]`.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

BLOQUEIA_MOVIMENTO = {"#", "P", "~"}   # parede, pilastra, água funda
BLOQUEIA_VISAO = {"#", "P"}
TERRENO_DIFICIL = {"^"}
COBERTURA = {"C"}
VIZINHOS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
SIMBOLOS_VALIDOS = set("#.P~^CD")

# Obstáculos dinâmicos (eventos por cima do tilemap): tipo → (bloqueia movimento, bloqueia visão)
OBSTACULOS = {
    "fogo_magico": (True, False),
    "parede_de_gelo": (True, True),
    "escombros": (False, False),      # vira terreno difícil
    "nevoa": (False, True),
}

Ponto = tuple[int, int]


@dataclass
class MapaLogico:
    tilemap: list[str]                                        # tilemap[y][x]
    ocupados: set[Ponto] = field(default_factory=set)         # tokens que bloqueiam
    obstaculos: dict[Ponto, str] = field(default_factory=dict)  # (x, y) → tipo

    @property
    def largura(self) -> int:
        return len(self.tilemap[0]) if self.tilemap else 0

    @property
    def altura(self) -> int:
        return len(self.tilemap)

    def dentro(self, x: int, y: int) -> bool:
        return 0 <= y < self.altura and 0 <= x < self.largura

    def simbolo(self, x: int, y: int) -> str:
        return self.tilemap[y][x]

    def parede(self, x: int, y: int) -> bool:
        """Célula que bloqueia movimento (parede, pilastra, água, obstáculo sólido)."""
        if not self.dentro(x, y):
            return True
        if self.tilemap[y][x] in BLOQUEIA_MOVIMENTO:
            return True
        obst = self.obstaculos.get((x, y))
        return bool(obst and OBSTACULOS.get(obst, (True, False))[0])

    def bloqueia_visao(self, x: int, y: int) -> bool:
        if not self.dentro(x, y):
            return True
        if self.tilemap[y][x] in BLOQUEIA_VISAO:
            return True
        obst = self.obstaculos.get((x, y))
        return bool(obst and OBSTACULOS.get(obst, (True, False))[1])

    def passavel(self, x: int, y: int) -> bool:
        return not self.parede(x, y) and (x, y) not in self.ocupados

    def multiplicador(self, x: int, y: int) -> int:
        if self.tilemap[y][x] in TERRENO_DIFICIL or self.obstaculos.get((x, y)) == "escombros":
            return 2
        return 1

    def cobertura(self, x: int, y: int) -> bool:
        return self.dentro(x, y) and self.tilemap[y][x] in COBERTURA


def validar_tilemap(tilemap: list[str]) -> list[str]:
    """Devolve a lista de problemas (vazia = ok)."""
    erros: list[str] = []
    if not tilemap:
        return ["tilemap vazio"]
    largura = len(tilemap[0])
    for y, linha in enumerate(tilemap):
        if len(linha) != largura:
            erros.append(f"linha {y} tem {len(linha)} colunas (esperado {largura})")
        for x, ch in enumerate(linha):
            if ch not in SIMBOLOS_VALIDOS:
                erros.append(f"símbolo inválido {ch!r} em ({x},{y})")
    return erros


def distancia_quadrados(a: Ponto, b: Ponto, metrica: str = "1-2-1-2") -> int:
    """Distância em quadrados ignorando obstáculos (para alcance de ataques e magias)."""
    dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
    diag, reto = min(dx, dy), abs(dx - dy)
    if metrica == "1-1-1":        # D&D 5e padrão: toda diagonal custa 1
        return diag + reto
    if metrica == "1-2-1-2":      # Tormenta20 / PF2e: diagonais alternam 1 e 2
        return reto + diag + diag // 2
    if metrica == "manhattan":    # sem diagonais
        return dx + dy
    raise ValueError(f"métrica desconhecida: {metrica}")


def custos_de_movimento(origem: Ponto, mapa: MapaLogico, metrica: str = "1-2-1-2",
                        limite: int | None = None) -> dict[Ponto, int]:
    """Dijkstra: menor custo (em quadrados) da origem até cada célula alcançável,
    respeitando paredes, tokens, quinas e terreno difícil."""
    return _dijkstra(tuple(origem), mapa, metrica, limite)[0]


def _dijkstra(origem: Ponto, mapa: MapaLogico, metrica: str, limite: int | None):
    inicio = (origem[0], origem[1], 0)       # estado = (x, y, paridade da próxima diagonal)
    dist = {inicio: 0}
    melhor: dict[Ponto, int] = {origem: 0}
    anterior: dict[tuple, tuple | None] = {inicio: None}
    fila = [(0, inicio)]
    while fila:
        custo, (x, y, par) = heapq.heappop(fila)
        if custo > dist[(x, y, par)]:
            continue
        for dx, dy in VIZINHOS:
            nx, ny = x + dx, y + dy
            diagonal = dx != 0 and dy != 0
            if not mapa.passavel(nx, ny):
                continue
            if diagonal and (metrica == "manhattan" or mapa.parede(nx, y) or mapa.parede(x, ny)):
                continue                      # não corta quina de parede
            passo, npar = 1, par
            if diagonal and metrica == "1-2-1-2":
                passo, npar = (2, 0) if par == 1 else (1, 1)
            novo = custo + passo * mapa.multiplicador(nx, ny)
            if limite is not None and novo > limite:
                continue
            estado = (nx, ny, npar)
            if novo < dist.get(estado, float("inf")):
                dist[estado] = novo
                anterior[estado] = (x, y, par)
                if novo < melhor.get((nx, ny), float("inf")):
                    melhor[(nx, ny)] = novo
                heapq.heappush(fila, (novo, estado))
    return melhor, dist, anterior


def caminho(origem: Ponto, destino: Ponto, mapa: MapaLogico, metrica: str = "1-2-1-2",
            limite: int | None = None) -> tuple[list[Ponto], int] | None:
    """Caminho de menor custo (lista de células, incluindo origem e destino) e o custo.
    None se o destino não for alcançável dentro do limite."""
    origem, destino = tuple(origem), tuple(destino)
    if origem == destino:
        return [origem], 0
    melhor, dist, anterior = _dijkstra(origem, mapa, metrica, limite)
    if destino not in melhor:
        return None
    custo = melhor[destino]
    estado = min((e for e in dist if (e[0], e[1]) == destino), key=lambda e: dist[e])
    pontos: list[Ponto] = []
    while estado is not None:
        pontos.append((estado[0], estado[1]))
        estado = anterior.get(estado)
    pontos.reverse()
    return pontos, custo


def mais_proximo_alcancavel(origem: Ponto, destino: Ponto, mapa: MapaLogico, metrica: str,
                            limite: int) -> Ponto:
    """Quando o destino está bloqueado ou longe: a célula alcançável mais perto do destino."""
    alc = custos_de_movimento(origem, mapa, metrica, limite)
    return min(alc, key=lambda p: (distancia_quadrados(p, destino, metrica), alc[p]))


def bresenham(a: Ponto, b: Ponto) -> list[Ponto]:
    (x0, y0), (x1, y1) = a, b
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err, pontos = dx + dy, []
    while True:
        pontos.append((x0, y0))
        if (x0, y0) == (x1, y1):
            return pontos
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def linha_de_visao(a: Ponto, b: Ponto, mapa: MapaLogico) -> bool:
    """Centro a centro. Sistemas com regra de cobertura própria podem usar um plugin."""
    return all(not mapa.bloqueia_visao(x, y) for x, y in bresenham(tuple(a), tuple(b))[1:-1])


def adjacentes(a: Ponto, b: Ponto) -> bool:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1])) == 1


# ------------------------------------------------------------------ áreas de efeito
def area_raio(centro: Ponto, raio: int, mapa: MapaLogico, metrica: str = "1-2-1-2") -> list[Ponto]:
    cx, cy = centro
    celulas = []
    for y in range(max(0, cy - raio), min(mapa.altura, cy + raio + 1)):
        for x in range(max(0, cx - raio), min(mapa.largura, cx + raio + 1)):
            if distancia_quadrados(centro, (x, y), metrica) <= raio and linha_de_visao(centro, (x, y), mapa):
                celulas.append((x, y))
    return celulas


def area_linha(origem: Ponto, direcao: Ponto, comprimento: int, mapa: MapaLogico) -> list[Ponto]:
    """Linha reta a partir da origem (exclusiva) até `comprimento` quadrados ou a primeira parede."""
    dx, dy = direcao
    if dx == dy == 0:
        return []
    n = max(abs(dx), abs(dy))
    fim = (origem[0] + round(dx / n * comprimento), origem[1] + round(dy / n * comprimento))
    celulas = []
    for p in bresenham(tuple(origem), fim)[1:]:
        if mapa.bloqueia_visao(*p):
            break
        celulas.append(p)
    return celulas


def area_cone(origem: Ponto, direcao: Ponto, comprimento: int, mapa: MapaLogico,
              metrica: str = "1-2-1-2") -> list[Ponto]:
    """Cone de ~90° a partir da origem na direção dada."""
    dx, dy = direcao
    if dx == dy == 0:
        return []
    ang0 = math.atan2(dy, dx)
    celulas = []
    for y in range(max(0, origem[1] - comprimento), min(mapa.altura, origem[1] + comprimento + 1)):
        for x in range(max(0, origem[0] - comprimento), min(mapa.largura, origem[0] + comprimento + 1)):
            if (x, y) == tuple(origem):
                continue
            if distancia_quadrados(origem, (x, y), metrica) > comprimento:
                continue
            ang = math.atan2(y - origem[1], x - origem[0])
            delta = abs((ang - ang0 + math.pi) % (2 * math.pi) - math.pi)
            if delta <= math.pi / 4 + 1e-9 and linha_de_visao(origem, (x, y), mapa):
                celulas.append((x, y))
    return celulas


def bfs_conectado(tilemap: list[str], origem: Ponto) -> set[Ponto]:
    """Células alcançáveis a partir da origem (sem diagonais). Usado pelo gerador de mapas."""
    mapa = MapaLogico(tilemap)
    vistos, fila = {tuple(origem)}, [tuple(origem)]
    while fila:
        x, y = fila.pop()
        for dx, dy in VIZINHOS[:4]:
            nx, ny = x + dx, y + dy
            if (nx, ny) not in vistos and not mapa.parede(nx, ny):
                vistos.add((nx, ny))
                fila.append((nx, ny))
    return vistos
