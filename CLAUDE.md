# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

TeIA — IA para o setor de impacto: chat multi-tenant com Claude. Docs, UI e textos em pt-BR; código e commits em inglês (conventional commits).

## Princípios inegociáveis (íntegra em context/principles.md)

- **A IA sugere, a equipe decide**: todo fluxo de IA tem ponto de aprovação humana — nunca publica/decide sozinho.
- **Soberania de dados**: chaves de API e dados pertencem à organização cliente. Chaves nunca vão ao banco nem ao código — orgs referenciam só o nome de uma env var (`api_key_env`).
- **Tecnologia serve à missão**: nenhuma feature existe "porque é possível".
- Antes de entrega significativa: skill `revisao-principios`. Texto voltado a usuário: skill `tom-teia`.

## Economia de tokens (regra transversal)

- **No produto**: nunca concatenar bases inteiras no prompt quando houver índice — busca híbrida (`server/app/kb/`) envia só os ~8 chunks relevantes; prompt caching sempre ativo (maior alavanca de custo, ver `context/custos-ia.md`).
- **No trabalho neste repo**: ler trechos, não arquivos inteiros; não duplicar conteúdo existente em docs novas — linkar a fonte; respostas e documentos enxutos.

## Orquestração de demandas complexas (Fable → Opus)

Quando uma demanda se decompõe em **3+ tasks independentes e bem definidas**, orquestre em vez de executar tudo sozinho (design em docs/superpowers/specs/2026-07-14-orquestracao-fable-opus-design.md):

- Decomponha e mantenha para si as tasks de raciocínio complexo (arquitetura, segurança, decisões); despache as simples ao agente `executor-opus` — **em paralelo** quando não houver dependência entre elas.
- Cada prompt de task deve ser auto-contido: paths, contexto necessário e critério de aceite (o worker parte frio).
- Ao receber os resultados, revise criticamente (correção, isolamento multi-tenant, padrões do repo), corrija o necessário, integre e só então reporte.
- Fora do gatilho (menos de 3 tasks, ou tasks encadeadas): execute direto, sem orquestrar.

## Comandos

Tudo com `py` (Windows). **NUNCA fazer `cd` persistente para subpastas** — os hooks deste repo rodam com caminho relativo à raiz e passam a bloquear toda a shell. Usar subshell no Bash: `(cd server && ...)`.

```bash
py -m pip install -r server/requirements.txt              # dependências
(cd server && py -m pytest tests)                         # todos os testes
(cd server && py -m pytest tests/test_auth.py::test_x)    # um teste
(cd server && py -m alembic upgrade head)                 # migrations
(cd server && py -m app.seed --demo)                      # admin + usuários demo
(cd server && py -m app.ingest <slug>)                    # ingerir pasta do tenant na base indexada
```

Servidor: preferir a skill `/rodar` ou `.claude/launch.json` (nunca Bash para servidor). Config: `.env` na **raiz** (base em `server/.env.example`); mínimo `ANTHROPIC_API_KEY`, `TEIA_SECRET_KEY`, `TEIA_ADMIN_PASSWORD`. Banco: SQLite automático em dev; Postgres via `docker compose up -d`.

## Arquitetura (detalhes em server/README.md e docs/arquitetura-c4.md)

- **server/** — v1 produção: FastAPI + SQLAlchemy 2 + Alembic. Auth por senha (argon2) e Google OIDC (só e-mails convidados); JWT 15 min + refresh rotacionado em cookie HttpOnly; papéis `admin`/`member`; rate limits em memória de processo + cotas (dia/mês) calculadas no banco.
- **server/app/kb/** — base de conhecimento indexada: upload → extração/chunking → classificação em taxonomia por tenant (Haiku; tags novas ficam **pendentes** até aprovação do admin) → embeddings opcionais (Voyage) → busca híbrida (RRF) atrás de `search_chunks()`.
- **chat-research/** — demo original, referência histórica (stdlib pura): não evoluir; features novas vão em `server/`.
- **Multi-tenant**: cada org tem `context_dir` e `api_key_env`. Isolamento entre tenants é o invariante de segurança nº 1 (agente `auditor-de-isolamento` audita).

## Regras por área

Regras detalhadas vivem em `.claude/rules/` com escopo por caminho (`paths:`) — carregam só quando arquivos daquela área são tocados: `server.md`, `texto-marca.md`, `chat-research.md`.
