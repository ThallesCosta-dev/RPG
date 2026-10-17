/** Converte uma cor CSS (#rgb, #rrggbb, #rrggbbaa, rgb(), rgba()) em {cor numérica, alpha}. */
export function lerCor(css: string, padrao = 0xffffff): { cor: number; alpha: number } {
  const s = css.trim()
  if (s.startsWith("#")) {
    let hex = s.slice(1)
    if (hex.length === 3 || hex.length === 4) hex = hex.split("").map((c) => c + c).join("")
    const cor = parseInt(hex.slice(0, 6), 16)
    const alpha = hex.length === 8 ? parseInt(hex.slice(6, 8), 16) / 255 : 1
    return Number.isNaN(cor) ? { cor: padrao, alpha: 1 } : { cor, alpha }
  }
  const m = s.match(/rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)(?:[\s,/]+([\d.]+))?\s*\)/)
  if (m) {
    const cor = (Number(m[1]) << 16) | (Number(m[2]) << 8) | Number(m[3])
    return { cor, alpha: m[4] !== undefined ? Number(m[4]) : 1 }
  }
  return { cor: padrao, alpha: 1 }
}

/** Lê uma CSS variable do <html>. */
export function varTema(nome: string, padrao = ""): string {
  if (typeof document === "undefined") return padrao
  const v = getComputedStyle(document.documentElement).getPropertyValue(nome)
  return v.trim() || padrao
}

export function corDeFaccao(faccao: string): number {
  if (faccao === "aliado") return 0x4ade80
  if (faccao === "inimigo") return 0xf87171
  return 0xfacc15
}
