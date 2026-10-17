// Mock do servidor para validar a UI sem backend (VITE_MOCK=1).
// Simula room_state com a cena da §10.2, alcance, previews, rolagens e o ciclo
// planejamento → resolvendo → round_log → narration_segment (sem áudio) → narration_end → state_sync.

import type {
  AcaoDeclarada,
  AcaoDoLog,
  Cartuchos,
  Coord,
  Estado,
  Evento,
  Fase,
  MsgCliente,
  MsgServidor,
  Personagem,
  RespostaCriarSala,
  RespostaEntrar,
  RespostaLobby,
  Rolagem,
  SystemConfig,
} from "../types"
import type { Conexao, FabricaConexao, HandlersConexao } from "../lib/ws"
import { chave, custosDeMovimento } from "../lib/grid"
import { aplicarEvento } from "../lib/eventos"

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
  }
}

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
  async criarSala(_corpo: { nome_host: string }): Promise<RespostaCriarSala> {
    return { sala_id: "mock", token: "mock-token-host", player_id: "p_thorin", convite: "MOCK-CONVITE" }
  },
  async lobby(_salaId: string): Promise<RespostaLobby> {
    return {
      sala_id: "mock",
      campanha: "O Coração de Rubi",
      tema: "medieval",
      personagens_disponiveis: [{ id: "player_lia", nome: "Lia", classe: "Arqueira" }],
      jogadores: [{ player_id: "p_thorin", nome: "Thalles", papel: "host", personagem_id: "player_thorin", conectado: true }],
    }
  },
  async entrar(_corpo: { nome: string; personagem_id: string }): Promise<RespostaEntrar> {
    return { token: "mock-token-jogador", player_id: "p_lia" }
  },
}

export const conectarMock: FabricaConexao = (salaId, token, handlers): Conexao => {
  const sim = new SimuladorSala(salaId, token, handlers)
  sim.iniciar()
  return {
    enviar: (msg) => sim.receber(msg),
    fechar: () => sim.parar(),
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
  private eu: { player_id: string; papel: "host" | "jogador"; personagem_id: string }
  private rodadaEmCurso = false

  constructor(
    _salaId: string,
    token: string,
    private h: HandlersConexao,
  ) {
    this.eu =
      token === "mock-token-jogador"
        ? { player_id: "p_lia", papel: "jogador", personagem_id: "player_lia" }
        : { player_id: "p_thorin", papel: "host", personagem_id: "player_thorin" }
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
    const p = this.state.personagens[this.eu.personagem_id]
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
      case "preview_move": {
        if (this.fase !== "planejamento") {
          this.enviar({ type: "error", code: "fase_invalida", msg: "Só é possível mover durante o planejamento." })
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
    const meu = s.personagens[this.eu.personagem_id]
    const acoes: AcaoDoLog[] = []

    // e1: movimento do meu personagem (se houve preview) + ataque declarado
    const eventos1: Evento[] = []
    if (this.destinoPreview) {
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

    // e3: Kargath avança e ataca Thorin
    const thorin = s.personagens.player_thorin
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
