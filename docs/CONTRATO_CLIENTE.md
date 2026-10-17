# Contrato Cliente ↔ Servidor (AI-VTT v4)

Complementa a §16 da documentação de arquitetura. **O servidor é a autoridade**: o cliente envia intenções, o estado chega pronto.

## 1. Estado da sala (`state`)

```ts
interface Estado {
  sala_id: string
  rodada: number
  modo: "exploracao" | "combate"
  cena: {
    id: string; nome: string; descricao: string; tema: string
    tilemap: string[]            // tilemap[y][x]; símbolos: # . P ~ ^ C D
    largura: number; altura: number
    imagem_url: string | null    // Camada 0; null = desenhar versão estilizada do tilemap
  }
  obstaculos: { x: number; y: number; tipo: string; rodadas_restantes: number }[]
  personagens: Record<string, Personagem>
  iniciativa: string[]          // ids em ordem; vazio fora de combate
  jogadores: Record<string, Jogador>
  memoria: Memoria | null
  cronica: LinhaCronica[]       // últimas rodadas (log resumido, para a Crônica)
}

interface Jogador { player_id: string; nome: string; papel: "host" | "jogador" | "espectador"; personagem_id: string | null; conectado: boolean }

interface Personagem {
  id: string; nome: string
  tipo: "jogador" | "npc"
  faccao: "aliado" | "inimigo" | "neutro"
  x: number; y: number
  barras: Record<string, { atual: number; max: number }>   // ids de system_config.barras_status (pv, pm…)
  defesa: number                 // campo cujo nome vem de system_config.campo_defesa
  deslocamento: number           // quadrados por ação de movimento
  iniciativa_bonus: number
  ataques: Ataque[]
  pericias: Record<string, number>
  condicoes: { id: string; rodadas_restantes: number | null }[]
  caido: boolean
  voz: string | null             // id em voices.json (NPCs)
  postura: string | null         // NPCs: agressivo | cauteloso | fugindo | rendido
  cor: string                    // cor do token (#hex)
  icone: string                  // emoji ou letra para o token
}

interface Ataque { id: string; nome: string; bonus: number; dano: string; tipo_dano: string; alcance: number; margem_critico?: number; mult_critico?: number; condicoes_ao_acertar?: string[] }

interface LinhaCronica { rodada: number; id: string; texto: string }   // id = e1, e2…
```

`room_state` também traz `config` (o `system_config.json` do sistema, §5.2), `eu` (`{player_id, papel, personagem_id}`) e `nivel_ia` (1–4).

## 2. Ação declarada (`confirm_turn.acao`)

```ts
interface AcaoDeclarada {
  movimento?: { destino: [number, number] }
  slots: Record<string, Slot>     // chave = id do slot em config.slots_de_acao_por_turno
}
type Slot =
  | { tipo: "ataque"; ataque_id: string; alvo_id: string; rolagem_id?: string }
  | { tipo: "pericia"; pericia: string; texto?: string }
  | { tipo: "criativa"; texto: string }
  | { tipo: "fala"; texto: string }
  | { tipo: "defender" }
  | { tipo: "esperar" }
```

`rolagem_id` vem do `dice_result` do slot (opcional; sem ele o servidor rola na resolução).

## 3. WebSocket `/ws/{sala_id}?token=…`

### Cliente → Servidor
| type | campos |
|---|---|
| `preview_move` | `destino: [x, y]` |
| `roll` | `slot_id`, `expressao` (ex.: `"1d20+8"`) |
| `confirm_turn` | `acao: AcaoDeclarada` |
| `unconfirm_turn` | — |
| `host_command` | `comando` + parâmetros (ver §5) |
| `ping` | — (responde `pong`) |

