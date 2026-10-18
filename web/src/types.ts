// Tipos do contrato cliente ↔ servidor (docs/CONTRATO_CLIENTE.md). Nomes de campo seguem o contrato.

export type Modo = "exploracao" | "combate"
export type Fase = "lobby" | "planejamento" | "resolvendo" | "narrando" | "pausado"
export type Papel = "host" | "jogador" | "espectador"
export type Faccao = "aliado" | "inimigo" | "neutro"
export type MetricaDiagonal = "1-1-1" | "1-2-1-2" | "manhattan"
export type Coord = [number, number]
export type Tema = "medieval" | "cyberpunk" | "terror"

// ---------- Estado da sala ----------

export interface Cena {
  id: string
  nome: string
  descricao: string
  tema: string
  tilemap: string[] // tilemap[y][x]; símbolos: # . P ~ ^ C D
  largura: number
  altura: number
  imagem_url: string | null
}

export interface Obstaculo {
  x: number
  y: number
  tipo: string
  rodadas_restantes: number
}

export interface Jogador {
  player_id: string
  nome: string
  papel: Papel
  personagem_id: string | null
  conectado: boolean
}

export interface Barra {
  atual: number
  max: number
}

export interface Ataque {
  id: string
  nome: string
  bonus: number
  dano: string
  tipo_dano: string
  alcance: number
  margem_critico?: number
  mult_critico?: number
  condicoes_ao_acertar?: string[]
}

export interface Condicao {
  id: string
  rodadas_restantes: number | null
}

export interface Personagem {
  id: string
  nome: string
  tipo: "jogador" | "npc"
  faccao: Faccao
  x: number
  y: number
  barras: Record<string, Barra>
  defesa: number
  deslocamento: number
  iniciativa_bonus: number
  ataques: Ataque[]
  pericias: Record<string, number>
  condicoes: Condicao[]
  caido: boolean
  voz: string | null
  postura: string | null
  cor: string
  icone: string
  // Campos extras das fichas criadas pelos jogadores (§7); ausentes nos NPCs e nos modelos da campanha.
  classe?: string
  atributos?: Record<string, number>
  historia?: string
}

export interface LinhaCronica {
  rodada: number
  id: string
  texto: string
}

export interface Memoria {
  resumo: string
  fatos: string[]
  npcs_conhecidos: Record<string, string>
  missoes_abertas: string[]
  atualizado_na_rodada: number
}

export interface Estado {
  sala_id: string
  rodada: number
  modo: Modo
  cena: Cena
  obstaculos: Obstaculo[]
  personagens: Record<string, Personagem>
  iniciativa: string[]
  jogadores: Record<string, Jogador>
  memoria: Memoria | null
  cronica: LinhaCronica[]
  chat: ChatMessage[] // últimas 60 mensagens (§6); sem `audio_url`
}

// ---------- Chat (§6) ----------

export interface ChatMessage {
  id: string
  de: string // player_id ou npc_id
  nome: string
  personagem_id: string | null
  texto: string
  para: string | null // null = mesa; npc_id quando dirigida a um NPC (ou personagem_id do jogador na resposta do NPC)
  npc: boolean
  ts: number // epoch em segundos
  audio_url?: string | null
  voz?: string | null
  por_host?: boolean
  rodada?: number
}

// ---------- system_config.json (§5.2) ----------

export interface BarraStatus {
  id: string
  nome: string
  cor_token: string // ex.: "--status-vida"
}

export interface SlotConfig {
  id: string
  label: string
  icone?: string
  tipos_permitidos?: string[]
  vinculado_ao_grid?: boolean
}

export interface SystemConfig {
  sistema_id: string
  sistema_nome: string
  versao_compilacao?: number
  grid: {
    tamanho_quadrado_metros: number
    metrica_diagonal: MetricaDiagonal
    terreno_dificil_multiplicador: number
  }
  atributos_principais?: string[]
  campo_defesa: string
  barras_status: BarraStatus[]
  iniciativa: { expressao: string }
  ataque: { expressao: string; compara_com: string }
  critico?: { margem_padrao: number; multiplicador_padrao: number; modo: string }
  tabela_dificuldade?: Record<string, number>
  slots_de_acao_por_turno: SlotConfig[]
}

export interface Eu {
  player_id: string
  papel: Papel
  personagem_id: string | null
}

// ---------- Ação declarada ----------

