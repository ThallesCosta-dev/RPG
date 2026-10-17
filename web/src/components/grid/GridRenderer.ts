import {
  Application,
  Assets,
  Container,
  FederatedPointerEvent,
  FederatedWheelEvent,
  Graphics,
  Sprite,
  Text,
  Texture,
  Ticker,
} from "pixi.js"
import type { Cena, CelulaAlcance, Coord, Evento, Obstaculo, Personagem, Tema } from "../../types"
import { TAMANHO_QUADRADO as T, chave, mapaDeAlcance } from "../../lib/grid"
import { corDeFaccao, lerCor, varTema } from "../../lib/cor"
import { reduzMovimento } from "../../lib/animacoes"
import { centro, desenharObstaculo, desenharTile, linhaTracejada } from "./desenho"
import type { Preview } from "../../store/useSala"

export interface SnapshotGrid {
  cena: Cena | null
  obstaculos: Obstaculo[]
  personagens: Record<string, Personagem>
  alcance: CelulaAlcance[]
  previews: Record<string, Preview>
  alvosRealcados: string[]
  selecionado: string | null
  meuPersonagemId: string | null
  podeArrastar: boolean
  barraVidaId: string
  tema: Tema
}

export interface CallbacksGrid {
  aoSelecionar(id: string | null): void
  aoSoltar(destino: Coord): void
}

interface TokenVisual {
  cont: Container
  corpo: Graphics
  icone: Text
  barra: Graphics
  marcaCaido: Text
  anel: Graphics
  rotulo: Text
  x: number
  y: number
  pvVisual: number
  pvAlvo: number
  pvMax: number
  movendo: boolean
  tremor: number
}

interface Animacao {
  atualizar(dtMs: number): boolean // true = terminou
}

const ESTILO_ICONE = { fontSize: 18, fill: 0xffffff, fontFamily: "sans-serif" }

/** Renderizador PixiJS do grid: 4 camadas (fundo, malha, tokens, realces), pan/zoom, arraste e animações. */
export class GridRenderer {
  private app = new Application()
  private mundo = new Container()
  private camadaFundo = new Container()
  private fundoTiles = new Graphics()
  private fundoObstaculos = new Graphics()
  private spriteFundo: Sprite | null = null
  private urlFundo: string | null = null
  private camadaMalha = new Graphics()
  private camadaTokens = new Container()
  private camadaRealces = new Container()
  private realceAlcance = new Graphics()
  private textosAlcance = new Container()
  private realcePreview = new Graphics()
  private textosPreview = new Container()
  private realceAlvos = new Graphics()
  private flutuantes = new Container()

  private tokens = new Map<string, TokenVisual>()
  private snap: SnapshotGrid | null = null
  private pronto = false
  private destruido = false
  private animacoes: Animacao[] = []
  private tempo = 0
  private reduz = reduzMovimento()
  private cenaEnquadrada: string | null = null
  private cores = { grid: 0xffffff, gridAlpha: 0.3, vida: 0xe0574a, acento: 0xd9a441 }
  private arrasto: { id: string; moveu: false | true; origem: Coord } | null = null
  private pan: { mx: number; my: number; px: number; py: number } | null = null
  private alcanceMapa = new Map<string, number>()
  private resize: ResizeObserver | null = null

  constructor(private callbacks: CallbacksGrid) {}

