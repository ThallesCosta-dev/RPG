# Expor a mesa na internet (§14.3)

O FastAPI serve tudo (SPA, API, WebSocket, áudios) em `localhost:8000`. Nenhuma porta precisa ser aberta no roteador.

## Cloudflare Named Tunnel (URL fixa, precisa de um domínio na Cloudflare)

```bash
cloudflared tunnel login
cloudflared tunnel create ai-vtt
cloudflared tunnel route dns ai-vtt mesa.seudominio.com.br
cloudflared tunnel run ai-vtt
```

`~/.cloudflared/config.yml` (no Windows: `%USERPROFILE%\.cloudflared\config.yml`):

```yaml
tunnel: ai-vtt
credentials-file: C:\Users\<voce>\.cloudflared\<ID-DO-TUNEL>.json
ingress:
  - hostname: mesa.seudominio.com.br
    service: http://localhost:8000
  - service: http_status:404
```

Opcional: Cloudflare Access (código por e-mail) como segunda barreira na frente do hostname.

## Quick tunnel (URL aleatória a cada execução; só para testes)

```bash
cloudflared tunnel --url http://localhost:8000
```

## Alternativa sem domínio

```bash
tailscale funnel 8000
```

## Rotina de sessão

1. `python -m server.main` (ou `uvicorn server.main:app --port 8000`)
2. `cloudflared tunnel run ai-vtt`
3. Criar a mesa em `https://mesa.seudominio.com.br/`, enviar o link de convite pelo Discord.
4. Ao terminar: `python scripts/backup.py`.