### Servidor → Cliente
| type | campos | quando |
|---|---|---|
| `room_state` | `state, fase, prazo, config, eu, nivel_ia` | ao conectar/reconectar |
| `phase` | `fase, prazo?, modo` | troca de fase |
| `alcance` | `personagem_id, celulas: [x, y, custo][]` | início do planejamento (só para o dono) |
| `player_preview` | `player_id, personagem_id, caminho: [x,y][], custo` | preview de outro jogador |
| `dice_result` | `player_id, slot_id, rolagem: {expressao, total, termos}` | alguém rolou |
| `ready_status` | `prontos: string[], total, prazo` | confirmação / desconexão |
| `round_log` | `rodada, modo, acoes: [{id, ator_id, texto, eventos: Evento[]}]` | início da narração (antes dos segmentos) |
| `narration_segment` | `seq, voz, texto, eventos: string[], audio_url` | durante a narração |
| `narration_end` | `rodada` | fim da narração |
| `state_sync` | `state` | fim da rodada, desfazer, correção do Host |
| `scene_image` | `cena_id, imagem_url` | battlemap gerado ficou pronto |
| `nivel_ia` | `nivel: 1\|2\|3\|4, provedor` | mudou o nível da IA |
| `error` | `code, msg?, detalhes?` | ação recusada |
| `pong` | `t` | resposta ao ping |

Fases: `lobby`, `planejamento`, `resolvendo`, `narrando`, `pausado`.

### Eventos brutos (`round_log.acoes[].eventos`)
Cada evento tem `tipo` e campos próprios. Os que o cliente anima:
- `movimento {personagem, de:[x,y], para:[x,y], caminho:[x,y][]}`
- `ataque {atacante, alvo, ataque, rolagem, defesa, acertou, critico}`
- `dano {alvo, valor, tipo_dano, barra:"pv"}` → barra desce, número flutua
- `cura {alvo, valor, barra}`
- `condicao {alvo, condicao, rodadas}` / `condicao_removida {alvo, condicao}`
- `caiu {personagem}` / `levantou {personagem}`
- `teste {personagem, pericia, cd, rolagem, sucesso}`
- `fala {personagem, texto}`
- `obstaculo_adicionado {x, y, tipo, duracao_rodadas}` / `obstaculo_removido {x, y}`
- `combate_iniciado {ordem}` / `combate_encerrado {}`
- `cena_mudou {cena_id}`
- `intencao_rejeitada {npc, motivo}` (só depuração)

O cliente aplica a animação quando o `narration_segment` que carrega o id da ação (`e1`) começa a tocar. `state_sync` no fim garante o estado final.

## 4. HTTP

| método | rota | corpo / resposta |
|---|---|---|
| GET | `/api/cartuchos` | `{sistemas: [{id,nome,revisado}], campanhas: [{id,nome,tema,sistema_id,revisado}]}` |
| POST | `/api/salas` | `{nome_host, sistema_id, campanha_id}` → `{sala_id, token, player_id, convite}` |
| GET | `/api/salas/{id}/lobby?convite=…` | `{sala_id, campanha, tema, personagens_disponiveis: [{id,nome,...}], jogadores}` |
| POST | `/api/salas/{id}/entrar` | `{convite, nome, personagem_id}` → `{token, player_id}` |
| POST | `/api/salas/{id}/convites` | header `Authorization: Bearer <token host>` → `{convite}` |
| GET | `/api/salas/{id}/debug` | (token host) → últimas chamadas LLM, intenções rejeitadas, cota |
| GET | `/audio/{id}` | áudio Opus do segmento |
| GET | `/mapas/{arquivo}` | imagem de battlemap |
| GET | `/*` | SPA (`web/dist/index.html`) |

O token vai em `localStorage` e no `?token=` do WS. O `player_id` sai sempre do token.

## 5. Comandos do Host (`host_command`)

| comando | parâmetros |
|---|---|
| `iniciar` | — (lobby → planejamento) |
| `pausar` / `retomar` | — |
| `resolver_agora` | — |
| `desfazer_rodada` | — |
| `iniciar_combate` / `encerrar_combate` | — |
| `mudar_cena` | `cena_id` |
| `editar_personagem` | `personagem_id, campos: {x?, y?, barras?, condicoes?, caido?}` |
| `mudar_nivel_ia` | `nivel: 1\|2\|3\|4` |
| `nova_narracao` | — (re-narra a última rodada) |