  async iniciar(el: HTMLElement): Promise<void> {
    await this.app.init({
      background: 0x0b0908,
      antialias: true,
      resolution: Math.min(2, window.devicePixelRatio || 1),
      autoDensity: true,
      width: Math.max(1, el.clientWidth),
      height: Math.max(1, el.clientHeight),
    })
    if (this.destruido) {
      this.app.destroy()
      return
    }
    el.appendChild(this.app.canvas)
    this.app.canvas.style.display = "block"
    this.app.canvas.style.touchAction = "none"

    this.camadaTokens.sortableChildren = true
    this.camadaFundo.addChild(this.fundoTiles, this.fundoObstaculos)
    this.camadaRealces.addChild(this.realceAlcance, this.textosAlcance, this.realcePreview, this.textosPreview, this.realceAlvos, this.flutuantes)
    this.mundo.addChild(this.camadaFundo, this.camadaMalha, this.camadaTokens, this.camadaRealces)
    this.app.stage.addChild(this.mundo)

    const stage = this.app.stage
    stage.eventMode = "static"
    stage.hitArea = this.app.screen
    stage.on("pointerdown", this.aoPointerDownStage)
    stage.on("globalpointermove", this.aoPointerMove)
    stage.on("pointerup", this.aoPointerUp)
    stage.on("pointerupoutside", this.aoPointerUp)
    stage.on("wheel", this.aoWheel)

    this.resize = new ResizeObserver(() => {
      if (this.destruido) return
      const w = Math.max(1, el.clientWidth)
      const h = Math.max(1, el.clientHeight)
      this.app.renderer.resize(w, h)
      stage.hitArea = this.app.screen
    })
    this.resize.observe(el)

    this.app.ticker.add(this.tick)
    this.pronto = true
    this.aplicarTema()
    if (this.snap) this.atualizar(this.snap, true)
  }

  destruir(): void {
    this.destruido = true
    this.resize?.disconnect()
    if (this.pronto) {
      this.app.ticker.remove(this.tick)
      this.app.destroy({ removeView: true }, { children: true })
    }
  }

  /** Recebe um novo snapshot do estado e redesenha só o que mudou (por referência). */
  atualizar(snap: SnapshotGrid, forcar = false): void {
    const anterior = this.snap
    this.snap = snap
    if (!this.pronto) return
    if (!snap.cena) return

    if (forcar || anterior?.tema !== snap.tema) this.aplicarTema()
    if (forcar || anterior?.cena !== snap.cena || anterior?.obstaculos !== snap.obstaculos) {
      this.redesenharFundo(snap.cena, snap.obstaculos)
    }
    if (forcar || anterior?.cena !== snap.cena || anterior?.tema !== snap.tema) this.redesenharMalha(snap.cena)
    if (forcar || anterior?.cena?.id !== snap.cena.id) this.enquadrar(snap.cena)
    if (forcar || anterior?.personagens !== snap.personagens || anterior?.selecionado !== snap.selecionado || anterior?.barraVidaId !== snap.barraVidaId) {
      this.sincronizarTokens(snap)
    }
    if (forcar || anterior?.alcance !== snap.alcance || anterior?.podeArrastar !== snap.podeArrastar) {
      this.alcanceMapa = mapaDeAlcance(snap.alcance)
      this.redesenharAlcance(snap)
    }
    if (forcar || anterior?.previews !== snap.previews || anterior?.personagens !== snap.personagens) this.redesenharPreviews(snap)
    if (forcar || anterior?.alvosRealcados !== snap.alvosRealcados || anterior?.personagens !== snap.personagens) this.redesenharAlvos(snap)
    for (const [id, tv] of this.tokens) tv.cont.cursor = snap.podeArrastar && id === snap.meuPersonagemId ? "grab" : "pointer"
  }

  // ---------- Animações por evento ----------

