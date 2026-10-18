# AI-VTT v4 — Mesa virtual multiplayer com IA como mestre

Implementação da `Documentacao_Arquitetura_AI-VTT_v4.md`: **o código é o juiz, a IA é o narrador.**
Motor de regras determinístico + Event Store em SQLite; o LLM só propõe intenções (validadas) e narra o que já foi resolvido.

```
ai-vtt/
├── server/          FastAPI + WebSocket, motor, event store, IA, TTS, mapas
├── web/             SPA (Vite + React + TypeScript + PixiJS + Zustand) → web/dist
├── cartuchos/       sistemas (tormenta20) e campanhas (coracao-de-rubi), somente leitura em jogo
├── tests/           55 testes (grid, regras, motor, sala, TTS, provedores, mapas)
├── scripts/         simular_combate.py, cliente_teste.py, backup.py, tunel.md
├── docs/            CONTRATO_CLIENTE.md (estado, mensagens WS, HTTP, comandos do Host)
├── voices.json      atores de voz do TTS
└── .env.example     chaves, modelos, cotas, timers
```

## Rodando

```bash
pip install -r requirements.txt
cp .env.example .env            # GEMINI_API_KEY, CHAVE_TOKENS, cotas…
cd web && npm install && npm run build && cd ..
python -m server.main           # http://localhost:8000  (SPA + API + WS + áudio)
```

Sem `GEMINI_API_KEY` e sem LLM local o jogo roda no **nível 4** (IA heurística + narração por template): a partida nunca para.

| Nível | Quando | Planejador / Narrador |
| --- | --- | --- |
| 1 Normal | cota folgada | Gemini Flash-Lite / Flash |
| 2 Econômico | > 70% da cota diária | Flash-Lite / Flash-Lite (narração curta) |
| 3 Local | cota esgotada ou API fora | `LLM_LOCAL_URL` (Ollama/llama.cpp, OpenAI-compatível) |
| 4 Sem LLM | nada disponível | `heuristic_ai.py` / `narrador_template.py` |

O Host pode forçar o nível no painel (`mudar_nivel_ia`).

### Voz (opcional)

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu128   # GPU (RTX 50xx precisa de cu128+); sem isso roda em CPU
pip install kokoro soundfile
python scripts/testar_voz.py        # sintetiza uma frase por ator de voices.json
# ou: pip install piper-tts e modelos em modelos/piper/pt_BR-faber-medium.onnx
```
`TTS_MOTOR=auto|kokoro|piper|nenhum`. Sem motor, os segmentos chegam só com legenda (o jogo não para).
Se o Kokoro reclamar de espeak, instale o eSpeak NG (MSI em https://github.com/espeak-ng/espeak-ng/releases).

### Battlemaps (opcional)

`COMFYUI_URL=http://localhost:8188` + `comfyui_workflow.json` ajustado aos checkpoints da sua instalação
(SDXL-Lightning + ControlNet de segmentação). O tilemap lógico vem primeiro; a imagem é gerada a partir dele
na faixa pesada do GPU Scheduler, nunca durante a narração. Sem ComfyUI, o cliente desenha o tilemap estilizado.

### Fichas, chat e revisão de arbitragens

- **Fichas**: no lobby de convite (ou dentro da mesa, se ainda não tiver personagem) o jogador cria a ficha num formulário
  gerado pelo `system_config` do sistema (atributos, barras, perícias, ataques com expressão de dano). O servidor valida
  limites e expressões; fichas ficam salvas em `data/fichas/<sistema>/` e podem ser reaproveitadas em outras mesas.
- **Chat**: painel de chat da mesa; escolhendo um NPC em "Para:", a IA responde em personagem (personalidade do `npcs.json`,
  memória da campanha, conversas recentes) com voz do NPC quando o TTS está ativo. O Host também pode falar como qualquer NPC.
- **Revisão de arbitragens** (§7.4): ligando no painel do Host, as arbitragens do Planejador aparecem para ele antes da
  resolução, com prazo de 45 s para editar perícia, dificuldade ou efeito.

## Fluxo de uma sessão

1. Host cria a mesa em `/` (escolhe sistema, campanha e personagem) e recebe um link de convite de uso único.
2. Jogadores abrem `/sala/<id>?convite=<código>`, escolhem nome e personagem e recebem um token assinado.
3. Host clica **Iniciar**: o grupo é posicionado na cena inicial; NPCs instanciados.
4. Cada rodada: **planejamento** (preview de movimento, dados rolados no servidor, confirmar) → **resolução**
   (Planejador em JSON validado → motor em ordem de iniciativa → eventos) → **narração** (stream → segmentador →
   TTS → `narration_segment` com `[EVENTO:id]` para sincronizar animações) → `state_sync`.
5. Ao terminar: `python scripts/backup.py`. Para expor na internet: `scripts/tunel.md`.

## Ferramentas

```bash
python -m pytest -q                                   # testes
python scripts/simular_combate.py --seed 42 -v        # combate inteiro pela linha de comando, sem IA
python scripts/cliente_teste.py                       # ponta a ponta contra o servidor (3 clientes WS)
python -m server.compiler sistema tormenta20          # compila um cartucho a partir do .md (precisa de LLM)
python -m server.compiler campanha coracao-de-rubi
python -m server.compiler aprovar campanha coracao-de-rubi
cd web && VITE_MOCK=1 npm run dev                     # SPA com servidor simulado (/sala/mock)
```

### Cartuchos

Um **sistema** = `manifest.json` + `compilado/{system_config.json, efeitos.json, monstros.json}` (+ `plugin.py` opcional
com `resolver_ataque`, `inicio_de_turno`, `rolar_iniciativa`). Uma **campanha** = `manifest.json` + `compilado/{personagens.json,
npcs.json, cenas.json}` (+ `mapas/` prontos). O compilador gera tudo isso a partir do `.md` (fatiamento → RAG → extração com
`response_schema`), deixa o cartucho em `pendente_revisao` e o Host aprova. Salas só abrem com cartuchos `revisado`.

Os de exemplo (`tormenta20`, `coracao-de-rubi`) foram escritos à mão e já estão revisados.

## Segurança

Token assinado (`itsdangerous`) no handshake do WS; `player_id` nunca vem da URL. Convite de uso único. 16 KB por mensagem,
500 caracteres por texto, 20 mensagens/s por conexão. Texto de jogador sempre entre `<fala_jogador>`; nenhum número sai dele.
Áudios por id hexadecimal de 32 caracteres. Segredos só no `.env`.
