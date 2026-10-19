import { useEffect, useMemo, useState } from "react"
import { api, errosDoDetail } from "../lib/api"
import { expressaoValida } from "../lib/dados"
import type { AtaqueEnvio, FichaEnvio, FichaEnvioLivre, Intervalo, ModeloFicha } from "../types"
import FichaCamposBasicos, { COR_PADRAO, ErrosFicha, validarBasicos, type Basicos } from "./FichaCamposBasicos"
import FichaFormClasses from "./FichaFormClasses"

interface Props {
  sistemaId: string
  /** Faz o POST; deve lançar `ErroApi` (400 com `detail`) para os erros aparecerem no formulário. */
  aoCriar(ficha: FichaEnvio): Promise<void>
  aoCancelar?(): void
}

/**
 * Formulário de ficha gerado a partir de `GET /api/sistemas/{id}/modelo-ficha` (§7).
 * `modo: "classes"` → o jogador escolhe classe, nível, atributos, perícias e equipamento e o servidor calcula o resto;
 * `modo: "livre"` (ou ausente) → o jogador digita todos os números.
 */
export default function FichaForm({ sistemaId, aoCriar, aoCancelar }: Props) {
  const [modelo, setModelo] = useState<ModeloFicha | null>(null)
  const [erroCarga, setErroCarga] = useState<string | null>(null)

  useEffect(() => {
    let cancelado = false
    setModelo(null)
    setErroCarga(null)
    api
      .modeloFicha(sistemaId)
      .then((m) => !cancelado && setModelo(m))
      .catch((e: Error) => !cancelado && setErroCarga(e.message))
    return () => {
      cancelado = true
    }
  }, [sistemaId])

  if (erroCarga) return <p style={{ color: "var(--status-vida)" }}>Não foi possível carregar o modelo de ficha: {erroCarga}</p>
  if (!modelo) return <p className="piscando text-suave">Carregando o modelo de ficha…</p>
  if (modelo.modo === "classes" && (modelo.classes?.length ?? 0) > 0) return <FichaFormClasses modelo={modelo} aoCriar={aoCriar} aoCancelar={aoCancelar} />
  return <FichaFormLivre modelo={modelo} aoCriar={aoCriar} aoCancelar={aoCancelar} />
}

// ====================================================================== modo "livre"

interface AtaqueEditor {
  chave: number
  nome: string
  bonus: string
  dano: string
  tipo_dano: string
  alcance: string
}

let proximaChave = 1
const novoAtaque = (tipo = "corte"): AtaqueEditor => ({ chave: proximaChave++, nome: "", bonus: "0", dano: "", tipo_dano: tipo, alcance: "1" })

const inteiro = (v: string): number | null => {
  const t = v.trim()
  if (!/^[+-]?\d+$/.test(t)) return null
  return Number(t)
}

function checarInt(v: string, lim: Intervalo, rotulo: string, erros: string[]): number {
  const n = inteiro(v)
  if (n === null) {
    erros.push(`${rotulo} deve ser um número inteiro`)
    return 0
  }
  if (n < lim[0] || n > lim[1]) erros.push(`${rotulo} fora dos limites (${lim[0]} a ${lim[1]})`)
  return n
}

interface PropsLivre {
  modelo: ModeloFicha
  aoCriar(ficha: FichaEnvio): Promise<void>
  aoCancelar?(): void
}