  animar(ev: Evento, instantaneo: boolean): void {
    if (!this.pronto) return
    const imediato = instantaneo || this.reduz
    switch (ev.tipo) {
      case "movimento": {
        const tv = this.tokens.get(ev.personagem)
        if (!tv) return
        const pontos = ev.caminho && ev.caminho.length > 1 ? ev.caminho : [ev.de, ev.para]
        if (imediato) {
          this.posicionar(tv, ev.para)
          return
        }
        tv.movendo = true
        this.animacoes.push(this.animMovimento(tv, pontos))
        return
      }
      case "dano": {
        const tv = this.tokens.get(ev.alvo)
        if (!tv) return
        if (ev.barra === this.snap?.barraVidaId || !ev.barra) tv.pvAlvo = Math.max(0, tv.pvAlvo - ev.valor)
        if (imediato) tv.pvVisual = tv.pvAlvo
        this.flutuar(tv, `-${ev.valor}`, 0xff5a5a, imediato)
        this.animacoes.push(this.animFlash(tv, 0xff5a5a))
        return
      }
      case "cura": {
        const tv = this.tokens.get(ev.alvo)
        if (!tv) return
        if (ev.barra === this.snap?.barraVidaId || !ev.barra) tv.pvAlvo = Math.min(tv.pvMax, tv.pvAlvo + ev.valor)
        if (imediato) tv.pvVisual = tv.pvAlvo
        this.flutuar(tv, `+${ev.valor}`, 0x4ade80, imediato)
        return
      }
      case "ataque": {
        if (ev.acertou) return
        const atacante = this.tokens.get(ev.atacante)
        const alvo = this.tokens.get(ev.alvo)
        if (atacante && !imediato) this.animacoes.push(this.animTremor(atacante))
        if (alvo) this.flutuar(alvo, "errou", 0xcccccc, imediato, 13)
        return
      }
      case "condicao": {
        const tv = this.tokens.get(ev.alvo)
        if (tv) this.flutuar(tv, `✦ ${ev.condicao}`, 0xc084fc, imediato, 12)
        return
      }
      case "condicao_removida": {
        const tv = this.tokens.get(ev.alvo)
        if (tv) this.flutuar(tv, `✧ ${ev.condicao}`, 0x9ca3af, imediato, 11)
        return
      }
      case "caiu": {
        const tv = this.tokens.get(ev.personagem)
        if (tv) {
          tv.marcaCaido.visible = true
          tv.cont.alpha = 0.6
          if (!imediato) this.animacoes.push(this.animTremor(tv))
        }
        return
      }
      case "levantou": {
        const tv = this.tokens.get(ev.personagem)
        if (tv) {
          tv.marcaCaido.visible = false
          tv.cont.alpha = 1
        }
        return
      }
      case "teste": {
        const tv = this.tokens.get(ev.personagem)
        if (tv) this.flutuar(tv, `${ev.sucesso ? "✓" : "✗"} ${ev.pericia}`, ev.sucesso ? 0x4ade80 : 0xff5a5a, imediato, 12)
        return
      }
      case "fala": {
        const tv = this.tokens.get(ev.personagem)
        if (tv) this.flutuar(tv, "💬", 0xffffff, imediato, 16)
        return
      }
      default:
        return
    }
  }

  // ---------- Camada 0 ----------

  private redesenharFundo(cena: Cena, obstaculos: Obstaculo[]): void {
    const g = this.fundoTiles
    g.clear()
    const url = cena.imagem_url
    if (url && url !== this.urlFundo) {
      this.urlFundo = url
      this.spriteFundo?.destroy()
      this.spriteFundo = null
      Assets.load<Texture>(url)
        .then((tex) => {
          if (this.destruido || this.urlFundo !== url) return
          const sp = new Sprite(tex)
          sp.width = cena.largura * T
          sp.height = cena.altura * T
          this.spriteFundo = sp
          this.camadaFundo.addChildAt(sp, 0)
          this.fundoTiles.visible = false
        })
        .catch(() => {
          // imagem indisponível: mantém a versão estilizada
        })
    } else if (!url) {
      this.urlFundo = null
      this.spriteFundo?.destroy()
      this.spriteFundo = null
    }
    this.fundoTiles.visible = !this.spriteFundo
    for (let y = 0; y < cena.tilemap.length; y++) {
      const linha = cena.tilemap[y]
      for (let x = 0; x < linha.length; x++) desenharTile(g, linha[x], x, y, T)
    }
    const o = this.fundoObstaculos
    o.clear()
    for (const ob of obstaculos) desenharObstaculo(o, ob.tipo, ob.x, ob.y, T)
  }

  // ---------- Camada 1 ----------

