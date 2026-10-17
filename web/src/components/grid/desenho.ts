import { Graphics } from "pixi.js"
import type { Coord } from "../../types"

// Camada 0 estilizada: cores por tipo de tile, usadas quando a cena ainda não tem imagem.
const CORES_TILE: Record<string, number> = {
  "#": 0x1f1a17,
  ".": 0x3a332c,
  P: 0x5a5047,
  "~": 0x1e4d7a,
  "^": 0x4a3f2a,
  C: 0x5c4a30,
  D: 0x7a5a2a,
}

export function desenharTile(g: Graphics, simbolo: string, x: number, y: number, T: number): void {
  const px = x * T
  const py = y * T
  const cor = CORES_TILE[simbolo] ?? 0x3a332c
  g.rect(px, py, T, T).fill(cor)
  switch (simbolo) {
    case "#":
      // argamassa sutil
      g.rect(px + 2, py + 2, T - 4, T - 4).stroke({ width: 1, color: 0x000000, alpha: 0.35 })
      break
    case "P":
      g.circle(px + T / 2, py + T / 2, T * 0.32).fill(0x7a6d62).stroke({ width: 2, color: 0x2a2420 })
      break
    case "~":
      for (let i = 0; i < 3; i++) {
        const yy = py + T * (0.25 + i * 0.25)
        g.moveTo(px + 6, yy).lineTo(px + T / 2, yy - 4).lineTo(px + T - 6, yy).stroke({ width: 1.5, color: 0x6fb3e8, alpha: 0.7 })
      }
      break
    case "^":
      // hachura diagonal
      for (let d = -T; d < T; d += 8) {
        g.moveTo(px + Math.max(0, d), py + Math.max(0, -d)).lineTo(px + Math.min(T, d + T), py + Math.min(T, T - d))
      }
      g.stroke({ width: 1, color: 0xc9a86a, alpha: 0.45 })
      break
    case "C":
      g.rect(px + 6, py + 10, T - 12, T - 20).fill(0x8a6f45).stroke({ width: 1, color: 0x2a2015 })
      g.rect(px + 10, py + 14, T - 20, 6).fill({ color: 0x000000, alpha: 0.25 })
      break
    case "D":
      g.rect(px + 4, py + 4, T - 8, T - 8).stroke({ width: 3, color: 0x3a2a14 })
      g.circle(px + T * 0.7, py + T / 2, 2.5).fill(0xe0c070)
      break
    default:
      // chão: leve textura
      g.circle(px + T * 0.3, py + T * 0.7, 1).fill({ color: 0x000000, alpha: 0.2 })
      break
  }
}

export function desenharObstaculo(g: Graphics, tipo: string, x: number, y: number, T: number): void {
  const px = x * T
  const py = y * T
  const t = tipo.toLowerCase()
  if (t.includes("fogo") || t.includes("chama")) {
    g.rect(px + 2, py + 2, T - 4, T - 4).fill({ color: 0xf97316, alpha: 0.75 })
    g.moveTo(px + T * 0.25, py + T * 0.85)
      .lineTo(px + T * 0.4, py + T * 0.3)
      .lineTo(px + T * 0.5, py + T * 0.6)
      .lineTo(px + T * 0.62, py + T * 0.2)
      .lineTo(px + T * 0.78, py + T * 0.85)
      .closePath()
      .fill({ color: 0xfde047, alpha: 0.85 })
  } else if (t.includes("gelo") || t.includes("ice")) {
    g.rect(px + 2, py + 2, T - 4, T - 4).fill({ color: 0x93c5fd, alpha: 0.7 }).stroke({ width: 2, color: 0xe0f2fe })
  } else if (t.includes("nevoa") || t.includes("névoa") || t.includes("fumaca")) {
    g.circle(px + T / 2, py + T / 2, T * 0.45).fill({ color: 0xcbd5e1, alpha: 0.5 })
  } else {
    g.rect(px + 2, py + 2, T - 4, T - 4).fill({ color: 0xa855f7, alpha: 0.6 })
  }
}

/** Linha tracejada por uma sequência de pontos (em pixels). */
export function linhaTracejada(g: Graphics, pontos: [number, number][], traco = 8, vao = 6): void {
  for (let i = 0; i < pontos.length - 1; i++) {
    const [x0, y0] = pontos[i]
    const [x1, y1] = pontos[i + 1]
    const dx = x1 - x0
    const dy = y1 - y0
    const comp = Math.hypot(dx, dy)
    if (comp === 0) continue
    const ux = dx / comp
    const uy = dy / comp
    let d = 0
    while (d < comp) {
      const fim = Math.min(comp, d + traco)
      g.moveTo(x0 + ux * d, y0 + uy * d).lineTo(x0 + ux * fim, y0 + uy * fim)
      d += traco + vao
    }
  }
}

export const centro = (c: Coord, T: number): [number, number] => [(c[0] + 0.5) * T, (c[1] + 0.5) * T]
