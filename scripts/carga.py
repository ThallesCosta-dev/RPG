"""Teste de carga (§18.1): N clientes simulados numa mesa, um deles lento de propósito, R rodadas.

    python scripts/carga.py --url http://localhost:8000 --clientes 6 --rodadas 3
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

import httpx
import websockets

PERSONAGENS = ["player_thorin", "player_lia", "player_maya", "player_bruno"]


async def cliente(nome: str, url_ws: str, token: str, lento: bool, rodadas: int, stats: dict):
    async with websockets.connect(url_ws + f"?token={token}", max_queue=None) as ws:
        estado = None
        rodada_vista = 0
        t_confirmou = None
        async for bruto in ws:
            if lento:
                await asyncio.sleep(0.25)                      # cliente lento: processa devagar
            msg = json.loads(bruto)
            t = msg["type"]
            if t in ("room_state", "state_sync"):
                estado = msg["state"]
            elif t == "phase" and msg["fase"] == "planejamento" and estado is not None:
                if rodada_vista >= rodadas:
                    break
                rodada_vista += 1
                await asyncio.sleep(0.1)
                t_confirmou = time.time()
                await ws.send(json.dumps({"type": "confirm_turn", "acao": {"slots": {"padrao": {"tipo": "defender"}, "livre": {"tipo": "fala", "texto": f"{nome} na rodada {rodada_vista}"}}}}))
            elif t == "narration_segment" and t_confirmou is not None:
                stats.setdefault("ate_primeiro_segmento", []).append(time.time() - t_confirmou)
                t_confirmou = None
            elif t == "error":
                stats.setdefault("erros", []).append((nome, msg))
        stats.setdefault("rodadas", {})[nome] = rodada_vista


async def main(url: str, n: int, rodadas: int):
    ws_url = url.replace("http", "ws", 1)
    async with httpx.AsyncClient(base_url=url, timeout=30) as http:
        host = (await http.post("/api/salas", json={"nome_host": "Host", "sistema_id": "tormenta20", "campanha_id": "coracao-de-rubi", "personagem_id": PERSONAGENS[0]})).json()
        sala = host["sala_id"]
        tokens = [("host", host["token"], False)]
        for i in range(1, n):
            conv = (await http.post(f"/api/salas/{sala}/convites", headers={"Authorization": f"Bearer {host['token']}"})).json()["convite"]
            pid = PERSONAGENS[i] if i < len(PERSONAGENS) else None
            e = (await http.post(f"/api/salas/{sala}/entrar", json={"convite": conv, "nome": f"c{i}", "personagem_id": pid})).json()
            tokens.append((f"c{i}", e["token"], i == n - 1))   # o último é lento
        stats: dict = {}
        tarefas = [asyncio.create_task(cliente(nome, f"{ws_url}/ws/{sala}", tok, lento, rodadas, stats)) for nome, tok, lento in tokens]
        await asyncio.sleep(1.0)
        async with websockets.connect(f"{ws_url}/ws/{sala}?token={host['token']}") as wh:
            await wh.send(json.dumps({"type": "host_command", "comando": "iniciar"}))
            await asyncio.sleep(0.2)
        t0 = time.time()
        await asyncio.wait_for(asyncio.gather(*tarefas, return_exceptions=True), timeout=120 * rodadas)
        dur = time.time() - t0
        lat = stats.get("ate_primeiro_segmento", [])
        print(f"clientes: {n} (1 lento) | rodadas por cliente: {stats.get('rodadas')} | {dur:.1f}s")
        if lat:
            print(f"do 'pronto' ao primeiro segmento: mediana {statistics.median(lat):.2f}s, máx {max(lat):.2f}s (meta < 5 s)")
        print("erros:", stats.get("erros", []))
        dbg = (await http.get(f"/api/salas/{sala}/debug", headers={"Authorization": f"Bearer {host['token']}"})).json()
        print("IA:", dbg["ia"]["nome"], "| chamadas:", [(c["tipo"], c["provedor"], c["latencia_ms"]) for c in dbg["chamadas"][:6]])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--clientes", type=int, default=6)
    ap.add_argument("--rodadas", type=int, default=3)
    a = ap.parse_args()
    asyncio.run(main(a.url, a.clientes, a.rodadas))
