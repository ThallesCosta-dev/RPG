import type { MsgCliente, MsgServidor } from "../types"

export type StatusConexao = "conectando" | "conectado" | "desconectado" | "encerrado"

export interface HandlersConexao {
  aoReceber(msg: MsgServidor): void
  aoStatus(status: StatusConexao, motivo?: string): void
}

export interface Conexao {
  enviar(msg: MsgCliente): void
  fechar(): void
}

export type FabricaConexao = (salaId: string, token: string, handlers: HandlersConexao) => Conexao

const BACKOFF_MS = [1000, 2000, 4000, 8000, 15000]
const PING_MS = 20000
// Códigos de fechamento em que não faz sentido reconectar.
const CODIGOS_FINAIS: Record<number, string> = {
  4401: "Token inválido ou expirado.",
  4009: "Esta conexão foi substituída por outra aba.",
  4404: "Sala não encontrada.",
}

export function urlWs(salaId: string, token: string): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws"
  return `${proto}://${window.location.host}/ws/${encodeURIComponent(salaId)}?token=${encodeURIComponent(token)}`
}

/** Abre o WebSocket da sala com reconexão em backoff (1s, 2s, 4s… máx. 15s) e ping a cada 20s. */
export const conectarWs: FabricaConexao = (salaId, token, handlers) => {
  let ws: WebSocket | null = null
  let tentativa = 0
  let encerrado = false
  let timerReconexao: ReturnType<typeof setTimeout> | null = null
  let timerPing: ReturnType<typeof setInterval> | null = null

  const pararPing = () => {
    if (timerPing) clearInterval(timerPing)
    timerPing = null
  }

  const agendarReconexao = () => {
    if (encerrado) return
    const espera = BACKOFF_MS[Math.min(tentativa, BACKOFF_MS.length - 1)]
    tentativa += 1
    handlers.aoStatus("desconectado", `Reconectando em ${Math.round(espera / 1000)}s…`)
    timerReconexao = setTimeout(abrir, espera)
  }

  const abrir = () => {
    if (encerrado) return
    handlers.aoStatus("conectando")
    const sock = new WebSocket(urlWs(salaId, token))
    ws = sock
    sock.onopen = () => {
      tentativa = 0
      handlers.aoStatus("conectado")
      pararPing()
      timerPing = setInterval(() => {
        if (sock.readyState === WebSocket.OPEN) sock.send(JSON.stringify({ type: "ping" }))
      }, PING_MS)
    }
    sock.onmessage = (ev: MessageEvent<string>) => {
      try {
        const msg = JSON.parse(ev.data) as MsgServidor
        if (msg && typeof msg === "object" && typeof msg.type === "string") handlers.aoReceber(msg)
      } catch {
        /* mensagem inválida: ignora */
      }
    }
    sock.onclose = (ev: CloseEvent) => {
      pararPing()
      if (ws !== sock) return
      ws = null
      if (encerrado) return
      const motivoFinal = CODIGOS_FINAIS[ev.code]
      if (motivoFinal) {
        encerrado = true
        handlers.aoStatus("encerrado", motivoFinal)
        return
      }
      agendarReconexao()
    }
    sock.onerror = () => {
      /* onclose cuida da reconexão */
    }
  }

  abrir()

  return {
    enviar(msg) {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg))
      else handlers.aoStatus(ws ? "conectando" : "desconectado", "Sem conexão: a ação não foi enviada.")
    },
    fechar() {
      encerrado = true
      if (timerReconexao) clearTimeout(timerReconexao)
      pararPing()
      const sock = ws
      ws = null
      sock?.close(1000)
    },
  }
}

/** Escolhe a fábrica real ou o mock (`VITE_MOCK=1`), sem levar o mock para o bundle de produção. */
export async function obterFabricaConexao(): Promise<FabricaConexao> {
  if (import.meta.env.DEV && import.meta.env.VITE_MOCK === "1") return (await import("../dev/mock")).conectarMock
  return conectarWs
}
