import { useEffect, useState } from "react"
import { api } from "../lib/api"
import { storage } from "../lib/storage"
import { aplicarTema, temaEfetivo } from "../lib/tema"
import type { PersonagemDisponivel, RespostaLobby } from "../types"
import { useToast } from "../store/useToast"
import FichaForm from "./FichaForm"
import { ROTULO_ORIGEM } from "./SemPersonagem"

interface Props {
  salaId: string
  convite: string
  aoEntrar(token: string): void
}

/** Tela de entrada via convite: escolhe nome + personagem (ou cria a ficha) e chama POST /entrar. */
export default function Lobby({ salaId, convite, aoEntrar }: Props) {
  const mostrar = useToast((s) => s.mostrar)
  const [lobby, setLobby] = useState<RespostaLobby | null>(null)
  const [sistemaId, setSistemaId] = useState<string | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [nome, setNome] = useState(storage.nomeJogador())
  const [personagemId, setPersonagemId] = useState("")
  const [ocupado, setOcupado] = useState(false)
  const [criando, setCriando] = useState(false)

  useEffect(() => {
    let cancelado = false
    api
      .lobby(salaId, convite)
      .then(async (l) => {
        if (cancelado) return
        setLobby(l)
        setPersonagemId(l.personagens_disponiveis[0]?.id ?? "")
        storage.setCampanha(salaId, l.campanha, l.tema)
        aplicarTema(temaEfetivo(l.tema))
        // O sistema vem em `sistema` (fora do contrato); como reserva, casa a campanha pelo nome nos cartuchos.
        if (l.sistema) setSistemaId(l.sistema)
        else {
          try {
            const c = await api.cartuchos()
            if (!cancelado) setSistemaId(c.campanhas.find((x) => x.nome === l.campanha)?.sistema_id ?? null)
          } catch {
            /* sem cartuchos: fica sem criação de ficha */
          }
        }
      })
      .catch((e: Error) => !cancelado && setErro(e.message))
    return () => {
      cancelado = true
    }
  }, [salaId, convite])

  const jogadores = lobby ? (Array.isArray(lobby.jogadores) ? lobby.jogadores : Object.values(lobby.jogadores)) : []

  const entrar = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!nome.trim()) return
    setOcupado(true)
    try {
      storage.setNomeJogador(nome.trim())
      const r = await api.entrar(salaId, { convite, nome: nome.trim(), personagem_id: personagemId || null })
      storage.setToken(salaId, r.token)
      aoEntrar(r.token)
    } catch (err) {
      mostrar(`Não foi possível entrar: ${(err as Error).message}`, "erro")
    } finally {
      setOcupado(false)
    }
  }

  const disponiveis = lobby?.personagens_disponiveis ?? []
  const entraComoEspectador = disponiveis.length === 0 || !personagemId

  return (
    <main className="flex min-h-full items-center justify-center overflow-auto p-6">
      <div className={`painel w-full ${criando ? "max-w-3xl" : "max-w-md"} space-y-4 p-6`}>
        <h1 className="text-2xl">{criando ? "Criar minha ficha" : "Entrar na mesa"}</h1>
        {erro && <p style={{ color: "var(--status-vida)" }}>Convite inválido: {erro}</p>}
        {!lobby && !erro && <p className="text-suave">Carregando o lobby…</p>}
        {lobby && (
          <p className="text-suave">
            Campanha <strong className="text-texto">{lobby.campanha}</strong> · tema {lobby.tema}
          </p>
        )}

        {lobby && criando && sistemaId && (
          <FichaForm
            sistemaId={sistemaId}
            aoCancelar={() => setCriando(false)}
            aoCriar={async (ficha) => {
              const r = await api.criarFicha(salaId, { convite, ficha })
              const nova: PersonagemDisponivel = {
                id: r.personagem_id,
                nome: r.ficha.nome,
                classe: r.ficha.classe,
                icone: r.ficha.icone,
                cor: r.ficha.cor,
                origem: "sala",
              }
              setLobby({ ...lobby, personagens_disponiveis: [nova, ...disponiveis.filter((p) => p.id !== nova.id)] })
              setPersonagemId(nova.id)
              setCriando(false)
              mostrar(`Ficha de ${nova.nome} criada. Agora é só entrar na mesa.`, "ok")
            }}
          />
        )}

        {lobby && !criando && (
          <form onSubmit={entrar} className="space-y-4">
            <div>
              <label className="rotulo" htmlFor="nome">Seu nome</label>
              <input id="nome" className="campo" value={nome} onChange={(e) => setNome(e.target.value)} required maxLength={40} />
            </div>
            <div>
              <div className="flex items-center justify-between">
                <span className="rotulo mb-0" id="rotulo-personagem">Personagem</span>
                {sistemaId && (
                  <button type="button" className="botao px-2 py-0.5 text-xs" onClick={() => setCriando(true)}>
                    📜 Criar minha ficha
                  </button>
                )}
              </div>
              {disponiveis.length === 0 && <p className="mt-1 text-sm text-suave">Nenhum personagem disponível: crie a sua ficha ou entre como espectador.</p>}
              <div className="mt-1 grid gap-2" role="radiogroup" aria-labelledby="rotulo-personagem">
                {disponiveis.map((p) => (
                  <label key={p.id} className={`chip cursor-pointer justify-start px-3 py-2 text-sm ${personagemId === p.id ? "ring-2 ring-[var(--acento)]" : ""}`}>
                    <input type="radio" name="personagem" value={p.id} checked={personagemId === p.id} onChange={() => setPersonagemId(p.id)} className="mr-2" />
                    <span
                      className="mr-2 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs"
                      style={{ background: p.cor || "#666", border: "2px solid #4ade80", textShadow: "0 1px 2px #000" }}
                      aria-hidden
                    >
                      {p.icone || p.nome.charAt(0)}
                    </span>
                    <span className="min-w-0 flex-1 truncate">
                      {p.nome}
                      {p.classe && <span className="text-suave"> · {p.classe}</span>}
                    </span>
                    {p.origem && <span className="ml-2 shrink-0 text-[10px] uppercase tracking-wide text-suave">{ROTULO_ORIGEM[p.origem] ?? p.origem}</span>}
                  </label>
                ))}
                {disponiveis.length > 0 && (
                  <label className={`chip cursor-pointer justify-start px-3 py-2 text-sm ${personagemId === "" ? "ring-2 ring-[var(--acento)]" : ""}`}>
                    <input type="radio" name="personagem" value="" checked={personagemId === ""} onChange={() => setPersonagemId("")} className="mr-2" />
                    <span className="text-suave">👁 Entrar como espectador</span>
                  </label>
                )}
              </div>
            </div>
            {jogadores.length > 0 && <p className="text-xs text-suave">Na mesa: {jogadores.map((j) => j.nome).join(", ")}</p>}
            <button className="botao botao-primario w-full" disabled={ocupado}>
              {ocupado ? "Entrando…" : entraComoEspectador ? "Entrar como espectador" : "Entrar na mesa"}
            </button>
          </form>
        )}
      </div>
    </main>
  )
}