  private redesenharMalha(cena: Cena): void {
    const g = this.camadaMalha
    g.clear()
    const W = cena.largura * T
    const H = cena.altura * T
    const tracejado = this.snap?.tema === "terror"
    for (let x = 0; x <= cena.largura; x++) {
      if (tracejado) linhaTracejada(g, [[x * T, 0], [x * T, H]], 6, 4)
      else g.moveTo(x * T, 0).lineTo(x * T, H)
    }
    for (let y = 0; y <= cena.altura; y++) {
      if (tracejado) linhaTracejada(g, [[0, y * T], [W, y * T]], 6, 4)
      else g.moveTo(0, y * T).lineTo(W, y * T)
    }
    g.stroke({ width: 1, color: this.cores.grid, alpha: this.cores.gridAlpha })
    // indicadores de parede/água/cobertura (§6.2): contorno mais forte
    for (let y = 0; y < cena.tilemap.length; y++) {
      for (let x = 0; x < cena.tilemap[y].length; x++) {
        const s = cena.tilemap[y][x]
        if (s === "#" || s === "P" || s === "~") g.rect(x * T + 1, y * T + 1, T - 2, T - 2).stroke({ width: 1, color: this.cores.grid, alpha: this.cores.gridAlpha * 0.6 })
        if (s === "C") g.rect(x * T + 3, y * T + 3, T - 6, T - 6).stroke({ width: 1, color: this.cores.acento, alpha: 0.5 })
      }
    }
  }

  // ---------- Camada 2 ----------

  private sincronizarTokens(snap: SnapshotGrid): void {
    const vistos = new Set<string>()
    for (const p of Object.values(snap.personagens)) {
      vistos.add(p.id)
      let tv = this.tokens.get(p.id)
      if (!tv) {
        tv = this.criarToken(p)
        this.tokens.set(p.id, tv)
        this.camadaTokens.addChild(tv.cont)
        this.posicionar(tv, [p.x, p.y])
      }
      this.atualizarToken(tv, p, snap)
      if (!tv.movendo && (tv.x !== p.x || tv.y !== p.y)) this.posicionar(tv, [p.x, p.y])
    }
    for (const [id, tv] of this.tokens) {
      if (!vistos.has(id)) {
        tv.cont.destroy({ children: true })
        this.tokens.delete(id)
      }
    }
  }

  private criarToken(p: Personagem): TokenVisual {
    const cont = new Container()
    const anel = new Graphics()
    const corpo = new Graphics()
    const icone = new Text({ text: p.icone || p.nome.charAt(0).toUpperCase(), style: ESTILO_ICONE })
    icone.anchor.set(0.5)
    const barra = new Graphics()
    const marcaCaido = new Text({ text: "✕", style: { fontSize: 28, fill: 0xff3b3b, fontWeight: "bold" } })
    marcaCaido.anchor.set(0.5)
    marcaCaido.visible = false
    const rotulo = new Text({ text: p.nome, style: { fontSize: 10, fill: 0xffffff, fontFamily: "sans-serif" } })
    rotulo.anchor.set(0.5, 0)
    rotulo.position.set(0, -T * 0.5 - 2)
    rotulo.alpha = 0.9
    cont.addChild(anel, corpo, icone, marcaCaido, barra, rotulo)
    cont.eventMode = "static"
    cont.cursor = "pointer"
    cont.on("pointerdown", (e: FederatedPointerEvent) => this.aoPointerDownToken(e, p.id))
    const pv = p.barras[this.snap?.barraVidaId ?? "pv"]
    return {
      cont,
      corpo,
      icone,
      barra,
      marcaCaido,
      anel,
      rotulo,
      x: p.x,
      y: p.y,
      pvVisual: pv?.atual ?? 1,
      pvAlvo: pv?.atual ?? 1,
      pvMax: pv?.max ?? 1,
      movendo: false,
      tremor: 0,
    }
  }

  private atualizarToken(tv: TokenVisual, p: Personagem, snap: SnapshotGrid): void {
    const r = T * 0.4
    const { cor } = lerCor(p.cor, 0x666666)
    tv.corpo.clear()
    tv.corpo.circle(0, 0, r).fill(cor).stroke({ width: 3, color: corDeFaccao(p.faccao) })
    tv.icone.text = p.icone || p.nome.charAt(0).toUpperCase()
    tv.rotulo.text = p.nome
    const pv = p.barras[snap.barraVidaId]
    const alvo = pv?.atual ?? tv.pvAlvo
    tv.pvMax = pv?.max ?? tv.pvMax
    // O valor visual persegue o alvo no ticker (barra desce suavemente).
    tv.pvAlvo = alvo
    tv.marcaCaido.visible = p.caido
    tv.cont.alpha = p.caido ? 0.6 : 1
    tv.anel.clear()
    if (snap.selecionado === p.id) tv.anel.circle(0, 0, r + 5).stroke({ width: 2, color: 0xffffff, alpha: 0.9 })
    this.desenharBarra(tv)
  }

