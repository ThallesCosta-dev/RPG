import { useCallback, useEffect, useMemo } from "react"
import { montarSlot, useSala, type SlotEditor } from "../store/useSala"
import { DADOS_RAPIDOS, SLOT_LIVRE_DADO, expressaoDeAtaque } from "../lib/dados"
import { distanciaQuadrados } from "../lib/grid"
import type { AcaoDeclarada, Ataque, Coord, Personagem, Slot, SlotConfig } from "../types"
import Temporizador from "./Temporizador"

// Tipos do contrato que o console sabe montar; "magia" e outros do system_config ficam de fora por enquanto.
const TIPOS_SUPORTADOS = new Set(["ataque", "pericia", "criativa", "fala"])
const TIPOS_EXTRAS = ["defender", "esperar"]
const ROTULO_TIPO: Record<string, string> = {
  ataque: "Ataque",
  pericia: "Perícia",
  criativa: "Ação criativa",
  fala: "Fala",
  defender: "Defender",
  esperar: "Esperar",
}
const MAX_TEXTO = 500

function alvosValidos(
  personagens: Record<string, Personagem>,
  eu: Personagem,
  ataque: Ataque | undefined,
  origem: Coord,
  metrica: "1-1-1" | "1-2-1-2" | "manhattan",
): Personagem[] {
  if (!ataque) return []
  return Object.values(personagens).filter((p) => {
    if (p.id === eu.id || p.faccao === "aliado" || p.caido) return false
    const pv = p.barras.pv
    if (pv && pv.atual <= 0) return false
    return distanciaQuadrados(origem, [p.x, p.y], metrica) <= ataque.alcance
  })
}

