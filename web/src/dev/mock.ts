// Mock do servidor para validar a UI sem backend (VITE_MOCK=1).
// Simula room_state com a cena da §10.2, alcance, previews, rolagens e o ciclo
// planejamento → resolvendo → round_log → narration_segment (sem áudio) → narration_end → state_sync,
// além do chat (§6: eco + resposta de NPC após 1 s) e das fichas (§7: modelo-ficha, fichas, personagem).
// Atalhos de URL: `?auto=1` resolve a rodada sozinho; `?sem_personagem=1` abre a mesa como Host sem personagem.

import type {
  AcaoDeclarada,
  AcaoDoLog,
  Cartuchos,
  ChatMessage,
  Coord,
  Estado,
  Evento,
  Fase,
  FichaEnvio,
  FichaSalva,
  ModeloFicha,
  MsgCliente,
  MsgServidor,
  Personagem,
  PersonagemDisponivel,
  RespostaCriarFicha,
  RespostaCriarSala,
  RespostaEntrar,
  RespostaLobby,
  Rolagem,
  SystemConfig,
} from "../types"
import type { Conexao, FabricaConexao, HandlersConexao } from "../lib/ws"
import { chave, custosDeMovimento } from "../lib/grid"
import { aplicarEvento } from "../lib/eventos"
import { ErroApi } from "../lib/api"
import { expressaoValida } from "../lib/dados"

const TILEMAP = [
  "####################",
  "#..................#",
  "#..P............P..#",
  "#..................#",
  "#..................#",
  "#..................#",
  "#..........CC......#",
  "D..................#",
  "#..................#",
  "#...........~~.....#",
  "#....^^^....~~.....#",
  "#....^^^....~~.....#",
  "#..P........~~..P..#",
  "#...........~~.....#",
  "#########DD#########",
]

export const CONFIG_MOCK: SystemConfig = {
  sistema_id: "tormenta20",
  sistema_nome: "Tormenta20",
  versao_compilacao: 1,
  grid: { tamanho_quadrado_metros: 1.5, metrica_diagonal: "1-2-1-2", terreno_dificil_multiplicador: 2 },
  atributos_principais: ["FOR", "DES", "CON", "INT", "SAB", "CAR"],
  campo_defesa: "defesa",
  barras_status: [
    { id: "pv", nome: "Pontos de Vida (PV)", cor_token: "--status-vida" },
    { id: "pm", nome: "Pontos de Mana (PM)", cor_token: "--status-recurso" },
  ],
  iniciativa: { expressao: "1d20+{iniciativa}" },
  ataque: { expressao: "1d20+{bonus}", compara_com: "defesa" },
  critico: { margem_padrao: 20, multiplicador_padrao: 2, modo: "multiplica_dados" },
  tabela_dificuldade: { facil: 10, media: 15, dificil: 20, muito_dificil: 25 },
  slots_de_acao_por_turno: [
    { id: "padrao", label: "Ação Padrão", icone: "⚔️", tipos_permitidos: ["ataque", "magia", "pericia", "criativa"] },
    { id: "movimento", label: "Ação de Movimento", icone: "🥾", vinculado_ao_grid: true },
    { id: "livre", label: "Ação Livre / Fala", icone: "💬", tipos_permitidos: ["fala"] },
  ],
}

function personagem(p: Partial<Personagem> & Pick<Personagem, "id" | "nome" | "x" | "y">): Personagem {
  return {
    tipo: "jogador",
    faccao: "aliado",
    barras: { pv: { atual: 30, max: 30 }, pm: { atual: 10, max: 10 } },
    defesa: 15,
    deslocamento: 6,
    iniciativa_bonus: 2,
    ataques: [],
    pericias: {},
    condicoes: [],
    caido: false,
    voz: null,
    postura: null,
    cor: "#888888",
    icone: p.nome.charAt(0),
    ...p,
  }
}