export type Slot =
  | { tipo: "ataque"; ataque_id: string; alvo_id: string; rolagem_id?: string }
  | { tipo: "pericia"; pericia: string; texto?: string }
  | { tipo: "criativa"; texto: string }
  | { tipo: "fala"; texto: string }
  | { tipo: "defender" }
  | { tipo: "esperar" }

export type TipoSlot = Slot["tipo"]

export interface AcaoDeclarada {
  movimento?: { destino: Coord }
  slots: Record<string, Slot>
}

// ---------- Rolagens ----------

export interface TermoRolagem {
  termo: string
  dados?: number[]
  mantidos?: number[]
}

export interface Rolagem {
  expressao: string
  total: number
  termos: TermoRolagem[]
  id?: string // interpretação: o servidor pode mandar o id da rolagem aqui ou em `rolagem_id`
}

// ---------- Eventos brutos ----------

export type Evento =
  | { tipo: "movimento"; personagem: string; de: Coord; para: Coord; caminho: Coord[] }
  | {
      tipo: "ataque"
      atacante: string
      alvo: string
      ataque: string
      rolagem: Rolagem | number
      defesa: number
      acertou: boolean
      critico: boolean
    }
  | { tipo: "dano"; alvo: string; valor: number; tipo_dano: string; barra: string }
  | { tipo: "cura"; alvo: string; valor: number; barra: string }
  | { tipo: "condicao"; alvo: string; condicao: string; rodadas: number | null }
  | { tipo: "condicao_removida"; alvo: string; condicao: string }
  | { tipo: "caiu"; personagem: string }
  | { tipo: "levantou"; personagem: string }
  | {
      tipo: "teste"
      personagem: string
      pericia: string
      cd: number
      rolagem: Rolagem | number
      sucesso: boolean
    }
  | { tipo: "fala"; personagem: string; texto: string }
  | {
      tipo: "obstaculo_adicionado"
      x: number
      y: number
      // O contrato usa `tipo` para o tipo do obstáculo, que colide com o discriminador.
      // Aceitamos `tipo_obstaculo` ou `obstaculo` como nome do campo.
      tipo_obstaculo?: string
      obstaculo?: string
      duracao_rodadas: number
    }
  | { tipo: "obstaculo_removido"; x: number; y: number }
  | { tipo: "combate_iniciado"; ordem: string[] }
  | { tipo: "combate_encerrado" }
  | { tipo: "cena_mudou"; cena_id: string }
  | { tipo: "intencao_rejeitada"; npc: string; motivo: string }

export interface AcaoDoLog {
  id: string // e1, e2…
  ator_id: string
  texto: string
  eventos: Evento[]
}

// ---------- WebSocket: servidor → cliente ----------

export interface MsgRoomState {
  type: "room_state"
  state: Estado
  fase: Fase
  prazo: number | null
  config: SystemConfig
  eu: Eu
  nivel_ia: number
}
export interface MsgPhase {
  type: "phase"
  fase: Fase
  prazo?: number | null
  modo: Modo
}
export type CelulaAlcance = [number, number, number] // x, y, custo
export interface MsgAlcance {
  type: "alcance"
  personagem_id: string
  celulas: CelulaAlcance[]
}
export interface MsgPlayerPreview {
  type: "player_preview"
  player_id: string
  personagem_id: string
  caminho: Coord[]
  custo: number
}
export interface MsgDiceResult {
  type: "dice_result"
  player_id: string
  slot_id: string
  rolagem: Rolagem
  rolagem_id?: string
}
export interface MsgReadyStatus {
  type: "ready_status"
  prontos: string[]
  total: number
  prazo: number | null
}
export interface MsgRoundLog {
  type: "round_log"
  rodada: number
  modo: Modo
  acoes: AcaoDoLog[]
}
export interface MsgNarrationSegment {
  type: "narration_segment"
  seq: number
  voz: string
  texto: string
  eventos: string[]
  audio_url: string | null
}
export interface MsgNarrationEnd {
  type: "narration_end"
  rodada: number
}
export interface MsgStateSync {
  type: "state_sync"
  state: Estado
}
export interface MsgSceneImage {
  type: "scene_image"
  cena_id: string
  imagem_url: string
}
export interface MsgNivelIa {
  type: "nivel_ia"
  nivel: 1 | 2 | 3 | 4
  provedor: string
}
export interface MsgError {
  type: "error"
  code: string
  msg?: string
  detalhes?: unknown
}
export interface MsgPong {
  type: "pong"
  t?: number
}
export interface MsgChatMessage extends ChatMessage {
  type: "chat_message"
}
export interface MsgChatTyping {
  type: "chat_typing"
  personagem_id: string
  nome: string
  fim?: boolean
}

