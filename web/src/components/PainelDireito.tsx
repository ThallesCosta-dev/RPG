import { useEffect, useState } from "react"
import { useSala } from "../store/useSala"
import Cronica from "./Cronica"
import Chat from "./Chat"

type Aba = "cronica" | "chat"

/** Painel superior da coluna direita: abas Crônica / Chat (com badge de não lidas). */
export default function PainelDireito() {
  const [aba, setAba] = useState<Aba>("cronica")
  const naoLidas = useSala((s) => s.chatNaoLidas)
  const narrando = useSala((s) => s.narrando)
  const pendentes = useSala((s) => s.segmentosPendentes)
  const pular = useSala((s) => s.pularNarracao)
  const setChatVisivel = useSala((s) => s.setChatVisivel)

  useEffect(() => {
    setChatVisivel(aba === "chat")
    return () => setChatVisivel(false)
  }, [aba, setChatVisivel])

  const abaBtn = (id: Aba, rotulo: string, badge?: number) => (
    <button
      role="tab"
      id={`aba-${id}`}
      aria-selected={aba === id}
      aria-controls={`painel-${id}`}
      className={`aba ${aba === id ? "aba-ativa" : ""}`}
      onClick={() => setAba(id)}
    >
      {rotulo}
      {badge ? (
        <span className="badge" aria-label={`${badge} mensagens não lidas`}>
          {badge > 99 ? "99+" : badge}
        </span>
      ) : null}
    </button>
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-1 border-b px-2 py-1" style={{ borderColor: "var(--painel-borda)" }} role="tablist" aria-label="Crônica e chat">
        {abaBtn("cronica", "Crônica")}
        {abaBtn("chat", "Chat", aba === "chat" ? 0 : naoLidas)}
        {narrando && (
          <button className="botao ml-auto px-2 py-0.5 text-xs" onClick={pular} title="Esvazia a fila e aplica as animações pendentes">
            ⏭ Pular{pendentes > 0 ? ` (${pendentes})` : ""}
          </button>
        )}
      </div>
      <div id={`painel-${aba}`} role="tabpanel" aria-labelledby={`aba-${aba}`} className="flex min-h-0 flex-1 flex-col">
        {aba === "cronica" ? <Cronica semCabecalho /> : <Chat />}
      </div>
    </div>
  )
}