  private desenharBarra(tv: TokenVisual): void {
    const w = T * 0.8
    const h = 5
    const frac = tv.pvMax > 0 ? Math.max(0, Math.min(1, tv.pvVisual / tv.pvMax)) : 0
    const g = tv.barra
    g.clear()
    g.rect(-w / 2, T * 0.42, w, h).fill({ color: 0x000000, alpha: 0.7 })
    if (frac > 0) g.rect(-w / 2, T * 0.42, w * frac, h).fill(frac > 0.5 ? this.cores.vida : frac > 0.25 ? 0xf59e0b : 0xdc2626)
    g.rect(-w / 2, T * 0.42, w, h).stroke({ width: 1, color: 0xffffff, alpha: 0.35 })
  }

  private posicionar(tv: TokenVisual, c: Coord): void {
    tv.x = c[0]
    tv.y = c[1]
    const [px, py] = centro(c, T)
    tv.cont.position.set(px, py)
    tv.movendo = false
  }

  // ---------- Camada 3 ----------

  private redesenharAlcance(snap: SnapshotGrid): void {
    const g = this.realceAlcance
    g.clear()
    for (const t of this.textosAlcance.removeChildren()) t.destroy()
    if (!snap.podeArrastar || snap.alcance.length === 0) return
    for (const [x, y, custo] of snap.alcance) {
      if (custo === 0) continue
      g.rect(x * T + 1, y * T + 1, T - 2, T - 2).fill({ color: this.cores.acento, alpha: 0.22 }).stroke({ width: 1, color: this.cores.acento, alpha: 0.45 })
      const txt = new Text({ text: String(custo), style: { fontSize: 9, fill: 0xffffff, fontFamily: "sans-serif" } })
      txt.alpha = 0.8
      txt.position.set(x * T + 3, y * T + 2)
      this.textosAlcance.addChild(txt)
    }
  }

  private redesenharPreviews(snap: SnapshotGrid): void {
    const g = this.realcePreview
    g.clear()
    for (const t of this.textosPreview.removeChildren()) t.destroy()
    for (const pv of Object.values(snap.previews)) {
      if (pv.caminho.length === 0) continue
      const p = snap.personagens[pv.personagem_id]
      const { cor } = lerCor(p?.cor ?? "#ffffff", 0xffffff)
      const pontos = pv.caminho.map((c) => centro(c, T))
      const origem = p ? centro([p.x, p.y], T) : pontos[0]
      linhaTracejada(g, [origem, ...pontos])
      g.stroke({ width: 3, color: 0x000000, alpha: 0.5 })
      linhaTracejada(g, [origem, ...pontos])
      g.stroke({ width: 2, color: cor, alpha: 0.95 })
      const fim = pontos[pontos.length - 1]
      // token fantasma no destino
      g.circle(fim[0], fim[1], T * 0.36).fill({ color: cor, alpha: 0.35 }).stroke({ width: 2, color: cor, alpha: 0.8 })
      const rot = new Text({
        text: `${p?.nome ?? pv.personagem_id} · custo ${pv.custo}`,
        style: { fontSize: 10, fill: 0xffffff, fontFamily: "sans-serif", stroke: { color: 0x000000, width: 3 } },
      })
      rot.anchor.set(0.5, 1)
      rot.position.set(fim[0], fim[1] - T * 0.45)
      this.textosPreview.addChild(rot)
    }
  }

