import { useEffect, useRef } from "react"
import { GridRenderer, type SnapshotGrid } from "./GridRenderer"
import { useSala, type SalaStore } from "../../store/useSala"
import { barramento } from "../../lib/animacoes"

function extrairSnapshot(s: SalaStore): SnapshotGrid {
  const podeArrastar = s.fase === "planejamento" && !s.confirmado && !!s.eu?.personagem_id && s.eu.papel !== "espectador"
  return {
    cena: s.state?.cena ?? null,
    obstaculos: s.state?.obstaculos ?? [],
    personagens: s.state?.personagens ?? {},
    alcance: s.alcance,
    previews: s.previews,
    alvosRealcados: s.alvosRealcados,
    selecionado: s.selecionado,
    meuPersonagemId: s.eu?.personagem_id ?? null,
    podeArrastar,
    barraVidaId: s.config?.barras_status[0]?.id ?? "pv",
    tema: s.tema,
  }
}

/** Wrapper React do renderizador PixiJS. Assina o store diretamente para não re-renderizar o React a cada frame. */
export default function GridCanvas() {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const renderer = new GridRenderer({
      aoSelecionar: (id) => useSala.getState().selecionarToken(id),
      aoSoltar: (destino) => useSala.getState().enviar({ type: "preview_move", destino }),
    })
    renderer.atualizar(extrairSnapshot(useSala.getState()))
    void renderer.iniciar(el)
    const cancelarStore = useSala.subscribe((s) => renderer.atualizar(extrairSnapshot(s)))
    const cancelarEventos = barramento.on((ev, instantaneo) => renderer.animar(ev, instantaneo))
    return () => {
      cancelarStore()
      cancelarEventos()
      renderer.destruir()
    }
  }, [])

  return <div ref={ref} className="absolute inset-0" aria-label="Grid tático" role="img" />
}
