"""Pipeline de voz: segmentador de frases + produtor/consumidor de TTS + motores (§11).

Motores são opcionais: Kokoro (GPU, pt-BR), Piper (CPU). Sem nenhum, os segmentos seguem só com legenda.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path

log = logging.getLogger("ai_vtt.tts")

TAG = re.compile(r"\[(VOZ|EVENTO):([\w-]+)\]")
TAG_FALA = re.compile(r"<\s*/?\s*fala_jogador\s*>", re.I)     # o LLM às vezes repete a tag; nunca vai para o TTS
FIM_DE_FRASE = re.compile(r"[.!?…]+[\"”»')]*\s+")
ABREVIACOES = {"sr", "sra", "srta", "dr", "dra", "prof", "etc", "ex", "cap", "gen"}
DIR_AUDIO = Path(os.getenv("DIR_DADOS", "data")) / "audio_cache"


class Segmentador:
    """Junta os pedaços do stream e devolve frases completas.
    Exige espaço depois da pontuação: '1.5' e tags cortadas esperam o próximo pedaço."""

    def __init__(self):
        self.buf = ""

    def alimentar(self, texto: str) -> list[str]:
        self.buf += texto
        frases, inicio = [], 0
        for m in FIM_DE_FRASE.finditer(self.buf):
            ultima = self.buf[inicio:m.start()].rsplit(maxsplit=1)[-1:]
            if ultima and ultima[0].lower().strip("\"'([") in ABREVIACOES:
                continue                                  # "Sr. Kargath" não termina a frase
            frases.append(self.buf[inicio:m.end()].strip())
            inicio = m.end()
        self.buf = self.buf[inicio:]
        # quebras de linha também fecham um trecho (o LLM separa vozes por linha)
        if "\n" in self.buf:
            cabeca, _, resto = self.buf.rpartition("\n")
            if cabeca.strip():
                frases.append(cabeca.strip())
            self.buf = resto
        return [f for f in frases if f]

    def finalizar(self) -> list[str]:
        resto, self.buf = self.buf.strip(), ""
        return [resto] if resto else []


class PipelineNarracao:
    def __init__(self, gpu, vozes: dict | None = None):
        self.gpu = gpu          # GPUScheduler
        self.vozes = vozes or {"NARRADOR": {}}   # id da voz → config (voices.json + npcs.json já resolvidos)

    async def narrar(self, stream: AsyncIterator[str], vozes: dict | None = None) -> AsyncIterator[dict]:
        """Produtor (LLM → frases → jobs de TTS) e consumidor (ordem de seq) em paralelo:
        a frase N é sintetizada enquanto o LLM ainda escreve a frase N+1."""
        vozes = vozes or self.vozes
        fila: asyncio.Queue = asyncio.Queue()

        async def produtor():
            seg, voz = Segmentador(), "NARRADOR"
            try:
                async for pedaco in stream:
                    for frase in seg.alimentar(pedaco):
                        voz = self._enfileirar(frase, voz, fila, vozes)
                for frase in seg.finalizar():
                    voz = self._enfileirar(frase, voz, fila, vozes)
            except Exception:
                log.exception("stream de narração interrompido")
            finally:
                fila.put_nowait(None)

        tarefa = asyncio.create_task(produtor())
        seq = 0
        try:
            while (item := await fila.get()) is not None:
                texto, voz, eventos, futuro = item
                try:
                    audio_id = await futuro if futuro else None
                except Exception:
                    log.warning("TTS falhou; segmento segue só com legenda", exc_info=True)
                    audio_id = None
                yield {"seq": seq, "voz": voz, "texto": texto, "eventos": eventos,
                       "audio_url": f"/audio/{audio_id}" if audio_id else None}
                seq += 1
        finally:
            tarefa.cancel()

    def _enfileirar(self, frase: str, voz: str, fila: asyncio.Queue, vozes: dict) -> str:
        """[VOZ:x] fecha o trecho atual e troca a voz; [EVENTO:id] marca o trecho
        para disparar animações quando ele começar a tocar. Tags nunca vão para o TTS."""
        partes = TAG.split(frase)        # [texto, tipo, valor, texto, tipo, valor, texto, ...]
        texto, eventos = partes[0], []
        for i in range(1, len(partes), 3):
            tipo, valor, seguinte = partes[i], partes[i + 1], partes[i + 2]
            if tipo == "EVENTO":
                eventos.append(valor)
                texto += seguinte
            else:
                self._submeter(texto, voz, eventos, fila, vozes)
                texto, eventos = seguinte, []
                voz = valor if valor in vozes else "NARRADOR"
        self._submeter(texto, voz, eventos, fila, vozes)
        return voz

    def _submeter(self, texto: str, voz: str, eventos: list, fila: asyncio.Queue, vozes: dict):
        texto = " ".join(TAG_FALA.sub("", texto).split())
        if not texto and not eventos:
            return
        futuro = None
        if texto and self.gpu is not None and self.gpu.tem_handler("tts"):
            futuro = self.gpu.submeter(0, ("tts", texto, vozes.get(voz) or vozes.get("NARRADOR") or {}))
        fila.put_nowait((texto, voz, eventos, futuro))


# ====================================================================== motores
def resolver_vozes(voices: dict, estado: dict) -> dict:
    """Mapa {tag → config do ator}: NARRADOR + cada NPC vivo da cena pelo seu id."""
    out = {"NARRADOR": voices.get("NARRADOR", {})}
    for pid, p in estado.get("personagens", {}).items():
        if p.get("tipo") == "npc" and p.get("voz") in voices:
            out[p.get("id", pid)] = voices[p["voz"]]
    return out


def _gravar(audio, taxa: int) -> str:
    import numpy as np
    import soundfile as sf
    DIR_AUDIO.mkdir(parents=True, exist_ok=True)
    audio_id = uuid.uuid4().hex
    dados = np.asarray(audio, dtype="float32")
    try:
        sf.write(str(DIR_AUDIO / f"{audio_id}.ogg"), dados, taxa, format="OGG", subtype="OPUS")
    except Exception:                                   # libsndfile sem Opus: cai para Vorbis
        sf.write(str(DIR_AUDIO / f"{audio_id}.ogg"), dados, taxa, format="OGG", subtype="VORBIS")
    return audio_id


def _pitch_shift(audio, taxa: int, semitons: float):
    """Deslocamento de tom simples por reamostragem (muda levemente a duração; bom o bastante para 'atores')."""
    if not semitons:
        return audio
    import numpy as np
    fator = 2 ** (semitons / 12)
    n = int(len(audio) / fator)
    idx = np.linspace(0, len(audio) - 1, n)
    return np.interp(idx, np.arange(len(audio)), audio).astype("float32")


def criar_handler_kokoro() -> Callable | None:
    try:
        from kokoro import KPipeline  # type: ignore
        import numpy as np
    except Exception:
        return None
    try:
        pipeline = KPipeline(lang_code="p")        # "p" = português do Brasil (requer espeak-ng instalado)
    except Exception as exc:
        log.warning("Kokoro indisponível: %s", exc)
        return None

    def sintetizar(texto: str, cfg: dict) -> str:
        partes = [np.asarray(a) for _, _, a in pipeline(texto, voice=cfg.get("voz", "pm_alex"), speed=float(cfg.get("velocidade", 1.0)))]
        audio = np.concatenate(partes) if partes else np.zeros(2400, dtype="float32")
        return _gravar(_pitch_shift(audio, 24000, cfg.get("pitch_semitons", 0)), 24000)
    log.info("TTS: Kokoro carregado")
    return sintetizar


def criar_handler_piper() -> Callable | None:
    try:
        from piper import PiperVoice  # type: ignore
        import numpy as np
    except Exception:
        return None
    vozes: dict[str, object] = {}
    dir_modelos = Path(os.getenv("PIPER_MODELOS", "modelos/piper"))

    def carregar(nome: str):
        if nome not in vozes:
            vozes[nome] = PiperVoice.load(str(dir_modelos / f"{nome}.onnx"))
        return vozes[nome]

    def sintetizar(texto: str, cfg: dict) -> str:
        voz = carregar(cfg.get("voz_piper") or os.getenv("PIPER_VOZ", "pt_BR-faber-medium"))
        pedacos = []
        for chunk in voz.synthesize(texto):
            pedacos.append(np.frombuffer(chunk.audio_int16_bytes, dtype="int16").astype("float32") / 32768)
        audio = np.concatenate(pedacos) if pedacos else np.zeros(2400, dtype="float32")
        return _gravar(_pitch_shift(audio, voz.config.sample_rate, cfg.get("pitch_semitons", 0)), voz.config.sample_rate)
    log.info("TTS: Piper carregado")
    return sintetizar


def escolher_handler_tts() -> Callable | None:
    modo = os.getenv("TTS_MOTOR", "auto").lower()
    if modo == "nenhum":
        return None
    if modo in ("auto", "kokoro"):
        h = criar_handler_kokoro()
        if h or modo == "kokoro":
            return h
    if modo in ("auto", "piper"):
        return criar_handler_piper()
    return None


def caminho_audio(audio_id: str) -> Path | None:
    """Só aceita 32 hexadecimais: impede acessar outros arquivos do disco."""
    if not re.fullmatch(r"[0-9a-f]{32}", audio_id or ""):
        return None
    p = DIR_AUDIO / f"{audio_id}.ogg"
    return p if p.exists() else None


def limpar_audio_antigo(max_idade_h: float = 24) -> int:
    import time
    limite = time.time() - max_idade_h * 3600
    n = 0
    if DIR_AUDIO.exists():
        for f in DIR_AUDIO.glob("*.ogg"):
            if f.stat().st_mtime < limite:
                f.unlink(missing_ok=True)
                n += 1
    return n
