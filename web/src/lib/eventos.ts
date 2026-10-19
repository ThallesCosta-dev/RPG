import type { Estado, Evento, Personagem } from "../types"

// Aplica um evento bruto ao estado local (otimista, até o state_sync confirmar).
// Devolve um novo objeto; nunca muta o estado anterior.

function comPersonagem(state: Estado, id: string, mudar: (p: Personagem) => Personagem): Estado {
  const p = state.personagens[id]
  if (!p) return state
  return { ...state, personagens: { ...state.personagens, [id]: mudar(p) } }
}

function ajustarBarra(p: Personagem, barra: string, delta: number): Personagem {
  const b = p.barras[barra]
  if (!b) return p
  const atual = Math.max(0, Math.min(b.max, b.atual + delta))
  return { ...p, barras: { ...p.barras, [barra]: { ...b, atual } } }
}

export function aplicarEvento(state: Estado, ev: Evento): Estado {
  switch (ev.tipo) {
    case "movimento":
      return comPersonagem(state, ev.personagem, (p) => ({ ...p, x: ev.para[0], y: ev.para[1] }))
    case "dano":
      return comPersonagem(state, ev.alvo, (p) => ajustarBarra(p, ev.barra || "pv", -ev.valor))
    case "cura":
      return comPersonagem(state, ev.alvo, (p) => ajustarBarra(p, ev.barra || "pv", ev.valor))
    case "recurso":
      // Custo de habilidade: a barra indicada (PM, espaços…) desce como no dano.
      return comPersonagem(state, ev.personagem, (p) => ajustarBarra(p, ev.barra || "pm", -ev.valor))
    case "uso_gasto":
      return comPersonagem(state, ev.personagem, (p) => ({ ...p, usos: { ...(p.usos ?? {}), [ev.habilidade]: Math.max(0, (p.usos?.[ev.habilidade] ?? 0) - 1) } }))
    case "condicao":
      return comPersonagem(state, ev.alvo, (p) => ({
        ...p,
        condicoes: [...p.condicoes.filter((c) => c.id !== ev.condicao), { id: ev.condicao, rodadas_restantes: ev.rodadas }],
      }))
    case "condicao_removida":
      return comPersonagem(state, ev.alvo, (p) => ({ ...p, condicoes: p.condicoes.filter((c) => c.id !== ev.condicao) }))
    case "caiu":
      return comPersonagem(state, ev.personagem, (p) => ({ ...p, caido: true }))
    case "levantou":
      return comPersonagem(state, ev.personagem, (p) => ({ ...p, caido: false }))
    case "obstaculo_adicionado": {
      const tipo = ev.tipo_obstaculo ?? ev.obstaculo ?? "obstaculo"
      const outros = state.obstaculos.filter((o) => o.x !== ev.x || o.y !== ev.y)
      return { ...state, obstaculos: [...outros, { x: ev.x, y: ev.y, tipo, rodadas_restantes: ev.duracao_rodadas }] }
    }
    case "obstaculo_removido":
      return { ...state, obstaculos: state.obstaculos.filter((o) => o.x !== ev.x || o.y !== ev.y) }
    case "combate_iniciado":
      return { ...state, modo: "combate", iniciativa: ev.ordem }
    case "combate_encerrado":
      return { ...state, modo: "exploracao", iniciativa: [] }
    default:
      return state
  }
}

/** Nome do personagem (ou o id, se não estiver no estado). */
export function nomeDe(state: Estado | null, id: string): string {
  return state?.personagens[id]?.nome ?? id
}
