# Knowledge Graph — design

Data: 2026-07-15 · Status: aprovado pelo Juliano

## Problema

A base de conhecimento indexada (`server/app/kb/`) é invisível para quem a
administra: documentos, taxonomia e associações só existem no banco. Uma
tela de grafo permite ao admin explorar visualmente o que a organização
tem — enxergar concentrações, buracos de cobertura e tags pendentes de
aprovação.

## Decisões (validadas em conversa)

- **Acesso: só admin.** Tela nova, à parte do chat e do painel, com link de
  entrada no `admin.html`. Member não vê o grafo (API responde 403).
- **Nós:** tags e documentos — o grafo natural dos dados que já existem,
  nada é inferido.
- **Arestas:** hierarquia entre tags (derivada do caminho materializado:
  `rh/beneficios` é filho de `rh`) e associação documento↔tag
  (`document_tags`).
- **Interação: exploração apenas.** Clique mostra detalhes, busca destaca
  nós. Edição de taxonomia continua nas telas atuais do painel (e qualquer
  edição futura via grafo seguirá o padrão de aprovação humana).
- **Atualização: manual.** Botão "atualizar" refaz a chamada e redesenha.
  Sem polling nem SSE na v1.
- **Visualização: Cytoscape.js vendorado** em
  `server/static/vendor/cytoscape.min.js` (MIT, versão pinada, ~370 KB).
  Sem CDN em runtime — soberania preservada.

## Alternativas descartadas

- **Tela compartilhada member/admin** com visibilidade por papel: Juliano
  preferiu tela exclusiva de admin — simplifica permissões e conteúdo.
- **SVG próprio** (física + zoom/pan à mão, ~200–300 linhas): zero
  dependência, mas layout inferior e frágil com 100+ nós.
- **Lib via CDN:** chamada externa em runtime contraria a postura de
  soberania de dados do projeto e quebra em rede restrita.
- **Arestas de coocorrência de tags** (peso = docs em comum): grafo mais
  denso e query extra sem pedido claro; candidata a fase futura.
- **Polling/SSE:** descartados em conversa; atualização manual atende.

## Arquitetura

### Backend

- Rota nova `GET /api/graph` no router de KB (`app/routers/documents.py`),
  com `Depends(require_admin)` como as demais rotas de administração.
  Toda query filtra por `organization_id` do usuário do token — isolamento
  entre tenants é o invariante nº 1.
- Resposta: `{nodes, edges, generated_at}`.
  - Nó de tag: `{id: "tag:<id>", label: <último segmento do path>, path,
    status}` — inclui `pending` (o admin precisa vê-las).
  - Nó de documento: `{id: "doc:<id>", label: filename, status,
    chunk_count}` — inclui documentos com erro, sinalizados.
  - Aresta: `{source, target, kind: "hierarchy" | "doc_tag"}`. Hierarquia é
    derivada em memória do `path` das tags da org (pai = path sem o último
    segmento, quando existir como tag).
- Grafo completo numa resposta só, sem paginação: bases por tenant são
  pequenas (centenas de nós). Payload leve — nenhum texto de chunk vai ao
  front, só metadados.

### Frontend

- Página nova `server/static/graph.html`, vanilla, mesmo padrão de auth do
  chat (access token JS + refresh em cookie). Link de entrada no
  `admin.html`.
- Cytoscape com layout de força; formas/cores distintas para tag e
  documento seguindo a paleta de `context/brand.md`; tag pendente com
  estilo tracejado; documento com erro sinalizado.
- Clique num nó abre painel lateral: tag mostra sub-tags e documentos
  associados; documento mostra suas tags e nº de trechos. Dados vêm do
  próprio grafo já carregado — sem chamadas extras por clique.
- Busca por nome com destaque do nó; zoom/pan/arrastar nativos da lib;
  botão "atualizar" refaz o `GET /api/graph` e redesenha.
- Copy da tela revisada com a skill `tom-teia` e o agente
  `revisor-de-marca` antes do commit, conforme
  `.claude/rules/texto-marca.md`.

## Testes

- **Isolamento:** admin da org A não recebe nós/arestas da org B.
- **Autorização:** member autenticado recebe 403.
- **Shape:** payload com nós de tag (inclusive pendente) e documento,
  arestas de hierarquia e doc↔tag corretas para uma taxonomia de exemplo.

## Fora de escopo (v1)

Edição/curadoria pelo grafo, arestas de coocorrência, polling/SSE,
similaridade por embeddings, visão para members.
