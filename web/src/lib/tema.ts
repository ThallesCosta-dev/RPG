import type { Tema } from "../types"
import { storage } from "./storage"

export const TEMAS: Tema[] = ["medieval", "cyberpunk", "terror"]

/** Mapeia o `tema` livre da cena/campanha para um dos três temas do design system. */
export function temaDe(valor: string | null | undefined): Tema {
  const v = (valor ?? "").toLowerCase()
  if ((TEMAS as string[]).includes(v)) return v as Tema
  if (/cyber|sci|neon|futur|tech/.test(v)) return "cyberpunk"
  if (/terror|horror|cthulhu|ordem|dossi|invest/.test(v)) return "terror"
  return "medieval"
}

export function aplicarTema(tema: Tema): void {
  document.documentElement.dataset.theme = tema
}

/** Tema efetivo: override do usuário (localStorage) ou o sugerido pela cena/campanha. */
export function temaEfetivo(sugerido: string | null | undefined): Tema {
  const override = storage.tema()
  if (override && (TEMAS as string[]).includes(override)) return override as Tema
  return temaDe(sugerido)
}
