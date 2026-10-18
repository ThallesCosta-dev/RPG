import { useEffect, useRef, type ReactNode } from "react"
import { createPortal } from "react-dom"

interface Props {
  titulo: string
  aoFechar(): void
  children: ReactNode
  /** Largura máxima (classe Tailwind), ex.: "max-w-2xl". */
  largura?: string
}

/**
 * Diálogo modal em portal (o `.painel` usa backdrop-filter, que prende `position: fixed` dentro dele).
 * Esc fecha, foco vai para o diálogo ao abrir e volta ao elemento anterior ao fechar.
 */
export default function Modal({ titulo, aoFechar, children, largura = "max-w-xl" }: Props) {
  const caixa = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const anterior = document.activeElement as HTMLElement | null
    caixa.current?.focus()
    const aoTecla = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation()
        aoFechar()
      }
    }
    window.addEventListener("keydown", aoTecla)
    return () => {
      window.removeEventListener("keydown", aoTecla)
      anterior?.focus?.()
    }
  }, [aoFechar])

  return createPortal(
    <div className="modal-fundo" onMouseDown={(e) => e.target === e.currentTarget && aoFechar()}>
      <div
        ref={caixa}
        role="dialog"
        aria-modal="true"
        aria-label={titulo}
        tabIndex={-1}
        className={`painel toast-entrada flex max-h-[92vh] w-full ${largura} flex-col overflow-hidden outline-none`}
      >
        <div className="flex items-center justify-between border-b px-4 py-2" style={{ borderColor: "var(--painel-borda)" }}>
          <h2 className="text-base">{titulo}</h2>
          <button className="botao px-2 py-0.5" onClick={aoFechar} aria-label="Fechar">
            ✕
          </button>
        </div>
        <div className="rolavel min-h-0 flex-1 overflow-y-auto px-4 py-3">{children}</div>
      </div>
    </div>,
    document.body,
  )
}
