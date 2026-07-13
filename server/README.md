# Servidor TeIA — v1

Versão de produção do chat multi-tenant da TeIA. Substitui a demo de
`chat-research/` (que permanece no repositório como referência histórica).

O que esta versão adiciona sobre a demo:

- **Login por e-mail/senha** (hash argon2) **e login com Google** (OIDC,
  Authorization Code + PKCE) — apenas para e-mails convidados por um admin.
- **Sessões seguras**: JWT de acesso de 15 min + refresh token revogável
  (rotacionado a cada uso) em cookie HttpOnly.
- **Banco de dados** (PostgreSQL via Docker, ou SQLite em desenvolvimento)
  com usuários, papéis, organizações (tenants) e todo o histórico de uso.
- **Proteções de uso de IA**: rate limit por IP (login) e por usuário (chat),
  cota diária por usuário, cotas mensais por tenant (mensagens e custo US$),
  limite de tamanho de payload, truncamento de histórico e limite de chamadas
  simultâneas.
- **Painel administrativo** em `/admin` (só papel `admin`): uso e custo por
  dia/tenant/usuário, cotas com alertas, eventos de segurança e gestão de
  usuários — atualiza sozinho a cada 10 s.
- **Prompt caching** na chamada à Anthropic (a maior alavanca de custo — ver
  [context/custos-ia.md](../context/custos-ia.md)).

## Como rodar

Pré-requisito: Python 3.9+.

```powershell
# 1. dependências
py -m pip install -r server/requirements.txt

# 2. configuração: copie server/.env.example para .env NA RAIZ e preencha
#    (no mínimo ANTHROPIC_API_KEY, TEIA_SECRET_KEY e TEIA_ADMIN_PASSWORD)

# 3. banco de dados — escolha UM:
#    a) desenvolvimento: nada a fazer (SQLite criado automaticamente)
#    b) Postgres via Docker (requer Docker Desktop):
docker compose up -d          # na raiz do repositório
# e no .env: TEIA_DATABASE_URL=postgresql+psycopg2://teia:teia-dev@localhost:5432/teia
cd server
py -m alembic upgrade head    # aplica as migrations

# 4. admin inicial (e usuários de demonstração, se quiser)
cd server
py -m app.seed                # cria orgs + admin
py -m app.seed --demo         # também cria teia@teia.org.br e ong@raizes.org.br

# 5. servidor
py -m uvicorn app.main:app --port 8000
```

Abra <http://localhost:8000> (chat) e <http://localhost:8000/admin> (painel,
requer login de admin).

## Login com Google

1. Em [console.cloud.google.com](https://console.cloud.google.com) crie um
   projeto → *APIs & Services* → *Credentials* → *Create OAuth client ID*
   (tipo **Web application**).
2. Em *Authorized redirect URIs* adicione
   `http://localhost:8000/api/auth/google/callback` (e a URL de produção).
3. Copie o Client ID e o Secret para `TEIA_GOOGLE_CLIENT_ID` e
   `TEIA_GOOGLE_CLIENT_SECRET` no `.env`.

Importante: o Google só autentica — **não cadastra**. O e-mail precisa ter
sido convidado antes por um admin no painel; caso contrário a pessoa vê
"este e-mail ainda não foi convidado".

## Testes

```powershell
cd server
py -m pytest tests
```

Cobrem: login (senha e Google mockado), rotação/revogação de refresh token,
controle de acesso admin × member, rate limits, cotas (diária do usuário e
mensal do tenant), validação estrita de payload, isolamento de tenant no
system prompt e registro de `usage_events`.

## Arquitetura e decisões

- **FastAPI + SQLAlchemy 2 + Alembic.** Endpoints síncronos (o proxy à
  Anthropic é a única operação lenta e roda no threadpool do Starlette).
- **Rate limiting em memória de processo** (janela deslizante). Suficiente
  para uma instância; para escalar horizontalmente, troque a implementação em
  [app/rate_limit.py](app/rate_limit.py) por Redis mantendo a interface.
  As **cotas** (dia/mês) são calculadas no banco e já funcionam com N instâncias.
- **DDoS volumétrico é papel da infra**, não da aplicação — use um proxy
  reverso com `limit_req` ([nginx.example.conf](nginx.example.conf)) e um
  serviço de borda (ex.: Cloudflare). A aplicação mitiga abuso lógico:
  força bruta de login, flood de chat, estouro de cota e payloads gigantes.
- **Chaves da Anthropic nunca vão ao banco** — cada organização aponta para o
  nome de uma variável de ambiente (`api_key_env`), preservando a soberania
  de custo por cliente (uma conta/workspace por organização).
- **Papéis**: `admin` (painel, gestão, métricas de todos os tenants) e
  `member` (só o chat do próprio tenant). Novos papéis: adicione em
  `ROLES` ([app/models.py](app/models.py)) e trate em
  [app/deps.py](app/deps.py) — sem migração.
- **`/admin` serve só a casca** da página; todos os dados vêm de
  `/api/admin/*`, que valida o papel no servidor a cada requisição.

### Dependências (justificativa)

| Pacote | Por quê |
|---|---|
| fastapi / uvicorn | framework web + servidor ASGI |
| SQLAlchemy / alembic | ORM + migrations versionadas |
| greenlet (pin <3.2) | dependência do SQLAlchemy; última série com wheel p/ Python 3.9 no Windows |
| pydantic / pydantic-settings / email-validator | validação estrita de payloads e configuração via env |
| argon2-cffi | hash de senha (recomendação OWASP) |
| PyJWT[crypto] | JWT de acesso + verificação do id_token do Google (RS256/JWKS) |
| httpx | chamadas à Anthropic e ao Google com timeout |
| psycopg2-binary | driver PostgreSQL |
| pytest | testes |

### Cotas e limites — onde ajustar

| Limite | Default | Onde mudar |
|---|---|---|
| Tentativas de login por IP/min | 10 | `TEIA_LOGIN_RATE_PER_MINUTE` |
| Mensagens de chat por usuário/min | 10 | `TEIA_CHAT_RATE_PER_MINUTE` |
| Mensagens por usuário/dia | 100 | painel (por usuário) ou `TEIA_DEFAULT_USER_DAILY_MESSAGES` |
| Mensagens por tenant/mês | 10.000 | painel (por org) ou `TEIA_DEFAULT_ORG_MONTHLY_MESSAGES` |
| Custo por tenant/mês (US$) | 50 | painel (por org) ou `TEIA_DEFAULT_ORG_MONTHLY_COST_USD` |
| Corpo máximo da requisição | 32 KB | `TEIA_MAX_BODY_BYTES` |
| Tamanho máximo de uma mensagem | 8.000 chars | `TEIA_MAX_MESSAGE_CHARS` |
| Histórico enviado ao modelo | 20 msgs | `TEIA_MAX_HISTORY_MESSAGES` |

Recomendação extra: configure também um **spend limit** na própria conta da
Anthropic (console) — é a última linha de defesa de custo.
