"""Teste de ponta a ponta contra um servidor rodando (sem navegador): cria sala, entra com convite, joga 2 rodadas.

    python scripts/cliente_teste.py [--url http://localhost:8000]
"""
from __future__ import annotations

import argparse
import asyncio
import json

import httpx
import websockets


async def ouvir(ws, nome, caixa, parar):
    try:
        async for bruto in ws:
            msg = json.loads(bruto)
            caixa.append(msg)
            t = msg["type"]
            if t == "narration_segment":
                print(f"  [{nome}] 🔊 {msg['voz']}: {msg['texto']}  eventos={msg['eventos']} audio={'sim' if msg['audio_url'] else 'não'}")
            elif t in ("phase", "ready_status", "dice_result", "error", "nivel_ia", "round_log", "narration_end"):
                resumo = {k: v for k, v in msg.items() if k not in ("type", "acoes")}
                if t == "round_log":
                    resumo["acoes"] = [a["texto"] for a in msg["acoes"]]
                print(f"  [{nome}] {t}: {json.dumps(resumo, ensure_ascii=False)[:300]}")
            if parar.is_set():
                break
    except websockets.ConnectionClosed:
        pass


async def main(url: str):
    ws_url = url.replace("http", "ws", 1)
    async with httpx.AsyncClient(base_url=url, timeout=30) as http:
        cart = (await http.get("/api/cartuchos")).json()
        print("cartuchos:", cart)
        r = await http.post("/api/salas", json={"nome_host": "Thalles", "sistema_id": "tormenta20", "campanha_id": "coracao-de-rubi", "personagem_id": "player_thorin"})
        r.raise_for_status()
        host = r.json()
        sala = host["sala_id"]
        print("sala criada:", sala, "convite:", host["convite"])
        lobby = (await http.get(f"/api/salas/{sala}/lobby", params={"convite": host["convite"]})).json()
        print("lobby:", [p["id"] for p in lobby["personagens_disponiveis"]], "convite válido:", lobby["convite_valido"])
        r = await http.post(f"/api/salas/{sala}/entrar", json={"convite": host["convite"], "nome": "Ana", "personagem_id": "player_lia"})
        r.raise_for_status()
        jog = r.json()
        r = await http.post(f"/api/salas/{sala}/entrar", json={"convite": host["convite"], "nome": "Intruso", "personagem_id": "player_maya"})
        print("reuso do convite →", r.status_code)
        r = await http.post(f"/api/salas/{sala}/convites", headers={"Authorization": f"Bearer {host['token']}"})
        convite2 = r.json()["convite"]
        r = await http.post(f"/api/salas/{sala}/entrar", json={"convite": convite2, "nome": "Espectador"})
        esp = r.json()
        print("espectador:", esp["papel"])

        parar = asyncio.Event()
        async with websockets.connect(f"{ws_url}/ws/{sala}?token={host['token']}") as w1, \
                   websockets.connect(f"{ws_url}/ws/{sala}?token={jog['token']}") as w2, \
                   websockets.connect(f"{ws_url}/ws/{sala}?token={esp['token']}") as w3:
            c1, c2, c3 = [], [], []
            tarefas = [asyncio.create_task(ouvir(w1, "host", c1, parar)), asyncio.create_task(ouvir(w2, "ana", c2, parar)),
                       asyncio.create_task(ouvir(w3, "esp", c3, parar))]
            await asyncio.sleep(0.5)
            print("room_state host:", c1[0]["eu"], "fase", c1[0]["fase"], "cena", c1[0]["state"]["cena"]["nome"])
            await w1.send(json.dumps({"type": "host_command", "comando": "iniciar"}))
            await asyncio.sleep(0.5)
            est = [m for m in c1 if m["type"] == "state_sync"][-1]["state"]
            thorin, lia = est["personagens"]["player_thorin"], est["personagens"]["player_lia"]
            print("posições: Thorin", (thorin["x"], thorin["y"]), "Lia", (lia["x"], lia["y"]), "NPCs:", [p["id"] for p in est["personagens"].values() if p["tipo"] == "npc"])
            alc = [m for m in c1 if m["type"] == "alcance"][-1]["celulas"]
            destino = max(alc, key=lambda c: -c[1])[:2]        # sobe o máximo que der
            await w1.send(json.dumps({"type": "preview_move", "destino": destino}))
            await w1.send(json.dumps({"type": "roll", "slot_id": "padrao", "expressao": "1d20+8"}))
            await w2.send(json.dumps({"type": "roll", "slot_id": "livre_dado", "expressao": "1d100"}))
            await asyncio.sleep(0.3)
            await w1.send(json.dumps({"type": "confirm_turn", "acao": {"movimento": {"destino": destino}, "slots": {"livre": {"tipo": "fala", "texto": "Bram, onde está o rubi?"}}}}))
            await w2.send(json.dumps({"type": "confirm_turn", "acao": {"slots": {"padrao": {"tipo": "criativa", "texto": "Observo a taverna procurando alguém suspeito"}}}}))
            # espera a rodada 1 terminar
            for _ in range(200):
                await asyncio.sleep(0.1)
                if any(m["type"] == "narration_end" for m in c2):
                    break
            await asyncio.sleep(0.3)
            print("fases vistas por Ana:", [m["fase"] for m in c2 if m["type"] == "phase"])
            est = [m for m in c2 if m["type"] == "state_sync"][-1]["state"]
            print("rodada:", est["rodada"], "crônica:", [l["texto"] for l in est["cronica"]])
            # rodada 2: host força
            await w1.send(json.dumps({"type": "host_command", "comando": "resolver_agora"}))
            for _ in range(200):
                await asyncio.sleep(0.1)
                if sum(m["type"] == "narration_end" for m in c2) >= 2:
                    break
            dbg = (await http.get(f"/api/salas/{sala}/debug", headers={"Authorization": f"Bearer {host['token']}"})).json()
            print("debug: fase", dbg["fase"], "ia", dbg["ia"]["nome"], "chamadas", [(c["tipo"], c["provedor"], c["latencia_ms"]) for c in dbg["chamadas"][:4]])
            print("espectador recebeu", len(c3), "mensagens; erros:", [m for m in c1 + c2 + c3 if m["type"] == "error"])
            parar.set()
            for t in tarefas:
                t.cancel()
    print("OK")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    asyncio.run(main(ap.parse_args().url))
