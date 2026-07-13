# Base de conhecimento indexada — design

Data: 2026-07-12 · Status: aprovado pelo Juliano (com PDF incluído na fase 1)

## Problema

Hoje o contexto de cada tenant é uma pasta de arquivos .md concatenada inteira
no system prompt (`server/app/context_loader.py`). Para organizações grandes
(milhares de documentos) isso estoura a janela de contexto, custa caro por
mensagem e fica lento. Precisamos ingerir grandes volumes de arquivos,
classificá-los e indexá-los para que a consulta seja rápida e econômica.

## Decisões (validadas em conversa)

- **Escala alvo:** milhares de arquivos por tenant (1.000–10.000).
- **Busca:** híbrida — tags filtram o escopo, full-text pega termos exatos,
  vetorial (embeddings) pega sinônimos. Combinação por Reciprocal Rank Fusion.
- **Taxonomia:** hierárquica por tenant (ex.: `rh/beneficios/ferias`). A IA
  (Haiku) classifica documentos dentro da árvore; tags novas propostas pela IA
  nascem `pendentes` e o admin aprova ou rejeita. Cada nível da hierarquia é
  indexável.
- **Ingestão:** upload via API (arquivo individual ou .zip) para admins,
  processado de forma assíncrona; as pastas de contexto atuais continuam
  funcionando via comando de ingestão (`python -m app.ingest <tenant>`).
- **Formatos fase 1:** .md, .txt e **.pdf** (extração com pypdf).
- **Armazenamento:** tudo no Postgres já existente (docker-compose) — texto,
  chunks, tags e embeddings. Arquivos originais no disco, fora da pasta
  pública. Sem serviço novo: mais barato e uma única superfície para backup,
  criptografia e isolamento por tenant.

## Alternativas descartadas

- **Banco vetorial dedicado (Qdrant/Pinecone/Weaviate):** só compensa a partir
  de milhões de vetores; adiciona custo, operação e um segundo sistema para
  proteger e sincronizar.
- **Elasticsearch/OpenSearch:** pesado de operar; o full-text do Postgres
  cobre o caso.
- **Só tags + full-text (sem vetores):** mais barato, mas erra quando o
  usuário pergunta com palavras diferentes das do documento.
- **`ltree` do Postgres para tags:** trocado por caminho materializado em
  coluna string (`rh.beneficios.ferias`) com índice btree — mesmo resultado
  (consulta por prefixo em qualquer nível), portátil para SQLite em dev/teste.

## Arquitetura

### Dados (novas tabelas, todas com `organization_id` indexado)

- `documents` — arquivo ingerido: nome, formato, hash do conteúdo (dedup),
  caminho do original em disco, status (`pending | processing | indexed |
  error`), erro se houver, contadores.
- `document_chunks` — trecho de ~700 tokens com sobreposição: texto, posição,
  embedding (nullable), referência ao documento e ao tenant.
- `tags` — nó da taxonomia: caminho materializado (`rh.beneficios.ferias`),
  status (`approved | pending | rejected`), origem (`admin | ia`).
- `document_tags` — associação documento↔tag.
- `ingest_jobs` — fila de processamento no próprio banco (sem Redis):
  documento a processar, status, tentativas.

### Portabilidade Postgres/SQLite

O servidor roda com SQLite em dev/teste e Postgres em produção. Fase 1 usa
um único motor portátil, dentro da escala alvo (milhares de documentos):

- **Termos exatos:** casamento por `LIKE` em SQL, sempre filtrado por
  `organization_id` (indexado).
- **Vetorial:** embeddings guardados como bytes (float32); similaridade por
  produto escalar com numpy sobre a matriz do tenant, cacheada em memória e
  invalidada a cada ingestão/remoção (dezenas de milhares de chunks →
  milissegundos).
- **Tags:** bônus de relevância quando termos da pergunta casam com tags
  aprovadas do documento.

A interface pública é uma só (`search_chunks(db, org, query, top_k)`);
`tsvector`+GIN e `pgvector`+HNSW entram na fase 2 atrás da mesma interface,
sem mexer em quem consome.

### Pipeline de ingestão

1. `POST /api/admin/documents` recebe arquivo ou .zip (limite de corpo maior
   só nessa rota), grava o original em `server/uploads/<org_slug>/`, cria
   `documents` com status `pending` + `ingest_jobs`, responde 202.
2. Worker (thread iniciada no startup + gatilho pós-upload) processa a fila:
   extrai texto (md/txt direto; pdf via pypdf), quebra em chunks,
   classifica tags com Haiku contra a taxonomia do tenant (tags novas ficam
   `pending`), gera embeddings (Voyage `voyage-3.5-lite` via HTTP; sem
   `VOYAGE_API_KEY`, pula embeddings e o documento fica pesquisável por
   tags + full-text), grava tudo e marca `indexed`.
3. `python -m app.ingest <tenant>` ingere a pasta `context_dir` do tenant
   pelo mesmo pipeline (migração suave dos tenants atuais).

### Consulta no chat

`/api/chat`: se o tenant tem documentos `indexed`, o bloco de base de
conhecimento passa a ser os top-k (~8) chunks da busca híbrida para a última
pergunta do usuário, com a origem (`arquivo · tag`) anotada em cada trecho.
Senão, mantém o comportamento atual (pasta concatenada) — nada quebra para
os tenants existentes. O bloco de regras continua com cache.

### Rotas novas (todas admin, isoladas por tenant)

- `POST /api/admin/documents` (upload), `GET /api/admin/documents` (lista com
  status), `DELETE /api/admin/documents/{id}` (remove doc + chunks + original).
- `GET /api/admin/tags`, `POST /api/admin/tags` (criar nó aprovado),
  `PATCH /api/admin/tags/{id}` (aprovar/rejeitar pendente).
- `GET /api/admin/search?q=` (busca de teste para o admin validar o índice).

### Segurança

- Toda query filtra por `organization_id`; admin só enxerga documentos do
  próprio tenant (exceto o admin da TeIA, que segue o padrão atual do painel).
- Uploads validados por extensão e tamanho; originais gravados com nome
  gerado (hash), nunca o nome enviado; path traversal impossível por
  construção.
- Agente `auditor-de-isolamento` revisa ao final.

### Custos (ordem de grandeza)

- Classificação: Haiku, ~US$1 por milhar de documentos.
- Embeddings: Voyage lite, ~US$0,02 por milhão de tokens (~centavos por
  10 mil páginas).
- Consulta: ~8 chunks (~4 mil tokens) por pergunta em vez da base inteira.

## Fora do escopo (fase 2+)

DOCX/OCR, reranker, UI de gestão de taxonomia (começa via API), S3 para
originais, RLS no Postgres, atualização incremental de documento (v1:
re-upload substitui pelo hash), índices `tsvector`/GIN e `pgvector`/HNSW no
Postgres (a interface de busca já isola essa troca), contabilização do custo
de ingestão em `usage_events`.

## Testes

Suite pytest existente continua verde. Novos testes: extração/chunking,
classificação com IA mockada, busca híbrida (tags, full-text, vetorial com
embeddings falsos), rotas admin (upload, lista, delete, tags), isolamento
entre tenants na busca e nas rotas, fallback sem documentos indexados.
