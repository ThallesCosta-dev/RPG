import { Fragment, useEffect, useMemo, useRef, useState } from "react"
import { useSala, type ItemCronica } from "../store/useSala"
import type { Rolagem } from "../types"

function Dados({ r }: { r: Rolagem }) {
  return (
    <ul className="mt-1 space-y-0.5 text-[11px] text-suave">
      {r.termos.map((t, i) => (
        <li key={i}>
          <code>{t.termo}</code>
          {t.dados && (
            <>
              {" → "}
              {t.dados.map((d, j) => {
                const mantido = !t.mantidos || t.mantidos.includes(d)
                return (
                  <span key={j} className="chip mr-0.5" style={{ opacity: mantido ? 1 : 0.45, textDecoration: mantido ? undefined : "line-through" }}>
                    {d}
                  </span>
                )
              })}
            </>
          )}
        </li>
      ))}
    </ul>
  )
}

export default function Cronica({ semCabecalho = false }: { semCabecalho?: boolean }) {
  const state = useSala((s) => s.state)
  const itens = useSala((s) => s.itensCronica)
  const narrando = useSala((s) => s.narrando)
  const pendentes = useSala((s) => s.segmentosPendentes)
  const pular = useSala((s) => s.pularNarracao)
  const [abertas, setAbertas] = useState<Set<number>>(new Set())
  const fim = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fim.current?.scrollIntoView({ block: "end" })
  }, [itens.length])

  // Histórico do servidor (state.cronica) só para rodadas anteriores às que já temos localmente.
  const primeiraRodadaLocal = useMemo(() => (itens.length > 0 ? Math.min(...itens.map((i) => i.rodada)) : Infinity), [itens])
  const historico = (state?.cronica ?? []).filter((l) => l.rodada < primeiraRodadaLocal)

  const nome = (id: string) => state?.personagens[id]?.nome ?? state?.jogadores[id]?.nome ?? id

  const alternar = (chave: number) =>
    setAbertas((prev) => {
      const n = new Set(prev)
      if (n.has(chave)) n.delete(chave)
      else n.add(chave)
      return n
    })

  const renderItem = (it: ItemCronica, i: number) => {
    switch (it.tipo) {
      case "legenda":
        return (
          <p key={`l${i}`} className="leading-snug">
            {it.voz !== "NARRADOR" && <strong style={{ color: "var(--acento)" }}>{nome(it.voz)}: </strong>}
            {it.texto}
          </p>
        )
      case "acao":
        return (
          <p key={`a${i}`} className="text-[12px] text-suave">
            <span className="chip mr-1">{it.id}</span>
            {it.texto}
          </p>
        )
      case "rolagem": {
        const aberta = abertas.has(it.chave)
        return (
          <div key={`r${it.chave}`} className="text-[12px]">
            <button className="text-left underline decoration-dotted" onClick={() => alternar(it.chave)} aria-expanded={aberta}>
              🎲 {nome(it.player_id)} · {it.slot_id}: <strong>{it.rolagem.total}</strong> <span className="text-suave">({it.rolagem.expressao})</span>
            </button>
            {aberta && <Dados r={it.rolagem} />}
          </div>
        )
      }
      case "sistema":
        return (
          <p key={`s${i}`} className="text-[12px] italic text-suave">
            {it.texto}
          </p>
        )
      default:
        return null
    }
  }

  // Agrupa por rodada mantendo a ordem de chegada.
  const grupos: { rodada: number; itens: { it: ItemCronica; i: number }[] }[] = []
  itens.forEach((it, i) => {
    const ultimo = grupos[grupos.length - 1]
    if (ultimo && ultimo.rodada === it.rodada) ultimo.itens.push({ it, i })
    else grupos.push({ rodada: it.rodada, itens: [{ it, i }] })
  })

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {!semCabecalho && (
        <div className="flex items-center justify-between border-b px-3 py-2" style={{ borderColor: "var(--painel-borda)" }}>
          <h2 className="text-sm uppercase tracking-wider text-suave">Crônica</h2>
          {narrando && (
            <button className="botao px-2 py-0.5 text-xs" onClick={pular} title="Esvazia a fila e aplica as animações pendentes">
              ⏭ Pular narração{pendentes > 0 ? ` (${pendentes})` : ""}
            </button>
          )}
        </div>
      )}
      <div className="rolavel flex-1 space-y-3 overflow-y-auto px-3 py-2 text-[14px]">
        {state?.cena.descricao && itens.length === 0 && historico.length === 0 && (
          <p className="italic text-suave">{state.cena.descricao}</p>
        )}
        {historico.length > 0 && (
          <div className="space-y-1">
            {historico.map((l, i) => {
              const nova = i === 0 || historico[i - 1].rodada !== l.rodada
              return (
                <Fragment key={`${l.rodada}-${l.id}-${i}`}>
                  {nova && <h3 className="mt-2 text-xs uppercase text-suave">Rodada {l.rodada}</h3>}
                  <p className="text-[12px] text-suave">
                    <span className="chip mr-1">{l.id}</span>
                    {l.texto}
                  </p>
                </Fragment>
              )
            })}
          </div>
        )}
        {grupos.map((g) => (
          <section key={g.rodada}>
            <h3 className="mb-1 text-xs uppercase text-suave">Rodada {g.rodada}</h3>
            <div className="space-y-1">{g.itens.map(({ it, i }) => renderItem(it, i))}</div>
          </section>
        ))}
        {narrando && <p className="piscando text-xs text-suave">▌ narrando…</p>}
        <div ref={fim} />
      </div>
    </div>
  )
}
