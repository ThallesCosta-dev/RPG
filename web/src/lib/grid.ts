import type { CelulaAlcance, Coord, MetricaDiagonal } from "../types"

export const TAMANHO_QUADRADO = 48

export const BLOQUEIA_MOVIMENTO = new Set(["#", "P", "~"])
export const TERRENO_DIFICIL = new Set(["^"])

const VIZINHOS: Coord[] = [
  [1, 0], [-1, 0], [0, 1], [0, -1],
  [1, 1], [1, -1], [-1, 1], [-1, -1],
]

export const chave = (x: number, y: number): string => `${x},${y}`

/** Distância em quadrados ignorando obstáculos (§6.3). */
export function distanciaQuadrados(a: Coord, b: Coord, metrica: MetricaDiagonal = "1-2-1-2"): number {
  const dx = Math.abs(a[0] - b[0])
  const dy = Math.abs(a[1] - b[1])
  const diag = Math.min(dx, dy)
  const reto = Math.abs(dx - dy)
  switch (metrica) {
    case "1-1-1":
      return diag + reto
    case "1-2-1-2":
      return reto + diag + Math.floor(diag / 2)
    case "manhattan":
      return dx + dy
    default:
      throw new Error(`métrica desconhecida: ${String(metrica)}`)
  }
}

export function dentro(tilemap: string[], x: number, y: number): boolean {
  return y >= 0 && y < tilemap.length && x >= 0 && x < (tilemap[0]?.length ?? 0)
}

export function parede(tilemap: string[], x: number, y: number): boolean {
  return !dentro(tilemap, x, y) || BLOQUEIA_MOVIMENTO.has(tilemap[y][x])
}

export function multiplicador(tilemap: string[], x: number, y: number): number {
  return TERRENO_DIFICIL.has(tilemap[y][x]) ? 2 : 1
}

export interface CelulaCusto {
  custo: number
  caminho: Coord[] // da origem (inclusa) até a célula
}

/**
 * Dijkstra portado de grid_math.py: menor custo da origem a cada célula alcançável,
 * respeitando paredes, tokens, quinas e terreno difícil. Usado pelo mock;
 * o servidor é quem valida de verdade.
 */
export function custosDeMovimento(
  origem: Coord,
  tilemap: string[],
  ocupados: Set<string>,
  metrica: MetricaDiagonal = "1-2-1-2",
  limite: number | null = null,
): Map<string, CelulaCusto> {
  type Estado = { x: number; y: number; par: number }
  const chaveEstado = (e: Estado) => `${e.x},${e.y},${e.par}`
  const inicio: Estado = { x: origem[0], y: origem[1], par: 0 }
  const dist = new Map<string, number>([[chaveEstado(inicio), 0]])
  const anterior = new Map<string, Estado>()
  const melhor = new Map<string, { custo: number; estado: Estado }>([
    [chave(origem[0], origem[1]), { custo: 0, estado: inicio }],
  ])
  const fila: { custo: number; estado: Estado }[] = [{ custo: 0, estado: inicio }]
  const passavel = (x: number, y: number) => !parede(tilemap, x, y) && !ocupados.has(chave(x, y))

  while (fila.length > 0) {
    fila.sort((a, b) => a.custo - b.custo)
    const { custo, estado } = fila.shift() as { custo: number; estado: Estado }
    if (custo > (dist.get(chaveEstado(estado)) ?? Infinity)) continue
    for (const [dx, dy] of VIZINHOS) {
      const nx = estado.x + dx
      const ny = estado.y + dy
      const diagonal = dx !== 0 && dy !== 0
      if (!passavel(nx, ny)) continue
      if (diagonal && (metrica === "manhattan" || parede(tilemap, nx, estado.y) || parede(tilemap, estado.x, ny))) continue
      let passo = 1
      let npar = estado.par
      if (diagonal && metrica === "1-2-1-2") {
        if (estado.par === 1) {
          passo = 2
          npar = 0
        } else {
          passo = 1
          npar = 1
        }
      }
      const novo = custo + passo * multiplicador(tilemap, nx, ny)
      if (limite !== null && novo > limite) continue
      const prox: Estado = { x: nx, y: ny, par: npar }
      const k = chaveEstado(prox)
      if (novo < (dist.get(k) ?? Infinity)) {
        dist.set(k, novo)
        anterior.set(k, estado)
        const atual = melhor.get(chave(nx, ny))
        if (!atual || novo < atual.custo) melhor.set(chave(nx, ny), { custo: novo, estado: prox })
        fila.push({ custo: novo, estado: prox })
      }
    }
  }

  const resultado = new Map<string, CelulaCusto>()
  for (const [k, { custo, estado }] of melhor) {
    const caminho: Coord[] = []
    let e: Estado | undefined = estado
    while (e) {
      caminho.push([e.x, e.y])
      e = anterior.get(chaveEstado(e))
    }
    caminho.reverse()
    resultado.set(k, { custo, caminho })
  }
  return resultado
}

/** Converte a lista `alcance.celulas` do servidor num mapa "x,y" → custo. */
export function mapaDeAlcance(celulas: CelulaAlcance[]): Map<string, number> {
  const m = new Map<string, number>()
  for (const [x, y, c] of celulas) m.set(chave(x, y), c)
  return m
}
