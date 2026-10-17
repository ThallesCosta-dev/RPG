import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { api, interpretarConvite, MOCK } from "../lib/api"
import { storage } from "../lib/storage"
import { TEMAS, aplicarTema, temaEfetivo } from "../lib/tema"
import type { Cartuchos, Tema } from "../types"
import { useToast } from "../store/useToast"

export default function Inicio() {
  const navegar = useNavigate()
  const mostrar = useToast((s) => s.mostrar)
  const [cartuchos, setCartuchos] = useState<Cartuchos | null>(null)
  const [nomeHost, setNomeHost] = useState(storage.nomeJogador())
  const [sistemaId, setSistemaId] = useState("")
  const [campanhaId, setCampanhaId] = useState("")
  const [ocupado, setOcupado] = useState(false)
  const [link, setLink] = useState("")
  const [salaManual, setSalaManual] = useState("")
  const [tema, setTema] = useState<Tema>(temaEfetivo(null))

  useEffect(() => {
    aplicarTema(temaEfetivo(null))
    api
      .cartuchos()
      .then((c) => {
        setCartuchos(c)
        if (c.sistemas[0]) setSistemaId(c.sistemas[0].id)
      })
      .catch((e: Error) => mostrar(`Não foi possível carregar os cartuchos: ${e.message}`, "erro"))
  }, [mostrar])

  const campanhas = useMemo(
    () => (cartuchos?.campanhas ?? []).filter((c) => !sistemaId || c.sistema_id === sistemaId),
    [cartuchos, sistemaId],
  )
  useEffect(() => {
    if (!campanhas.find((c) => c.id === campanhaId)) setCampanhaId(campanhas[0]?.id ?? "")
  }, [campanhas, campanhaId])

  const criar = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!nomeHost.trim() || !sistemaId || !campanhaId) return
    setOcupado(true)
    try {
      storage.setNomeJogador(nomeHost.trim())
      const r = await api.criarSala({ nome_host: nomeHost.trim(), sistema_id: sistemaId, campanha_id: campanhaId })
      storage.setToken(r.sala_id, r.token)
      storage.setConvite(r.sala_id, r.convite)
      const camp = cartuchos?.campanhas.find((c) => c.id === campanhaId)
      if (camp) storage.setCampanha(r.sala_id, camp.nome, camp.tema)
      navegar(`/sala/${encodeURIComponent(r.sala_id)}`)
    } catch (err) {
      mostrar(`Erro ao criar a mesa: ${(err as Error).message}`, "erro")
    } finally {
      setOcupado(false)
    }
  }

  const entrar = (e: React.FormEvent) => {
    e.preventDefault()
    const lido = interpretarConvite(link)
    if (lido) {
      navegar(`/sala/${encodeURIComponent(lido.salaId)}?convite=${encodeURIComponent(lido.convite)}`)
      return
    }
    const codigo = link.trim()
    if (codigo && salaManual.trim()) {
      navegar(`/sala/${encodeURIComponent(salaManual.trim())}?convite=${encodeURIComponent(codigo)}`)
      return
    }
    mostrar("Cole o link completo do convite ou informe o código e o ID da sala.", "erro")
  }

  const ehLink = interpretarConvite(link) !== null

  return (
    <main className="min-h-full overflow-auto px-6 py-10">
      <header className="mx-auto mb-8 flex max-w-5xl items-end justify-between gap-4">
        <div>
          <h1 className="text-4xl">AI-VTT</h1>
          <p className="text-suave">Mesa virtual multiplayer com uma IA como mestre.</p>
        </div>
        <label className="text-xs text-suave">
          Tema{" "}
          <select
            className="campo w-auto"
            value={tema}
            onChange={(e) => {
              const t = e.target.value as Tema
              setTema(t)
              storage.setTema(t)
              aplicarTema(t)
            }}
          >
            {TEMAS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
      </header>

      <div className="mx-auto grid max-w-5xl gap-6 md:grid-cols-2">
        <form onSubmit={criar} className="painel p-6 space-y-4">
          <h2 className="text-xl">Criar mesa</h2>
          <div>
            <label className="rotulo" htmlFor="nome-host">Seu nome (Host)</label>
            <input id="nome-host" className="campo" value={nomeHost} onChange={(e) => setNomeHost(e.target.value)} required maxLength={40} />
          </div>
          <div>
            <label className="rotulo" htmlFor="sistema">Sistema</label>
            <select id="sistema" className="campo" value={sistemaId} onChange={(e) => setSistemaId(e.target.value)} required>
              {(cartuchos?.sistemas ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.nome}
                  {s.revisado ? "" : " (não revisado)"}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="rotulo" htmlFor="campanha">Campanha</label>
            <select id="campanha" className="campo" value={campanhaId} onChange={(e) => setCampanhaId(e.target.value)} required>
              {campanhas.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.nome} — {c.tema}
                  {c.revisado ? "" : " (não revisada)"}
                </option>
              ))}
            </select>
            {cartuchos && campanhas.length === 0 && <p className="mt-1 text-xs text-suave">Nenhuma campanha compilada para este sistema.</p>}
          </div>
          <button className="botao botao-primario w-full" disabled={ocupado || !cartuchos || !campanhaId}>
            {ocupado ? "Criando…" : "Criar mesa"}
          </button>
          {MOCK && <p className="text-xs text-suave">Modo mock ativo: a mesa abre sem backend.</p>}
        </form>

        <form onSubmit={entrar} className="painel p-6 space-y-4">
          <h2 className="text-xl">Entrar com convite</h2>
          <div>
            <label className="rotulo" htmlFor="link">Link ou código do convite</label>
            <input
              id="link"
              className="campo"
              value={link}
              onChange={(e) => setLink(e.target.value)}
              placeholder="https://…/sala/abc123?convite=XYZ"
              required
            />
          </div>
          {!ehLink && link.trim() && (
            <div>
              <label className="rotulo" htmlFor="sala-id">ID da sala (quando colar só o código)</label>
              <input id="sala-id" className="campo" value={salaManual} onChange={(e) => setSalaManual(e.target.value)} />
            </div>
          )}
          <button className="botao botao-primario w-full">Entrar</button>
          <p className="text-xs text-suave">O link de convite tem o formato <code>/sala/&lt;id&gt;?convite=&lt;código&gt;</code>.</p>
        </form>
      </div>
    </main>
  )
}
