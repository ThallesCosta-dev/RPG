import asyncio

import pytest

from server.gpu_scheduler import GPUScheduler
from server.tts_engine import PipelineNarracao, Segmentador, caminho_audio, resolver_vozes


def test_segmentador_frases_e_abreviacoes():
    seg = Segmentador()
    assert seg.alimentar("Olá, Sr. Kargath. Como vai? Bem") == ["Olá, Sr. Kargath.", "Como vai?"]
    assert seg.finalizar() == ["Bem"]


def test_segmentador_decimais_e_tags_cortadas():
    seg = Segmentador()
    assert seg.alimentar("Custa 1.5 moedas. [EVEN") == ["Custa 1.5 moedas."]
    assert seg.alimentar("TO:e1] O orc ataca. ") == ["[EVENTO:e1] O orc ataca."]
    assert seg.finalizar() == []


def test_segmentador_quebra_de_linha():
    seg = Segmentador()
    frases = seg.alimentar("[VOZ:NARRADOR] Texto sem ponto final\n[VOZ:boss_orc] \"Oi")
    assert frases == ["[VOZ:NARRADOR] Texto sem ponto final"]
    assert seg.finalizar() == ["[VOZ:boss_orc] \"Oi"]


async def _stream(pedacos):
    for p in pedacos:
        yield p
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_pipeline_sem_tts_gera_segmentos_com_eventos_e_vozes():
    gpu = GPUScheduler({})
    pipe = PipelineNarracao(gpu)
    vozes = {"NARRADOR": {}, "boss_orc": {"voz": "x"}}
    texto = ("[VOZ:NARRADOR] [EVENTO:e1] Thorin avança e acerta o orc. [EVENTO:e2] Lia derruba o lustre. \n"
             "[VOZ:boss_orc] \"É só isso?\"\n[VOZ:desconhecida] [EVENTO:e3] O goblin erra. O que fazem?")
    segs = [s async for s in pipe.narrar(_stream([texto[i:i + 17] for i in range(0, len(texto), 17)]), vozes)]
    assert [s["seq"] for s in segs] == list(range(len(segs)))
    assert segs[0]["voz"] == "NARRADOR" and segs[0]["eventos"] == ["e1"] and "[" not in segs[0]["texto"]
    assert any(s["eventos"] == ["e2"] for s in segs)
    orc = next(s for s in segs if "só isso" in s["texto"])
    assert orc["voz"] == "boss_orc"
    gob = next(s for s in segs if "goblin" in s["texto"])
    assert gob["voz"] == "NARRADOR" and gob["eventos"] == ["e3"]      # voz desconhecida cai no narrador
    assert all(s["audio_url"] is None for s in segs)


@pytest.mark.asyncio
async def test_pipeline_com_tts_falhando_segue_com_legenda():
    def tts(texto, cfg):
        if "falha" in texto:
            raise RuntimeError("GPU explodiu")
        return "a" * 32
    gpu = GPUScheduler({"tts": tts})
    gpu.iniciar()
    try:
        pipe = PipelineNarracao(gpu)
        segs = [s async for s in pipe.narrar(_stream(["[EVENTO:e1] Primeira frase. [EVENTO:e2] Esta falha. [EVENTO:e3] Terceira frase."]), {"NARRADOR": {}})]
        assert segs[0]["audio_url"] == "/audio/" + "a" * 32
        assert segs[1]["audio_url"] is None
        assert segs[2]["audio_url"].startswith("/audio/")
    finally:
        gpu.parar()


@pytest.mark.asyncio
async def test_gpu_scheduler_faixa_pesada_espera_narracao():
    ordem = []
    gpu = GPUScheduler({"tts": lambda t, c: ordem.append("tts") or "x" * 32, "mapa": lambda *a: ordem.append("mapa") or "/m.png"})
    gpu.iniciar()
    try:
        gpu.narracao_iniciada()
        f_mapa = gpu.submeter(2, ("mapa", [], "", "", 0))
        f_tts = gpu.submeter(0, ("tts", "oi", {}))
        await f_tts
        await asyncio.sleep(0.05)
        assert not f_mapa.done()
        gpu.narracao_terminada()
        assert await f_mapa == "/m.png"
        assert ordem == ["tts", "mapa"]
    finally:
        gpu.parar()


def test_caminho_audio_so_aceita_hex():
    assert caminho_audio("../../etc/passwd") is None
    assert caminho_audio("zz" * 16) is None


def test_resolver_vozes():
    voices = {"NARRADOR": {"voz": "n"}, "grave": {"voz": "g"}}
    estado = {"personagens": {"orc": {"tipo": "npc", "voz": "grave"}, "x": {"tipo": "npc", "voz": "inexistente"}, "p": {"tipo": "jogador"}}}
    assert resolver_vozes(voices, estado) == {"NARRADOR": {"voz": "n"}, "orc": {"voz": "g"}}


@pytest.mark.asyncio
async def test_pipeline_junta_frases_curtas_da_mesma_voz():
    pipe = PipelineNarracao(GPUScheduler({}))
    vozes = {"NARRADOR": {}, "bram": {}}
    texto = "[VOZ:NARRADOR] [EVENTO:e1] Thorin pergunta. [VOZ:bram] \"Saudações, Thorin. As coisas andam tensas. Meu sobrinho sumiu.\" [VOZ:NARRADOR] Bram aperta a caneca. O vento uiva."
    segs = [s async for s in pipe.narrar(_stream([texto]), vozes)]
    assert [s["voz"] for s in segs] == ["NARRADOR", "bram", "NARRADOR"]          # 3 segmentos, não 6
    assert segs[1]["texto"].count(".") == 3 and segs[2]["texto"] == "Bram aperta a caneca. O vento uiva."


@pytest.mark.asyncio
async def test_marcador_antes_da_troca_de_voz_vai_para_o_proximo_segmento():
    pipe = PipelineNarracao(GPUScheduler({}))
    vozes = {"NARRADOR": {}, "bram": {}}
    texto = "[VOZ:NARRADOR] [EVENTO:e1] O anão pergunta. [EVENTO:e2] [VOZ:bram] \"Não sei de nada.\" [VOZ:NARRADOR] Ele desvia o olhar. [EVENTO:e3]"
    segs = [s async for s in pipe.narrar(_stream([texto]), vozes)]
    assert all(s["texto"] or s["eventos"] for s in segs)
    assert [(s["voz"], s["eventos"]) for s in segs] == [("NARRADOR", ["e1"]), ("bram", ["e2"]), ("NARRADOR", ["e3"])]   # e3 órfão junta-se ao último


@pytest.mark.asyncio
async def test_narracao_sem_aspas_na_tag_do_npc_volta_para_o_narrador():
    pipe = PipelineNarracao(GPUScheduler({}))
    vozes = {"NARRADOR": {}, "bram": {}}
    texto = '[VOZ:bram] "Eles foram para o norte." [VOZ:bram] O taverneiro junta as mãos em súplica.'
    segs = [s async for s in pipe.narrar(_stream([texto]), vozes)]
    assert [s["voz"] for s in segs] == ["bram", "NARRADOR"]
