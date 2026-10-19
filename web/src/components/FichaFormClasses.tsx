import { useMemo, useState } from "react"
import { errosDoDetail } from "../lib/api"
import { custoDaHabilidade, derivarFicha, nivelMaximo, sinal, somaMaximaAtributos } from "../lib/ficha"
import type { ClasseModelo, FichaEnvio, FichaEnvioClasses, Habilidade, ModeloFicha } from "../types"
import FichaCamposBasicos, { COR_PADRAO, ErrosFicha, validarBasicos, type Basicos } from "./FichaCamposBasicos"

interface Props {
  modelo: ModeloFicha
  aoCriar(ficha: FichaEnvio): Promise<void>
  aoCancelar?(): void
}

const ROTULO_ALVO: Record<string, string> = { self: "em si", aliado: "aliado", inimigo: "inimigo", area: "área" }
const ROTULO_SLOT: Record<string, string> = { padrao: "ação", bonus: "ação bônus" }

/** Resumo de uma classe para o card: dado de vida ou PV/PM por nível, atributo principal, conjurador. */
function resumoClasse(c: ClasseModelo, tipo: string): string {
  const partes: string[] = []
  if (tipo === "t20") partes.push(`PV ${c.pv_nivel1 ?? "?"} +${c.pv_por_nivel ?? "?"}/nível`, `PM ${c.pm_por_nivel ?? "?"}/nível`)
  else partes.push(`dado de vida d${c.dado_vida ?? "?"}`)
  if (c.atributo_principal) partes.push(c.atributo_principal)
  if (c.conjurador) partes.push("conjurador")
  return partes.join(" · ")
}

function Passo({ n, titulo, extra, children }: { n: number; titulo: string; extra?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="rotulo mb-0">
          <span className="chip mr-1 tabular-nums">{n}</span>
          {titulo}
        </h3>
        {extra}
      </div>
      {children}
    </section>
  )
}

/** Linha de habilidade (prévia e ficha): nome, nível, tipo/slot/alvo, custo ou usos e descrição. */
export function LinhaHabilidade({ h, usosRestantes }: { h: Habilidade; usosRestantes?: number }) {
  const custo = custoDaHabilidade(h)
  return (
    <li className="rounded px-2 py-1.5" style={{ background: "#00000033" }}>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <strong>{h.nome}</strong>
        <span className="text-[11px] text-suave">
          nível {h.nivel} · {h.tipo === "passiva" ? "passiva" : `${ROTULO_SLOT[h.slot ?? "padrao"] ?? h.slot} · ${ROTULO_ALVO[h.alvo ?? "self"] ?? h.alvo}`}
          {h.tipo === "ativa" && h.alcance ? ` · alcance ${h.alcance} q` : ""}
          {h.raio ? ` · raio ${h.raio}` : ""}
        </span>
        {custo && (
          <span className="chip ml-auto" style={{ borderColor: "var(--status-recurso)" }}>
            {custo}
            {h.usos && usosRestantes !== undefined ? ` · restam ${usosRestantes}/${h.usos.max}` : ""}
          </span>
        )}
      </div>
      <p className="text-[12px] leading-snug text-suave">{h.descricao}</p>
    </li>
  )
}