  private redesenharAlvos(snap: SnapshotGrid): void {
    const g = this.realceAlvos
    g.clear()
    for (const id of snap.alvosRealcados) {
      const p = snap.personagens[id]
      if (!p) continue
      const [cx, cy] = centro([p.x, p.y], T)
      g.circle(cx, cy, T * 0.48).stroke({ width: 3, color: 0xff5a5a, alpha: 0.9 })
      g.moveTo(cx - T * 0.55, cy).lineTo(cx - T * 0.35, cy).stroke({ width: 2, color: 0xff5a5a })
      g.moveTo(cx + T * 0.35, cy).lineTo(cx + T * 0.55, cy).stroke({ width: 2, color: 0xff5a5a })
    }
  }

  // ---------- Tema ----------

  private aplicarTema(): void {
    const grid = lerCor(varTema("--grid-line", "#ffffff66"), 0xffffff)
    const vida = lerCor(varTema("--status-vida", "#e0574a"), 0xe0574a)
    const acento = lerCor(varTema("--acento", "#d9a441"), 0xd9a441)
    const fundo = lerCor(varTema("--grid-fundo", "#171310"), 0x171310)
    this.cores = { grid: grid.cor, gridAlpha: grid.alpha, vida: vida.cor, acento: acento.cor }
    this.app.renderer.background.color = fundo.cor
    for (const tv of this.tokens.values()) this.desenharBarra(tv)
  }

  // ---------- Enquadramento, pan e zoom ----------

  private enquadrar(cena: Cena): void {
    if (this.cenaEnquadrada === cena.id) return
    this.cenaEnquadrada = cena.id
    const W = cena.largura * T
    const H = cena.altura * T
    const sw = this.app.screen.width
    const sh = this.app.screen.height
    const escala = Math.min(sw / W, sh / H) * 0.95
    this.mundo.scale.set(escala)
    this.mundo.position.set((sw - W * escala) / 2, (sh - H * escala) / 2)
  }

  private aoWheel = (e: FederatedWheelEvent): void => {
    e.preventDefault()
    const fator = e.deltaY < 0 ? 1.1 : 1 / 1.1
    const atual = this.mundo.scale.x
    const nova = Math.min(3, Math.max(0.3, atual * fator))
    const local = this.mundo.toLocal(e.global)
    this.mundo.scale.set(nova)
    this.mundo.position.set(e.global.x - local.x * nova, e.global.y - local.y * nova)
  }

  private aoPointerDownStage = (e: FederatedPointerEvent): void => {
    if (e.target !== this.app.stage) return
    this.pan = { mx: e.global.x, my: e.global.y, px: this.mundo.position.x, py: this.mundo.position.y }
    this.callbacks.aoSelecionar(null)
  }

  private aoPointerDownToken(e: FederatedPointerEvent, id: string): void {
    e.stopPropagation()
    const tv = this.tokens.get(id)
    if (!tv) return
    if (this.snap?.podeArrastar && id === this.snap.meuPersonagemId) {
      this.arrasto = { id, moveu: false, origem: [tv.x, tv.y] }
      tv.cont.cursor = "grabbing"
      tv.cont.zIndex = 1000
    } else {
      this.callbacks.aoSelecionar(id)
    }
  }

  private aoPointerMove = (e: FederatedPointerEvent): void => {
    if (this.pan) {
      this.mundo.position.set(this.pan.px + (e.global.x - this.pan.mx), this.pan.py + (e.global.y - this.pan.my))
      return
    }
    if (this.arrasto) {
      const tv = this.tokens.get(this.arrasto.id)
      if (!tv) return
      const local = this.mundo.toLocal(e.global)
      tv.cont.position.set(local.x, local.y)
      this.arrasto.moveu = true
    }
  }

  private aoPointerUp = (e: FederatedPointerEvent): void => {
    this.pan = null
    const arr = this.arrasto
    if (!arr) return
    this.arrasto = null
    const tv = this.tokens.get(arr.id)
    if (!tv) return
    tv.cont.cursor = "grab"
    tv.cont.zIndex = 0
    if (!arr.moveu) {
      this.posicionar(tv, arr.origem)
      this.callbacks.aoSelecionar(arr.id)
      return
    }
    const local = this.mundo.toLocal(e.global)
    const cx = Math.floor(local.x / T)
    const cy = Math.floor(local.y / T)
    // Volta o token para a posição oficial; o destino só vira preview se o servidor confirmar.
    this.posicionar(tv, arr.origem)
    if (this.alcanceMapa.has(chave(cx, cy)) && (cx !== arr.origem[0] || cy !== arr.origem[1])) {
      this.callbacks.aoSoltar([cx, cy])
    }
  }

