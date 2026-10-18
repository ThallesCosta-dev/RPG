import type { MsgNarrationSegment } from "../types"

/**
 * Segmento da fila. `chat` marca falas de NPC vindas do chat (§6): tocam na mesma fila, com a voz do NPC,
 * sempre depois dos segmentos de narração pendentes, sem aplicar eventos nem entrar na Crônica.
 */
export type Segmento = Omit<MsgNarrationSegment, "type"> & { chat?: { mensagem_id: string } }

const ordem = (a: Segmento, b: Segmento) => Number(!!a.chat) - Number(!!b.chat) || a.seq - b.seq

export interface CallbacksNarracao {
  /** Chamado quando o segmento começa a tocar (ou é pulado, com `instantaneo = true`). */
  aoIniciar(seg: Segmento, instantaneo: boolean): void
  /** Chamado quando a fila esvazia e o servidor já mandou `narration_end`. */
  aoFimDaFila(): void
  aoTerminarSegmento?(seg: Segmento): void
}

/** Fila de narração (§11.4): ordenada por seq, um segmento por vez, legenda + eventos no início de cada um. */
export class FilaNarracao {
  private fila: Segmento[] = []
  private atual: Segmento | null = null
  private audio: HTMLAudioElement | null = null
  private timer: ReturnType<typeof setTimeout> | null = null
  private encerrada = false
  private chatSeq = 0
  volume = 0.8
  mudo = false

  constructor(private cb: CallbacksNarracao) {}

  get tocando(): boolean {
    return this.atual !== null
  }

  get pendentes(): number {
    return this.fila.length + (this.atual ? 1 : 0)
  }

  /** Nova rodada de narração: a partir de agora `aoFimDaFila` só dispara depois de `encerrar()`. */
  iniciarRodada(): void {
    this.encerrada = false
  }

  enfileirar(seg: Segmento): void {
    this.fila.push(seg)
    this.fila.sort(ordem)
    if (!this.atual) this.proximo()
  }

  /** Fala de NPC do chat: entra no fim da fila (depois da narração que estiver tocando) e toca com a voz dele. */
  enfileirarChat(mensagem_id: string, voz: string, texto: string, audio_url: string): void {
    this.chatSeq += 1
    this.enfileirar({ seq: this.chatSeq, voz, texto, eventos: [], audio_url, chat: { mensagem_id } })
  }

  /** `narration_end` chegou: quando a fila esvaziar, avisa. */
  encerrar(): void {
    this.encerrada = true
    if (!this.atual && this.fila.length === 0) this.cb.aoFimDaFila()
  }

  /** Pular narração: esvazia a fila e aplica imediatamente os eventos pendentes. */
  pular(): void {
    this.pararAudio()
    const restantes = this.fila.splice(0)
    this.atual = null
    for (const seg of restantes) this.cb.aoIniciar(seg, true)
    this.encerrada = true
    this.cb.aoFimDaFila()
  }

  /** Reset total (reconexão). */
  limpar(): void {
    this.pararAudio()
    this.fila = []
    this.atual = null
    this.encerrada = false
  }

  ajustarVolume(volume: number, mudo: boolean): void {
    this.volume = volume
    this.mudo = mudo
    if (this.audio) this.audio.volume = mudo ? 0 : volume
  }

  private pararAudio(): void {
    if (this.timer) clearTimeout(this.timer)
    this.timer = null
    if (this.audio) {
      this.audio.onended = null
      this.audio.onerror = null
      this.audio.pause()
      this.audio = null
    }
  }

  private proximo(): void {
    const seg = this.fila.shift()
    if (!seg) {
      this.atual = null
      if (this.encerrada) this.cb.aoFimDaFila()
      return
    }
    this.atual = seg
    this.cb.aoIniciar(seg, false)
    const duracaoTexto = Math.max(1500, 60 * seg.texto.length)
    const terminou = () => {
      if (this.atual !== seg) return
      this.pararAudio()
      this.cb.aoTerminarSegmento?.(seg)
      this.proximo()
    }
    if (seg.audio_url) {
      const audio = new Audio(seg.audio_url)
      audio.volume = this.mudo ? 0 : this.volume
      audio.onended = terminou
      audio.onerror = terminou
      this.audio = audio
      audio.play().catch(() => {
        // Autoplay bloqueado ou arquivo inválido: cai na duração pelo texto.
        this.audio = null
        this.timer = setTimeout(terminou, duracaoTexto)
      })
    } else {
      this.timer = setTimeout(terminou, duracaoTexto)
    }
  }
}