/** Ficha livre: todos os números digitados pelo jogador, validados pelos `limites` do modelo. */
export function FichaFormLivre({ modelo, aoCriar, aoCancelar }: PropsLivre) {
  const [ocupado, setOcupado] = useState(false)
  const [errosServidor, setErrosServidor] = useState<string[]>([])
  const [tentou, setTentou] = useState(false)

  const [basicos, setBasicos] = useState<Basicos>({ nome: "", icone: modelo.icones[0] ?? "", cor: COR_PADRAO, voz: "", historia: "" })
  const [classe, setClasse] = useState("")
  const [atributos, setAtributos] = useState<Record<string, string>>(() => Object.fromEntries(modelo.atributos.map((a) => [a, "0"])))
  const [barras, setBarras] = useState<Record<string, string>>(() => Object.fromEntries(modelo.barras.map((b) => [b.id, b.id === "pv" ? "10" : "0"])))
  const [defesa, setDefesa] = useState("10")
  const [deslocamento, setDeslocamento] = useState("6")
  const [iniciativa, setIniciativa] = useState("0")
  const [pericias, setPericias] = useState<Record<string, { ativa: boolean; bonus: string }>>(() => Object.fromEntries(modelo.pericias.map((p) => [p, { ativa: false, bonus: "0" }])))
  const [ataques, setAtaques] = useState<AtaqueEditor[]>(() => [novoAtaque(modelo.tipos_dano[0] ?? "corte")])

  /** Validação local com os `limites` do modelo; devolve a ficha pronta para envio ou a lista de erros. */
  const validar = useMemo(() => {
    return (): { ficha: FichaEnvioLivre | null; erros: string[] } => {
      const L = modelo.limites
      const e: string[] = validarBasicos(basicos, modelo)
      if (classe.length > L.classe) e.push(`classe com no máximo ${L.classe} caracteres`)
      const atr: Record<string, number> = {}
      for (const a of modelo.atributos) atr[a] = checarInt(atributos[a] ?? "0", L.atributo, `atributo ${a}`, e)
      const bar: Record<string, number> = {}
      for (const b of modelo.barras) bar[b.id] = checarInt(barras[b.id] ?? "0", b.id === "pv" ? L.pv : L.barra, `barra ${b.nome}`, e)
      const def = checarInt(defesa, L.defesa, modelo.campo_defesa, e)
      const des = checarInt(deslocamento, L.deslocamento, "deslocamento", e)
      const ini = checarInt(iniciativa, L.iniciativa_bonus, "iniciativa", e)
      const per: Record<string, number> = {}
      for (const p of modelo.pericias) {
        const ed = pericias[p]
        if (ed?.ativa) per[p] = checarInt(ed.bonus, L.pericia, `perícia ${p}`, e)
      }
      if (Object.keys(per).length > L.max_pericias) e.push(`no máximo ${L.max_pericias} perícias`)
      const atq: AtaqueEnvio[] = []
      if (ataques.length === 0) e.push("inclua pelo menos um ataque")
      if (ataques.length > L.max_ataques) e.push(`no máximo ${L.max_ataques} ataques`)
      ataques.forEach((a, i) => {
        const an = a.nome.trim() || `Ataque ${i + 1}`
        if (!a.nome.trim()) e.push(`ataque ${i + 1}: informe o nome`)
        const dano = a.dano.replace(/\s/g, "")
        if (!expressaoValida(dano)) e.push(`ataque '${an}': expressão de dano inválida (ex.: ${modelo.exemplo_dano})`)
        atq.push({
          nome: an,
          bonus: checarInt(a.bonus, L.bonus_ataque, `bônus de '${an}'`, e),
          dano,
          tipo_dano: modelo.tipos_dano.includes(a.tipo_dano) ? a.tipo_dano : (modelo.tipos_dano[0] ?? "impacto"),
          alcance: checarInt(a.alcance, L.alcance, `alcance de '${an}'`, e),
        })
      })
      if (e.length > 0) return { ficha: null, erros: e }
      const ficha: FichaEnvioLivre = {
        nome: basicos.nome.trim(),
        atributos: atr,
        barras: bar,
        defesa: def,
        deslocamento: des,
        iniciativa_bonus: ini,
        pericias: per,
        ataques: atq,
        cor: basicos.cor,
      }
      if (classe.trim()) ficha.classe = classe.trim()
      if (basicos.icone) ficha.icone = basicos.icone
      if (basicos.historia.trim()) ficha.historia = basicos.historia.trim()
      if (basicos.voz) ficha.voz = basicos.voz
      return { ficha, erros: [] }
    }
  }, [modelo, basicos, classe, atributos, barras, defesa, deslocamento, iniciativa, pericias, ataques])

  const enviar = async (ev: React.FormEvent) => {
    ev.preventDefault()
    setTentou(true)
    const { ficha } = validar()
    if (!ficha) return
    setOcupado(true)
    setErrosServidor([])
    try {
      await aoCriar(ficha)
    } catch (err) {
      setErrosServidor(errosDoDetail(err))
    } finally {
      setOcupado(false)
    }
  }

  const L = modelo.limites
  // Depois da primeira tentativa, os erros locais acompanham a edição; os do servidor ficam até o próximo envio.
  const errosLocais = tentou ? validar().erros : []
  const atualizarAtaque = (chave: number, patch: Partial<AtaqueEditor>) => setAtaques((lista) => lista.map((a) => (a.chave === chave ? { ...a, ...patch } : a)))

  return (
    <form onSubmit={enviar} className="space-y-4 text-sm" aria-label={`Nova ficha (${modelo.sistema_nome})`} noValidate>
      <p className="text-xs text-suave">
        Sistema <strong className="text-texto">{modelo.sistema_nome}</strong>. Os campos seguem os limites do sistema; o servidor valida de novo ao criar.
      </p>

      <FichaCamposBasicos
        modelo={modelo}
        valor={basicos}
        aoMudar={(patch) => setBasicos((b) => ({ ...b, ...patch }))}
        aposNome={
          <div>
            <label className="rotulo" htmlFor="ficha-classe">Classe</label>
            <input id="ficha-classe" className="campo" value={classe} maxLength={L.classe} onChange={(e) => setClasse(e.target.value)} placeholder="Guerreiro, Arcanista…" />
          </div>
        }
      />

      {modelo.atributos.length > 0 && (
        <section>
          <h3 className="rotulo">Atributos ({L.atributo[0]} a {L.atributo[1]})</h3>
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
            {modelo.atributos.map((a) => (
              <div key={a}>
                <label className="block text-center text-[11px] uppercase text-suave" htmlFor={`atr-${a}`}>{a}</label>
                <input
                  id={`atr-${a}`}
                  className="campo text-center tabular-nums"
                  type="number"
                  inputMode="numeric"
                  min={L.atributo[0]}
                  max={L.atributo[1]}
                  value={atributos[a] ?? "0"}
                  onChange={(e) => setAtributos({ ...atributos, [a]: e.target.value })}
                />
              </div>
            ))}
          </div>
        </section>
      )}

      <section>
        <h3 className="rotulo">Recursos e combate</h3>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {modelo.barras.map((b) => {
            const lim = b.id === "pv" ? L.pv : L.barra
            return (
              <div key={b.id}>
                <label className="block text-[11px] text-suave" htmlFor={`barra-${b.id}`}>{b.nome} (máx.)</label>
                <input id={`barra-${b.id}`} className="campo tabular-nums" type="number" inputMode="numeric" min={lim[0]} max={lim[1]} value={barras[b.id] ?? "0"} onChange={(e) => setBarras({ ...barras, [b.id]: e.target.value })} />
              </div>
            )
          })}
          <div>
            <label className="block text-[11px] text-suave" htmlFor="ficha-defesa">{modelo.nome_defesa ?? modelo.campo_defesa}</label>
            <input id="ficha-defesa" className="campo tabular-nums" type="number" inputMode="numeric" min={L.defesa[0]} max={L.defesa[1]} value={defesa} onChange={(e) => setDefesa(e.target.value)} />
          </div>
          <div>
            <label className="block text-[11px] text-suave" htmlFor="ficha-desloc">Deslocamento (quadrados)</label>
            <input id="ficha-desloc" className="campo tabular-nums" type="number" inputMode="numeric" min={L.deslocamento[0]} max={L.deslocamento[1]} value={deslocamento} onChange={(e) => setDeslocamento(e.target.value)} />
          </div>
          <div>
            <label className="block text-[11px] text-suave" htmlFor="ficha-ini">Bônus de iniciativa</label>
            <input id="ficha-ini" className="campo tabular-nums" type="number" inputMode="numeric" min={L.iniciativa_bonus[0]} max={L.iniciativa_bonus[1]} value={iniciativa} onChange={(e) => setIniciativa(e.target.value)} />
          </div>
        </div>
      </section>

      {modelo.pericias.length > 0 && (
        <section>
          <h3 className="rotulo">
            Perícias treinadas <span className="normal-case">(bônus {L.pericia[0]} a {L.pericia[1]})</span>
          </h3>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 sm:grid-cols-3">
            {modelo.pericias.map((p) => {
              const ed = pericias[p] ?? { ativa: false, bonus: "0" }
              return (
                <div key={p} className="flex items-center gap-1">
                  <input id={`per-${p}`} type="checkbox" checked={ed.ativa} onChange={(e) => setPericias({ ...pericias, [p]: { ...ed, ativa: e.target.checked } })} />
                  <label htmlFor={`per-${p}`} className={`flex-1 truncate capitalize ${ed.ativa ? "" : "text-suave"}`}>{p}</label>
                  <input
                    className="campo px-1 py-0.5 text-center tabular-nums"
                    style={{ width: "3.5rem", flex: "0 0 auto" }}
                    type="number"
                    inputMode="numeric"
                    min={L.pericia[0]}
                    max={L.pericia[1]}
                    value={ed.bonus}
                    disabled={!ed.ativa}
                    aria-label={`Bônus de ${p}`}
                    onChange={(e) => setPericias({ ...pericias, [p]: { ...ed, bonus: e.target.value } })}
                  />
                </div>
              )
            })}
          </div>
        </section>
      )}

      <section>
        <div className="flex items-center justify-between">
          <h3 className="rotulo mb-0">Ataques (1 a {L.max_ataques})</h3>
          <button type="button" className="botao px-2 py-0.5 text-xs" disabled={ataques.length >= L.max_ataques} onClick={() => setAtaques([...ataques, novoAtaque(modelo.tipos_dano[0] ?? "corte")])}>
            ➕ Ataque
          </button>
        </div>
        <p className="mb-1 text-[11px] text-suave">
          Rolagem de ataque: <code>{modelo.expressao_ataque}</code> · dano no formato <code>{modelo.exemplo_dano}</code>
        </p>
        <ul className="space-y-2">
          {ataques.map((a, i) => {
            const danoOk = a.dano.trim() === "" || expressaoValida(a.dano)
            return (
              <li key={a.chave} className="rounded p-2" style={{ background: "#00000033" }}>
                <div className="grid grid-cols-2 gap-1 sm:grid-cols-6">
                  <div className="col-span-2">
                    <label className="block text-[10px] uppercase text-suave" htmlFor={`atq-nome-${a.chave}`}>Nome</label>
                    <input id={`atq-nome-${a.chave}`} className="campo" value={a.nome} maxLength={40} placeholder={`Ataque ${i + 1}`} onChange={(e) => atualizarAtaque(a.chave, { nome: e.target.value })} />
                  </div>
                  <div>
                    <label className="block text-[10px] uppercase text-suave" htmlFor={`atq-bonus-${a.chave}`}>Bônus</label>
                    <input id={`atq-bonus-${a.chave}`} className="campo tabular-nums" type="number" inputMode="numeric" min={L.bonus_ataque[0]} max={L.bonus_ataque[1]} value={a.bonus} onChange={(e) => atualizarAtaque(a.chave, { bonus: e.target.value })} />
                  </div>
                  <div>
                    <label className="block text-[10px] uppercase text-suave" htmlFor={`atq-dano-${a.chave}`}>Dano</label>
                    <input
                      id={`atq-dano-${a.chave}`}
                      className="campo font-mono"
                      value={a.dano}
                      placeholder={modelo.exemplo_dano}
                      aria-invalid={!danoOk}
                      style={{ borderColor: danoOk ? undefined : "var(--status-vida)" }}
                      onChange={(e) => atualizarAtaque(a.chave, { dano: e.target.value })}
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] uppercase text-suave" htmlFor={`atq-tipo-${a.chave}`}>Tipo</label>
                    <select id={`atq-tipo-${a.chave}`} className="campo" value={a.tipo_dano} onChange={(e) => atualizarAtaque(a.chave, { tipo_dano: e.target.value })}>
                      {modelo.tipos_dano.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-[10px] uppercase text-suave" htmlFor={`atq-alc-${a.chave}`}>Alcance</label>
                    <div className="flex gap-1">
                      <input id={`atq-alc-${a.chave}`} className="campo tabular-nums" type="number" inputMode="numeric" min={L.alcance[0]} max={L.alcance[1]} value={a.alcance} onChange={(e) => atualizarAtaque(a.chave, { alcance: e.target.value })} />
                      <button type="button" className="botao botao-perigo px-2" disabled={ataques.length <= 1} aria-label={`Remover ataque ${i + 1}`} onClick={() => setAtaques(ataques.filter((x) => x.chave !== a.chave))}>
                        ✕
                      </button>
                    </div>
                  </div>
                </div>
                {!danoOk && (
                  <p className="mt-1 text-[11px]" style={{ color: "var(--status-vida)" }}>
                    Expressão de dano inválida. Use o formato <code>{modelo.exemplo_dano}</code> (até 100 dados de 2 a 1000 faces).
                  </p>
                )}
              </li>
            )
          })}
        </ul>
      </section>

      <ErrosFicha locais={errosLocais} servidor={errosServidor} />

      <div className="flex gap-2">
        <button className="botao botao-primario flex-1 py-2" disabled={ocupado}>
          {ocupado ? "Criando…" : "Criar ficha"}
        </button>
        {aoCancelar && (
          <button type="button" className="botao" onClick={aoCancelar} disabled={ocupado}>
            Cancelar
          </button>
        )}
      </div>
    </form>
  )
}
