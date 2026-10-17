import { useEffect, useState } from "react"
import { useNavigate, useParams, useSearchParams } from "react-router-dom"
import { storage } from "../lib/storage"
import { MOCK } from "../lib/api"
import { obterFabricaConexao, type Conexao } from "../lib/ws"
import { useSala } from "../store/useSala"
import Lobby from "../components/Lobby"
import Header from "../components/Header"
import PartyHUD from "../components/PartyHUD"
import Cronica from "../components/Cronica"
import ConsoleTurno from "../components/ConsoleTurno"
import HostDrawer from "../components/HostDrawer"
import GridCanvas from "../components/grid/GridCanvas"

export default function Sala() {
  const { id } = useParams<{ id: string }>()
  const salaId = id ?? ""
  const [params] = useSearchParams()
  const convite = params.get("convite")
  const navegar = useNavigate()
  // Em modo mock, a sala abre direto como Host (sem passar pelo convite).
  const [token, setToken] = useState<string | null>(() => storage.token(salaId) ?? (MOCK ? "mock-token-host" : null))

  const conexao = useSala((s) => s.conexao)
  const motivoConexao = useSala((s) => s.motivoConexao)
  const state = useSala((s) => s.state)
  const eu = useSala((s) => s.eu)
  const fase = useSala((s) => s.fase)
  const [hostAberto, setHostAberto] = useState(false)

  // Conexão WebSocket: abre quando há token; reconecta sozinha (ws.ts).
  useEffect(() => {
    if (!token || !salaId) return
    let conexaoObj: Conexao | null = null
    let cancelado = false
    const loja = useSala.getState()
    loja.iniciarSala(salaId)
    obterFabricaConexao().then((fabrica) => {
      if (cancelado) return
      conexaoObj = fabrica(salaId, token, {
        aoReceber: (msg) => useSala.getState().receber(msg),
        aoStatus: (status, motivo) => useSala.getState().setConexao(status, motivo),
      })
      useSala.getState().setConexaoObj(conexaoObj)
    })
    return () => {
      cancelado = true
      conexaoObj?.fechar()
      useSala.getState().setConexaoObj(null)
    }
  }, [token, salaId])

  if (!salaId) return null

  if (!token) {
    if (convite) return <Lobby salaId={salaId} convite={convite} aoEntrar={(t) => setToken(t)} />
    return (
      <main className="flex min-h-full items-center justify-center p-6">
        <div className="painel max-w-md space-y-3 p-6">
          <h1 className="text-xl">Sem acesso a esta sala</h1>
          <p className="text-suave">Você precisa de um link de convite (<code>/sala/{salaId}?convite=…</code>).</p>
          <button className="botao" onClick={() => navegar("/")}>Voltar ao início</button>
        </div>
      </main>
    )
  }

  if (conexao === "encerrado") {
    return (
      <main className="flex min-h-full items-center justify-center p-6">
        <div className="painel max-w-md space-y-3 p-6">
          <h1 className="text-xl">Conexão encerrada</h1>
          <p className="text-suave">{motivoConexao ?? "A sessão foi encerrada pelo servidor."}</p>
          <div className="flex gap-2">
            <button className="botao" onClick={() => window.location.reload()}>Tentar de novo</button>
            <button
              className="botao botao-perigo"
              onClick={() => {
                storage.setToken(salaId, null)
                navegar("/")
              }}
            >
              Sair da sala
            </button>
          </div>
        </div>
      </main>
    )
  }

  if (!state || !eu) {
    return (
      <main className="flex min-h-full items-center justify-center p-6">
        <div className="painel p-6 text-center">
          <p className="piscando">{conexao === "conectado" ? "Aguardando o estado da sala…" : "Conectando à mesa…"}</p>
          {motivoConexao && <p className="mt-2 text-xs text-suave">{motivoConexao}</p>}
        </div>
      </main>
    )
  }

  const ehHost = eu.papel === "host"
  const espectador = eu.papel === "espectador" || !eu.personagem_id

  return (
    <div className="flex h-full flex-col">
      <Header salaId={salaId} token={token} ehHost={ehHost} aoAbrirHost={() => setHostAberto((v) => !v)} />
      <div className="relative flex min-h-0 flex-1">
        <aside className="painel m-2 mr-0 flex w-64 shrink-0 flex-col overflow-hidden">
          <PartyHUD />
        </aside>
        <main className="relative min-w-0 flex-1">
          <GridCanvas />
          {fase === "lobby" && (
            <div className="pointer-events-none absolute inset-x-0 top-3 flex justify-center">
              <div className="painel pointer-events-auto px-4 py-2 text-sm">
                {ehHost ? "Lobby: abra o painel do Host para iniciar a sessão." : "Aguardando o Host iniciar a sessão…"}
              </div>
            </div>
          )}
          {fase === "pausado" && (
            <div className="pointer-events-none absolute inset-x-0 top-3 flex justify-center">
              <div className="painel px-4 py-2 text-sm">⏸ Sessão pausada pelo Host.</div>
            </div>
          )}
          {conexao !== "conectado" && (
            <div className="pointer-events-none absolute inset-x-0 bottom-3 flex justify-center">
              <div className="painel px-4 py-2 text-sm piscando" style={{ borderColor: "var(--status-vida)" }}>
                🔌 {motivoConexao ?? "Reconectando…"}
              </div>
            </div>
          )}
        </main>
        <aside className="m-2 ml-0 flex w-[22rem] shrink-0 flex-col gap-2">
          <section className="painel flex min-h-0 flex-1 flex-col overflow-hidden">
            <Cronica />
          </section>
          {!espectador && (
            <section className="painel flex max-h-[55%] shrink-0 flex-col overflow-hidden">
              <ConsoleTurno />
            </section>
          )}
        </aside>
        {ehHost && hostAberto && <HostDrawer salaId={salaId} token={token} aoFechar={() => setHostAberto(false)} />}
      </div>
    </div>
  )
}
