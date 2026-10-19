// Prévia da ficha no modo "classes": espelha `server/fichas.py` (construir_ficha) para o jogador ver
// PV, recurso, Defesa, ataques, perícias e habilidades antes de criar. O servidor é a fonte da verdade.

import type { ArmaModelo, ArmaduraModelo, ClasseModelo, FichaEnvioClasses, Habilidade, ModeloFicha } from "../types"

export interface AtaquePrevia {
  id: string
  nome: string
  bonus: number
  dano: string
  tipo_dano: string
  alcance: number
}

export interface PreviaFicha {
  tipo: "5e" | "t20"
  prof: number
  meioNivel: number
  pv: number
  recurso: number
  /** id da barra de recurso (segunda barra do sistema), se houver. */
  barraRecurso: string | null
  defesa: number
  cd: number
  bonusMagia: number
  ataques: AtaquePrevia[]
  /** perícia → bônus (todas as perícias do sistema). */
  pericias: Record<string, number>
  treinadas: string[]
  habilidades: Habilidade[]
  /** Perícias escolhidas da lista da classe / fora dela (para os contadores). */
  deClasse: string[]
  livres: string[]
  somaAtributos: number
  somaMax: number
  erros: string[]
}

export const sinal = (n: number) => (n >= 0 ? `+${n}` : String(n))

/** Soma máxima dos modificadores: `limites.soma_atributos` (+2 a cada 4 níveis), como no servidor. */
export function somaMaximaAtributos(modelo: ModeloFicha, nivel: number): number {
  const base = modelo.limites.soma_atributos ?? 12
  return base + Math.floor((nivel - 1) / 4) * 2
}

export function nivelMaximo(modelo: ModeloFicha): number {
  return Math.max(1, modelo.progressao?.nivel_max ?? modelo.limites.nivel?.[1] ?? 5)
}

function modArma(arma: ArmaModelo, atributos: Record<string, number>): number {
  const regra = arma.atributo ?? "FOR"
  if (regra === "melhor") return Math.max(atributos.FOR ?? 0, atributos.DES ?? 0)
  return atributos[regra] ?? 0
}

function comMod(dano: string, mod: number): string {
  return mod ? `${dano}${mod >= 0 ? "+" : ""}${mod}` : dano
}

