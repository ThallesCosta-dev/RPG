import type { Evento } from "../types"

// Barramento simples: a narração emite eventos, o renderizador do grid anima.

export type OuvinteAnimacao = (ev: Evento, instantaneo: boolean) => void

const ouvintes = new Set<OuvinteAnimacao>()

export const barramento = {
  on(cb: OuvinteAnimacao): () => void {
    ouvintes.add(cb)
    return () => ouvintes.delete(cb)
  },
  emitir(ev: Evento, instantaneo = false): void {
    for (const cb of ouvintes) cb(ev, instantaneo)
  },
}

export function reduzMovimento(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches
}
