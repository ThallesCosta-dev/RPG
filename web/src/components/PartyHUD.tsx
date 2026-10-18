import { useState } from "react"
import { useSala } from "../store/useSala"
import type { BarraStatus, Personagem } from "../types"
import TokenAvatar from "./TokenAvatar"
import Modal from "./Modal"
import FichaPanel from "./FichaPanel"

const ICONE_BARRA: Record<string, string> = {
  "--status-vida": "♥",
  "--status-recurso": "◆",
  "--status-sanidade": "☗",
}

function Barras({ p, barras }: { p: Personagem; barras: BarraStatus[] }) {
  return (
    <div className="space-y-1">
      {barras.map((b) => {
        const v = p.barras[b.id]
        if (!v) return null
        const frac = v.max > 0 ? Math.max(0, Math.min(1, v.atual / v.max)) : 0
        const cor = b.cor_token.startsWith("--") ? `var(${b.cor_token})` : b.cor_token
        return (
          <div key={b.id} title={b.nome}>
            <div className="flex justify-between text-[11px] leading-tight">
              <span>
                <span aria-hidden style={{ color: cor }}>{ICONE_BARRA[b.cor_token] ?? "▪"}</span> {b.id.toUpperCase()}
              </span>
              <span className="tabular-nums">
                {v.atual}/{v.max}
              </span>
            </div>
            <div className="barra" role="progressbar" aria-valuenow={v.atual} aria-valuemin={0} aria-valuemax={v.max} aria-label={b.nome}>
              <div style={{ width: `${frac * 100}%`, background: cor }} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default function PartyHUD() {
  const state = useSala((s) => s.state)
  const config = useSala((s) => s.config)
  const fase = useSala((s) => s.fase)
  const prontos = useSala((s) => s.prontos)
  const eu = useSala((s) => s.eu)
  const selecionado = useSala((s) => s.selecionado)
  const selecionar = useSala((s) => s.selecionarToken)
  const [fichaAberta, setFichaAberta] = useState(false)
  if (!state || !config) return null
  const meuPersonagem = eu?.personagem_id ? state.personagens[eu.personagem_id] : undefined

  const jogadores = Object.values(state.jogadores).filter((j) => j.papel !== "espectador")
  const espectadores = Object.values(state.jogadores).filter((j) => j.papel === "espectador")
  const idsDeJogadores = new Set(jogadores.map((j) => j.personagem_id))
  const npcs = Object.values(state.personagens).filter((p) => !idsDeJogadores.has(p.id))

  return (
    <div className="rolavel flex-1 overflow-y-auto p-3">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm uppercase tracking-wider text-suave">Grupo</h2>
        {meuPersonagem && (
          <button className="botao px-2 py-0.5 text-xs" onClick={() => setFichaAberta(true)} title="Ver a ficha completa do meu personagem">
            📜 Minha ficha
          </button>
        )}
      </div>
      {fichaAberta && meuPersonagem && (
        <Modal titulo={`Minha ficha — ${meuPersonagem.nome}`} aoFechar={() => setFichaAberta(false)} largura="max-w-2xl">
          <FichaPanel p={meuPersonagem} config={config} />
        </Modal>
      )}
      <ul className="space-y-2">
        {jogadores.map((j) => {
          const p = j.personagem_id ? state.personagens[j.personagem_id] : null
          const status = !j.conectado
            ? { icone: "🔌", texto: "Desconectado", cor: "var(--status-vida)" }
            : prontos.includes(j.player_id)
              ? { icone: "✅", texto: "Pronto", cor: "#4ade80" }
              : fase === "planejamento"
                ? { icone: "⏳", texto: "Planejando…", cor: "var(--texto-suave)" }
                : { icone: "·", texto: "", cor: "var(--texto-suave)" }
          const ehEu = j.player_id === eu?.player_id
          return (
            <li
              key={j.player_id}
              className={`rounded p-2 ${selecionado && selecionado === p?.id ? "ring-1 ring-[var(--acento)]" : ""}`}
              style={{ background: "#00000033", outline: ehEu ? "1px solid var(--painel-borda)" : undefined }}
              onClick={() => p && selecionar(p.id)}
            >
              <div className="flex items-center gap-2">
                {p ? <TokenAvatar p={p} /> : <span className="inline-block h-9 w-9 rounded-full bg-black/40" aria-hidden />}
                <div className="min-w-0 flex-1">
                  <div className="truncate font-semibold leading-tight">{p?.nome ?? "(sem personagem)"}</div>
                  <div className="truncate text-[11px] text-suave">
                    {j.nome}
                    {j.papel === "host" ? " 👑" : ""}
                    {ehEu ? " (você)" : ""}
                  </div>
                </div>
                <span className="text-[11px]" style={{ color: status.cor }} title={status.texto}>
                  {status.icone} {status.texto}
                </span>
              </div>
              {p && (
                <div className="mt-2">
                  <Barras p={p} barras={config.barras_status} />
                  {(p.condicoes.length > 0 || p.caido) && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {p.caido && <span className="chip" style={{ borderColor: "var(--status-vida)" }}>✕ caído</span>}
                      {p.condicoes.map((c) => (
                        <span key={c.id} className="chip" title={c.rodadas_restantes === null ? "permanente" : `${c.rodadas_restantes} rodadas`}>
                          ✦ {c.id}
                          {c.rodadas_restantes !== null && <span className="text-suave">({c.rodadas_restantes})</span>}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </li>
          )
        })}
      </ul>

      {npcs.length > 0 && (
        <>
          <h2 className="mb-2 mt-4 text-sm uppercase tracking-wider text-suave">Em cena</h2>
          <ul className="space-y-1">
            {npcs.map((p) => {
              const pv = p.barras[config.barras_status[0]?.id ?? "pv"]
              return (
                <li
                  key={p.id}
                  className={`flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-xs ${selecionado === p.id ? "ring-1 ring-[var(--acento)]" : ""}`}
                  onClick={() => selecionar(p.id)}
                >
                  <TokenAvatar p={p} tamanho={24} />
                  <span className="min-w-0 flex-1 truncate">
                    {p.nome}
                    {p.postura && <span className="text-suave"> · {p.postura}</span>}
                  </span>
                  {pv && (
                    <span className="tabular-nums" style={{ color: "var(--status-vida)" }}>
                      ♥ {pv.atual}/{pv.max}
                    </span>
                  )}
                  {p.caido && <span aria-label="caído">✕</span>}
                </li>
              )
            })}
          </ul>
        </>
      )}

      {espectadores.length > 0 && (
        <p className="mt-3 text-[11px] text-suave">👁 Espectadores: {espectadores.map((e) => e.nome).join(", ")}</p>
      )}

      {state.modo === "combate" && state.iniciativa.length > 0 && (
        <div className="mt-4">
          <h2 className="mb-1 text-sm uppercase tracking-wider text-suave">Iniciativa</h2>
          <ol className="list-decimal pl-5 text-xs">
            {state.iniciativa.map((id) => (
              <li key={id}>{state.personagens[id]?.nome ?? id}</li>
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}
