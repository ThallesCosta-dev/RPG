import { describe, expect, it } from "vitest"
import { custosDeMovimento, distanciaQuadrados } from "./grid"

describe("distanciaQuadrados", () => {
  it("1-1-1: toda diagonal custa 1", () => {
    expect(distanciaQuadrados([0, 0], [3, 3], "1-1-1")).toBe(3)
    expect(distanciaQuadrados([0, 0], [5, 2], "1-1-1")).toBe(5)
  })
  it("1-2-1-2: diagonais alternam 1 e 2", () => {
    expect(distanciaQuadrados([0, 0], [1, 1], "1-2-1-2")).toBe(1)
    expect(distanciaQuadrados([0, 0], [2, 2], "1-2-1-2")).toBe(3)
    expect(distanciaQuadrados([0, 0], [3, 3], "1-2-1-2")).toBe(4)
    expect(distanciaQuadrados([0, 0], [5, 2], "1-2-1-2")).toBe(6)
  })
  it("manhattan: sem diagonais", () => {
    expect(distanciaQuadrados([0, 0], [3, 3], "manhattan")).toBe(6)
    expect(distanciaQuadrados([2, 9], [6, 5], "manhattan")).toBe(8)
  })
})

describe("custosDeMovimento", () => {
  const mapa = ["#####", "#...#", "#.#.#", "#..^#", "#####"]
  it("respeita paredes, quinas e terreno difícil", () => {
    const custos = custosDeMovimento([1, 1], mapa, new Set(), "1-1-1")
    expect(custos.get("1,1")?.custo).toBe(0)
    expect(custos.get("3,1")?.custo).toBe(2)
    expect(custos.has("2,2")).toBe(false)
    // (3,3) é terreno difícil e a diagonal por (2,2) corta quina: 1+1+1 + 2 = 5
    expect(custos.get("3,3")?.custo).toBe(5)
  })
  it("não atravessa tokens", () => {
    const custos = custosDeMovimento([1, 1], mapa, new Set(["2,1"]), "manhattan")
    expect(custos.has("2,1")).toBe(false)
    // contorna por baixo passando pelo terreno difícil (3,3): 1+1+1+2+1+1 = 7
    expect(custos.get("3,1")?.custo).toBe(7)
  })
})
