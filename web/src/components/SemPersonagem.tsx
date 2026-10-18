import { useCallback, useEffect, useState } from "react"
import { api } from "../lib/api"
import { useSala } from "../store/useSala"
import { useToast } from "../store/useToast"
import type { PersonagemDisponivel } from "../types"
import FichaForm from "./FichaForm"
import Modal from "./Modal"

export const ROTULO_ORIGEM: Record<string, string> = {
  campanha: "da campanha",
  sala: "criado nesta mesa",
  salva: "ficha salva",
}

interface Props {
  salaId: string
  token: string
}

type Visao = "fechado" | "escolher" | "criar"

/** Card "Você ainda não tem personagem" + modal para escolher um da lista do lobby ou criar pela ficha (§7). */
export default function SemPersonagem({ salaId, token }: Props) {
  const config = useSala((s) => s.config)
  const eu = useSala((s) => s.eu)
  const mostrar = useToast((s) => s.mostrar)
  const [visao, setVisao] = useState<Visao>("fechado")
  const [lista, setLista] = useState<PersonagemDisponivel[] | null>(null)
  const [erroLista, setErroLista] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState<string | null>(null)

  useEffect(() => {
    if (visao !== "escolher") return
    let cancelado = false
    setLista(null)
    setErroLista(null)
    api
      .lobby(salaId)
      .then((l) => !cancelado && setLista(l.personagens_disponiveis))
      .catch((e: Error) => !cancelado && setErroLista(e.message))
    return () => {
      cancelado = true
    }
  }, [visao, salaId])

  const fechar = useCallback(() => setVisao("fechado"), [])

  const escolher = async (id: string) => {
    setOcupado(id)
    try {
      await api.escolherPersonagem(salaId, id, token)
      mostrar("Personagem vinculado. Aguardando o estado da sala…", "ok", 3000)
      setVisao("fechado")
    } catch (e) {
      mostrar(`Não foi possível escolher: ${(e as Error).message}`, "erro")
    } finally {
      setOcupado(null)
    }
  }

  if (!config) return null
  const ehHost = eu?.papel === "host"

  return (
    <>
      <div className="painel pointer-events-auto max-w-md space-y-2 px-4 py-3 text-sm">
        <h2 className="text-base">Você ainda não tem personagem</h2>
        <p className="text-xs text-suave">
          {ehHost ? "Como Host você pode assistir, mas para agir na mesa precisa de um personagem." : "Escolha um personagem disponível ou crie a sua ficha para entrar em cena."}
        </p>
        <div className="flex gap-2">
          <button className="botao botao-primario" onClick={() => setVisao("escolher")}>
            👥 Escolher da lista
          </button>
          <button className="botao" onClick={() => setVisao("criar")}>
            📜 Criar minha ficha
          </button>
        </div>
      </div>

      {visao === "escolher" && (
        <Modal titulo="Escolher personagem" aoFechar={fechar} largura="max-w-md">
          {erroLista && <p style={{ color: "var(--status-vida)" }}>Não foi possível listar: {erroLista}</p>}
          {!lista && !erroLista && <p className="piscando text-suave">Carregando personagens…</p>}
          {lista && lista.length === 0 && <p className="text-suave">Nenhum personagem disponível. Crie a sua ficha.</p>}
          {lista && lista.length > 0 && (
            <ul className="space-y-1">
              {lista.map((p) => (
                <li key={p.id}>
                  <button
                    className="botao w-full justify-start gap-2 px-3 py-2 text-left"
                    disabled={ocupado !== null}
                    onClick={() => escolher(p.id)}
                  >
                    <span
                      className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
                      style={{ background: p.cor || "#666", border: "2px solid #4ade80", textShadow: "0 1px 2px #000" }}
                      aria-hidden
                    >
                      {p.icone || p.nome.charAt(0)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-semibold">{p.nome}</span>
                      <span className="block text-[11px] font-normal text-suave">
                        {p.classe ? `${p.classe} · ` : ""}
                        {ROTULO_ORIGEM[p.origem ?? ""] ?? p.origem ?? ""}
                      </span>
                    </span>
                    {ocupado === p.id && <span className="text-xs text-suave">…</span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-3 border-t pt-3" style={{ borderColor: "var(--painel-borda)" }}>
            <button className="botao w-full" onClick={() => setVisao("criar")}>
              📜 Prefiro criar minha ficha
            </button>
          </div>
        </Modal>
      )}

      {visao === "criar" && (
        <Modal titulo="Criar minha ficha" aoFechar={fechar} largura="max-w-3xl">
          <FichaForm
            sistemaId={config.sistema_id}
            aoCancelar={fechar}
            aoCriar={async (ficha) => {
              await api.criarFicha(salaId, { ficha }, token)
              mostrar("Ficha criada e vinculada. Aguardando o estado da sala…", "ok", 3000)
              setVisao("fechado")
            }}
          />
        </Modal>
      )}
    </>
  )
}
