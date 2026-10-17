import { useEffect, useState } from "react"

function restante(prazo: number | null): number | null {
  if (prazo === null) return null
  return Math.max(0, Math.floor(prazo - Date.now() / 1000))
}

/** Contagem regressiva a partir de `prazo` (epoch em segundos). */
export default function Temporizador({ prazo, className = "" }: { prazo: number | null; className?: string }) {
  const [seg, setSeg] = useState<number | null>(() => restante(prazo))
  useEffect(() => {
    setSeg(restante(prazo))
    if (prazo === null) return
    const id = setInterval(() => setSeg(restante(prazo)), 500)
    return () => clearInterval(id)
  }, [prazo])
  if (seg === null) return null
  const m = Math.floor(seg / 60)
  const s = seg % 60
  const urgente = seg <= 10
  return (
    <span
      className={`font-mono tabular-nums ${urgente ? "piscando" : ""} ${className}`}
      style={{ color: urgente ? "var(--status-vida)" : undefined }}
      aria-label={`Tempo restante ${m} minutos e ${s} segundos`}
    >
      ⏱ {m}:{s.toString().padStart(2, "0")}
    </span>
  )
}
