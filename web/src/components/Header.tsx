import { useSala } from "../store/useSala"
import { storage } from "../lib/storage"
import { TEMAS } from "../lib/tema"
import type { Tema } from "../types"
import Temporizador from "./Temporizador"

const NOME_FASE: Record<string, string> = {
  lobby: "Lobby",
  planejamento: "Planejamento",
  resolvendo: "Resolvendo…",
  narrando: "Narrando",
  pausado: "Pausado",
}

const NOME_NIVEL: Record<number, string> = { 1: "Local", 2: "Flash", 3: "Pro", 4: "Premium" }

interface Props {
  salaId: string
  token: string
  ehHost: boolean
  aoAbrirHost(): void
}

export default function Header({ salaId, ehHost, aoAbrirHost }: Props) {
  const state = useSala((s) => s.state)
  const fase = useSala((s) => s.fase)
  const prazo = useSala((s) => s.prazo)
  const nivelIa = useSala((s) => s.nivelIa)
  const provedorIa = useSala((s) => s.provedorIa)
  const vozAtual = useSala((s) => s.vozAtual)
  const narrando = useSala((s) => s.narrando)
  const volume = useSala((s) => s.volume)
  const mudo = useSala((s) => s.mudo)
  const tema = useSala((s) => s.tema)
  const setVolume = useSala((s) => s.setVolume)
  const setMudo = useSala((s) => s.setMudo)
  const setTemaOverride = useSala((s) => s.setTemaOverride)
  const pular = useSala((s) => s.pularNarracao)
  const conexao = useSala((s) => s.conexao)

  const campanha = storage.campanhaInfo(salaId)?.nome
  const combate = state?.modo === "combate"
  const nomeVoz = vozAtual ? (state?.personagens[vozAtual]?.nome ?? vozAtual) : null

  return (
    <header className="painel m-2 mb-0 flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2 text-sm">
      <div className="flex min-w-0 items-center gap-3">
        <h1 className="truncate text-lg leading-tight">{campanha ?? state?.cena.nome ?? "AI-VTT"}</h1>
        {campanha && state && <span className="truncate text-suave">— {state.cena.nome}</span>}
      </div>

      <span className="chip" title="Modo atual" style={{ borderColor: combate ? "var(--status-vida)" : undefined }}>
        {combate ? "⚔ Combate" : "🧭 Exploração"}
        {state && state.rodada > 0 && <span className="text-suave"> · rodada {state.rodada}</span>}
      </span>
      <span className="chip" title="Fase">
        {NOME_FASE[fase] ?? fase}
      </span>
      {fase === "planejamento" && <Temporizador prazo={prazo} className="text-base" />}

      <span className="chip" title="Narração" aria-live="polite">
        {narrando || vozAtual ? (
          <>
            <span className="onda" aria-hidden>
              <span /><span /><span /><span />
            </span>
            <span>{nomeVoz ?? "Narrador"}</span>
            {narrando && (
              <button className="ml-1 underline" onClick={pular} title="Pular narração">
                pular
              </button>
            )}
          </>
        ) : (
          <span className="text-suave">🔇 silêncio</span>
        )}
      </span>

      <div className="ml-auto flex items-center gap-3">
        <label className="flex items-center gap-1" title="Volume da narração">
          <button className="botao px-2 py-0.5" onClick={() => setMudo(!mudo)} aria-label={mudo ? "Ativar som" : "Silenciar"}>
            {mudo ? "🔇" : volume > 0.5 ? "🔊" : "🔉"}
          </button>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={mudo ? 0 : volume}
            onChange={(e) => {
              setVolume(Number(e.target.value))
              if (mudo) setMudo(false)
            }}
            className="w-20"
            aria-label="Volume"
          />
        </label>
        <span className="chip" title={provedorIa ?? "nível da IA"}>
          🤖 IA: {NOME_NIVEL[nivelIa] ?? nivelIa}{provedorIa ? ` (${provedorIa})` : ""}
        </span>
        <label className="flex items-center gap-1 text-xs text-suave">
          Tema
          <select className="campo w-auto py-0.5" value={tema} onChange={(e) => setTemaOverride(e.target.value as Tema)} aria-label="Tema visual">
            {TEMAS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <button className="underline" onClick={() => setTemaOverride(null)} title="Voltar ao tema da campanha">
            auto
          </button>
        </label>
        <span className="chip" title="Conexão">
          <span
            aria-hidden
            style={{
              width: 8,
              height: 8,
              borderRadius: 4,
              background: conexao === "conectado" ? "#4ade80" : "var(--status-vida)",
              display: "inline-block",
            }}
          />
          {conexao === "conectado" ? "online" : conexao}
        </span>
        {ehHost && (
          <button className="botao" onClick={aoAbrirHost}>
            👑 Host
          </button>
        )}
      </div>
    </header>
  )
}
