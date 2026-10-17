// Chaves de localStorage usadas pelo cliente.

const ler = (k: string): string | null => {
  try {
    return localStorage.getItem(k)
  } catch {
    return null
  }
}
const gravar = (k: string, v: string | null) => {
  try {
    if (v === null) localStorage.removeItem(k)
    else localStorage.setItem(k, v)
  } catch {
    /* sem storage disponível */
  }
}

export const storage = {
  token: (salaId: string) => ler(`aivtt_token_${salaId}`),
  setToken: (salaId: string, token: string | null) => gravar(`aivtt_token_${salaId}`, token),
  convite: (salaId: string) => ler(`aivtt_convite_${salaId}`),
  setConvite: (salaId: string, c: string) => gravar(`aivtt_convite_${salaId}`, c),
  campanhaInfo: (salaId: string): { nome: string; tema: string } | null => {
    const v = ler(`aivtt_campanha_${salaId}`)
    if (!v) return null
    try {
      return JSON.parse(v) as { nome: string; tema: string }
    } catch {
      return null
    }
  },
  setCampanha: (salaId: string, nome: string, tema: string) =>
    gravar(`aivtt_campanha_${salaId}`, JSON.stringify({ nome, tema })),
  tema: () => ler("aivtt_tema"),
  setTema: (t: string | null) => gravar("aivtt_tema", t),
  volume: (): number => {
    const bruto = ler("aivtt_volume")
    const v = Number(bruto)
    return bruto !== null && Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : 0.8
  },
  setVolume: (v: number) => gravar("aivtt_volume", String(v)),
  mudo: () => ler("aivtt_mudo") === "1",
  setMudo: (m: boolean) => gravar("aivtt_mudo", m ? "1" : "0"),
  nomeJogador: () => ler("aivtt_nome") ?? "",
  setNomeJogador: (n: string) => gravar("aivtt_nome", n),
}
