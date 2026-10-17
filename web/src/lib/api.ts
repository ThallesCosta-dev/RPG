import type { Cartuchos, RespostaCriarSala, RespostaEntrar, RespostaLobby } from "../types"

export const MOCK = import.meta.env.VITE_MOCK === "1"

export class ErroApi extends Error {
  constructor(public status: number, mensagem: string, public detalhes?: unknown) {
    super(mensagem)
  }
}

async function requisitar<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } })
  if (!resp.ok) {
    let detalhes: unknown = undefined
    let msg = `${resp.status} ${resp.statusText}`
    try {
      detalhes = await resp.json()
      if (detalhes && typeof detalhes === "object" && "detail" in detalhes) {
        const d = (detalhes as { detail: unknown }).detail
        msg = typeof d === "string" ? d : JSON.stringify(d)
      }
    } catch {
      /* corpo não é JSON */
    }
    throw new ErroApi(resp.status, msg, detalhes)
  }
  return (await resp.json()) as T
}

async function mock() {
  return (await import("../dev/mock")).apiMock
}

export const api = {
  async cartuchos(): Promise<Cartuchos> {
    if (MOCK) return (await mock()).cartuchos()
    return requisitar<Cartuchos>("/api/cartuchos")
  },
  async criarSala(corpo: { nome_host: string; sistema_id: string; campanha_id: string }): Promise<RespostaCriarSala> {
    if (MOCK) return (await mock()).criarSala(corpo)
    return requisitar<RespostaCriarSala>("/api/salas", { method: "POST", body: JSON.stringify(corpo) })
  },
  async lobby(salaId: string, convite: string): Promise<RespostaLobby> {
    if (MOCK) return (await mock()).lobby(salaId)
    return requisitar<RespostaLobby>(`/api/salas/${encodeURIComponent(salaId)}/lobby?convite=${encodeURIComponent(convite)}`)
  },
  async entrar(salaId: string, corpo: { convite: string; nome: string; personagem_id: string }): Promise<RespostaEntrar> {
    if (MOCK) return (await mock()).entrar(corpo)
    return requisitar<RespostaEntrar>(`/api/salas/${encodeURIComponent(salaId)}/entrar`, { method: "POST", body: JSON.stringify(corpo) })
  },
  async novoConvite(salaId: string, token: string): Promise<{ convite: string }> {
    if (MOCK) return { convite: "MOCK-CONVITE" }
    return requisitar<{ convite: string }>(`/api/salas/${encodeURIComponent(salaId)}/convites`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    })
  },
  async debug(salaId: string, token: string): Promise<unknown> {
    if (MOCK) return { mock: true, chamadas_llm: [], intencoes_rejeitadas: [], cota: { usado: 0 } }
    return requisitar<unknown>(`/api/salas/${encodeURIComponent(salaId)}/debug`, { headers: { Authorization: `Bearer ${token}` } })
  },
}

/** Extrai {salaId, convite} de um link `/sala/<id>?convite=<codigo>` (ou URL completa). */
export function interpretarConvite(texto: string): { salaId: string; convite: string } | null {
  const t = texto.trim()
  try {
    const url = new URL(t, window.location.origin)
    const m = url.pathname.match(/\/sala\/([^/]+)/)
    const convite = url.searchParams.get("convite")
    if (m && convite) return { salaId: decodeURIComponent(m[1]), convite }
  } catch {
    /* não é URL */
  }
  return null
}
