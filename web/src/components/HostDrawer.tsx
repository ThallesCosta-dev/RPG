import { useState } from "react"
import { useSala } from "../store/useSala"
import { api } from "../lib/api"
import { storage } from "../lib/storage"
import { useToast } from "../store/useToast"
import type { ComandoHost, NivelIa } from "../types"

interface Props {
  salaId: string
  token: string
  aoFechar(): void
}

/** Gaveta lateral do Host com todos os comandos da §5 do contrato. */
export default function HostDrawer({ salaId, token, aoFechar }: Props) {
  const state = useSala((s) => s.state)
  const fase = useSala((s) => s.fase)
  const nivelIa = useSala((s) => s.nivelIa)
  const enviar = useSala((s) => s.enviar)
  const mostrar = useToast((s) => s.mostrar)

  const [cenaId, setCenaId] = useState("")
  const [personagemId, setPersonagemId] = useState("")
  const [px, setPx] = useState("")
  const [py, setPy] = useState("")
  const [barraId, setBarraId] = useState("pv")
  const [barraAtual, setBarraAtual] = useState("")
  const [condicoes, setCondicoes] = useState("")
  const [convite, setConvite] = useState(storage.convite(salaId))
  const [debug, setDebug] = useState<string | null>(null)

  const comando = (c: ComandoHost) => enviar({ type: "host_command", ...c })

  const personagem = personagemId ? state?.personagens[personagemId] : undefined
  const linkConvite = convite ? `${window.location.origin}/sala/${encodeURIComponent(salaId)}?convite=${encodeURIComponent(convite)}` : null

  const editar = () => {
    if (!personagem) return
    const campos: Extract<ComandoHost, { comando: "editar_personagem" }>["campos"] = {}
    if (px !== "") campos.x = Number(px)
    if (py !== "") campos.y = Number(py)
    if (barraAtual !== "") {
      const b = personagem.barras[barraId]
      campos.barras = { ...personagem.barras, [barraId]: { atual: Number(barraAtual), max: b?.max ?? Number(barraAtual) } }
    }
    if (condicoes.trim() !== "") {
      campos.condicoes = condicoes
        .split(",")
        .map((c) => c.trim())
        .filter(Boolean)
        .map((id) => ({ id, rodadas_restantes: null }))
    }
    comando({ comando: "editar_personagem", personagem_id: personagem.id, campos })
  }

  const copiar = async (texto: string) => {
    try {
      await navigator.clipboard.writeText(texto)
      mostrar("Copiado.", "ok", 2000)
    } catch {
      mostrar("Não foi possível copiar; selecione o texto manualmente.", "erro")
    }
  }

  return (
    <aside className="painel absolute right-2 top-2 bottom-2 z-30 flex w-80 flex-col overflow-hidden" aria-label="Painel do Host">
      <div className="flex items-center justify-between border-b px-3 py-2" style={{ borderColor: "var(--painel-borda)" }}>
        <h2 className="text-sm uppercase tracking-wider">👑 Host</h2>
        <button className="botao px-2 py-0.5" onClick={aoFechar} aria-label="Fechar painel do Host">
          ✕
        </button>
      </div>
      <div className="rolavel flex-1 space-y-4 overflow-y-auto px-3 py-3 text-sm">
        <section className="space-y-1">
          <h3 className="rotulo">Sessão (fase: {fase})</h3>
          <div className="flex flex-wrap gap-1">
            <button className="botao" onClick={() => comando({ comando: "iniciar" })} disabled={fase !== "lobby"}>▶ Iniciar</button>
            {fase === "pausado" ? (
              <button className="botao" onClick={() => comando({ comando: "retomar" })}>⏵ Retomar</button>
            ) : (
              <button className="botao" onClick={() => comando({ comando: "pausar" })} disabled={fase === "lobby"}>⏸ Pausar</button>
            )}
            <button className="botao" onClick={() => comando({ comando: "resolver_agora" })} disabled={fase !== "planejamento"}>⏩ Resolver agora</button>
            <button className="botao botao-perigo" onClick={() => comando({ comando: "desfazer_rodada" })}>↶ Desfazer rodada</button>
            <button className="botao" onClick={() => comando({ comando: "nova_narracao" })}>🔁 Nova narração</button>
          </div>
        </section>

        <section className="space-y-1">
          <h3 className="rotulo">Combate (modo: {state?.modo})</h3>
          <div className="flex gap-1">
            <button className="botao" onClick={() => comando({ comando: "iniciar_combate" })} disabled={state?.modo === "combate"}>⚔ Iniciar combate</button>
            <button className="botao" onClick={() => comando({ comando: "encerrar_combate" })} disabled={state?.modo !== "combate"}>🕊 Encerrar</button>
          </div>
        </section>

        <section className="space-y-1">
          <h3 className="rotulo">Nível da IA (atual: {nivelIa})</h3>
          <div className="flex gap-1">
            {([1, 2, 3, 4] as NivelIa[]).map((n) => (
              <button key={n} className={`botao ${nivelIa === n ? "botao-primario" : ""}`} onClick={() => comando({ comando: "mudar_nivel_ia", nivel: n })}>
                {n}
              </button>
            ))}
          </div>
        </section>

        <section className="space-y-1">
          <h3 className="rotulo">Mudar cena</h3>
          <div className="flex gap-1">
            <input className="campo" placeholder="cena_id" value={cenaId} onChange={(e) => setCenaId(e.target.value)} />
            <button className="botao" onClick={() => cenaId && comando({ comando: "mudar_cena", cena_id: cenaId })} disabled={!cenaId}>Ir</button>
          </div>
          {state && <p className="text-[11px] text-suave">Atual: {state.cena.id}</p>}
        </section>

        <section className="space-y-1">
          <h3 className="rotulo">Editar personagem</h3>
          <select className="campo" value={personagemId} onChange={(e) => setPersonagemId(e.target.value)} aria-label="Personagem">
            <option value="">— personagem —</option>
            {Object.values(state?.personagens ?? {}).map((p) => (
              <option key={p.id} value={p.id}>
                {p.nome} ({p.x},{p.y})
              </option>
            ))}
          </select>
          {personagem && (
            <div className="space-y-1">
              <div className="flex gap-1">
                <input className="campo" placeholder={`x (${personagem.x})`} value={px} onChange={(e) => setPx(e.target.value)} inputMode="numeric" />
                <input className="campo" placeholder={`y (${personagem.y})`} value={py} onChange={(e) => setPy(e.target.value)} inputMode="numeric" />
              </div>
              <div className="flex gap-1">
                <select className="campo" value={barraId} onChange={(e) => setBarraId(e.target.value)} aria-label="Barra">
                  {Object.keys(personagem.barras).map((b) => (
                    <option key={b} value={b}>
                      {b} ({personagem.barras[b].atual}/{personagem.barras[b].max})
                    </option>
                  ))}
                </select>
                <input className="campo" placeholder="novo valor" value={barraAtual} onChange={(e) => setBarraAtual(e.target.value)} inputMode="numeric" />
              </div>
              <input className="campo" placeholder="condições (ids separados por vírgula)" value={condicoes} onChange={(e) => setCondicoes(e.target.value)} />
              <div className="flex gap-1">
                <button className="botao" onClick={editar}>Aplicar</button>
                <button className="botao" onClick={() => comando({ comando: "editar_personagem", personagem_id: personagem.id, campos: { caido: !personagem.caido } })}>
                  {personagem.caido ? "Levantar" : "Derrubar"}
                </button>
              </div>
            </div>
          )}
        </section>

        <section className="space-y-1">
          <h3 className="rotulo">Convite</h3>
          {linkConvite ? (
            <div className="space-y-1">
              <input className="campo text-[11px]" readOnly value={linkConvite} onFocus={(e) => e.currentTarget.select()} />
              <button className="botao" onClick={() => copiar(linkConvite)}>📋 Copiar link</button>
            </div>
          ) : (
            <p className="text-[11px] text-suave">Nenhum convite salvo neste navegador.</p>
          )}
          <button
            className="botao"
            onClick={async () => {
              try {
                const r = await api.novoConvite(salaId, token)
                storage.setConvite(salaId, r.convite)
                setConvite(r.convite)
              } catch (e) {
                mostrar(`Erro ao gerar convite: ${(e as Error).message}`, "erro")
              }
            }}
          >
            ➕ Novo convite
          </button>
        </section>

        <section className="space-y-1">
          <h3 className="rotulo">Depuração</h3>
          <button
            className="botao"
            onClick={async () => {
              try {
                setDebug(JSON.stringify(await api.debug(salaId, token), null, 2))
              } catch (e) {
                mostrar(`Erro ao buscar depuração: ${(e as Error).message}`, "erro")
              }
            }}
          >
            🔍 Ver log de depuração
          </button>
          {debug && <pre className="rolavel max-h-64 overflow-auto rounded bg-black/40 p-2 text-[10px]">{debug}</pre>}
          {state?.memoria && (
            <details className="text-[11px]">
              <summary className="cursor-pointer">Memória da campanha (rodada {state.memoria.atualizado_na_rodada})</summary>
              <p className="mt-1">{state.memoria.resumo}</p>
              <ul className="list-disc pl-4">
                {state.memoria.fatos.map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ul>
            </details>
          )}
        </section>
      </div>
    </aside>
  )
}
