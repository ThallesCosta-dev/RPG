import type { Personagem } from "../types"

const BORDA: Record<string, string> = { aliado: "#4ade80", inimigo: "#f87171", neutro: "#facc15" }

/** Ícone redondo do token, igual ao do grid. */
export default function TokenAvatar({ p, tamanho = 36 }: { p: Personagem; tamanho?: number }) {
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-full select-none"
      style={{
        width: tamanho,
        height: tamanho,
        background: p.cor || "#666",
        border: `3px solid ${BORDA[p.faccao] ?? "#aaa"}`,
        fontSize: tamanho * 0.5,
        opacity: p.caido ? 0.5 : 1,
        textShadow: "0 1px 2px #000",
      }}
      title={`${p.nome} (${p.faccao})`}
      aria-hidden
    >
      {p.icone || p.nome.charAt(0).toUpperCase()}
    </span>
  )
}
