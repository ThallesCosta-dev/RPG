import { create } from "zustand"
import type {
  AcaoDeclarada,
  CelulaAlcance,
  ChatMessage,
  Coord,
  Estado,
  Eu,
  Fase,
  MsgCliente,
  MsgRoundLog,
  MsgServidor,
  Rolagem,
  Slot,
  SystemConfig,
  Tema,
} from "../types"
import { FilaNarracao, type Segmento } from "../lib/narracao"
import { aplicarEvento } from "../lib/eventos"
import { barramento } from "../lib/animacoes"
import { storage } from "../lib/storage"
import { aplicarTema, temaEfetivo } from "../lib/tema"
import { SLOT_LIVRE_DADO } from "../lib/dados"
import type { Conexao, StatusConexao } from "../lib/ws"
import { useToast } from "./useToast"

export interface Preview {
  player_id: string
  personagem_id: string
  caminho: Coord[]
  custo: number
}

export type ItemCronica =
  | { tipo: "legenda"; rodada: number; seq: number; voz: string; texto: string }
  | { tipo: "rolagem"; rodada: number; player_id: string; slot_id: string; rolagem: Rolagem; chave: number }
  | { tipo: "acao"; rodada: number; id: string; ator_id: string; texto: string }
  | { tipo: "sistema"; rodada: number; texto: string }

export interface SlotEditor {
  tipo: string
  ataque_id?: string
  alvo_id?: string
  pericia?: string
  texto: string
}

export interface SalaStore {
  salaId: string | null
  conexao: StatusConexao
  motivoConexao: string | null
  state: Estado | null
  statePendente: Estado | null
  fase: Fase
  prazo: number | null
  /** Troca de fase recebida enquanto a narração ainda tocava; aplicada no fim da fila. */
  fasePendente: { fase: Fase; prazo: number | null } | null
  config: SystemConfig | null
  eu: Eu | null
  nivelIa: number
  provedorIa: string | null
  tema: Tema

  alcance: CelulaAlcance[]
  previews: Record<string, Preview>
  meuDestino: Coord | null
  rolagensPorSlot: Record<string, { rolagem: Rolagem; rolagem_id?: string }>
  prontos: string[]
  totalProntos: number
  confirmado: boolean

  roundLog: MsgRoundLog | null
  itensCronica: ItemCronica[]
  narrando: boolean
  vozAtual: string | null
  segmentosPendentes: number

  planejamento: Record<string, SlotEditor>
  slotAtivo: string | null
  alvosRealcados: string[]
  selecionado: string | null

  volume: number
  mudo: boolean

  // chat (§6)
  chat: ChatMessage[]
  /** NPC que está respondendo (após `chat_typing`, até a `chat_message` dele ou `fim: true`). */
  digitando: { personagem_id: string; nome: string } | null
  chatNaoLidas: number
  chatVisivel: boolean

  // ações
  iniciarSala(salaId: string): void
  setConexao(status: StatusConexao, motivo?: string): void
  setConexaoObj(c: Conexao | null): void
  enviar(msg: MsgCliente): void
  receber(msg: MsgServidor): void
  definirSlot(slotId: string, patch: Partial<SlotEditor>): void
  setSlotAtivo(slotId: string | null): void
  setAlvosRealcados(ids: string[]): void
  selecionarToken(id: string | null): void
  confirmarTurno(acao: AcaoDeclarada): void
  desfazerConfirmacao(): void
  pularNarracao(): void
  setVolume(v: number): void
  setMudo(m: boolean): void
  setTemaOverride(t: Tema | null): void
  enviarChat(texto: string, para: string | null): boolean
  setChatVisivel(v: boolean): void
}

const CHAT_MAX_LOCAL = 200
const MENSAGEM_ERRO: Record<string, string> = {
  npc_ocupado: "O NPC está ocupado: espere a resposta ou o fim da rodada.",
  npc_invalido: "Esse NPC não está na cena.",
  sem_personagem: "Só quem tem personagem pode falar com NPCs.",
  mensagem_invalida: "Mensagem vazia.",
}

let conexaoAtual: Conexao | null = null
let chaveRolagem = 1

