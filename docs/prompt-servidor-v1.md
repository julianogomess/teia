# Prompt — Servidor TeIA v1 (versão final de produção)

> Prompt pronto para ser executado pelo Claude Code (ou usado com `/make-plan`).
> Contexto do repositório: `chat-research/server.py` é a demo atual (Python stdlib,
> usuários hardcoded, sessões em memória). `docs/arquitetura-c4.md` descreve a
> arquitetura multi-tenant e a tabela "Do demo para produção" — esta tarefa é
> exatamente essa migração.

---

## Prompt

Evolua o servidor do chat TeIA (`chat-research/server.py`) da demo atual para a
**versão final v1**, mantendo o comportamento multi-tenant existente (cada
organização conversa apenas com a própria base de conhecimento e usa a própria
chave de API Anthropic). Trabalhe em uma nova pasta `server/` na raiz do
repositório, sem apagar a demo antiga. Atualize `docs/arquitetura-c4.md` e o
`README.md` ao final para refletir a nova arquitetura.

### 1. Stack e infraestrutura

- Backend em **Python com FastAPI + Uvicorn** (substitui o servidor stdlib).
- **PostgreSQL 16 rodando localmente via Docker Compose** (`docker-compose.yml`
  na raiz), com volume persistente e healthcheck.
- Migrations com **Alembic** (schema versionado, nada de `CREATE TABLE` manual).
- ORM: SQLAlchemy 2.x.
- Configuração via variáveis de ambiente / `.env` (usar `pydantic-settings`);
  **nunca** commitar segredos — o `.gitignore` já cobre `.env`.
- O frontend atual (`chat-research/index.html`) deve continuar funcionando com
  ajustes mínimos; adaptar as chamadas de API conforme necessário e adicionar a
  tela/fluxo de login com Google.

### 2. Autenticação e autorização

- **Dois métodos de login**:
  1. E-mail + senha, com hash **argon2** (ou bcrypt), armazenados no Postgres.
  2. **Google Sign-In (OAuth 2.0 / OpenID Connect)** — fluxo Authorization Code
     com PKCE. No primeiro login com Google, criar o usuário automaticamente
     **apenas se o e-mail já estiver pré-cadastrado/convidado** por um admin
     (não é cadastro aberto ao público). Client ID/Secret via env vars.
- Sessões via **JWT de curta duração (15 min) + refresh token** persistido no
  banco (revogável). Logout revoga o refresh token.
- **Modelo de dados** (mínimo):
  - `organizations` (tenant): nome, slug, pasta/base de conhecimento, referência
    à env var da chave Anthropic (a chave em si nunca vai ao banco).
  - `users`: e-mail, hash de senha (nullable p/ contas só-Google), `google_sub`,
    organização, papel, status (ativo/bloqueado), timestamps.
  - `roles` / permissões — no mínimo dois papéis: **`admin`** (gerencia usuários,
    vê dashboard, vê métricas de todos os tenants) e **`member`** (só usa o chat
    do próprio tenant). Modelar de forma que novos papéis/permissões possam ser
    adicionados sem migração estrutural (tabela de permissões ou enum extensível).
  - `usage_events`: registro por chamada de IA — usuário, tenant, modelo, tokens
    de entrada/saída, custo estimado, latência, timestamp, resultado (ok/erro/
    bloqueado por limite).
- **Seed**: script/comando que cria a organização TeIA, a ONG de exemplo e um
  usuário admin inicial (credenciais vindas de env vars).
- Toda rota de API protegida por dependência de autenticação; rotas de admin
  exigem papel `admin` (verificado no servidor, nunca só no frontend).

### 3. Segurança do uso de IA (proteção e limites)

- **Rate limiting em camadas**, com estado no Postgres ou em memória com
  janela deslizante (documentar a escolha; deixar a interface pronta para
  trocar por Redis no futuro):
  1. **Por IP** (pré-autenticação): protege `/api/login` e o fluxo OAuth contra
     força bruta — ex.: 10 tentativas/min, com backoff.
  2. **Por usuário**: ex.: N mensagens de chat por minuto (configurável).
  3. **Por usuário/dia e por tenant/mês**: **cota máxima de uso** em número de
     mensagens **e** em custo estimado (US$), configurável por admin. Ao
     estourar, responder `429` com mensagem clara e registrar o evento.