  // ---------- Ticker ----------

  private tick = (ticker: Ticker): void => {
    const dt = ticker.deltaMS
    this.tempo += dt
    // barras de vida descem suavemente
    for (const tv of this.tokens.values()) {
      if (Math.abs(tv.pvVisual - tv.pvAlvo) > 0.01) {
        tv.pvVisual = this.reduz ? tv.pvAlvo : tv.pvVisual + (tv.pvAlvo - tv.pvVisual) * Math.min(1, dt / 180)
        if (Math.abs(tv.pvVisual - tv.pvAlvo) < 0.05) tv.pvVisual = tv.pvAlvo
        this.desenharBarra(tv)
      }
    }
    if (this.animacoes.length > 0) this.animacoes = this.animacoes.filter((a) => !a.atualizar(dt))
    // pulsos: alvos válidos e grade cyberpunk (respeitam prefers-reduced-motion)
    if (!this.reduz) {
      this.realceAlvos.alpha = 0.7 + 0.3 * Math.sin(this.tempo / 180)
      this.camadaMalha.alpha = this.snap?.tema === "cyberpunk" ? 0.75 + 0.25 * Math.sin(this.tempo / 700) : 1
    }
  }

  private animMovimento(tv: TokenVisual, pontos: Coord[]): Animacao {
    const duracaoPasso = 160
    let idx = 0
    let t = 0
    const pixels = pontos.map((c) => centro(c, T))
    return {
      atualizar: (dt) => {
        t += dt
        while (t >= duracaoPasso && idx < pixels.length - 1) {
          t -= duracaoPasso
          idx += 1
        }
        if (idx >= pixels.length - 1) {
          this.posicionar(tv, pontos[pontos.length - 1])
          return true
        }
        const a = pixels[idx]
        const b = pixels[idx + 1]
        const f = t / duracaoPasso
        tv.cont.position.set(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
        return false
      },
    }
  }

  private animTremor(tv: TokenVisual): Animacao {
    let t = 0
    const base = tv.cont.position.clone()
    return {
      atualizar: (dt) => {
        t += dt
        if (t >= 350 || tv.movendo) {
          if (!tv.movendo) tv.cont.position.copyFrom(base)
          return true
        }
        tv.cont.position.set(base.x + Math.sin(t / 18) * 4, base.y + Math.cos(t / 23) * 2)
        return false
      },
    }
  }

  private animFlash(tv: TokenVisual, cor: number): Animacao {
    let t = 0
    const g = new Graphics()
    g.circle(0, 0, T * 0.42).fill({ color: cor, alpha: 0.6 })
    tv.cont.addChild(g)
    return {
      atualizar: (dt) => {
        t += dt
        g.alpha = Math.max(0, 1 - t / 300)
        if (t >= 300) {
          g.destroy()
          return true
        }
        return false
      },
    }
  }

  private flutuar(tv: TokenVisual, texto: string, cor: number, imediato: boolean, tamanho = 16): void {
    const txt = new Text({
      text: texto,
      style: { fontSize: tamanho, fill: cor, fontWeight: "bold", fontFamily: "sans-serif", stroke: { color: 0x000000, width: 3 } },
    })
    txt.anchor.set(0.5, 1)
    const [px, py] = centro([tv.x, tv.y], T)
    txt.position.set(px + (Math.random() - 0.5) * 10, py - T * 0.5)
    this.flutuantes.addChild(txt)
    const duracao = imediato ? 900 : 1400
    let t = 0
    this.animacoes.push({
      atualizar: (dt) => {
        t += dt
        if (!this.reduz) txt.position.y -= dt * 0.03
        txt.alpha = t < duracao * 0.6 ? 1 : Math.max(0, 1 - (t - duracao * 0.6) / (duracao * 0.4))
        if (t >= duracao) {
          txt.destroy()
          return true
        }
        return false
      },
    })
  }
}
