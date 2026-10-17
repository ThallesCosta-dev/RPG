import type { Rolagem } from "../types"

export const DADOS_RAPIDOS = [4, 6, 8, 10, 12, 20, 100] as const

/** Slot especial para os dados rápidos (não vinculado a nenhum slot do sistema). */
export const SLOT_LIVRE_DADO = "livre_dado"

/** Substitui `{bonus}` na expressão do sistema (ex.: "1d20+{bonus}") e normaliza "+-". */
export function expressaoDeAtaque(modelo: string, bonus: number): string {
  return modelo.replace("{bonus}", String(bonus)).replace("+-", "-")
}

/** Resumo curto de uma rolagem para a Crônica. */
export function resumoRolagem(r: Rolagem): string {
  const dados = r.termos.flatMap((t) => t.dados ?? [])
  return dados.length > 0 ? `${r.expressao} = ${r.total} [${dados.join(", ")}]` : `${r.expressao} = ${r.total}`
}