const narracao = new FilaNarracao({
  aoIniciar(seg: Segmento, instantaneo: boolean) {
    const s = useSala.getState()
    if (seg.chat) {
      // Fala de NPC do chat: só a voz (a mensagem já está no painel de chat); nada de eventos nem Crônica.
      if (!instantaneo) useSala.setState({ vozAtual: seg.voz, segmentosPendentes: narracao.pendentes })
      return
    }
    const rodada = s.roundLog?.rodada ?? s.state?.rodada ?? 0
    let state = s.state
    const animadas = new Set(acoesAnimadas)
    for (const id of seg.eventos) {
      const acao = s.roundLog?.acoes.find((a) => a.id === id)
      if (!acao) continue
      animadas.add(id)
      for (const ev of acao.eventos) {
        if (state) state = aplicarEvento(state, ev)
        barramento.emitir(ev, instantaneo)
      }
    }
    acoesAnimadas = animadas
    useSala.setState({
      state,
      vozAtual: instantaneo ? s.vozAtual : seg.voz,
      segmentosPendentes: narracao.pendentes,
      itensCronica: [...s.itensCronica, { tipo: "legenda", rodada, seq: seg.seq, voz: seg.voz, texto: seg.texto }],
    })
  },
  aoTerminarSegmento() {
    const s = useSala.getState()
    // Fora da narração (fala de NPC do chat), a voz some ao fim do áudio; o próximo segmento a redefine.
    useSala.setState({ segmentosPendentes: narracao.pendentes, vozAtual: s.narrando ? s.vozAtual : null })
  },
  aoFimDaFila() {
    const s = useSala.getState()
    if (!s.narrando) {
      // Só falas de chat tocaram: não há rodada para fechar (nem round_log para reaplicar).
      useSala.setState({ vozAtual: null, segmentosPendentes: 0 })
      return
    }
    // Ações do round_log que nenhum segmento referenciou: anima de uma vez.
    let state = s.state
    for (const acao of s.roundLog?.acoes ?? []) {
      if (acoesAnimadas.has(acao.id)) continue
      for (const ev of acao.eventos) {
        if (state) state = aplicarEvento(state, ev)
        barramento.emitir(ev, true)
      }
    }
    acoesAnimadas = new Set()
    const fp = s.fasePendente
    useSala.setState({
      state: s.statePendente ?? state,
      statePendente: null,
      narrando: false,
      vozAtual: null,
      segmentosPendentes: 0,
      fasePendente: null,
      ...(fp ? { fase: fp.fase, prazo: fp.prazo } : {}),
    })
  },
})
let acoesAnimadas = new Set<string>()

const limpezaDePlanejamento = {
  alcance: [] as CelulaAlcance[],
  previews: {} as Record<string, Preview>,
  meuDestino: null as Coord | null,
  rolagensPorSlot: {} as Record<string, { rolagem: Rolagem; rolagem_id?: string }>,
  prontos: [] as string[],
  confirmado: false,
  planejamento: {} as Record<string, SlotEditor>,
  alvosRealcados: [] as string[],
}

