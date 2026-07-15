# Chat interativo — design

Data: 2026-07-15 · Status: aprovado pelo Juliano

## Problema

O chat (`server/static/index.html`) hoje é só texto: pergunta digitada,
resposta em texto puro. Queremos que a IA possa oferecer caminhos clicáveis
para o usuário direcionar a conversa, e que a tela renderize respostas com
formatação leve e mostre de onde vieram os trechos usados.

## Decisões (validadas em conversa)

- **Escopo:** esta spec cobre só o chat interativo. A tela de Knowledge
  Graph é uma segunda spec, com ciclo próprio depois desta.
- **Clique numa opção** envia o texto como se o usuário tivesse digitado —
  nada de fluxo guiado nem metadados escondidos.
- **Formato:** chips clicáveis (2–4) abaixo da resposta, apenas quando a IA
  julgar que há caminhos claros a seguir. Sem dropdown fixo, sem obrigar
  sugestão em toda resposta.
- **Geração das opções:** tool use da Anthropic na mesma chamada do chat
  (ferramenta `sugerir_continuacoes`). Estrutura garantida pela API, custo
  extra desprezível, sem segunda chamada.
- **Melhorias incluídas:** Markdown leve nas respostas, fontes consultadas,
  textarea que cresce, botão copiar.
- **Fora do escopo:** streaming (SSE), histórico persistente de conversas,
  opções com metadados de busca.

## Alternativas descartadas

- **Bloco delimitado no texto** (ex.: `---OPCOES---` parseado no servidor):
  frágil — o modelo pode errar o formato e o bloco vazar para o usuário.
- **Segunda chamada (Haiku) para gerar sugestões:** desacopla, mas adiciona
  ~1 s de latência e custo em toda mensagem, mesmo sem opções úteis.
- **Biblioteca de Markdown via CDN (marked + DOMPurify):** dependência
  externa e superfície de XSS; um mini-renderer próprio cobre o subconjunto
  necessário.

## Arquitetura

### Backend

- `anthropic_client.send_message` aceita `tools` opcional e devolve, além do
  texto concatenado, o input do bloco `tool_use` quando houver. Uma única
  chamada; a ferramenta é canal de saída estruturada — não devolvemos
  `tool_result` nem entramos em loop.
- Ferramenta `sugerir_continuacoes`: input `{opcoes: [string]}`. Instrução
  junto às regras do system prompt: responda sempre em texto; se houver
  caminhos claros de aprofundamento, chame a ferramenta ao final. O servidor
  valida: máximo 4 opções, cada uma truncada em 80 caracteres, strings
  vazias descartadas.
- `build_system_blocks` (`app/context_loader.py`) passa a retornar também os
  metadados dos trechos usados na busca híbrida (`arquivo`, `tags`) — hoje
  eles existem internamente e são descartados. No fallback de pasta
  concatenada, a lista vem vazia.
- Resposta de `POST /api/chat` vira `{reply, options: [...], sources: [...]}`.
  Campos novos sempre presentes (listas vazias quando não houver) — contrato
  não quebra para clientes que só leem `reply`.
- `RULES` (`app/context_loader.py`): a seção "estilo de conversa" deixa de
  proibir Markdown e passa a permitir formatação leve (negrito, itálico,
  listas curtas, títulos pequenos), mantendo o tom conversacional e as
  respostas curtas.

### Frontend (tudo em `server/static/index.html`, vanilla)

- **Chips:** quando `options` vier preenchido, botões-pílula abaixo da
  mensagem da IA. Clique envia o texto como mensagem do usuário e desativa
  os chips daquela mensagem (histórico legível, sem re-clique). Estilo segue
  a paleta de `context/brand.md`.
- **Markdown seguro:** mini-renderer próprio (~40 linhas): escapa todo HTML
  primeiro, depois aplica negrito, itálico, listas e títulos por regex sobre
  o texto já escapado. Sem CDN, sem `innerHTML` de conteúdo bruto.
- **Fontes:** linha discreta sob a resposta ("Fontes: manual.pdf ·
  rh.beneficios"), colapsada por padrão, expande ao clique. Só aparece
  quando `sources` não vier vazio.
- **Polimento:** textarea cresce com o conteúdo (até ~5 linhas), botão
  copiar em cada resposta da IA, indicador "tecendo resposta..." mantido.
- Copy de UI revisada com a skill `tom-teia` e o agente `revisor-de-marca`
  antes do commit, conforme `.claude/rules/texto-marca.md`.

### Erros

- Modelo chama a ferramenta sem emitir texto (raro): resposta segue sem
  opções; o servidor loga o caso. Nunca quebra o chat.
- Input da ferramenta malformado (sem `opcoes`, tipos errados): opções
  ignoradas, resposta normal.
- Falhas da API Anthropic: tratamento atual inalterado.

### Custos

A definição da ferramenta adiciona algumas centenas de tokens de entrada por
chamada — desprezível frente aos ~4 mil tokens de contexto por pergunta.
Nenhuma chamada adicional. `usage_events` continua registrando igual.

## Testes

Suite pytest existente continua verde. Novos testes (IA mockada):

- resposta com `tool_use` → `options` preenchidas e validadas;
- resposta sem `tool_use` → `options: []`;
- mais de 4 opções ou opções longas → truncadas;
- tenant com documentos indexados → `sources` com `arquivo` e `tags`;
- tenant no fallback de pasta → `sources: []`;
- `tool_use` malformado → resposta normal sem opções.
