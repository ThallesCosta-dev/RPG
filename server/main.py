"""Gateway FastAPI: HTTP + WebSocket + arquivos estáticos da SPA (§17.1). Origem única na porta 8000."""
from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import validar_token
from .bootstrap import RAIZ, App

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ai_vtt.main")

LIMITE_MSG = 16_384                                 # bytes por mensagem
appctx = App()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await appctx.iniciar()
    try:
        yield
    finally:
        await appctx.parar()


app = FastAPI(title="AI-VTT", version="4.0", lifespan=lifespan)


# ====================================================================== HTTP
class NovaSala(BaseModel):
    nome_host: str = Field(min_length=1, max_length=40)
    sistema_id: str
    campanha_id: str
    personagem_id: str | None = None


class Entrada(BaseModel):
    convite: str
    nome: str = Field(min_length=1, max_length=40)
    personagem_id: str | None = None


def _ident_http(sala_id: str, authorization: str | None = Header(default=None)):
    token = (authorization or "").removeprefix("Bearer ").strip()
    ident = validar_token(token, sala_id)
    if ident is None:
        raise HTTPException(401, "token inválido")
    return ident


@app.get("/api/cartuchos")
async def cartuchos():
    return {"sistemas": appctx.biblioteca.listar_sistemas(), "campanhas": appctx.biblioteca.listar_campanhas()}


@app.post("/api/salas")
async def criar_sala(corpo: NovaSala):
    try:
        return appctx.criar_sala(corpo.nome_host, corpo.sistema_id, corpo.campanha_id, corpo.personagem_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/salas/{sala_id}/lobby")
async def lobby(sala_id: str, convite: str | None = Query(default=None)):
    try:
        dados = appctx.lobby(sala_id)
    except KeyError:
        raise HTTPException(404, "sala inexistente")
    dados["convite_valido"] = bool(convite) and appctx.store.convite_valido(sala_id, convite)
    return dados


@app.post("/api/salas/{sala_id}/entrar")
async def entrar(sala_id: str, corpo: Entrada):
    try:
        return appctx.entrar(sala_id, corpo.convite, corpo.nome, corpo.personagem_id)
    except KeyError:
        raise HTTPException(404, "sala inexistente")
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/salas/{sala_id}/convites")
async def convites(sala_id: str, ident=Depends(_ident_http)):
    if ident.papel != "host":
        raise HTTPException(403, "só o host cria convites")
    return {"convite": appctx.novo_convite(sala_id)}


@app.get("/api/salas/{sala_id}/debug")
async def debug(sala_id: str, ident=Depends(_ident_http)):
    if ident.papel != "host":
        raise HTTPException(403)
    try:
        sala = appctx.obter_sala(sala_id)
    except KeyError:
        raise HTTPException(404)
    return JSONResponse(sala.debug())


@app.get("/api/salas/{sala_id}/cenas")
async def cenas(sala_id: str, ident=Depends(_ident_http)):
    sala = appctx.obter_sala(sala_id)
    return [{"id": c["id"], "nome": c["nome"], "tipo_mapa": c.get("tipo_mapa")} for c in sala.campanha.cenas.values()]


@app.get("/audio/{audio_id}")
async def audio(audio_id: str):
    caminho = appctx.caminho_audio(audio_id)        # só aceita 32 hexadecimais
    if caminho is None:
        raise HTTPException(404)
    return FileResponse(caminho, media_type="audio/ogg", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/mapas/{arquivo}")
async def mapas(arquivo: str):
    if not arquivo.endswith(".png") or "/" in arquivo or ".." in arquivo:
        raise HTTPException(404)
    caminho = RAIZ / os.getenv("DIR_DADOS", "data") / "mapas_cache" / arquivo
    if not caminho.exists():
        raise HTTPException(404)
    return FileResponse(caminho, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/cartuchos/campanhas/{campanha_id}/mapas/{arquivo}")
async def mapas_prontos(campanha_id: str, arquivo: str):
    base = (RAIZ / os.getenv("DIR_CARTUCHOS", "cartuchos") / "campanhas").resolve()
    caminho = (base / campanha_id / "mapas" / arquivo).resolve()
    if base not in caminho.parents or not caminho.exists():
        raise HTTPException(404)
    return FileResponse(caminho)


# ====================================================================== WebSocket
@app.websocket("/ws/{sala_id}")
async def ws_mesa(websocket: WebSocket, sala_id: str, token: str = Query(default="")):
    ident = validar_token(token, sala_id)          # player_id e papel vêm do token assinado
    if ident is None:
        await websocket.close(code=4401)
        return
    try:
        sala = appctx.obter_sala(sala_id)
    except KeyError:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    await sala.conectar(ident.player_id, websocket)
    try:
        while True:
            bruto = await websocket.receive_text()
            if len(bruto) > LIMITE_MSG:
                sala.enviar(ident.player_id, {"type": "error", "code": "mensagem_grande"})
                continue
            if not sala.aceita_mensagem(ident.player_id):
                sala.enviar(ident.player_id, {"type": "error", "code": "muitas_mensagens"})
                continue
            try:
                await despachar(sala, ident.player_id, json.loads(bruto))
            except (ValueError, KeyError, TypeError) as exc:
                sala.enviar(ident.player_id, {"type": "error", "code": "mensagem_invalida", "msg": str(exc)[:200]})
    except WebSocketDisconnect:
        pass
    finally:
        await sala.desconectar(ident.player_id, websocket)


async def despachar(sala, player_id: str, msg: dict):
    if not isinstance(msg, dict):
        raise ValueError("mensagem deve ser um objeto")
    match msg.get("type"):
        case "preview_move":
            await sala.preview(player_id, msg["destino"])
        case "roll":
            await sala.rolar(player_id, str(msg["slot_id"]), str(msg["expressao"]))
        case "confirm_turn":
            await sala.confirmar(player_id, msg["acao"])
        case "unconfirm_turn":
            await sala.desconfirmar(player_id)
        case "host_command":
            await sala.comando_host(player_id, msg)
        case "ping":
            import time
            sala.enviar(player_id, {"type": "pong", "t": time.time()})
        case outro:
            raise ValueError(f"tipo de mensagem desconhecido: {outro}")


# ====================================================================== SPA (sempre por último)
DIST = RAIZ / "web" / "dist"
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{caminho:path}")
async def spa(caminho: str):
    alvo = (DIST / caminho).resolve() if caminho else DIST / "index.html"
    if caminho and DIST.resolve() in alvo.parents and alvo.is_file():
        return FileResponse(alvo)
    index = DIST / "index.html"
    if not index.exists():
        return JSONResponse({"detail": "SPA não compilada: rode `npm run build` em web/"}, status_code=503)
    return FileResponse(index)


def main():
    import uvicorn
    uvicorn.run("server.main:app", host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")), reload=False)


if __name__ == "__main__":
    main()
