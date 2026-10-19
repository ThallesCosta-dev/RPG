import { useEffect, useRef, useState } from "react"
import type { ModeloFicha } from "../types"

export interface Basicos {
  nome: string
  icone: string
  cor: string
  voz: string
  historia: string
}

export const COR_PADRAO = "#2563eb"

interface Props {
  modelo: ModeloFicha
  valor: Basicos
  aoMudar(patch: Partial<Basicos>): void
  /** Campo extra entre o nome e o ícone (ex.: classe livre). */
  aposNome?: React.ReactNode
}

/** Nome, ícone, cor, voz e história: comuns aos modos "livre" e "classes" da ficha (§7). */
export default function FichaCamposBasicos({ modelo, valor, aoMudar, aposNome }: Props) {
  const L = modelo.limites
  const [ouvindo, setOuvindo] = useState<string | null>(null)
  const [erroVoz, setErroVoz] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  const ouvir = async (id: string) => {
    setErroVoz(null)
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
      if (ouvindo === id) {
        setOuvindo(null)
        return
      }
    }
    try {
      setOuvindo(id)
      const r = await fetch(`/api/vozes/${encodeURIComponent(id)}/amostra`)
      if (!r.ok) throw new Error(r.status === 404 || r.status === 503 ? "TTS desligado no servidor" : `erro ${r.status}`)
      const { audio_url } = (await r.json()) as { audio_url: string | null }
      if (!audio_url) throw new Error("sem áudio de amostra")
      const a = new Audio(audio_url)
      audioRef.current = a
      a.onended = () => setOuvindo((v) => (v === id ? null : v))
      await a.play()
    } catch (e) {
      setOuvindo(null)
      setErroVoz(e instanceof Error ? e.message : "não foi possível tocar a amostra")
    }
  }

  useEffect(() => () => audioRef.current?.pause(), [])

  return (
    <section className="grid gap-3 sm:grid-cols-2">
      <div>
        <label className="rotulo" htmlFor="ficha-nome">Nome *</label>
        <input id="ficha-nome" className="campo" value={valor.nome} maxLength={L.nome} onChange={(e) => aoMudar({ nome: e.target.value })} required autoFocus />
      </div>
      {aposNome ?? <div />}
      <div className="sm:col-span-2">
        <span className="rotulo" id="ficha-icone-rotulo">Ícone do token</span>
        <div className="flex flex-wrap gap-1" role="radiogroup" aria-labelledby="ficha-icone-rotulo">
          {modelo.icones.map((ic) => (
            <button
              key={ic}
              type="button"
              role="radio"
              aria-checked={valor.icone === ic}
              aria-label={`Ícone ${ic}`}
              className={`botao h-9 w-9 px-0 text-lg ${valor.icone === ic ? "botao-primario" : ""}`}
              onClick={() => aoMudar({ icone: ic })}
            >
              {ic}
            </button>
          ))}
        </div>
      </div>
      <div>
        <label className="rotulo" htmlFor="ficha-cor">Cor do token</label>
        <div className="flex items-center gap-2">
          <input id="ficha-cor" type="color" value={valor.cor} onChange={(e) => aoMudar({ cor: e.target.value })} className="h-9 w-12 cursor-pointer rounded border bg-transparent" style={{ borderColor: "var(--painel-borda)" }} />
          <span
            className="inline-flex h-9 w-9 items-center justify-center rounded-full text-base"
            style={{ background: valor.cor, border: "3px solid #4ade80", textShadow: "0 1px 2px #000" }}
            aria-hidden
          >
            {valor.icone || valor.nome.charAt(0).toUpperCase()}
          </span>
          <code className="text-xs text-suave">{valor.cor}</code>
        </div>
      </div>
      <div className="sm:col-span-2">
        <label className="rotulo" htmlFor="ficha-voz">Voz do personagem</label>
        <div className="flex items-center gap-2">
          <select id="ficha-voz" className="campo flex-1" value={valor.voz} onChange={(e) => aoMudar({ voz: e.target.value })}>
            <option value="">Sem voz própria (o narrador cita as falas)</option>
            {(modelo.vozes ?? []).map((v) => (
              <option key={v.id} value={v.id}>
                {v.descricao} ({v.motor})
              </option>
            ))}
          </select>
          <button type="button" className="botao px-3 py-1" disabled={!valor.voz} onClick={() => ouvir(valor.voz)} aria-pressed={ouvindo === valor.voz} title="Ouvir uma frase de amostra">
            {ouvindo === valor.voz ? "■ Parar" : "▶ Ouvir"}
          </button>
        </div>
        <p className="text-[11px] text-suave">Suas falas na narração saem com essa voz. {erroVoz && <span className="text-perigo">{erroVoz}</span>}</p>
      </div>
      <div className="sm:col-span-2">
        <label className="rotulo" htmlFor="ficha-historia">História</label>
        <textarea id="ficha-historia" className="campo h-20 resize-y" value={valor.historia} maxLength={L.historia} onChange={(e) => aoMudar({ historia: e.target.value })} placeholder="Quem é, de onde veio, o que busca…" />
        <div className="text-right text-[10px] text-suave">
          {valor.historia.length}/{L.historia}
        </div>
      </div>
    </section>
  )
}

/** Erros locais dos campos básicos (nome, cor, história). */
export function validarBasicos(b: Basicos, modelo: ModeloFicha): string[] {
  const L = modelo.limites
  const e: string[] = []
  const n = b.nome.trim()
  if (!n) e.push("nome é obrigatório")
  if (n.length > L.nome) e.push(`nome com no máximo ${L.nome} caracteres`)
  if (!/^#[0-9a-fA-F]{6}$/.test(b.cor)) e.push("cor deve ser #rrggbb")
  if (b.historia.length > L.historia) e.push(`história com no máximo ${L.historia} caracteres`)
  return e
}

/** Bloco de erros (locais e do servidor) usado pelos dois formulários. */
export function ErrosFicha({ locais, servidor }: { locais: string[]; servidor: string[] }) {
  if (locais.length === 0 && servidor.length === 0) return null
  return (
    <div className="rounded border px-3 py-2 text-[12px]" style={{ borderColor: "var(--status-vida)", color: "var(--status-vida)" }} role="alert">
      {servidor.length > 0 && (
        <>
          <p className="font-semibold">O servidor recusou a ficha:</p>
          <ul className="list-disc pl-5">
            {servidor.map((e, i) => (
              <li key={`s${i}`}>{e}</li>
            ))}
          </ul>
        </>
      )}
      {locais.length > 0 && (
        <ul className="list-disc pl-5">
          {locais.map((e, i) => (
            <li key={`l${i}`}>{e}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
