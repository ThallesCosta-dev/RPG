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
| `phase` | `fase, modo, prazo?, aguardando_host?` | troca de fase |
| `players` | `jogadores: Record<player_id, Jogador>` | alguém conectou, desconectou, entrou ou escolheu personagem |
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

## 6. Chat da mesa e diálogo com NPCs

### Cliente → Servidor
| type | campos |
|---|---|
| `chat` | `texto` (≤ 500), `para: null \| <npc_id>` — `para` exige ter personagem; só um NPC responde por vez e nunca durante `resolvendo`/`narrando` (erro `npc_ocupado`) |

### Servidor → Cliente
| type | campos | quando |
|---|---|---|
| `chat_message` | `id, de (player_id ou npc_id), nome, personagem_id, texto, para, npc: bool, ts, audio_url?, voz?, por_host?` | toda mensagem (de jogador, de NPC via IA, ou do Host falando como NPC) |
| `chat_typing` | `personagem_id, nome, fim?` | o NPC começou (ou desistiu) de responder |

`state.chat` traz as últimas 60 mensagens (mesmo formato, sem `audio_url`) para quem entra depois. Mensagens de NPC com `audio_url` devem entrar na mesma fila de áudio da narração (voz do NPC), sem bloquear o chat.

Comando do Host: `falar_como_npc {personagem_id, texto}` → `chat_message` com `npc: true, por_host: true`.

### Revisão de arbitragens pelo Host (§7.4)
- `host_command {comando:"revisar_arbitragens", ativo: bool}` liga/desliga (padrão: desligado; `room_state.revisar_arbitragens` informa o estado). Resposta: `config_sala {revisar_arbitragens}`.
- Quando ligado e o Planejador devolve arbitragens, o servidor manda SÓ ao Host `arbitragens {rodada, prazo, arbitragens: [{personagem_id, pericia, dificuldade, motivo, efeito_sucesso, efeito_falha, alvos}], catalogo: string[], faixas: string[]}` e a todos `phase {fase:"resolvendo", aguardando_host:true, prazo}`.
- O Host responde com `host_command {comando:"editar_arbitragem", arbitragens:[...]}` (mesmo formato; `remover:true` descarta uma) ou `{comando:"aprovar_arbitragens"}`. Sem resposta até `prazo`, a rodada segue com as arbitragens originais.

## 7. Fichas de personagem

| método | rota | corpo / resposta |
|---|---|---|
| GET | `/api/sistemas/{sistema_id}/modelo-ficha` | `{sistema_id, sistema_nome, atributos: string[], pericias: string[], barras: [{id,nome}], campo_defesa, tipos_dano: string[], icones: string[], limites, expressao_ataque, exemplo_dano}` |
| GET | `/api/sistemas/{sistema_id}/fichas` | fichas salvas (reutilizáveis entre mesas): `[{id,nome,classe,icone,cor}]` |
| DELETE | `/api/sistemas/{sistema_id}/fichas/{id}` | apaga uma ficha salva |
| POST | `/api/salas/{id}/fichas` | `{convite?, ficha}` + opcional `Authorization: Bearer` → `{personagem_id, ficha}`; 400 com a lista de erros em `detail` |
| POST | `/api/salas/{id}/personagem` | `{personagem_id}` (token) → vincula um personagem disponível a quem ainda não tem (host incluído) |

`ficha` enviada (modo **classes**, quando `modelo-ficha.modo === "classes"`): `{nome, classe_id, nivel, atributos: {ATR: modificador}, pericias: [ids escolhidos], armas: [ids de modelo.armas, ≤3], armadura_id, escudo: bool, voz?, icone?, cor?, historia?}`.
O servidor calcula PV, recurso de classe, Defesa/CA, bônus de ataque e perícia, CD de magia e a lista `habilidades` (com `usos_restantes`). Regras: perícias fixas da classe sempre treinadas; até `quantidade_pericias` da lista da classe + 2 livres; soma dos modificadores de atributo ≤ `limites.soma_atributos` (+2 a cada 4 níveis).

`ficha` enviada (modo **livre**, sistemas sem `classes.json`): `{nome, classe?, icone?, cor?, historia?, atributos: {ATR: int}, barras: {pv: max, pm: max…}, defesa, deslocamento, iniciativa_bonus, pericias: {nome: bônus}, ataques: [{nome, bonus, dano, tipo_dano, alcance}]}`.

### Habilidades de classe (slot `habilidade`)
`Personagem.habilidades: [{id, nome, nivel, tipo: "ativa"|"passiva", slot: "padrao"|"bonus", alvo: "self"|"aliado"|"inimigo"|"area", alcance, raio?, descricao, efeito, custo?: {barra, valor}, usos?: {max, recupera}}]`
e `Personagem.usos: {habilidade_id: restantes}`. Slot: `{tipo: "habilidade", habilidade_id, alvo_id?, ataque_id?}` (o `slot` da habilidade diz em qual slot ela entra; `ataque_id` só para efeitos de ataque com arma). Eventos novos no `round_log`: `habilidade {personagem, habilidade, nome, alvo}`, `recurso {personagem, barra, valor}`, `uso_gasto {personagem, habilidade}`, `habilidade_erro`. Comando do Host: `descanso {tipo: "curto"|"longo", npcs?: bool}` (restaura PV/recursos/usos e envia um `chat_message` de sistema).

Com **token** (jogador já na sala sem personagem, ou o Host): a ficha é criada e vinculada na hora; o servidor manda um novo `room_state`. Com **convite** (antes de entrar): a ficha aparece em `personagens_disponiveis` com `origem: "sala"` e o jogador entra com `/entrar {personagem_id}`.

`GET /lobby` agora devolve `origem: "campanha" | "sala" | "salva"` em cada personagem disponível. O Host pode criar a mesa sem `personagem_id` e escolher ou criar a ficha depois pelo painel.

## 8. Vozes

| método | rota | resposta |
|---|---|---|
| GET | `/api/vozes` | `[{id, descricao, motor}]` — atores que um jogador pode escolher (`modelo-ficha` também traz `vozes`) |
| GET | `/api/vozes/{id}/amostra` | `{voz, audio_url}` — frase de amostra sintetizada (cache); 404 se TTS desligado |

A ficha aceita `voz: <id>` (opcional). Personagens de jogador com voz falam na narração com a própria tag `[VOZ:<personagem_id>]`,
e o `narration_segment.voz` traz esse id: o cliente deve mostrar o **nome** do personagem (NPC ou jogador) na legenda, nunca o id.
Áudio pode vir como `.ogg` (Kokoro) ou `.mp3` (Edge-TTS); o `audio_url` já aponta para o arquivo certo.

### Motor de voz em jogo
`room_state` traz `tts_motores: string[]` (ex.: `["edge","kokoro"]`) e `tts_preferido: string|null`. O Host envia
`host_command {comando:"mudar_tts", motor:"kokoro"|"edge"|""}` (vazio = cada ator usa o próprio motor) e todos recebem
`config_sala {tts_preferido, tts_motores}`. Kokoro = offline, rápido, pouca entonação; Edge = online, expressivo, ~1,5 s por frase.

### Tamanho da narração
`host_command {comando:"mudar_narracao", tamanho:"curta"|"normal"}` → `config_sala {narracao_curta: bool}`; `room_state.narracao_curta` traz o estado. "Curta" limita o narrador a ~50–90 palavras.