function estadoInicial(): Estado {
  return {
    sala_id: "mock",
    rodada: 6,
    modo: "combate",
    cena: {
      id: "salao_trono",
      nome: "Salão do Trono Profanado",
      descricao: "Um salão de pedra negra, iluminado por braseiros. O trono, ao fundo, foi lascado por garras.",
      tema: "medieval",
      tilemap: TILEMAP,
      largura: 20,
      altura: 15,
      imagem_url: null,
    },
    obstaculos: [{ x: 10, y: 7, tipo: "fogo_magico", rodadas_restantes: 2 }],
    personagens: {
      player_thorin: personagem({
        id: "player_thorin",
        nome: "Thorin",
        x: 6,
        y: 5,
        barras: { pv: { atual: 43, max: 45 }, pm: { atual: 4, max: 6 } },
        defesa: 19,
        iniciativa_bonus: 1,
        ataques: [
          { id: "machado_batalha", nome: "Machado de Batalha", bonus: 8, dano: "1d10+5", tipo_dano: "corte", alcance: 1, margem_critico: 20, mult_critico: 3 },
          { id: "machadinha", nome: "Machadinha (arremesso)", bonus: 6, dano: "1d6+5", tipo_dano: "corte", alcance: 4 },
        ],
        pericias: { atletismo: 9, intimidacao: 6, percepcao: 3 },
        cor: "#b45309",
        icone: "🪓",
      }),
      player_lia: personagem({
        id: "player_lia",
        nome: "Lia",
        x: 2,
        y: 9,
        barras: { pv: { atual: 28, max: 28 }, pm: { atual: 12, max: 12 } },
        defesa: 17,
        iniciativa_bonus: 5,
        ataques: [{ id: "arco_longo", nome: "Arco Longo", bonus: 9, dano: "1d8+3", tipo_dano: "perfuração", alcance: 12 }],
        pericias: { furtividade: 10, acrobacia: 8, percepcao: 7 },
        cor: "#15803d",
        icone: "🏹",
      }),
      boss_orc: personagem({
        id: "boss_orc",
        nome: "Kargath, o Destruidor",
        tipo: "npc",
        faccao: "inimigo",
        x: 6,
        y: 4,
        barras: { pv: { atual: 92, max: 110 } },
        defesa: 18,
        ataques: [{ id: "machado_serrilhado", nome: "Machado Serrilhado", bonus: 11, dano: "2d8+6", tipo_dano: "corte", alcance: 1 }],
        voz: "grave",
        postura: "agressivo",
        cor: "#7f1d1d",
        icone: "👹",
      }),
      goblin_arqueiro: personagem({
        id: "goblin_arqueiro",
        nome: "Arqueiro Goblin",
        tipo: "npc",
        faccao: "inimigo",
        x: 15,
        y: 3,
        barras: { pv: { atual: 9, max: 9 } },
        defesa: 15,
        ataques: [{ id: "arco_curto", nome: "Arco Curto", bonus: 5, dano: "1d6", tipo_dano: "perfuração", alcance: 12 }],
        voz: "agudo",
        postura: "cauteloso",
        cor: "#4d7c0f",
        icone: "👺",
      }),
    },
    iniciativa: ["player_lia", "boss_orc", "player_thorin", "goblin_arqueiro"],
    jogadores: {
      p_thorin: { player_id: "p_thorin", nome: "Thalles", papel: "host", personagem_id: "player_thorin", conectado: true },
      p_lia: { player_id: "p_lia", nome: "Marina", papel: "jogador", personagem_id: "player_lia", conectado: true },
      p_olho: { player_id: "p_olho", nome: "Curioso", papel: "espectador", personagem_id: null, conectado: false },
    },
    memoria: {
      resumo: "O grupo invadiu o Salão do Trono atrás do Coração de Rubi e enfrenta Kargath.",
      fatos: ["Kargath serve a alguém chamado 'o Rubro'", "Lia deve um favor ao taverneiro Bram"],
      npcs_conhecidos: { bram: "taverneiro, aliado", kargath: "chefe orc, hostil" },
      missoes_abertas: ["Recuperar o Coração de Rubi"],
      atualizado_na_rodada: 5,
    },
    cronica: [
      { rodada: 5, id: "e1", texto: "Thorin derruba a porta do salão com um chute." },
      { rodada: 5, id: "e2", texto: "Kargath ruge e avança; o arqueiro goblin se esconde atrás da pilastra." },
    ],
    chat: [
      { id: "c-1", de: "p_lia", nome: "Lia", personagem_id: "player_lia", texto: "Cubro a porta da esquerda. Alguém viu o goblin?", para: null, npc: false, ts: Date.now() / 1000 - 400, rodada: 5 },
      { id: "c-2", de: "p_olho", nome: "Curioso", personagem_id: null, texto: "boa sorte aí, pessoal", para: null, npc: false, ts: Date.now() / 1000 - 300, rodada: 5 },
      { id: "c-3", de: "p_thorin", nome: "Thorin", personagem_id: "player_thorin", texto: "Kargath! Onde está o Coração de Rubi?", para: "boss_orc", npc: false, ts: Date.now() / 1000 - 120, rodada: 5 },
      { id: "c-4", de: "boss_orc", nome: "Kargath, o Destruidor", personagem_id: "boss_orc", texto: "Hah! O Rubro já o tem, anão. Vocês chegaram tarde.", para: "player_thorin", npc: true, ts: Date.now() / 1000 - 110, rodada: 5 },
    ],
  }
}

const MODELO_FICHA_MOCK: ModeloFicha = {
  sistema_id: "tormenta20",
  sistema_nome: "Tormenta20",
  atributos: ["FOR", "DES", "CON", "INT", "SAB", "CAR"],
  pericias: ["acrobacia", "atletismo", "atuacao", "cavalgar", "conhecimento", "cura", "diplomacia", "enganacao", "fortitude", "furtividade", "guerra", "iniciativa", "intimidacao", "intuicao", "investigacao", "jogatina", "ladinagem", "luta", "misticismo", "nobreza", "oficio", "percepcao", "pilotagem", "pontaria", "reflexos", "religiao", "sobrevivencia", "vontade"],
  barras: [
    { id: "pv", nome: "Pontos de Vida (PV)" },
    { id: "pm", nome: "Pontos de Mana (PM)" },
  ],
  campo_defesa: "defesa",
  tipos_dano: ["corte", "perfuracao", "impacto", "fogo", "frio", "eletricidade", "acido", "energia", "luz", "trevas", "veneno", "psiquico"],
  icones: ["⚔️", "🛡️", "🏹", "🔮", "✨", "🗡️", "🪓", "🔥", "🌿", "🎭", "📖", "🐾", "💀", "🎵", "🧪", "🪄"],
  limites: {
    atributo: [-5, 15],
    pv: [1, 999],
    barra: [0, 999],
    defesa: [1, 60],
    deslocamento: [1, 30],
    iniciativa_bonus: [-5, 30],
    pericia: [-5, 40],
    bonus_ataque: [-5, 40],
    alcance: [1, 40],
    max_ataques: 6,
    max_pericias: 30,
    nome: 40,
    classe: 60,
    icone: 4,
    historia: 1500,
  },
  expressao_ataque: "1d20+{bonus}",
  exemplo_dano: "1d8+3",
  monstros_modelo: [{ id: "goblin", nome: "Goblin" }],
}