export default function ConsoleTurno() {
  const state = useSala((s) => s.state)
  const config = useSala((s) => s.config)
  const eu = useSala((s) => s.eu)
  const fase = useSala((s) => s.fase)
  const prazo = useSala((s) => s.prazo)
  const meuDestino = useSala((s) => s.meuDestino)
  const alcance = useSala((s) => s.alcance)
  const rolagensPorSlot = useSala((s) => s.rolagensPorSlot)
  const prontos = useSala((s) => s.prontos)
  const totalProntos = useSala((s) => s.totalProntos)
  const confirmado = useSala((s) => s.confirmado)
  const planejamento = useSala((s) => s.planejamento)
  const slotAtivo = useSala((s) => s.slotAtivo)
  const definirSlot = useSala((s) => s.definirSlot)
  const setSlotAtivo = useSala((s) => s.setSlotAtivo)
  const setAlvosRealcados = useSala((s) => s.setAlvosRealcados)
  const enviar = useSala((s) => s.enviar)
  const confirmarTurno = useSala((s) => s.confirmarTurno)
  const desfazerConfirmacao = useSala((s) => s.desfazerConfirmacao)

  const meuPersonagem = eu?.personagem_id ? state?.personagens[eu.personagem_id] : undefined
  const slots: SlotConfig[] = useMemo(() => config?.slots_de_acao_por_turno ?? [], [config])
  const slotsDeAcao = useMemo(() => slots.filter((s) => !s.vinculado_ao_grid), [slots])
  const planejando = fase === "planejamento"
  const travado = !planejando || confirmado
  const metrica = config?.grid.metrica_diagonal ?? "1-2-1-2"
  // Alcance de ataque medido a partir do destino do movimento (ataque acontece depois de mover).
  const origem = useMemo<Coord>(
    () => meuDestino ?? (meuPersonagem ? [meuPersonagem.x, meuPersonagem.y] : [0, 0]),
    [meuDestino, meuPersonagem],
  )

  // Slot ativo padrão = primeiro slot de ação.
  useEffect(() => {
    if (!slotAtivo && slotsDeAcao[0]) setSlotAtivo(slotsDeAcao[0].id)
  }, [slotAtivo, slotsDeAcao, setSlotAtivo])

  // Camada 3: alvos válidos do ataque selecionado no slot ativo.
  useEffect(() => {
    if (!state || !meuPersonagem || !planejando) {
      setAlvosRealcados([])
      return
    }
    const ed = slotAtivo ? planejamento[slotAtivo] : undefined
    if (!ed || ed.tipo !== "ataque") {
      setAlvosRealcados([])
      return
    }
    const atq = meuPersonagem.ataques.find((a) => a.id === ed.ataque_id)
    setAlvosRealcados(alvosValidos(state.personagens, meuPersonagem, atq, origem, metrica).map((p) => p.id))
  }, [state, meuPersonagem, planejamento, slotAtivo, planejando, origem, metrica, setAlvosRealcados])

  const rolar = useCallback(
    (slotId: string) => {
      if (!config || !meuPersonagem || travado || rolagensPorSlot[slotId]) return
      const ed = planejamento[slotId]
      if (!ed || ed.tipo !== "ataque" || !ed.ataque_id) return
      const atq = meuPersonagem.ataques.find((a) => a.id === ed.ataque_id)
      if (!atq) return
      enviar({ type: "roll", slot_id: slotId, expressao: expressaoDeAtaque(config.ataque.expressao, atq.bonus) })
    },
    [config, meuPersonagem, travado, rolagensPorSlot, planejamento, enviar],
  )

  const montarAcao = useCallback((): { acao: AcaoDeclarada; incompletos: string[] } => {
    const slotsAcao: Record<string, Slot> = {}
    const incompletos: string[] = []
    for (const s of slotsDeAcao) {
      const slot = montarSlot(planejamento[s.id], rolagensPorSlot[s.id]?.rolagem_id)
      if (slot) slotsAcao[s.id] = slot
      else {
        slotsAcao[s.id] = { tipo: "esperar" }
        if (planejamento[s.id]?.tipo && planejamento[s.id]?.tipo !== "esperar") incompletos.push(s.label)
      }
    }
    const acao: AcaoDeclarada = { slots: slotsAcao }
    if (meuDestino) acao.movimento = { destino: meuDestino }
    return { acao, incompletos }
  }, [slotsDeAcao, planejamento, rolagensPorSlot, meuDestino])

  const confirmar = useCallback(() => {
    if (travado) return
    confirmarTurno(montarAcao().acao)
  }, [travado, confirmarTurno, montarAcao])

  // Atalhos: 1–3 selecionam o slot, R rola, Enter confirma (fora de campos de texto).
  useEffect(() => {
    const aoTecla = (e: KeyboardEvent) => {
      const alvo = e.target as HTMLElement | null
      const emTexto = alvo && (alvo.tagName === "TEXTAREA" || alvo.tagName === "INPUT" || alvo.tagName === "SELECT")
      if (e.key === "Enter" && !emTexto && planejando) {
        e.preventDefault()
        if (confirmado) desfazerConfirmacao()
        else confirmar()
        return
      }
      if (emTexto) return
      if (/^[1-9]$/.test(e.key)) {
        const s = slotsDeAcao[Number(e.key) - 1]
        if (s) setSlotAtivo(s.id)
      } else if (e.key === "r" || e.key === "R") {
        if (slotAtivo) rolar(slotAtivo)
      }
    }
    window.addEventListener("keydown", aoTecla)
    return () => window.removeEventListener("keydown", aoTecla)
  }, [planejando, confirmado, confirmar, desfazerConfirmacao, slotsDeAcao, setSlotAtivo, slotAtivo, rolar])

  if (!state || !config || !eu || !meuPersonagem) return null

  const { incompletos } = montarAcao()

  const renderSlot = (s: SlotConfig, idx: number) => {
    const ed: SlotEditor = planejamento[s.id] ?? { tipo: "", texto: "" }
    const ativo = slotAtivo === s.id
    const tipos = [...(s.tipos_permitidos ?? []).filter((t) => TIPOS_SUPORTADOS.has(t)), ...TIPOS_EXTRAS]
    const atq = meuPersonagem.ataques.find((a) => a.id === ed.ataque_id)
    const alvos = ed.tipo === "ataque" ? alvosValidos(state.personagens, meuPersonagem, atq, origem, metrica) : []
    const rolagem = rolagensPorSlot[s.id]
    return (
      <fieldset
        key={s.id}
        className={`rounded p-2 ${ativo ? "ring-1 ring-[var(--acento)]" : ""}`}
        style={{ background: "#00000033" }}
        onFocus={() => setSlotAtivo(s.id)}
        onClick={() => setSlotAtivo(s.id)}
        disabled={travado}
      >
        <legend className="px-1 text-xs uppercase tracking-wide text-suave">
          <kbd className="chip mr-1">{idx + 1}</kbd>
          {s.icone ? `${s.icone} ` : ""}
          {s.label}
        </legend>
        <div className="space-y-1.5">
          <select className="campo" value={ed.tipo} onChange={(e) => definirSlot(s.id, { tipo: e.target.value, ataque_id: undefined, alvo_id: undefined, pericia: undefined })} aria-label={`Tipo de ${s.label}`}>
            <option value="">— escolher —</option>
            {tipos.map((t) => (
              <option key={t} value={t}>
                {ROTULO_TIPO[t] ?? t}
              </option>
            ))}
          </select>

          {ed.tipo === "ataque" && (
            <>
              <select className="campo" value={ed.ataque_id ?? ""} onChange={(e) => definirSlot(s.id, { ataque_id: e.target.value, alvo_id: undefined })} aria-label="Ataque">
                <option value="">— ataque —</option>
                {meuPersonagem.ataques.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.nome} (+{a.bonus}, {a.dano} {a.tipo_dano}, alc. {a.alcance})
                  </option>
                ))}
              </select>
              <select className="campo" value={ed.alvo_id ?? ""} onChange={(e) => definirSlot(s.id, { alvo_id: e.target.value })} disabled={!atq} aria-label="Alvo">
                <option value="">{atq ? (alvos.length ? "— alvo —" : "nenhum alvo no alcance") : "— alvo —"}</option>
                {alvos.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.icone} {p.nome} ({distanciaQuadrados(origem, [p.x, p.y], metrica)} q)
                  </option>
                ))}
              </select>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="botao"
                  disabled={!atq || !!rolagem || travado}
                  onClick={(e) => {
                    e.stopPropagation()
                    rolar(s.id)
                  }}
                  title="R rola o slot ativo"
                >
                  🎲 [d20] {atq ? expressaoDeAtaque(config.ataque.expressao, atq.bonus) : ""}
                </button>
                {rolagem && (
                  <span className="text-sm">
                    = <strong className="text-lg">{rolagem.rolagem.total}</strong>{" "}
                    <span className="text-suave">[{rolagem.rolagem.termos.flatMap((t) => t.dados ?? []).join(", ")}]</span>
                  </span>
                )}
              </div>
            </>
          )}

          {ed.tipo === "pericia" && (
            <>
              <select className="campo" value={ed.pericia ?? ""} onChange={(e) => definirSlot(s.id, { pericia: e.target.value })} aria-label="Perícia">
                <option value="">— perícia —</option>
                {Object.entries(meuPersonagem.pericias).map(([k, v]) => (
                  <option key={k} value={k}>
                    {k} ({v >= 0 ? "+" : ""}
                    {v})
                  </option>
                ))}
              </select>
              <input className="campo" placeholder="O que você tenta fazer? (opcional)" value={ed.texto} maxLength={MAX_TEXTO} onChange={(e) => definirSlot(s.id, { texto: e.target.value })} />
            </>
          )}

          {(ed.tipo === "criativa" || ed.tipo === "fala") && (
            <div>
              <textarea
                className="campo h-16 resize-none"
                placeholder={ed.tipo === "fala" ? "O que o seu personagem diz?" : "Descreva a ação; o mestre arbitra."}
                value={ed.texto}
                maxLength={MAX_TEXTO}
                onChange={(e) => definirSlot(s.id, { texto: e.target.value.slice(0, MAX_TEXTO) })}
              />
              <div className="text-right text-[10px] text-suave">
                {ed.texto.length}/{MAX_TEXTO}
              </div>
            </div>
          )}
        </div>
      </fieldset>
    )
  }

  const slotGrid = slots.find((s) => s.vinculado_ao_grid)
  const custoDestino = meuDestino ? alcance.find((c) => c[0] === meuDestino[0] && c[1] === meuDestino[1])?.[2] : undefined

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between border-b px-3 py-2" style={{ borderColor: "var(--painel-borda)" }}>
        <h2 className="text-sm uppercase tracking-wider text-suave">Console de Turno</h2>
        {planejando && <Temporizador prazo={prazo} />}
      </div>
      <div className="rolavel flex-1 space-y-2 overflow-y-auto px-3 py-2">
        {!planejando && (
          <p className="text-xs text-suave">
            {fase === "lobby" ? "A sessão ainda não começou." : fase === "pausado" ? "Sessão pausada." : "Aguardando a resolução e a narração da rodada…"}
          </p>
        )}
        {slotGrid && (
          <div className="rounded p-2 text-sm" style={{ background: "#00000033" }}>
            <span className="text-xs uppercase tracking-wide text-suave">
              {slotGrid.icone ? `${slotGrid.icone} ` : ""}
              {slotGrid.label}
            </span>
            <div>
              {meuDestino ? (
                <>
                  → destino ({meuDestino[0]}, {meuDestino[1]}){custoDestino !== undefined && <span className="text-suave"> · custo {custoDestino}</span>}
                </>
              ) : (
                <span className="text-suave">sem movimento (arraste o seu token no grid)</span>
              )}
            </div>
          </div>
        )}
        {slotsDeAcao.map(renderSlot)}

        <div className="rounded p-2" style={{ background: "#00000033" }}>
          <span className="text-xs uppercase tracking-wide text-suave">Dados rápidos</span>
          <div className="mt-1 flex flex-wrap gap-1">
            {DADOS_RAPIDOS.map((d) => (
              <button key={d} type="button" className="botao px-2 py-0.5 text-xs" onClick={() => enviar({ type: "roll", slot_id: SLOT_LIVRE_DADO, expressao: `1d${d}` })}>
                [d{d}]
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="border-t px-3 py-2" style={{ borderColor: "var(--painel-borda)" }}>
        {incompletos.length > 0 && !confirmado && (
          <p className="mb-1 text-[11px]" style={{ color: "var(--status-sanidade)" }}>
            Incompleto (vira "esperar"): {incompletos.join(", ")}
          </p>
        )}
        {confirmado ? (
          <button className="botao w-full" onClick={desfazerConfirmacao} disabled={!planejando}>
            ↩ Desfazer confirmação ({prontos.length}/{totalProntos} prontos)
          </button>
        ) : (
          <button className="botao botao-primario w-full py-2 text-base" onClick={confirmar} disabled={!planejando} title="Enter confirma">
            ✅ CONFIRMAR TURNO ({prontos.length}/{totalProntos} prontos)
          </button>
        )}
      </div>
    </div>
  )
}
