import type { Personagem, SystemConfig } from "../types"
import TokenAvatar from "./TokenAvatar"

const sinal = (n: number) => (n >= 0 ? `+${n}` : String(n))

/** Ficha completa de um personagem (painel "Minha ficha"). */
export default function FichaPanel({ p, config }: { p: Personagem; config: SystemConfig }) {
  const pericias = Object.entries(p.pericias).sort(([a], [b]) => a.localeCompare(b))
  const atributos = Object.entries(p.atributos ?? {})
  return (
    <div className="space-y-4 text-sm">
      <header className="flex items-center gap-3">
        <TokenAvatar p={p} tamanho={48} />
        <div className="min-w-0">
          <h3 className="truncate text-lg leading-tight">{p.nome}</h3>
          <p className="text-xs text-suave">
            {p.classe ? `${p.classe} · ` : ""}
            {p.tipo === "npc" ? "NPC" : "personagem de jogador"} · {p.faccao} · posição ({p.x}, {p.y})
            {p.caido ? " · caído" : ""}
          </p>
        </div>
      </header>

      {atributos.length > 0 && (
        <section>
          <h4 className="rotulo">Atributos</h4>
          <dl className="grid grid-cols-3 gap-1 sm:grid-cols-6">
            {atributos.map(([k, v]) => (
              <div key={k} className="rounded px-2 py-1 text-center" style={{ background: "#00000033" }}>
                <dt className="text-[10px] uppercase text-suave">{k}</dt>
                <dd className="text-base tabular-nums">{sinal(v)}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      <section>
        <h4 className="rotulo">Recursos</h4>
        <dl className="grid grid-cols-2 gap-1 sm:grid-cols-4">
          {config.barras_status.map((b) => {
            const v = p.barras[b.id]
            if (!v) return null
            const cor = b.cor_token.startsWith("--") ? `var(${b.cor_token})` : b.cor_token
            return (
              <div key={b.id} className="rounded px-2 py-1" style={{ background: "#00000033" }}>
                <dt className="text-[10px] uppercase text-suave">{b.nome}</dt>
                <dd className="tabular-nums" style={{ color: cor }}>
                  {v.atual}/{v.max}
                </dd>
              </div>
            )
          })}
          <div className="rounded px-2 py-1" style={{ background: "#00000033" }}>
            <dt className="text-[10px] uppercase text-suave">{config.campo_defesa}</dt>
            <dd className="tabular-nums">{p.defesa}</dd>
          </div>
          <div className="rounded px-2 py-1" style={{ background: "#00000033" }}>
            <dt className="text-[10px] uppercase text-suave">Deslocamento</dt>
            <dd className="tabular-nums">{p.deslocamento} q</dd>
          </div>
          <div className="rounded px-2 py-1" style={{ background: "#00000033" }}>
            <dt className="text-[10px] uppercase text-suave">Iniciativa</dt>
            <dd className="tabular-nums">{sinal(p.iniciativa_bonus)}</dd>
          </div>
        </dl>
      </section>

      <section>
        <h4 className="rotulo">Ataques</h4>
        {p.ataques.length === 0 ? (
          <p className="text-xs text-suave">Nenhum ataque.</p>
        ) : (
          <table className="w-full text-left text-xs">
            <thead className="text-[10px] uppercase text-suave">
              <tr>
                <th className="py-0.5 font-normal">Nome</th>
                <th className="py-0.5 font-normal">Bônus</th>
                <th className="py-0.5 font-normal">Dano</th>
                <th className="py-0.5 font-normal">Tipo</th>
                <th className="py-0.5 font-normal">Alcance</th>
              </tr>
            </thead>
            <tbody>
              {p.ataques.map((a) => (
                <tr key={a.id} className="border-t" style={{ borderColor: "var(--painel-borda)" }}>
                  <td className="py-1">{a.nome}</td>
                  <td className="py-1 tabular-nums">{sinal(a.bonus)}</td>
                  <td className="py-1 font-mono">
                    {a.dano}
                    {a.margem_critico || a.mult_critico ? (
                      <span className="text-suave">
                        {" "}
                        ({a.margem_critico ?? 20}/x{a.mult_critico ?? 2})
                      </span>
                    ) : null}
                  </td>
                  <td className="py-1">{a.tipo_dano}</td>
                  <td className="py-1 tabular-nums">{a.alcance} q</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h4 className="rotulo">Perícias</h4>
        {pericias.length === 0 ? (
          <p className="text-xs text-suave">Nenhuma perícia treinada.</p>
        ) : (
          <ul className="flex flex-wrap gap-1">
            {pericias.map(([k, v]) => (
              <li key={k} className="chip capitalize">
                {k} <span className="tabular-nums text-suave">{sinal(v)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h4 className="rotulo">Condições</h4>
        {p.condicoes.length === 0 && !p.caido ? (
          <p className="text-xs text-suave">Nenhuma condição ativa.</p>
        ) : (
          <ul className="flex flex-wrap gap-1">
            {p.caido && (
              <li className="chip" style={{ borderColor: "var(--status-vida)" }}>
                ✕ caído
              </li>
            )}
            {p.condicoes.map((c) => (
              <li key={c.id} className="chip">
                ✦ {c.id}
                <span className="text-suave">{c.rodadas_restantes === null ? " (permanente)" : ` (${c.rodadas_restantes} rodadas)`}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {p.historia && (
        <section>
          <h4 className="rotulo">História</h4>
          <p className="whitespace-pre-wrap text-[13px] leading-snug">{p.historia}</p>
        </section>
      )}
    </div>
  )
}