/** Ficha no modo "classes": o jogador escolhe; o servidor calcula PV, recurso, Defesa, ataques, perícias e habilidades. */
export default function FichaFormClasses({ modelo, aoCriar, aoCancelar }: Props) {
  const classes = modelo.classes ?? []
  const L = modelo.limites
  const tipo = modelo.progressao?.tipo === "t20" ? "t20" : "5e"
  const nivelMax = nivelMaximo(modelo)
  const maxArmas = L.max_armas ?? 3
  const extrasMax = L.pericias_extras ?? 2
  const nomeDefesa = modelo.nome_defesa ?? modelo.campo_defesa
  const barraRecurso = modelo.barras.find((b) => b.id !== "pv")

  const [ocupado, setOcupado] = useState(false)
  const [errosServidor, setErrosServidor] = useState<string[]>([])
  const [tentou, setTentou] = useState(false)

  const [basicos, setBasicos] = useState<Basicos>({ nome: "", icone: modelo.icones[0] ?? "", cor: COR_PADRAO, voz: "", historia: "" })
  const [classeId, setClasseId] = useState("")
  const [nivel, setNivel] = useState(1)
  const [atributos, setAtributos] = useState<Record<string, number>>(() => Object.fromEntries(modelo.atributos.map((a) => [a, 0])))
  const [pericias, setPericias] = useState<string[]>([])
  const [armas, setArmas] = useState<string[]>([])
  const [armaduraId, setArmaduraId] = useState("nenhuma")
  const [escudo, setEscudo] = useState(false)

  const classe = classes.find((c) => c.id === classeId)

  const escolherClasse = (c: ClasseModelo) => {
    setClasseId(c.id)
    setPericias((atual) => atual.filter((p) => !c.pericias_fixas.includes(p)))
    setArmas(c.armas_iniciais.filter((id) => (modelo.armas ?? []).some((a) => a.id === id)).slice(0, maxArmas))
    setArmaduraId((modelo.armaduras ?? []).some((a) => a.id === c.armadura_inicial) ? c.armadura_inicial : "nenhuma")
    setEscudo(c.escudo)
  }

  const envio: FichaEnvioClasses = useMemo(
    () => ({
      nome: basicos.nome.trim(),
      classe_id: classeId,
      nivel,
      atributos,
      pericias,
      armas,
      armadura_id: armaduraId,
      escudo,
      cor: basicos.cor,
      icone: basicos.icone || undefined,
      historia: basicos.historia.trim() || undefined,
      voz: basicos.voz || undefined,
    }),
    [basicos, classeId, nivel, atributos, pericias, armas, armaduraId, escudo],
  )
  const previa = useMemo(() => (classe ? derivarFicha(modelo, envio) : null), [modelo, envio, classe])

  const somaAtr = Object.values(atributos).reduce((a, b) => a + b, 0)
  const somaMax = somaMaximaAtributos(modelo, nivel)
  const somaEstourou = somaAtr > somaMax

  const errosLocais = (): string[] => {
    const e = validarBasicos(basicos, modelo)
    if (!classe) e.push("escolha uma classe")
    if (previa) e.push(...previa.erros)
    return e
  }

  const enviar = async (ev: React.FormEvent) => {
    ev.preventDefault()
    setTentou(true)
    if (errosLocais().length > 0) return
    setOcupado(true)
    setErrosServidor([])
    try {
      await aoCriar(envio)
    } catch (err) {
      setErrosServidor(errosDoDetail(err))
    } finally {
      setOcupado(false)
    }
  }

  const mudarAtributo = (a: string, v: number) => {
    const n = Math.max(L.atributo[0], Math.min(L.atributo[1], Math.floor(v)))
    setAtributos((atual) => ({ ...atual, [a]: Number.isFinite(n) ? n : 0 }))
  }
  const alternarPericia = (p: string, marcada: boolean) => setPericias((atual) => (marcada ? [...atual.filter((x) => x !== p), p] : atual.filter((x) => x !== p)))
  const alternarArma = (id: string, marcada: boolean) => setArmas((atual) => (marcada ? [...atual.filter((x) => x !== id), id].slice(0, maxArmas) : atual.filter((x) => x !== id)))

  const fixas = classe?.pericias_fixas ?? []
  const deClasse = (classe?.pericias_de_classe ?? []).filter((p) => !fixas.includes(p) && modelo.pericias.includes(p))
  const outras = modelo.pericias.filter((p) => !fixas.includes(p) && !deClasse.includes(p))
  const nDeClasse = previa?.deClasse.length ?? 0
  const nLivres = previa?.livres.length ?? 0
  const cheioClasse = classe ? nDeClasse >= classe.quantidade_pericias : true
  const cheioLivres = nLivres >= extrasMax

  const mostrarErros = tentou ? errosLocais() : []

  return (
    <form onSubmit={enviar} className="space-y-5 text-sm" aria-label={`Nova ficha (${modelo.sistema_nome})`} noValidate>
      <p className="text-xs text-suave">
        Sistema <strong className="text-texto">{modelo.sistema_nome}</strong>. Escolha classe, nível, atributos, perícias e equipamento; PV, {nomeDefesa}, ataques e habilidades são calculados pelo servidor
        (a prévia abaixo é uma estimativa do cliente).
      </p>

      <Passo n={1} titulo="Identidade">
        <FichaCamposBasicos modelo={modelo} valor={basicos} aoMudar={(patch) => setBasicos((b) => ({ ...b, ...patch }))} />
      </Passo>

      <Passo n={2} titulo="Classe">
        <div className="grid gap-1.5 sm:grid-cols-2" role="radiogroup" aria-label="Classe">
          {classes.map((c) => {
            const ativa = c.id === classeId
            return (
              <button
                key={c.id}
                type="button"
                role="radio"
                aria-checked={ativa}
                id={`classe-${c.id}`}
                className={`rounded border px-3 py-2 text-left transition-colors ${ativa ? "ring-2 ring-[var(--acento)]" : ""}`}
                style={{ background: ativa ? "color-mix(in srgb, var(--acento) 18%, transparent)" : "#00000033", borderColor: "var(--painel-borda)" }}
                onClick={() => escolherClasse(c)}
              >
                <span className="block font-semibold">{c.nome}</span>
                <span className="block text-[12px] leading-snug text-suave">{c.descricao}</span>
                <span className="mt-1 block text-[11px] text-suave">{resumoClasse(c, tipo)}</span>
              </button>
            )
          })}
        </div>
      </Passo>

      {classe && (
        <>
          <Passo n={3} titulo="Nível">
            <div className="flex items-center gap-3">
              <select id="ficha-nivel" className="campo w-auto" value={nivel} onChange={(e) => setNivel(Number(e.target.value))} aria-label="Nível">
                {Array.from({ length: nivelMax }, (_, i) => i + 1).map((n) => (
                  <option key={n} value={n}>
                    Nível {n}
                  </option>
                ))}
              </select>
              {previa && (
                <span className="text-[11px] text-suave">
                  {tipo === "t20" ? `meio nível ${previa.meioNivel} · treino +${previa.prof}` : `proficiência +${previa.prof}`}
                </span>
              )}
            </div>
          </Passo>

          <Passo
            n={4}
            titulo="Atributos (modificadores)"
            extra={
              <span className={`text-[11px] tabular-nums ${somaEstourou ? "font-semibold" : "text-suave"}`} style={somaEstourou ? { color: "var(--status-vida)" } : undefined} aria-live="polite">
                soma {sinal(somaAtr)} / máx. +{somaMax}
                {somaEstourou ? " — acima do limite" : ""}
              </span>
            }
          >
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
              {modelo.atributos.map((a) => {
                const v = atributos[a] ?? 0
                const principal = classe.atributo_principal === a
                return (
                  <div key={a} className="rounded p-1.5 text-center" style={{ background: "#00000033", outline: principal ? "1px solid var(--acento)" : undefined }}>
                    <label className="block text-[11px] uppercase text-suave" htmlFor={`atr-${a}`} title={principal ? "atributo principal da classe" : undefined}>
                      {a}
                      {principal ? " ★" : ""}
                    </label>
                    <div className="flex items-center gap-0.5">
                      <button type="button" className="botao h-7 w-7 px-0" aria-label={`Diminuir ${a}`} onClick={() => mudarAtributo(a, v - 1)} disabled={v <= L.atributo[0]}>
                        −
                      </button>
                      <input
                        id={`atr-${a}`}
                        className="campo px-0 text-center tabular-nums"
                        type="number"
                        inputMode="numeric"
                        min={L.atributo[0]}
                        max={L.atributo[1]}
                        value={v}
                        onChange={(e) => mudarAtributo(a, Number(e.target.value))}
                      />
                      <button type="button" className="botao h-7 w-7 px-0" aria-label={`Aumentar ${a}`} onClick={() => mudarAtributo(a, v + 1)} disabled={v >= L.atributo[1]}>
                        +
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
            <p className="text-[11px] text-suave">
              De {L.atributo[0]} a +{L.atributo[1]}. O limite da soma sobe +2 a cada 4 níveis. ★ = atributo principal ({classe.atributo_principal ?? "—"}).
            </p>
          </Passo>

          <Passo n={5} titulo="Perícias">
            {fixas.length > 0 && (
              <div className="flex flex-wrap items-center gap-1 text-[12px]">
                <span className="text-suave">Fixas da classe:</span>
                {fixas.map((p) => (
                  <span key={p} className="chip capitalize" title="sempre treinada">
                    🔒 {p}
                  </span>
                ))}
              </div>
            )}
            <div>
              <div className="mb-1 flex items-center justify-between text-[12px]">
                <span>Da lista da classe</span>
                <span className={`tabular-nums ${nDeClasse > classe.quantidade_pericias ? "font-semibold" : "text-suave"}`} style={nDeClasse > classe.quantidade_pericias ? { color: "var(--status-vida)" } : undefined}>
                  {nDeClasse}/{classe.quantidade_pericias}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-1 sm:grid-cols-3">
                {deClasse.map((p) => {
                  const marcada = pericias.includes(p)
                  return (
                    <label key={p} className={`flex items-center gap-1 ${marcada ? "" : "text-suave"}`}>
                      <input id={`per-${p}`} type="checkbox" checked={marcada} disabled={!marcada && cheioClasse} onChange={(e) => alternarPericia(p, e.target.checked)} />
                      <span className="flex-1 truncate capitalize">{p}</span>
                      {previa && <span className="tabular-nums text-[11px] text-suave">{sinal(previa.pericias[p] ?? 0)}</span>}
                    </label>
                  )
                })}
              </div>
            </div>
            <div>
              <div className="mb-1 flex items-center justify-between text-[12px]">
                <span>Outras (antecedente / origem)</span>
                <span className={`tabular-nums ${nLivres > extrasMax ? "font-semibold" : "text-suave"}`} style={nLivres > extrasMax ? { color: "var(--status-vida)" } : undefined}>
                  {nLivres}/{extrasMax}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-1 sm:grid-cols-3">
                {outras.map((p) => {
                  const marcada = pericias.includes(p)
                  return (
                    <label key={p} className={`flex items-center gap-1 ${marcada ? "" : "text-suave"}`}>
                      <input id={`per-${p}`} type="checkbox" checked={marcada} disabled={!marcada && cheioLivres} onChange={(e) => alternarPericia(p, e.target.checked)} />
                      <span className="flex-1 truncate capitalize">{p}</span>
                      {previa && <span className="tabular-nums text-[11px] text-suave">{sinal(previa.pericias[p] ?? 0)}</span>}
                    </label>
                  )
                })}
              </div>
            </div>
          </Passo>

          <Passo
            n={6}
            titulo="Equipamento"
            extra={
              <span className={`text-[11px] tabular-nums ${armas.length > maxArmas ? "font-semibold" : "text-suave"}`}>
                armas {armas.length}/{maxArmas}
              </span>
            }
          >
            <div className="grid grid-cols-1 gap-x-3 gap-y-1 sm:grid-cols-2">
              {(modelo.armas ?? []).map((a) => {
                const marcada = armas.includes(a.id)
                return (
                  <label key={a.id} className={`flex items-center gap-1 ${marcada ? "" : "text-suave"}`}>
                    <input id={`arma-${a.id}`} type="checkbox" checked={marcada} disabled={!marcada && armas.length >= maxArmas} onChange={(e) => alternarArma(a.id, e.target.checked)} />
                    <span className="flex-1 truncate">{a.nome}</span>
                    <span className="text-[11px] tabular-nums text-suave">
                      {a.dano} {a.tipo_dano} · alc. {a.alcance}
                      {a.arremesso ? `/${a.arremesso}` : ""} · {a.atributo === "melhor" ? "FOR/DES" : (a.atributo ?? "FOR")}
                    </span>
                  </label>
                )
              })}
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <div>
                <label className="rotulo" htmlFor="ficha-armadura">Armadura</label>
                <select id="ficha-armadura" className="campo" value={armaduraId} onChange={(e) => setArmaduraId(e.target.value)}>
                  {(modelo.armaduras ?? []).map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.nome} ({nomeDefesa} {a.defesa_base}
                      {a.max_des === null || a.max_des === undefined ? " + DES" : a.max_des === 0 ? ", sem DES" : `, DES até +${a.max_des}`})
                    </option>
                  ))}
                </select>
              </div>
              <label className="flex items-center gap-2 self-end pb-2">
                <input id="ficha-escudo" type="checkbox" checked={escudo} onChange={(e) => setEscudo(e.target.checked)} />
                Escudo (+{modelo.escudo?.bonus ?? 2} {nomeDefesa})
              </label>
            </div>
          </Passo>

          {previa && (
            <Passo n={7} titulo="Prévia (estimativa do cliente)">
              <dl className="grid grid-cols-2 gap-1 sm:grid-cols-4">
                <div className="rounded px-2 py-1" style={{ background: "#00000033" }}>
                  <dt className="text-[10px] uppercase text-suave">PV</dt>
                  <dd className="text-base tabular-nums" style={{ color: "var(--status-vida)" }}>{previa.pv}</dd>
                </div>
                {barraRecurso && (
                  <div className="rounded px-2 py-1" style={{ background: "#00000033" }}>
                    <dt className="truncate text-[10px] uppercase text-suave" title={barraRecurso.nome}>{barraRecurso.nome}</dt>
                    <dd className="text-base tabular-nums" style={{ color: "var(--status-recurso)" }}>{previa.recurso}</dd>
                  </div>
                )}
                <div className="rounded px-2 py-1" style={{ background: "#00000033" }}>
                  <dt className="text-[10px] uppercase text-suave">{nomeDefesa}</dt>
                  <dd className="text-base tabular-nums">{previa.defesa}</dd>
                </div>
                <div className="rounded px-2 py-1" style={{ background: "#00000033" }}>
                  <dt className="text-[10px] uppercase text-suave">CD de habilidades</dt>
                  <dd className="text-base tabular-nums">
                    {previa.cd} <span className="text-[11px] text-suave">(magia {sinal(previa.bonusMagia)})</span>
                  </dd>
                </div>
              </dl>

              <div>
                <h4 className="text-[11px] uppercase text-suave">Ataques</h4>
                {previa.ataques.length === 0 ? (
                  <p className="text-xs text-suave">Nenhuma arma escolhida.</p>
                ) : (
                  <table className="w-full text-left text-xs">
                    <thead className="text-[10px] uppercase text-suave">
                      <tr>
                        <th className="py-0.5 font-normal">Arma</th>
                        <th className="py-0.5 font-normal">Bônus</th>
                        <th className="py-0.5 font-normal">Dano</th>
                        <th className="py-0.5 font-normal">Alcance</th>
                      </tr>
                    </thead>
                    <tbody>
                      {previa.ataques.map((a) => (
                        <tr key={a.id} className="border-t" style={{ borderColor: "var(--painel-borda)" }}>
                          <td className="py-1">{a.nome}</td>
                          <td className="py-1 tabular-nums">{sinal(a.bonus)}</td>
                          <td className="py-1 font-mono">
                            {a.dano} <span className="font-sans text-suave">{a.tipo_dano}</span>
                          </td>
                          <td className="py-1 tabular-nums">{a.alcance} q</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              <div>
                <h4 className="text-[11px] uppercase text-suave">Perícias treinadas</h4>
                {previa.treinadas.length === 0 ? (
                  <p className="text-xs text-suave">Nenhuma perícia treinada ainda.</p>
                ) : (
                  <ul className="flex flex-wrap gap-1">
                    {previa.treinadas.map((p) => (
                      <li key={p} className="chip capitalize">
                        {p} <span className="tabular-nums text-suave">{sinal(previa.pericias[p] ?? 0)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div>
                <h4 className="text-[11px] uppercase text-suave">Habilidades até o nível {nivel}</h4>
                {previa.habilidades.length === 0 ? (
                  <p className="text-xs text-suave">Nenhuma habilidade neste nível.</p>
                ) : (
                  <ul className="space-y-1">
                    {previa.habilidades.map((h) => (
                      <LinhaHabilidade key={h.id} h={h} />
                    ))}
                  </ul>
                )}
              </div>
            </Passo>
          )}
        </>
      )}

      <ErrosFicha locais={mostrarErros} servidor={errosServidor} />

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
