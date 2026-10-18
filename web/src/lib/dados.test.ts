import { describe, expect, it } from "vitest"
import { expressaoValida, expressaoDeAtaque } from "./dados"

describe("expressaoValida (espelha rules_engine.expressao_valida)", () => {
  it("aceita expressões comuns de dano e ataque", () => {
    for (const e of ["1d8+3", "2d6", "1d20+8", "4d6kh3", "2d10kl1-1", "3", "1d8 + 3", "d6", "1D8+2"]) expect(expressaoValida(e), e).toBe(true)
  })
  it("rejeita lixo, termos soltos e dados fora dos limites", () => {
    for (const e of ["", "2d6+x", "1d8+", "+", "abc", "1d1", "101d6", "1d1001", "1d6 3", "1d6++2"]) expect(expressaoValida(e), e).toBe(false)
  })
  it("limita o tamanho a 64 caracteres", () => {
    expect(expressaoValida("1d6+".repeat(16) + "1")).toBe(true)
    expect(expressaoValida("1d6+".repeat(17) + "1")).toBe(false)
  })
})

describe("expressaoDeAtaque", () => {
  it("substitui {bonus} e normaliza o sinal", () => {
    expect(expressaoDeAtaque("1d20+{bonus}", 8)).toBe("1d20+8")
    expect(expressaoDeAtaque("1d20+{bonus}", -2)).toBe("1d20-2")
  })
})