const slug = (t: string) =>
  t
    .normalize("NFKD")
    .replace(/[^\x00-\x7f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 24) || "pc"

/** Validação simplificada no estilo de `server/fichas.py` (lança ErroApi 400 com `detail` como o servidor). */
function validarFichaMock(f: FichaEnvio): Personagem {
  const erros: string[] = []
  const L = MODELO_FICHA_MOCK.limites
  const nome = (f.nome ?? "").trim()
  if (!nome) erros.push("nome é obrigatório")
  if (f.cor && !/^#[0-9a-fA-F]{6}$/.test(f.cor)) erros.push("cor deve ser #rrggbb")
  const dentro = (v: number, [a, b]: [number, number], rotulo: string) => {
    if (!Number.isInteger(v)) erros.push(`${rotulo} deve ser um número inteiro`)
    else if (v < a || v > b) erros.push(`${rotulo} fora dos limites (${a} a ${b})`)
  }
  for (const a of MODELO_FICHA_MOCK.atributos) dentro(f.atributos?.[a] ?? 0, L.atributo, `atributo ${a}`)
  for (const b of MODELO_FICHA_MOCK.barras) dentro(f.barras?.[b.id] ?? (b.id === "pv" ? 10 : 0), b.id === "pv" ? L.pv : L.barra, `barra ${b.nome}`)
  dentro(f.defesa, L.defesa, "defesa")
  dentro(f.deslocamento, L.deslocamento, "deslocamento")
  dentro(f.iniciativa_bonus, L.iniciativa_bonus, "iniciativa")
  for (const [k, v] of Object.entries(f.pericias ?? {})) {
    if (!MODELO_FICHA_MOCK.pericias.includes(k)) erros.push(`perícia desconhecida no sistema: ${k}`)
    else dentro(v, L.pericia, `perícia ${k}`)
  }
  if (!f.ataques?.length) erros.push("inclua pelo menos um ataque")
  if ((f.ataques?.length ?? 0) > L.max_ataques) erros.push(`no máximo ${L.max_ataques} ataques`)
  for (const a of f.ataques ?? []) {
    if (!expressaoValida(a.dano)) erros.push(`ataque '${a.nome}': expressão de dano inválida (ex.: 1d8+3)`)
    dentro(a.bonus, L.bonus_ataque, `bônus de '${a.nome}'`)
    dentro(a.alcance, L.alcance, `alcance de '${a.nome}'`)
  }
  if (erros.length) throw new ErroApi(400, erros.join("; "), { detail: erros.join("; ") })
  const barras: Personagem["barras"] = {}
  for (const b of MODELO_FICHA_MOCK.barras) {
    const max = f.barras?.[b.id] ?? (b.id === "pv" ? 10 : 0)
    barras[b.id] = { atual: max, max }
  }
  const ids = new Set<string>()
  return personagem({
    id: `pc_${slug(nome)}_${Math.random().toString(16).slice(2, 6)}`,
    nome: nome.slice(0, L.nome),
    x: 1,
    y: 7,
    classe: (f.classe ?? "").slice(0, L.classe),
    icone: (f.icone ?? "⚔️").slice(0, L.icone),
    cor: f.cor ?? "#2563eb",
    historia: (f.historia ?? "").slice(0, L.historia),
    atributos: { ...f.atributos },
    barras,
    defesa: f.defesa,
    deslocamento: f.deslocamento,
    iniciativa_bonus: f.iniciativa_bonus,
    pericias: { ...f.pericias },
    ataques: f.ataques.map((a, i) => {
      let id = slug(a.nome) || `ataque_${i + 1}`
      if (ids.has(id)) id = `${id}_${i + 1}`
      ids.add(id)
      return { id, nome: a.nome.slice(0, 40), bonus: a.bonus, dano: a.dano.replace(/\s/g, ""), tipo_dano: a.tipo_dano, alcance: a.alcance }
    }),
  })
}

/** Fichas criadas via convite (ficam disponíveis no lobby com `origem: "sala"`) e o simulador conectado. */
const fichasDaSala: Personagem[] = []
let simuladorAtivo: SimuladorSala | null = null

const rnd = (faces: number) => 1 + Math.floor(Math.random() * faces)

function rolar(expressao: string): Rolagem {
  const expr = expressao.replace(/\s/g, "").toLowerCase()
  const re = /([+-]?)(?:(\d*)d(\d+)|(\d+))/g
  let total = 0
  const termos: Rolagem["termos"] = []
  for (const m of expr.matchAll(re)) {
    const sinal = m[1] === "-" ? -1 : 1
    if (m[3]) {
      const qtd = Number(m[2] || 1)
      const dados = Array.from({ length: qtd }, () => rnd(Number(m[3])))
      total += sinal * dados.reduce((a, b) => a + b, 0)
      termos.push({ termo: m[0], dados, mantidos: dados })
    } else {
      total += sinal * Number(m[4])
      termos.push({ termo: m[0] })
    }
  }
  return { expressao, total, termos, id: `r-${Math.random().toString(16).slice(2, 6)}` }
}

export const apiMock = {
  async cartuchos(): Promise<Cartuchos> {
    return {
      sistemas: [{ id: "tormenta20", nome: "Tormenta20", revisado: true }],
      campanhas: [{ id: "coracao-de-rubi", nome: "O Coração de Rubi", tema: "medieval", sistema_id: "tormenta20", revisado: true }],
    }
  },
  async criarSala(_corpo: { nome_host: string; personagem_id?: string }): Promise<RespostaCriarSala> {
    return { sala_id: "mock", token: "mock-token-host", player_id: "p_thorin", convite: "MOCK-CONVITE" }
  },
  async lobby(_salaId: string): Promise<RespostaLobby> {
    const disponiveis: PersonagemDisponivel[] = [
      { id: "player_lia", nome: "Lia", classe: "Arqueira", icone: "🏹", cor: "#15803d", origem: "campanha" },
      { id: "pc_ragnar_salvo", nome: "Ragnar", classe: "Bárbaro", icone: "🪓", cor: "#9a3412", origem: "salva" },
      ...fichasDaSala.map((p) => ({ id: p.id, nome: p.nome, classe: p.classe ?? "", icone: p.icone, cor: p.cor, origem: "sala" as const })),
    ]
    if (simuladorAtivo?.semPersonagem) disponiveis.unshift({ id: "player_thorin", nome: "Thorin", classe: "Guerreiro", icone: "🪓", cor: "#b45309", origem: "campanha" })
    return {
      sala_id: "mock",
      campanha: "O Coração de Rubi",
      sistema: "tormenta20",
      tema: "medieval",
      personagens_disponiveis: disponiveis,
      jogadores: [{ player_id: "p_thorin", nome: "Thalles", papel: "host", personagem_id: "player_thorin", conectado: true }],
    }
  },
  async entrar(_corpo: { nome: string; personagem_id: string | null }): Promise<RespostaEntrar> {
    return { token: "mock-token-jogador", player_id: "p_lia" }
  },
  async modeloFicha(_sistemaId: string): Promise<ModeloFicha> {
    await new Promise((r) => setTimeout(r, 150))
    return MODELO_FICHA_MOCK
  },
  async fichasSalvas(_sistemaId: string): Promise<FichaSalva[]> {
    return [{ id: "pc_ragnar_salvo", nome: "Ragnar", classe: "Bárbaro", icone: "🪓", cor: "#9a3412" }]
  },
  async criarFicha(_salaId: string, corpo: { convite?: string; ficha: FichaEnvio }, token?: string | null): Promise<RespostaCriarFicha> {
    await new Promise((r) => setTimeout(r, 300))
    const ficha = validarFichaMock(corpo.ficha)
    if (token && simuladorAtivo) simuladorAtivo.adicionarFicha(ficha, true)
    else if (!corpo.convite) throw new ErroApi(403, "convite inválido", { detail: "convite inválido" })
    else fichasDaSala.push(ficha)
    return { personagem_id: ficha.id, ficha }
  },
  async escolherPersonagem(_salaId: string, personagemId: string, _token: string): Promise<{ personagem_id: string }> {
    await new Promise((r) => setTimeout(r, 200))
    if (!simuladorAtivo) throw new ErroApi(401, "token inválido", { detail: "token inválido" })
    const l = await apiMock.lobby("mock")
    const d = l.personagens_disponiveis.find((p) => p.id === personagemId)
    if (!d) throw new ErroApi(400, "personagem indisponível", { detail: "personagem indisponível" })
    const existente = fichasDaSala.find((p) => p.id === personagemId)
    const ficha =
      existente ??
      personagem({
        id: d.id,
        nome: d.nome,
        x: 1,
        y: 7,
        classe: d.classe,
        icone: d.icone || d.nome.charAt(0),
        cor: d.cor || "#2563eb",
        ataques: [{ id: "arma", nome: "Arma", bonus: 5, dano: "1d8+2", tipo_dano: "corte", alcance: 1 }],
      })
    simuladorAtivo.adicionarFicha(ficha, true)
    return { personagem_id: ficha.id }
  },
}

export const conectarMock: FabricaConexao = (salaId, token, handlers): Conexao => {
  const sim = new SimuladorSala(salaId, token, handlers)
  simuladorAtivo = sim
  sim.iniciar()
  return {
    enviar: (msg) => sim.receber(msg),
    fechar: () => {
      sim.parar()
      if (simuladorAtivo === sim) simuladorAtivo = null
    },
  }
}

class SimuladorSala {
  private state = estadoInicial()
  private fase: Fase = "planejamento"
  private prazo = 0
  private timers: ReturnType<typeof setTimeout>[] = []
  private ativo = true
  private prontos = new Set<string>()
  private acaoDoJogador: AcaoDeclarada | null = null
  private destinoPreview: Coord | null = null
  private rolagensUsadas = new Set<string>()
  private eu: { player_id: string; papel: "host" | "jogador"; personagem_id: string | null }
  private rodadaEmCurso = false
  private npcRespondendo: string | null = null
  readonly semPersonagem: boolean

  constructor(
    _salaId: string,
    token: string,
    private h: HandlersConexao,
  ) {
    this.eu =
      token === "mock-token-jogador"
        ? { player_id: "p_lia", papel: "jogador", personagem_id: "player_lia" }
        : { player_id: "p_thorin", papel: "host", personagem_id: "player_thorin" }
    // `?sem_personagem=1`: o Host entra sem personagem (Thorin fica disponível no lobby) para testar o card de escolha.
    this.semPersonagem = window.location.search.includes("sem_personagem=1") && this.eu.papel === "host"
    if (this.semPersonagem) {
      this.eu.personagem_id = null
      const { player_thorin: _fora, ...resto } = this.state.personagens
      void _fora
      this.state = {
        ...this.state,
        personagens: resto,
        iniciativa: this.state.iniciativa.filter((i) => i !== "player_thorin"),
        jogadores: { ...this.state.jogadores, p_thorin: { ...this.state.jogadores.p_thorin, personagem_id: null } },
      }
    }
  }

  /** POST /fichas ou /personagem com token: adiciona ao estado, vincula a mim e manda um novo room_state (§7). */
  adicionarFicha(ficha: Personagem, vincular: boolean) {
    if (!this.ativo) return
    const jogadores = { ...this.state.jogadores }
    if (vincular && !this.eu.personagem_id) {
      this.eu = { ...this.eu, personagem_id: ficha.id }
      jogadores[this.eu.player_id] = { ...jogadores[this.eu.player_id], personagem_id: ficha.id }
    }
    this.state = { ...this.state, personagens: { ...this.state.personagens, [ficha.id]: ficha }, jogadores }
    this.depois(100, () => {
      this.enviar({ type: "room_state", state: this.state, fase: this.fase, prazo: this.prazo, config: CONFIG_MOCK, eu: this.eu, nivel_ia: 2 })
      if (this.fase === "planejamento") this.depois(200, () => this.enviarAlcance())
    })
  }

  private depois(ms: number, fn: () => void) {
    const t = setTimeout(() => {
      if (this.ativo) fn()
    }, ms)
    this.timers.push(t)
  }

  private enviar(msg: MsgServidor) {
    if (this.ativo) this.h.aoReceber(msg)
  }

  iniciar() {
    this.h.aoStatus("conectando")
    this.depois(300, () => {
      this.h.aoStatus("conectado")
      this.prazo = Math.floor(Date.now() / 1000) + 90
      this.enviar({ type: "room_state", state: this.state, fase: this.fase, prazo: this.prazo, config: CONFIG_MOCK, eu: this.eu, nivel_ia: 2 })
      this.depois(200, () => this.enviarAlcance())
      this.depois(2500, () => this.previewDe("p_lia", "player_lia", [4, 7]))
      this.depois(4000, () => this.enviar({ type: "dice_result", player_id: "p_lia", slot_id: "padrao", rolagem: rolar("1d20+9") }))
      this.depois(90_000, () => this.resolver())
      // `?auto=1` resolve a rodada sozinho (útil para screenshots automáticos).
      if (window.location.search.includes("auto=1")) this.depois(2500, () => this.resolver())
    })
  }

  parar() {
    this.ativo = false
    for (const t of this.timers) clearTimeout(t)
  }

  private get outroJogador() {
    return this.eu.player_id === "p_thorin" ? "p_lia" : "p_thorin"
  }

  private ocupados(exceto: string): Set<string> {
    return new Set(Object.values(this.state.personagens).filter((p) => p.id !== exceto).map((p) => chave(p.x, p.y)))
  }

  private enviarAlcance() {
    const p = this.eu.personagem_id ? this.state.personagens[this.eu.personagem_id] : undefined
    if (!p) return
    const custos = custosDeMovimento([p.x, p.y], this.state.cena.tilemap, this.ocupados(p.id), CONFIG_MOCK.grid.metrica_diagonal, p.deslocamento)
    const celulas: [number, number, number][] = []
    for (const [k, v] of custos) {
      const [x, y] = k.split(",").map(Number)
      celulas.push([x, y, v.custo])
    }
    this.enviar({ type: "alcance", personagem_id: p.id, celulas })
  }

  private previewDe(playerId: string, personagemId: string, destino: Coord): boolean {
    const p = this.state.personagens[personagemId]
    const custos = custosDeMovimento([p.x, p.y], this.state.cena.tilemap, this.ocupados(p.id), CONFIG_MOCK.grid.metrica_diagonal, p.deslocamento)
    const c = custos.get(chave(destino[0], destino[1]))
    if (!c) return false
    this.enviar({ type: "player_preview", player_id: playerId, personagem_id: personagemId, caminho: c.caminho.slice(1), custo: c.custo })
    return true
  }

  receber(msg: MsgCliente) {
    switch (msg.type) {
      case "ping":
        this.enviar({ type: "pong", t: Date.now() })
        break
      case "chat":
        this.chat(msg.texto, msg.para)
        break
      case "preview_move": {
        if (this.fase !== "planejamento") {
          this.enviar({ type: "error", code: "fase_invalida", msg: "Só é possível mover durante o planejamento." })
          return
        }
        if (!this.eu.personagem_id) {
          this.enviar({ type: "error", code: "sem_personagem" })
          return
        }
        if (this.previewDe(this.eu.player_id, this.eu.personagem_id, msg.destino)) this.destinoPreview = msg.destino
        else this.enviar({ type: "error", code: "destino_invalido", msg: "Destino fora do alcance." })
        break
      }
      case "roll": {
        if (msg.slot_id !== "livre_dado" && this.rolagensUsadas.has(msg.slot_id)) {
          this.enviar({ type: "error", code: "rolagem_repetida", msg: "Cada slot aceita uma rolagem." })
          return
        }
        this.rolagensUsadas.add(msg.slot_id)
        this.enviar({ type: "dice_result", player_id: this.eu.player_id, slot_id: msg.slot_id, rolagem: rolar(msg.expressao) })
        break
      }
      case "confirm_turn":
        if (this.fase !== "planejamento") return
        this.acaoDoJogador = msg.acao
        this.prontos.add(this.eu.player_id)
        this.enviar({ type: "ready_status", prontos: [...this.prontos], total: 2, prazo: this.prazo })
        this.depois(1500, () => {
          this.prontos.add(this.outroJogador)
          this.enviar({ type: "ready_status", prontos: [...this.prontos], total: 2, prazo: this.prazo })
          this.depois(600, () => this.resolver())
        })
        break
      case "unconfirm_turn":
        this.prontos.delete(this.eu.player_id)
        this.enviar({ type: "ready_status", prontos: [...this.prontos], total: 2, prazo: this.prazo })
        break
      case "host_command":
        this.comandoHost(msg)
        break
      default:
        break
    }
  }

  // ------------------------------------------------------------------ chat (§6)
  private mensagemChat(parcial: Omit<ChatMessage, "id" | "ts">): ChatMessage {
    return { id: `c-${Math.random().toString(16).slice(2, 10)}`, ts: Date.now() / 1000, rodada: this.state.rodada, ...parcial }
  }

  private registrarChat(m: ChatMessage, extras: Partial<ChatMessage> = {}) {
    const { audio_url: _a, voz: _v, por_host: _h, ...persistida } = m
    void _a
    void _v
    void _h
    this.state = { ...this.state, chat: [...this.state.chat, persistida].slice(-60) }
    this.enviar({ type: "chat_message", ...m, ...extras })
  }

  private chat(texto: string, para: string | null) {
    const t = texto.replace(/\s+/g, " ").trim().slice(0, 500)
    if (!t) {
      this.enviar({ type: "error", code: "mensagem_invalida", msg: "texto vazio" })
      return
    }
    const pid = this.eu.personagem_id
    const falante = pid ? this.state.personagens[pid] : undefined
    const nomeJogador = this.state.jogadores[this.eu.player_id]?.nome ?? "Eu"
    let npc: Personagem | undefined
    if (para) {
      npc = this.state.personagens[para]
      if (!npc || npc.tipo !== "npc") {
        this.enviar({ type: "error", code: "npc_invalido" })
        return
      }
      if (!pid) {
        this.enviar({ type: "error", code: "sem_personagem", msg: "espectadores falam só com a mesa" })
        return
      }
    }
    this.registrarChat(this.mensagemChat({ de: this.eu.player_id, nome: falante?.nome ?? nomeJogador, personagem_id: pid, texto: t, para: npc?.id ?? null, npc: false }))
    if (!npc) return
    if (this.fase === "resolvendo" || this.fase === "narrando") {
      this.enviar({ type: "error", code: "npc_ocupado", msg: "espere a rodada terminar" })
      return
    }
    if (this.npcRespondendo) {
      this.enviar({ type: "error", code: "npc_ocupado", msg: `${this.npcRespondendo} ainda está respondendo` })
      return
    }
    this.npcRespondendo = npc.nome
    this.enviar({ type: "chat_typing", personagem_id: npc.id, nome: npc.nome })
    const alvo = npc
    this.depois(1000, () => {
      this.npcRespondendo = null
      const respostas = alvo.postura === "agressivo"
        ? [`"${t}"? Palavras não salvarão vocês, ${falante?.nome ?? "verme"}.`, "O Rubro ouve tudo. Ajoelhe-se ou morra."]
        : ["(espia por trás da pilastra) N-não me machuque! Eu só sigo ordens…", "O chefe guarda a pedra vermelha no andar de baixo, eu juro!"]
      const texto = respostas[Math.floor(Math.random() * respostas.length)]
      this.registrarChat(this.mensagemChat({ de: alvo.id, nome: alvo.nome, personagem_id: alvo.id, texto, para: pid, npc: true }), { audio_url: null, voz: alvo.voz, por_host: false })
    })
  }

  private comandoHost(msg: Extract<MsgCliente, { type: "host_command" }>) {
    if (this.eu.papel !== "host") {
      this.enviar({ type: "error", code: "nao_autorizado", msg: "Só o Host pode usar este comando." })
      return
    }
    switch (msg.comando) {
      case "iniciar":
        this.mudarFase("planejamento")
        break
      case "pausar":
        this.mudarFase("pausado")
        break
      case "retomar":
        this.mudarFase("planejamento")
        break
      case "resolver_agora":
        this.resolver()
        break
      case "iniciar_combate":
        this.state = { ...this.state, modo: "combate", iniciativa: ["player_lia", "boss_orc", "player_thorin", "goblin_arqueiro"] }
        this.enviar({ type: "state_sync", state: this.state })
        this.enviar({ type: "phase", fase: this.fase, prazo: this.prazo, modo: "combate" })
        break
      case "encerrar_combate":
        this.state = { ...this.state, modo: "exploracao", iniciativa: [] }
        this.enviar({ type: "state_sync", state: this.state })
        this.enviar({ type: "phase", fase: this.fase, prazo: this.prazo, modo: "exploracao" })
        break
      case "mudar_nivel_ia":
        this.enviar({ type: "nivel_ia", nivel: msg.nivel, provedor: ["", "local", "gemini-flash", "gemini-pro", "claude"][msg.nivel] })
        break
      case "editar_personagem": {
        const p = this.state.personagens[msg.personagem_id]
        if (!p) return
        const novo: Personagem = {
          ...p,
          x: msg.campos.x ?? p.x,
          y: msg.campos.y ?? p.y,
          barras: msg.campos.barras ?? p.barras,
          condicoes: msg.campos.condicoes ?? p.condicoes,
          caido: msg.campos.caido ?? p.caido,
        }
        this.state = { ...this.state, personagens: { ...this.state.personagens, [p.id]: novo } }
        this.enviar({ type: "state_sync", state: this.state })
        break
      }
      case "desfazer_rodada":
        this.state = estadoInicial()
        this.enviar({ type: "state_sync", state: this.state })
        this.mudarFase("planejamento")
        break
      case "mudar_cena":
        this.enviar({ type: "error", code: "cena_desconhecida", msg: `O mock só tem a cena ${this.state.cena.id}.` })
        break
      case "nova_narracao":
        this.enviar({ type: "error", code: "sem_rodada", msg: "Mock: re-narração não simulada." })
        break
      case "falar_como_npc": {
        const npc = this.state.personagens[msg.personagem_id]
        const texto = msg.texto.replace(/\s+/g, " ").trim().slice(0, 500)
        if (!npc || npc.tipo !== "npc" || !texto) {
          this.enviar({ type: "error", code: "comando_invalido", msg: "NPC ou texto inválido" })
          return
        }
        this.registrarChat(this.mensagemChat({ de: npc.id, nome: npc.nome, personagem_id: npc.id, texto, para: null, npc: true }), { audio_url: null, voz: npc.voz, por_host: true })
        break
      }
      default:
        break
    }
  }

  private mudarFase(fase: Fase) {
    this.fase = fase
    if (fase === "planejamento") {
      this.prazo = Math.floor(Date.now() / 1000) + 90
      this.prontos.clear()
      this.rolagensUsadas.clear()
      this.destinoPreview = null
      this.acaoDoJogador = null
      this.enviar({ type: "phase", fase, prazo: this.prazo, modo: this.state.modo })
      this.depois(200, () => this.enviarAlcance())
      this.depois(90_000, () => this.resolver())
    } else {
      this.enviar({ type: "phase", fase, prazo: null, modo: this.state.modo })
    }
  }

  /** Resolve a rodada com eventos fixos (mais o movimento escolhido no preview). */
  private resolver() {
    if (this.rodadaEmCurso || this.fase !== "planejamento") return
    this.rodadaEmCurso = true
    this.mudarFase("resolvendo")
    const rodada = this.state.rodada + 1
    const s = this.state
    const meu = (this.eu.personagem_id ? s.personagens[this.eu.personagem_id] : undefined) ?? s.personagens.player_lia
    const acoes: AcaoDoLog[] = []

    // e1: movimento do meu personagem (se houve preview) + ataque declarado
    const eventos1: Evento[] = []
    if (this.destinoPreview && this.eu.personagem_id) {
      const custos = custosDeMovimento([meu.x, meu.y], s.cena.tilemap, this.ocupados(meu.id), "1-2-1-2", meu.deslocamento)
      const c = custos.get(chave(this.destinoPreview[0], this.destinoPreview[1]))
      if (c) eventos1.push({ tipo: "movimento", personagem: meu.id, de: [meu.x, meu.y], para: this.destinoPreview, caminho: c.caminho })
    }
    const slotPadrao = this.acaoDoJogador?.slots.padrao
    let textoMeu = `${meu.nome} espera.`
    if (slotPadrao?.tipo === "ataque") {
      const alvo = s.personagens[slotPadrao.alvo_id]
      const atq = meu.ataques.find((a) => a.id === slotPadrao.ataque_id)
      const r = rolar(`1d20+${atq?.bonus ?? 0}`)
      const acertou = alvo ? r.total >= alvo.defesa : false
      eventos1.push({ tipo: "ataque", atacante: meu.id, alvo: slotPadrao.alvo_id, ataque: slotPadrao.ataque_id, rolagem: r, defesa: alvo?.defesa ?? 0, acertou, critico: false })
      if (acertou && alvo) {
        const dano = rolar(atq?.dano ?? "1d6").total
        eventos1.push({ tipo: "dano", alvo: alvo.id, valor: dano, tipo_dano: atq?.tipo_dano ?? "corte", barra: "pv" })
        textoMeu = `${meu.nome} ataca ${alvo.nome} com ${atq?.nome ?? "arma"}: ${r.total} vs Defesa ${alvo.defesa} — acerta, ${dano} de dano.`
      } else textoMeu = `${meu.nome} ataca ${alvo?.nome ?? "?"}: ${r.total} vs Defesa ${alvo?.defesa ?? "?"} — erra.`
    } else if (slotPadrao?.tipo === "pericia") {
      const r = rolar(`1d20+${meu.pericias[slotPadrao.pericia] ?? 0}`)
      eventos1.push({ tipo: "teste", personagem: meu.id, pericia: slotPadrao.pericia, cd: 15, rolagem: r, sucesso: r.total >= 15 })
      textoMeu = `${meu.nome} testa ${slotPadrao.pericia}: ${r.total} vs CD 15 — ${r.total >= 15 ? "sucesso" : "falha"}.`
    } else if (slotPadrao?.tipo === "criativa") {
      eventos1.push({ tipo: "condicao", alvo: "boss_orc", condicao: "atordoado", rodadas: 1 })
      textoMeu = `${meu.nome} improvisa: "${slotPadrao.texto}" — Kargath fica atordoado.`
    }
    const fala = this.acaoDoJogador?.slots.livre
    if (fala?.tipo === "fala") eventos1.push({ tipo: "fala", personagem: meu.id, texto: fala.texto })
    acoes.push({ id: "e1", ator_id: meu.id, texto: textoMeu, eventos: eventos1 })

    // e2: Lia atira no goblin
    const rLia = rolar("1d20+9")
    const acertouLia = rLia.total >= 15
    const ev2: Evento[] = [{ tipo: "ataque", atacante: "player_lia", alvo: "goblin_arqueiro", ataque: "arco_longo", rolagem: rLia, defesa: 15, acertou: acertouLia, critico: false }]
    if (acertouLia) {
      ev2.push({ tipo: "dano", alvo: "goblin_arqueiro", valor: 9, tipo_dano: "perfuração", barra: "pv" })
      ev2.push({ tipo: "caiu", personagem: "goblin_arqueiro" })
    }
    acoes.push({ id: "e2", ator_id: "player_lia", texto: `Lia atira no Arqueiro Goblin: ${rLia.total} vs Defesa 15 — ${acertouLia ? "acerta, 9 de dano, o goblin cai." : "erra."}`, eventos: ev2 })

    // e3: Kargath avança e ataca Thorin (ou Lia, se Thorin não estiver em cena)
    const thorin = s.personagens.player_thorin ?? s.personagens.player_lia
    const destinoOrc: Coord = [thorin.x, thorin.y - 1]
    const ev3: Evento[] = []
    const orc = s.personagens.boss_orc
    if (orc.x !== destinoOrc[0] || orc.y !== destinoOrc[1]) {
      const custos = custosDeMovimento([orc.x, orc.y], s.cena.tilemap, this.ocupados(orc.id), "1-2-1-2", 6)
      const c = custos.get(chave(destinoOrc[0], destinoOrc[1]))
      if (c) ev3.push({ tipo: "movimento", personagem: orc.id, de: [orc.x, orc.y], para: destinoOrc, caminho: c.caminho })
    }
    const rOrc = rolar("1d20+11")
    const acertouOrc = rOrc.total >= thorin.defesa
    ev3.push({ tipo: "ataque", atacante: "boss_orc", alvo: "player_thorin", ataque: "machado_serrilhado", rolagem: rOrc, defesa: thorin.defesa, acertou: acertouOrc, critico: false })
    if (acertouOrc) ev3.push({ tipo: "dano", alvo: "player_thorin", valor: 13, tipo_dano: "corte", barra: "pv" })
    acoes.push({ id: "e3", ator_id: "boss_orc", texto: `Kargath avança e golpeia Thorin: ${rOrc.total} vs Defesa ${thorin.defesa} — ${acertouOrc ? "acerta, 13 de dano." : "erra."}`, eventos: ev3 })

    // e4: fogo mágico se apaga
    acoes.push({ id: "e4", ator_id: "cena", texto: "O fogo mágico em (10,7) se apaga.", eventos: [{ tipo: "obstaculo_removido", x: 10, y: 7 }] })

    // Estado final da rodada
    let final = { ...s, rodada }
    for (const a of acoes) for (const ev of a.eventos) final = aplicarEvento(final, ev)
    final = { ...final, cronica: [...s.cronica, ...acoes.map((a) => ({ rodada, id: a.id, texto: a.texto }))] }

    this.depois(1200, () => {
      this.enviar({ type: "round_log", rodada, modo: s.modo, acoes })
      this.fase = "narrando"
      this.enviar({ type: "phase", fase: "narrando", prazo: null, modo: s.modo })
      const segmentos = [
        { seq: 1, voz: "NARRADOR", texto: acoes[0].eventos.length > 0 ? "Thorin avança pela pedra negra e desfere seu golpe contra o orc." : "Thorin hesita, firmando a postura.", eventos: ["e1"] },
        { seq: 2, voz: "NARRADOR", texto: "No alto, a flecha de Lia corta o ar em direção ao arqueiro goblin.", eventos: ["e2"] },
        { seq: 3, voz: "boss_orc", texto: "Vermes! O Rubro terá suas cabeças!", eventos: [] },
        { seq: 4, voz: "NARRADOR", texto: "Kargath cambaleia à frente e responde com o machado serrilhado, enquanto as chamas no salão finalmente morrem. O que vocês fazem?", eventos: ["e3", "e4"] },
      ]
      segmentos.forEach((seg, i) => this.depois(400 + i * 350, () => this.enviar({ type: "narration_segment", ...seg, audio_url: null })))
      this.depois(400 + segmentos.length * 350 + 200, () => {
        this.enviar({ type: "narration_end", rodada })
        this.state = final
        this.enviar({ type: "state_sync", state: final })
        this.rodadaEmCurso = false
        this.mudarFase("planejamento")
      })
    })
  }
}