- **Mitigação de DDoS/abuso no nível da aplicação** (documentar que proteção
  volumétrica real é responsabilidade de infra — Cloudflare/proxy reverso — e
  incluir exemplo de config nginx com `limit_req` no repositório):
  - Limite de tamanho do corpo da requisição (ex.: 32 KB) e do histórico de
    mensagens enviado ao modelo (truncar histórico antigo).
  - Timeouts em todas as chamadas externas; limite de conexões concorrentes
    por usuário para o endpoint de chat.
  - Validação estrita de payloads com Pydantic (rejeitar campos extras).
- **Endurecimento geral**: CORS restrito à origem do frontend, headers de
  segurança (CSP, X-Content-Type-Options, etc.), cookies de refresh `HttpOnly`/
  `Secure`/`SameSite`, comparações de segredo em tempo constante, logs sem
  vazamento de tokens ou chaves.
- A chave da Anthropic continua **apenas no servidor** (env vars por tenant,
  como hoje); o frontend nunca a vê.

### 4. Dashboard administrativo (apenas admins)

- Rota `/admin` servida pelo backend, acessível **somente** a usuários com papel
  `admin` (guard no backend; usuário não-admin recebe 403).
- Dashboard **dinâmico** — atualização automática (polling leve a cada ~10 s ou
  SSE), sem precisar recarregar a página. Pode ser HTML+JS vanilla seguindo a
  identidade visual da TeIA (`context/brand.md`); sem framework pesado.
- Deve mostrar, com filtro por período e por tenant:
  - **Uso de IA**: mensagens e tokens por dia, custo estimado acumulado
    (usar `context/custos-ia.md` como referência de preços), por tenant e por
    usuário (top consumidores).
  - **Limites**: consumo atual vs. cota de cada usuário/tenant, com destaque
    para quem está perto (>80%) ou estourou.
  - **Segurança**: tentativas de login falhas, bloqueios por rate limit,
    requisições 429 recentes, IPs mais ativos.
  - **Saúde**: latência média das chamadas à Anthropic, taxa de erro, uptime do
    processo.
- **Gestão de usuários** no mesmo painel: convidar/criar usuário (e-mail +
  papel + tenant), bloquear/desbloquear, alterar papel, ajustar cotas
  individuais e do tenant.

### 5. Qualidade e entrega

- Testes automatizados (pytest) cobrindo: login (senha e mock do Google),
  controle de acesso admin vs. member, rate limit (estourar e resetar janela),
  cota diária, isolamento de tenant (usuário da ONG nunca recebe contexto da
  TeIA) e registro de `usage_events`.
- `README.md` da pasta `server/` com passo a passo: subir Postgres
  (`docker compose up -d`), rodar migrations, seed, iniciar servidor, criar
  credenciais Google (console do Google Cloud) e acessar o dashboard.
- Rodar tudo localmente ao final e verificar o fluxo completo: login com senha,
  login com Google (ou mock, se não houver credenciais), chat respondendo com a
  base correta do tenant, limite disparando 429, dashboard exibindo os eventos.

### Restrições e princípios

- Respeitar os princípios da TeIA (`context/principles.md`): soberania de dados
  (nada de enviar dados de um tenant para outro contexto) e "a IA sugere, a
  equipe decide".
- Manter o tom e identidade visual da TeIA em qualquer tela nova.
- Preferir soluções simples e auditáveis a dependências pesadas; cada
  dependência nova deve ter justificativa no README.
- Não quebrar a demo antiga (`chat-research/`), que fica como referência
  histórica.

---

## Decisões em aberto (confirmar antes de executar)

1. **Cadastro via Google**: só e-mails pré-convidados (recomendado acima) ou
   qualquer conta Google de domínios permitidos?
2. **Valores padrão de cotas**: quantas mensagens/dia por usuário e qual teto
   de custo mensal por tenant?
3. **Redis agora ou depois**: o prompt assume rate limit sem Redis na v1, com
   interface pronta para troca. Se a v1 já for para múltiplas instâncias,
   incluir Redis no docker-compose desde já.
