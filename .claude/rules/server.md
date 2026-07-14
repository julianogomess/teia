---
paths:
  - "server/**"
---

# Regras — server/ (v1 produção)

- Chaves de API (Anthropic, Voyage) **nunca** no banco nem em código: orgs guardam só o nome da env var (`api_key_env`); env vars de chave não levam prefixo `TEIA_`.
- Todo fluxo novo de IA precisa de ponto de aprovação humana (padrão existente: tags propostas pela IA nascem `pending` até o admin aprovar).
- Endpoints síncronos por padrão — a única operação lenta (proxy à Anthropic) roda no threadpool do Starlette.
- Mudança de schema = migration Alembic. Manter portabilidade SQLite ↔ Postgres (ex.: embeddings como bytes float32); tipos exclusivos de Postgres (`pgvector`, `tsvector`) só na fase 2, atrás da mesma interface.
- Rate limiting: preservar a interface de `app/rate_limit.py` (troca por Redis sem mudar chamadores). Cotas dia/mês se calculam no banco (já funcionam com N instâncias).
- Papel novo: adicionar em `ROLES` (`app/models.py`) e tratar em `app/deps.py` — sem migração.
- `/admin` serve só a casca da página; dados sempre via `/api/admin/*`, que valida o papel no servidor a cada requisição.
- Backend novo de busca entra atrás de `search_chunks()` (`app/kb/search.py`).
- Toda rota nova: teste em `server/tests`, incluindo caso de **isolamento entre tenants**.
- Validação estrita de payload (Pydantic) e limite de tamanho; antes de criar limite novo, ver a tabela de cotas em `server/README.md` — o padrão é default em código + override por env `TEIA_*` ou painel.