/** Calcula os números derivados de uma ficha no modo "classes". Devolve null se a classe não existir. */
export function derivarFicha(modelo: ModeloFicha, f: FichaEnvioClasses): PreviaFicha | null {
  const classe: ClasseModelo | undefined = (modelo.classes ?? []).find((c) => c.id === f.classe_id)
  if (!classe) return null
  const erros: string[] = []
  const prog = modelo.progressao ?? {}
  const tipo: "5e" | "t20" = prog.tipo === "t20" ? "t20" : "5e"
  const nivel = Math.max(1, Math.min(nivelMaximo(modelo), Math.floor(f.nivel || 1)))
  const atributos: Record<string, number> = {}
  for (const a of modelo.atributos) atributos[a] = Math.floor(f.atributos[a] ?? 0)
  const con = atributos.CON ?? 0
  const des = atributos.DES ?? 0
  const principal = classe.atributo_principal ?? "FOR"
  const modPrincipal = atributos[principal] ?? 0

  const somaAtributos = Object.values(atributos).reduce((a, b) => a + b, 0)
  const somaMax = somaMaximaAtributos(modelo, nivel)
  if (somaAtributos > somaMax) erros.push(`a soma dos modificadores de atributo não pode passar de +${somaMax} no nível ${nivel}`)

  // ---- progressão
  let prof: number
  let meioNivel = Math.floor(nivel / 2)
  let pv: number
  let recurso: number
  let treinada: (mod: number) => number
  let destreinada: (mod: number) => number
  let ataque: (mod: number) => number
  let cd: number
  let bonusMagia: number
  if (tipo === "t20") {
    const treino = nivel < 7 ? (prog.treino ?? 2) : 4
    pv = (classe.pv_nivel1 ?? 12) + con + (nivel - 1) * ((classe.pv_por_nivel ?? 3) + con)
    recurso = (classe.pm_por_nivel ?? 3) * nivel
    treinada = (mod) => meioNivel + mod + treino
    destreinada = (mod) => meioNivel + mod
    ataque = (mod) => meioNivel + mod
    cd = 10 + meioNivel + modPrincipal
    bonusMagia = meioNivel + modPrincipal
    prof = treino
  } else {
    const tabela = prog.proficiencia ?? [2, 2, 2, 2, 3, 3, 3, 3, 4, 4]
    prof = tabela[Math.min(nivel, tabela.length) - 1] ?? 2
    const dv = classe.dado_vida ?? 8
    pv = dv + con + (nivel - 1) * (Math.floor(dv / 2) + 1 + con)
    const esp = prog.espacos_conjurador ?? [2, 3, 4, 4, 4]
    if (classe.conjurador) recurso = esp[Math.min(nivel, esp.length) - 1] ?? 0
    else recurso = classe.habilidades.some((h) => h.custo) ? nivel : 0
    treinada = (mod) => prof + mod
    destreinada = (mod) => mod
    ataque = (mod) => prof + mod
    cd = 8 + prof + modPrincipal
    bonusMagia = prof + modPrincipal
    meioNivel = Math.floor(nivel / 2)
  }
  pv = Math.max(1, pv)
  recurso = Math.max(0, recurso)

  // ---- perícias
  const todas = modelo.pericias
  const fixas = classe.pericias_fixas.filter((p) => todas.includes(p))
  const escolhidas = f.pericias.filter((p) => todas.includes(p) && !fixas.includes(p))
  const deClasse = escolhidas.filter((p) => classe.pericias_de_classe.includes(p))
  const livres = escolhidas.filter((p) => !classe.pericias_de_classe.includes(p))
  const extras = modelo.limites.pericias_extras ?? 2
  if (deClasse.length > classe.quantidade_pericias) erros.push(`a classe ${classe.nome} permite ${classe.quantidade_pericias} perícias de classe (escolheu ${deClasse.length})`)
  if (livres.length > extras) erros.push(`no máximo ${extras} perícias fora da lista da classe (antecedente)`)
  const treinadas = [...new Set([...fixas, ...escolhidas])].sort()
  const periciaAtr = modelo.pericia_atributo ?? {}
  const pericias: Record<string, number> = {}
  for (const p of todas) {
    const mod = atributos[periciaAtr[p] ?? "DES"] ?? 0
    pericias[p] = treinadas.includes(p) ? treinada(mod) : destreinada(mod)
  }

  // ---- equipamento
  const armasCfg = new Map((modelo.armas ?? []).map((a) => [a.id, a]))
  const armadurasCfg = new Map((modelo.armaduras ?? []).map((a) => [a.id, a]))
  const maxArmas = modelo.limites.max_armas ?? 3
  const idsArmas = (f.armas.length > 0 ? f.armas : classe.armas_iniciais).slice(0, maxArmas)
  if (f.armas.length > maxArmas) erros.push(`no máximo ${maxArmas} armas`)
  const ataques: AtaquePrevia[] = []
  for (const aid of idsArmas) {
    const arma = armasCfg.get(aid)
    if (!arma) {
      erros.push(`arma desconhecida: ${aid}`)
      continue
    }
    const mod = modArma(arma, atributos)
    const dano = comMod(arma.dano, mod)
    ataques.push({ id: arma.id, nome: arma.nome, bonus: ataque(mod), dano, tipo_dano: arma.tipo_dano ?? "impacto", alcance: arma.alcance ?? 1 })
    if (arma.arremesso) ataques.push({ id: `${arma.id}_arremesso`, nome: `${arma.nome} (arremesso)`, bonus: ataque(mod), dano, tipo_dano: arma.tipo_dano ?? "impacto", alcance: arma.arremesso })
  }
  if (ataques.length === 0) erros.push("escolha pelo menos uma arma")

  const armaduraId = f.armadura_id || classe.armadura_inicial || "nenhuma"
  let armadura: ArmaduraModelo | undefined = armadurasCfg.get(armaduraId)
  if (!armadura) {
    erros.push(`armadura desconhecida: ${armaduraId}`)
    armadura = armadurasCfg.get("nenhuma") ?? { id: "nenhuma", nome: "Sem armadura", defesa_base: 10, max_des: null }
  }
  const escudo = !!f.escudo
  let defesa = armadura.defesa_base + (armadura.max_des === null || armadura.max_des === undefined ? des : Math.min(des, armadura.max_des))
  if (escudo) defesa += modelo.escudo?.bonus ?? 2

  // ---- habilidades até o nível (+ passivas na defesa)
  const habilidades: Habilidade[] = []
  for (const h of classe.habilidades) {
    if ((h.nivel ?? 1) > nivel) continue
    habilidades.push(h.usos ? { ...h, usos_restantes: h.usos.max } : { ...h })
    const pas = h.efeito?.passiva
    if (!pas) continue
    if (pas.mod_defesa) defesa += pas.mod_defesa
    if (pas.defesa_sem_armadura && armaduraId === "nenhuma" && !escudo) {
      defesa = 10 + pas.defesa_sem_armadura.reduce((acc, a) => acc + (atributos[a] ?? 0), 0)
    }
  }
  defesa = Math.max(1, defesa)

  const barraRecurso = modelo.barras.find((b) => b.id !== "pv")?.id ?? null

  return {
    tipo,
    prof,
    meioNivel,
    pv,
    recurso,
    barraRecurso,
    defesa,
    cd,
    bonusMagia,
    ataques,
    pericias,
    treinadas,
    habilidades,
    deClasse,
    livres,
    somaAtributos,
    somaMax,
    erros,
  }
}

const ROTULO_BARRA: Record<string, string> = { pv: "PV", pm: "PM", espacos: "espaços", sanidade: "sanidade" }

/** Rótulo curto de uma barra pelo id ("pm" → "PM", "espacos" → "espaços"). */
export const rotuloBarra = (id: string) => ROTULO_BARRA[id] ?? id.toUpperCase()

/** Texto curto do custo/usos de uma habilidade (ex.: "1 PM", "2 usos / descanso longo"). */
export function custoDaHabilidade(h: Habilidade, nomeBarra: (id: string) => string = rotuloBarra): string | null {
  if (h.custo) return `${h.custo.valor} ${nomeBarra(h.custo.barra)}`
  if (h.usos) return `${h.usos.max} uso${h.usos.max === 1 ? "" : "s"} / descanso ${h.usos.recupera}`
  return null
}
