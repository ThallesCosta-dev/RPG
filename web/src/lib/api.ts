import type {
  Cartuchos,
  FichaEnvio,
  FichaSalva,
  ModeloFicha,
  RespostaCriarFicha,
  RespostaCriarSala,
  RespostaEntrar,
  RespostaLobby,
} from "../types"

export const MOCK = import.meta.env.DEV && import.meta.env.VITE_MOCK === "1"

export class ErroApi extends Error {
  constructor(public status: number, mensagem: string, public detalhes?: unknown) {
    super(mensagem)
  }
}

/**
 * Lista de erros a partir do `detail` de um 400 (§7): o servidor manda uma string com os erros
 * separados por "; " (ou uma lista). Para outros erros, devolve a mensagem inteira.
 */
export function errosDoDetail(err: unknown): string[] {
  if (err instanceof ErroApi && err.detalhes && typeof err.detalhes === "object" && "detail" in err.detalhes) {
    const d = (err.detalhes as { detail: unknown }).detail
    if (Array.isArray(d)) return d.map((x) => (typeof x === "string" ? x : typeof x === "object" && x && "msg" in x ? String((x as { msg: unknown }).msg) : JSON.stringify(x)))
    if (typeof d === "string") return d.split(/;\s+/).map((x) => x.trim()).filter(Boolean)
  }
  return [err instanceof Error ? err.message : String(err)]
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

const comToken = (token: string | undefined | null): Record<string, string> => (token ? { Authorization: `Bearer ${token}` } : {})

async function mock() {
  return (await import("../dev/mock")).apiMock
}

export const api = {
  async cartuchos(): Promise<Cartuchos> {
    if (MOCK) return (await mock()).cartuchos()
    return requisitar<Cartuchos>("/api/cartuchos")
  },
  async criarSala(corpo: { nome_host: string; sistema_id: string; campanha_id: string; personagem_id?: string }): Promise<RespostaCriarSala> {
    if (MOCK) return (await mock()).criarSala(corpo)
    return requisitar<RespostaCriarSala>("/api/salas", { method: "POST", body: JSON.stringify(corpo) })
  },
  /** Sem `convite`, lista os personagens disponíveis para quem já está na mesa (card "sem personagem"). */
  async lobby(salaId: string, convite?: string | null): Promise<RespostaLobby> {
    if (MOCK) return (await mock()).lobby(salaId)
    const q = convite ? `?convite=${encodeURIComponent(convite)}` : ""
    return requisitar<RespostaLobby>(`/api/salas/${encodeURIComponent(salaId)}/lobby${q}`)
  },
  async entrar(salaId: string, corpo: { convite: string; nome: string; personagem_id: string | null }): Promise<RespostaEntrar> {
    if (MOCK) return (await mock()).entrar(corpo)
    return requisitar<RespostaEntrar>(`/api/salas/${encodeURIComponent(salaId)}/entrar`, { method: "POST", body: JSON.stringify(corpo) })
  },
  async novoConvite(salaId: string, token: string): Promise<{ convite: string }> {
    if (MOCK) return { convite: "MOCK-CONVITE" }
    return requisitar<{ convite: string }>(`/api/salas/${encodeURIComponent(salaId)}/convites`, {
      method: "POST",
      headers: comToken(token),
    })
  },
  async debug(salaId: string, token: string): Promise<unknown> {
    if (MOCK) return { mock: true, chamadas_llm: [], intencoes_rejeitadas: [], cota: { usado: 0 } }
    return requisitar<unknown>(`/api/salas/${encodeURIComponent(salaId)}/debug`, { headers: comToken(token) })
  },

  // ---------- Fichas (§7) ----------
  async modeloFicha(sistemaId: string): Promise<ModeloFicha> {
    if (MOCK) return (await mock()).modeloFicha(sistemaId)
    return requisitar<ModeloFicha>(`/api/sistemas/${encodeURIComponent(sistemaId)}/modelo-ficha`)
  },
  async fichasSalvas(sistemaId: string): Promise<FichaSalva[]> {
    if (MOCK) return (await mock()).fichasSalvas(sistemaId)
    return requisitar<FichaSalva[]>(`/api/sistemas/${encodeURIComponent(sistemaId)}/fichas`)
  },
  async apagarFichaSalva(sistemaId: string, fichaId: string): Promise<void> {
    if (MOCK) return
    await requisitar<{ ok: boolean }>(`/api/sistemas/${encodeURIComponent(sistemaId)}/fichas/${encodeURIComponent(fichaId)}`, { method: "DELETE" })
  },
  /**
   * Cria a ficha na sala. Com `token`: vincula na hora (o servidor manda novo `room_state`).
   * Com `convite`: a ficha fica disponível no lobby para `/entrar`.
   */
  async criarFicha(salaId: string, corpo: { convite?: string; ficha: FichaEnvio }, token?: string | null): Promise<RespostaCriarFicha> {
    if (MOCK) return (await mock()).criarFicha(salaId, corpo, token)
    return requisitar<RespostaCriarFicha>(`/api/salas/${encodeURIComponent(salaId)}/fichas`, {
      method: "POST",
      headers: comToken(token),
      body: JSON.stringify(corpo),
    })
  },
  /** Vincula um personagem disponível a quem ainda não tem (Host incluído). */
  async escolherPersonagem(salaId: string, personagemId: string, token: string): Promise<{ personagem_id: string }> {
    if (MOCK) return (await mock()).escolherPersonagem(salaId, personagemId, token)
    return requisitar<{ personagem_id: string }>(`/api/salas/${encodeURIComponent(salaId)}/personagem`, {
      method: "POST",
      headers: comToken(token),
      body: JSON.stringify({ personagem_id: personagemId }),
    })
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