export const useSala = create<SalaStore>((set, get) => ({
  salaId: null,
  conexao: "conectando",
  motivoConexao: null,
  state: null,
  statePendente: null,
  fase: "lobby",
  prazo: null,
  fasePendente: null,
  config: null,
  eu: null,
  nivelIa: 0,
  provedorIa: null,
  tema: temaEfetivo(null),

  ...limpezaDePlanejamento,
  totalProntos: 0,

  roundLog: null,
  itensCronica: [],
  narrando: false,
  vozAtual: null,
  segmentosPendentes: 0,

  slotAtivo: null,
  selecionado: null,

  volume: storage.volume(),
  mudo: storage.mudo(),

  chat: [],
  digitando: null,
  chatNaoLidas: 0,
  chatVisivel: false,

  iniciarSala(salaId) {
    narracao.limpar()
    narracao.ajustarVolume(get().volume, get().mudo)
    const info = storage.campanhaInfo(salaId)
    const tema = temaEfetivo(info?.tema)
    aplicarTema(tema)
    set({
      salaId,
      state: null,
      statePendente: null,
      fase: "lobby",
      prazo: null,
      fasePendente: null,
      config: null,
      eu: null,
      roundLog: null,
      itensCronica: [],
      narrando: false,
      vozAtual: null,
      segmentosPendentes: 0,
      selecionado: null,
      slotAtivo: null,
      tema,
      chat: [],
      digitando: null,
      chatNaoLidas: 0,
      ...limpezaDePlanejamento,
    })
  },

  setConexao(status, motivo) {
    set({ conexao: status, motivoConexao: motivo ?? null })
    if (motivo && (status === "encerrado" || status === "desconectado")) useToast.getState().mostrar(motivo, "erro", 4000)
  },

  setConexaoObj(c) {
    conexaoAtual = c
  },

  enviar(msg) {
    conexaoAtual?.enviar(msg)
  },

  receber(msg) {
    const s = get()
    switch (msg.type) {
      case "room_state": {
        // Reconexão: substitui o estado inteiro e zera a narração local.
        narracao.limpar()
        acoesAnimadas = new Set()
        const tema = temaEfetivo(msg.state.cena?.tema ?? storage.campanhaInfo(msg.state.sala_id)?.tema)
        aplicarTema(tema)
        set({
          state: msg.state,
          statePendente: null,
          fase: msg.fase,
          prazo: msg.prazo ?? null,
          fasePendente: null,
          config: msg.config,
          eu: msg.eu,
          nivelIa: msg.nivel_ia,
          tema,
          narrando: false,
          vozAtual: null,
          segmentosPendentes: 0,
          roundLog: null,
          chat: msg.state.chat ?? [],
          digitando: null,
          chatNaoLidas: 0,
          ...limpezaDePlanejamento,
          totalProntos: 0,
        })
        break
      }
      case "chat_message": {
        const { type: _t, ...m } = msg
        void _t
        if (s.chat.some((c) => c.id === m.id)) break
        const chat = [...s.chat, m].slice(-CHAT_MAX_LOCAL)
        const terminouDeResponder = m.npc && s.digitando?.personagem_id === m.personagem_id
        const minha = !m.npc && m.de === s.eu?.player_id
        set({
          chat,
          digitando: terminouDeResponder ? null : s.digitando,
          chatNaoLidas: s.chatVisivel || minha ? s.chatNaoLidas : s.chatNaoLidas + 1,
        })
        // Voz do NPC entra na mesma fila da narração (depois do que estiver tocando), sem bloquear o chat.
        if (m.npc && m.audio_url && m.personagem_id) narracao.enfileirarChat(m.id, m.personagem_id, m.texto, m.audio_url)
        break
      }
      case "chat_typing":
        set({ digitando: msg.fim ? null : { personagem_id: msg.personagem_id, nome: msg.nome } })
        break
      case "phase": {
        const prazo = msg.prazo === undefined ? s.prazo : msg.prazo
        const state = s.state ? { ...s.state, modo: msg.modo } : s.state
        const limpeza = msg.fase === "planejamento" ? limpezaDePlanejamento : {}
        if (s.narrando && msg.fase !== "narrando" && msg.fase !== "pausado" && narracao.pendentes > 0) {
          // A narração ainda está tocando: limpa o planejamento anterior agora, mas só troca de fase no fim da fila.
          set({ state, ...limpeza, fasePendente: { fase: msg.fase, prazo } })
        } else {
          if (s.narrando) narracao.pular() // aplica o state_sync pendente antes de trocar a fase
          const atual = get().state
          set({ fase: msg.fase, prazo, state: atual ? { ...atual, modo: msg.modo } : null, ...limpeza, fasePendente: null })
        }
        break
      }
      case "alcance":
        if (msg.personagem_id === s.eu?.personagem_id) set({ alcance: msg.celulas })
        break
      case "player_preview": {
        const preview: Preview = {
          player_id: msg.player_id,
          personagem_id: msg.personagem_id,
          caminho: msg.caminho,
          custo: msg.custo,
        }
        const minha = msg.player_id === s.eu?.player_id
        const destino = msg.caminho.length > 0 ? msg.caminho[msg.caminho.length - 1] : null
        set({
          previews: { ...s.previews, [msg.personagem_id]: preview },
          meuDestino: minha ? destino : s.meuDestino,
        })
        break
      }
      case "dice_result": {
        // Durante o planejamento, a rolagem pertence à rodada que está sendo planejada (a próxima).
        const rodada = (s.state?.rodada ?? 0) + (s.fase === "planejamento" ? 1 : 0)
        const item: ItemCronica = {
          tipo: "rolagem",
          rodada,
          player_id: msg.player_id,
          slot_id: msg.slot_id,
          rolagem: msg.rolagem,
          chave: chaveRolagem++,
        }
        const minha = msg.player_id === s.eu?.player_id && msg.slot_id !== SLOT_LIVRE_DADO
        set({
          itensCronica: [...s.itensCronica, item],
          rolagensPorSlot: minha
            ? { ...s.rolagensPorSlot, [msg.slot_id]: { rolagem: msg.rolagem, rolagem_id: msg.rolagem_id ?? msg.rolagem.id } }
            : s.rolagensPorSlot,
        })
        break
      }
      case "ready_status":
        set({
          prontos: msg.prontos,
          totalProntos: msg.total,
          prazo: msg.prazo ?? s.prazo,
          confirmado: s.eu ? msg.prontos.includes(s.eu.player_id) : s.confirmado,
        })
        break
      case "round_log": {
        narracao.iniciarRodada()
        acoesAnimadas = new Set()
        const itens: ItemCronica[] = msg.acoes.map((a) => ({
          tipo: "acao",
          rodada: msg.rodada,
          id: a.id,
          ator_id: a.ator_id,
          texto: a.texto,
        }))
        set({ roundLog: msg, narrando: true, itensCronica: [...s.itensCronica, ...itens] })
        break
      }
      case "narration_segment":
        if (!s.narrando) {
          narracao.iniciarRodada()
          set({ narrando: true })
        }
        narracao.enfileirar({
          seq: msg.seq,
          voz: msg.voz,
          texto: msg.texto,
          eventos: msg.eventos ?? [],
          audio_url: msg.audio_url,
        })
        set({ segmentosPendentes: narracao.pendentes })
        break
      case "narration_end":
        narracao.encerrar()
        break
      case "state_sync":
        if (s.narrando) set({ statePendente: msg.state })
        else set({ state: msg.state, statePendente: null })
        break
      case "scene_image":
        if (s.state && s.state.cena.id === msg.cena_id) {
          set({ state: { ...s.state, cena: { ...s.state.cena, imagem_url: msg.imagem_url } } })
        }
        break
      case "nivel_ia":
        set({ nivelIa: msg.nivel, provedorIa: msg.provedor })
        break
      case "error": {
        const amigavel = MENSAGEM_ERRO[msg.code]
        useToast.getState().mostrar(amigavel ?? (msg.msg ? `${msg.code}: ${msg.msg}` : `Erro: ${msg.code}`), "erro")
        if (msg.code === "npc_ocupado" || msg.code === "npc_invalido" || msg.code === "sem_personagem") set({ digitando: null })
        break
      }
      case "pong":
        break
      default:
        break
    }
  },

  definirSlot(slotId, patch) {
    const atual = get().planejamento[slotId] ?? { tipo: "", texto: "" }
    set({ planejamento: { ...get().planejamento, [slotId]: { ...atual, ...patch } } })
  },

  setSlotAtivo(slotId) {
    set({ slotAtivo: slotId })
  },

  setAlvosRealcados(ids) {
    const atuais = get().alvosRealcados
    if (atuais.length === ids.length && atuais.every((v, i) => v === ids[i])) return
    set({ alvosRealcados: ids })
  },

  selecionarToken(id) {
    set({ selecionado: id })
  },

  confirmarTurno(acao) {
    get().enviar({ type: "confirm_turn", acao })
    set({ confirmado: true })
  },

  desfazerConfirmacao() {
    get().enviar({ type: "unconfirm_turn" })
    set({ confirmado: false })
  },

  pularNarracao() {
    if (get().narrando) narracao.pular()
  },

  setVolume(v) {
    storage.setVolume(v)
    narracao.ajustarVolume(v, get().mudo)
    set({ volume: v })
  },

  setMudo(m) {
    storage.setMudo(m)
    narracao.ajustarVolume(get().volume, m)
    set({ mudo: m })
  },

  setTemaOverride(t) {
    storage.setTema(t)
    const tema = temaEfetivo(get().state?.cena.tema)
    aplicarTema(tema)
    set({ tema })
  },

  enviarChat(texto, para) {
    const t = texto.replace(/\s+/g, " ").trim().slice(0, 500)
    if (!t) return false
    const s = get()
    if (para && !s.eu?.personagem_id) {
      useToast.getState().mostrar(MENSAGEM_ERRO.sem_personagem, "erro")
      return false
    }
    s.enviar({ type: "chat", texto: t, para })
    return true
  },

  setChatVisivel(v) {
    set({ chatVisivel: v, chatNaoLidas: v ? 0 : get().chatNaoLidas })
  },
}))

/** Monta o Slot do contrato a partir do editor; devolve null se o slot estiver incompleto. */
export function montarSlot(editor: SlotEditor | undefined, rolagemId?: string): Slot | null {
  if (!editor || !editor.tipo) return null
  switch (editor.tipo) {
    case "ataque":
      if (!editor.ataque_id || !editor.alvo_id) return null
      return rolagemId
        ? { tipo: "ataque", ataque_id: editor.ataque_id, alvo_id: editor.alvo_id, rolagem_id: rolagemId }
        : { tipo: "ataque", ataque_id: editor.ataque_id, alvo_id: editor.alvo_id }
    case "pericia":
      if (!editor.pericia) return null
      return editor.texto.trim() ? { tipo: "pericia", pericia: editor.pericia, texto: editor.texto.trim() } : { tipo: "pericia", pericia: editor.pericia }
    case "criativa":
      return editor.texto.trim() ? { tipo: "criativa", texto: editor.texto.trim() } : null
    case "fala":
      return editor.texto.trim() ? { tipo: "fala", texto: editor.texto.trim() } : null
    case "defender":
      return { tipo: "defender" }
    case "esperar":
      return { tipo: "esperar" }
    default:
      return null
  }
}