export type MsgServidor =
  | MsgRoomState
  | MsgPhase
  | MsgAlcance
  | MsgPlayerPreview
  | MsgDiceResult
  | MsgReadyStatus
  | MsgRoundLog
  | MsgNarrationSegment
  | MsgNarrationEnd
  | MsgStateSync
  | MsgSceneImage
  | MsgNivelIa
  | MsgError
  | MsgPong
  | MsgChatMessage
  | MsgChatTyping

// ---------- WebSocket: cliente → servidor ----------

export type NivelIa = 1 | 2 | 3 | 4

export type ComandoHost =
  | { comando: "iniciar" }
  | { comando: "pausar" }
  | { comando: "retomar" }
  | { comando: "resolver_agora" }
  | { comando: "desfazer_rodada" }
  | { comando: "iniciar_combate" }
  | { comando: "encerrar_combate" }
  | { comando: "mudar_cena"; cena_id: string }
  | {
      comando: "editar_personagem"
      personagem_id: string
      campos: {
        x?: number
        y?: number
        barras?: Record<string, Barra>
        condicoes?: Condicao[]
        caido?: boolean
      }
    }
  | { comando: "mudar_nivel_ia"; nivel: NivelIa }
  | { comando: "nova_narracao" }
  | { comando: "falar_como_npc"; personagem_id: string; texto: string }

export interface MsgChat {
  type: "chat"
  texto: string // ≤ 500
  para: string | null // null = mesa; npc_id exige ter personagem
}

export type MsgCliente =
  | MsgChat
  | { type: "preview_move"; destino: Coord }
  | { type: "roll"; slot_id: string; expressao: string }
  | { type: "confirm_turn"; acao: AcaoDeclarada }
  | { type: "unconfirm_turn" }
  | ({ type: "host_command" } & ComandoHost)
  | { type: "ping" }

// ---------- HTTP ----------

export interface Cartuchos {
  sistemas: { id: string; nome: string; revisado: boolean }[]
  campanhas: { id: string; nome: string; tema: string; sistema_id: string; revisado: boolean }[]
}

export interface RespostaCriarSala {
  sala_id: string
  token: string
  player_id: string
  convite: string
}

export type OrigemPersonagem = "campanha" | "sala" | "salva"

export interface PersonagemDisponivel {
  id: string
  nome: string
  origem?: OrigemPersonagem
  classe?: string
  icone?: string
  cor?: string
  [extra: string]: unknown
}

export interface RespostaLobby {
  sala_id: string
  campanha: string
  tema: string
  /** Interpretação: o servidor devolve o `sistema_id` da sala neste campo (não consta do contrato). */
  sistema?: string
  personagens_disponiveis: PersonagemDisponivel[]
  jogadores: Jogador[] | Partial<Jogador>[] | Record<string, Jogador>
}

export interface RespostaEntrar {
  token: string
  player_id: string
}

// ---------- Fichas (§7) ----------

export type Intervalo = [number, number]

export interface LimitesFicha {
  atributo: Intervalo
  pv: Intervalo
  barra: Intervalo
  defesa: Intervalo
  deslocamento: Intervalo
  iniciativa_bonus: Intervalo
  pericia: Intervalo
  bonus_ataque: Intervalo
  alcance: Intervalo
  max_ataques: number
  max_pericias: number
  nome: number
  classe: number
  icone: number
  historia: number
}

export interface ModeloFicha {
  sistema_id: string
  sistema_nome: string
  atributos: string[]
  pericias: string[]
  barras: { id: string; nome: string }[]
  campo_defesa: string
  tipos_dano: string[]
  icones: string[]
  limites: LimitesFicha
  expressao_ataque: string
  exemplo_dano: string
  monstros_modelo?: { id: string; nome: string }[]
}

export interface AtaqueEnvio {
  nome: string
  bonus: number
  dano: string // ex.: "1d8+3"
  tipo_dano: string
  alcance: number
}

export interface FichaEnvio {
  nome: string
  classe?: string
  icone?: string
  cor?: string // #rrggbb
  historia?: string
  atributos: Record<string, number>
  barras: Record<string, number> // id da barra → máximo
  defesa: number
  deslocamento: number
  iniciativa_bonus: number
  pericias: Record<string, number> // só perícias do modelo
  ataques: AtaqueEnvio[]
}

export interface RespostaCriarFicha {
  personagem_id: string
  ficha: Personagem
}

export interface FichaSalva {
  id: string
  nome: string
  classe: string
  icone: string
  cor: string
}
