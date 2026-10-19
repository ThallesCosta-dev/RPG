import { useEffect, useMemo, useRef, useState } from "react"
import { useSala } from "../store/useSala"
import type { ChatMessage, Personagem } from "../types"
import TokenAvatar from "./TokenAvatar"

const MAX_TEXTO = 500

/** Cor do token clareada para o nome continuar legível sobre o painel escuro. */
const corNome = (cor: string | undefined, padrao?: string) => (cor ? `color-mix(in srgb, ${cor} 55%, var(--texto))` : padrao)

const hora = (ts: number) => {
  const d = new Date(ts * 1000)
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
}

function Linha({ m, personagens, minha }: { m: ChatMessage; personagens: Record<string, Personagem>; minha: boolean }) {
  const p = m.personagem_id ? personagens[m.personagem_id] : undefined
  const destino = m.para ? (personagens[m.para]?.nome ?? m.para) : null
  if (m.de === "sistema") {
    // Aviso da mesa (descanso, etc.): discreto, centralizado, sem avatar.
    return (
      <div className="px-1 py-0.5 text-center text-[11px] italic text-suave" role="status" aria-label={`${m.nome}: ${m.texto}`}>
        <span className="tabular-nums">{hora(m.ts)} </span>
        <span className="chip mr-1 not-italic">{m.nome}</span>
        {m.texto}
      </div>
    )
  }
  if (m.npc) {
    return (
      <div className="msg-npc flex gap-2 rounded px-2 py-1.5" aria-label={`${m.nome} (NPC)`}>
        {p ? <TokenAvatar p={p} tamanho={28} /> : <span className="inline-block h-7 w-7 shrink-0 rounded-full bg-black/40" aria-hidden />}
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-1 text-[11px]">
            <strong style={{ color: corNome(p?.cor, "var(--acento)") }}>{m.nome}</strong>
            {m.por_host && <span className="text-suave">(Host)</span>}
            {destino && <span className="text-suave">→ {destino}</span>}
            <span className="ml-auto tabular-nums text-suave">{hora(m.ts)}</span>
          </div>
          <p className="italic leading-snug">{m.texto}</p>
        </div>
      </div>
    )
  }
  return (
    <div className="px-1 leading-snug">
      <span className="text-[11px] tabular-nums text-suave">{hora(m.ts)} </span>
      <strong style={{ color: corNome(p?.cor, minha ? "var(--acento)" : undefined) }}>{m.nome}</strong>
      {!m.personagem_id && <span className="text-[11px] text-suave"> (espectador)</span>}
      {destino && <span className="text-[11px] text-suave"> → {destino}</span>}
      <span className="text-suave">: </span>
      <span>{m.texto}</span>
    </div>
  )
}

/** Chat da mesa e diálogo com NPCs (§6). */
export default function Chat() {
  const state = useSala((s) => s.state)
  const eu = useSala((s) => s.eu)
  const chat = useSala((s) => s.chat)
  const digitando = useSala((s) => s.digitando)
  const enviarChat = useSala((s) => s.enviarChat)
  const [texto, setTexto] = useState("")
  const [para, setPara] = useState<string>("")
  const fim = useRef<HTMLDivElement>(null)
  const campo = useRef<HTMLInputElement>(null)

  const temPersonagem = !!eu?.personagem_id && eu.papel !== "espectador"
  const npcs = useMemo(
    () => (temPersonagem ? Object.values(state?.personagens ?? {}).filter((p) => p.tipo === "npc" && !p.caido) : []),
    [state, temPersonagem],
  )

  // Se o NPC escolhido caiu ou sumiu da cena, volta para a Mesa.
  useEffect(() => {
    if (para && !npcs.some((n) => n.id === para)) setPara("")
  }, [para, npcs])

  useEffect(() => {
    fim.current?.scrollIntoView({ block: "end" })
  }, [chat.length, digitando])

  const enviar = () => {
    if (enviarChat(texto, para || null)) {
      setTexto("")
      campo.current?.focus()
    }
  }

  const personagens = state?.personagens ?? {}
  const alvo = para ? personagens[para] : undefined

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="rolavel flex-1 space-y-1 overflow-y-auto px-2 py-2 text-[13px]" role="log" aria-live="polite" aria-label="Mensagens do chat">
        {chat.length === 0 && <p className="px-1 italic text-suave">Ninguém falou ainda. Diga olá à mesa ou escolha um NPC para conversar.</p>}
        {chat.map((m) => (
          <Linha key={m.id} m={m} personagens={personagens} minha={m.de === eu?.player_id} />
        ))}
        {digitando && (
          <p className="piscando px-1 text-[12px] italic text-suave" aria-live="polite">
            {digitando.nome} está respondendo…
          </p>
        )}
        <div ref={fim} />
      </div>
      <form
        className="space-y-1 border-t px-2 py-2"
        style={{ borderColor: "var(--painel-borda)" }}
        onSubmit={(e) => {
          e.preventDefault()
          enviar()
        }}
      >
        <div className="flex items-center gap-1">
          <label htmlFor="chat-para" className="text-[11px] uppercase tracking-wide text-suave">
            Para:
          </label>
          <select id="chat-para" className="campo w-auto flex-1 py-0.5 text-xs" value={para} onChange={(e) => setPara(e.target.value)} disabled={!temPersonagem}>
            <option value="">Mesa</option>
            {npcs.map((n) => (
              <option key={n.id} value={n.id}>
                {n.icone} {n.nome}
              </option>
            ))}
          </select>
          {!temPersonagem && <span className="text-[10px] text-suave">(só a mesa)</span>}
        </div>
        <div className="flex gap-1">
          <input
            ref={campo}
            id="chat-texto"
            className="campo"
            placeholder={alvo ? `Falar com ${alvo.nome}…` : "Mensagem para a mesa…"}
            value={texto}
            maxLength={MAX_TEXTO}
            onChange={(e) => setTexto(e.target.value.slice(0, MAX_TEXTO))}
            aria-label="Mensagem"
            autoComplete="off"
          />
          <button className="botao botao-primario px-3" disabled={!texto.trim()} title="Enter envia" aria-label="Enviar">
            ➤
          </button>
        </div>
        <div className="flex justify-between text-[10px] text-suave">
          <span>{alvo ? `${alvo.nome} responde pela IA` : "Visível para toda a mesa"}</span>
          <span>
            {texto.length}/{MAX_TEXTO}
          </span>
        </div>
      </form>
    </div>
  )
}
