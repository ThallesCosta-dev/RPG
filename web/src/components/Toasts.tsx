import { useToast } from "../store/useToast"

export default function Toasts() {
  const toasts = useToast((s) => s.toasts)
  const fechar = useToast((s) => s.fechar)
  if (toasts.length === 0) return null
  return (
    <div className="fixed bottom-4 left-1/2 z-50 flex -translate-x-1/2 flex-col gap-2" role="status" aria-live="polite">
      {toasts.map((t) => (
        <button
          key={t.id}
          onClick={() => fechar(t.id)}
          className="painel toast-entrada px-4 py-2 text-sm text-left shadow-lg"
          style={{ borderColor: t.tipo === "erro" ? "var(--status-vida)" : t.tipo === "ok" ? "#4ade80" : undefined }}
        >
          {t.tipo === "erro" ? "⚠ " : t.tipo === "ok" ? "✓ " : "ℹ "}
          {t.texto}
        </button>
      ))}
    </div>
  )
}
