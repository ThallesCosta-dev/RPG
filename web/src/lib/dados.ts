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

// Mesma gramática do servidor (rules_engine.TERMO): termos "+2d6", "-1", "4d6kh3", contíguos, sem espaços.
const TERMO = /([+-]?)(?:(\d*)d(\d+)(?:(kh|kl)(\d+))?|(\d+))/gy

/** Validação local de uma expressão de dados (ex.: "1d8+3"). Espelha `expressao_valida` do servidor. */
export function expressaoValida(expressao: string): boolean {
  if (typeof expressao !== "string" || expressao.length > 64) return false
  const expr = expressao.replace(/\s/g, "").toLowerCase()
  if (!expr) return false
  TERMO.lastIndex = 0
  let pos = 0
  let n = 0
  let m: RegExpExecArray | null
  while (pos < expr.length) {
    TERMO.lastIndex = pos
    m = TERMO.exec(expr)
    if (!m || m.index !== pos || m[0].length === 0) return false
    pos = TERMO.lastIndex
    n += 1
    if (m[3]) {
      const qtd = Number(m[2] || 1)
      const faces = Number(m[3])
      if (!(qtd >= 1 && qtd <= 100 && faces >= 2 && faces <= 1000)) return false
    }
  }
  return n > 0
}
