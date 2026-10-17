import { useEffect, useState } from "react"
import { api } from "../lib/api"
import { storage } from "../lib/storage"
import { aplicarTema, temaEfetivo } from "../lib/tema"
import type { RespostaLobby } from "../types"
import { useToast } from "../store/useToast"

interface Props {
  salaId: string
  convite: string
  aoEntrar(token: string): void
}

/** Tela de entrada via convite: escolhe nome + personagem e chama POST /entrar. */
export default function Lobby({ salaId, convite, aoEntrar }: Props) {
  const mostrar = useToast((s) => s.mostrar)
  const [lobby, setLobby] = useState<RespostaLobby | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [nome, setNome] = useState(storage.nomeJogador())
  const [personagemId, setPersonagemId] = useState("")
  const [ocupado, setOcupado] = useState(false)

  useEffect(() => {
    api
      .lobby(salaId, convite)
      .then((l) => {
        setLobby(l)
        setPersonagemId(l.personagens_disponiveis[0]?.id ?? "")
        storage.setCampanha(salaId, l.campanha, l.tema)
        aplicarTema(temaEfetivo(l.tema))
      })
      .catch((e: Error) => setErro(e.message))
  }, [salaId, convite])

  const jogadores = lobby ? (Array.isArray(lobby.jogadores) ? lobby.jogadores : Object.values(lobby.jogadores)) : []

  const entrar = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!nome.trim() || !personagemId) return
    setOcupado(true)
    try {
      storage.setNomeJogador(nome.trim())
      const r = await api.entrar(salaId, { convite, nome: nome.trim(), personagem_id: personagemId })
      storage.setToken(salaId, r.token)
      aoEntrar(r.token)
    } catch (err) {
      mostrar(`Não foi possível entrar: ${(err as Error).message}`, "erro")
    } finally {
      setOcupado(false)
    }
  }

  return (
    <main className="flex min-h-full items-center justify-center p-6">
      <form onSubmit={entrar} className="painel w-full max-w-md space-y-4 p-6">
        <h1 className="text-2xl">Entrar na mesa</h1>
        {erro && <p style={{ color: "var(--status-vida)" }}>Convite inválido: {erro}</p>}
        {!lobby && !erro && <p className="text-suave">Carregando o lobby…</p>}
        {lobby && (
          <>
            <p className="text-suave">
              Campanha <strong className="text-texto">{lobby.campanha}</strong> · tema {lobby.tema}
            </p>
            <div>
              <label className="rotulo" htmlFor="nome">Seu nome</label>
              <input id="nome" className="campo" value={nome} onChange={(e) => setNome(e.target.value)} required maxLength={40} />
            </div>
            <div>
              <span className="rotulo">Personagem</span>
              {lobby.personagens_disponiveis.length === 0 && <p className="text-sm text-suave">Nenhum personagem disponível (você entra como espectador).</p>}
              <div className="grid gap-2">
                {lobby.personagens_disponiveis.map((p) => (
                  <label key={p.id} className={`chip cursor-pointer justify-start px-3 py-2 text-sm ${personagemId === p.id ? "ring-2 ring-[var(--acento)]" : ""}`}>
                    <input type="radio" name="personagem" value={p.id} checked={personagemId === p.id} onChange={() => setPersonagemId(p.id)} className="mr-2" />
                    <span>{p.nome}</span>
                    {typeof p.classe === "string" && <span className="text-suave"> · {p.classe}</span>}
                  </label>
                ))}
              </div>
            </div>
            {jogadores.length > 0 && (
              <p className="text-xs text-suave">Na mesa: {jogadores.map((j) => j.nome).join(", ")}</p>
            )}
            <button className="botao botao-primario w-full" disabled={ocupado || (!personagemId && lobby.personagens_disponiveis.length > 0)}>
              {ocupado ? "Entrando…" : "Entrar na mesa"}
            </button>
          </>
        )}
      </form>
    </main>
  )
}
