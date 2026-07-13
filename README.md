# TeIA

**Inteligência Artificial para Impacto.**

TeIA é uma organização que vem do setor de impacto (ONGs, fundações, organismos multilaterais, sociedade civil) e leva IA para dentro dele — não uma empresa de tecnologia que "descobriu" a causa social. Propósito é a nossa arquitetura.

## Princípios

- **A tecnologia deve servir à missão.** Nenhuma feature ou automação existe só porque é possível.
- **As decisões continuam sendo humanas.** Toda solução é *human-in-the-loop* por padrão: a IA sugere, a equipe decide.
- **Impacto continua sendo o objetivo final.** O sucesso se mede pelo efeito real na capacidade da organização de cumprir sua missão, não pelo volume de conteúdo gerado.
- **Soberania de dados.** Contas, chaves de API e dados de IA pertencem à organização cliente, não à TeIA.
- **Personalização sobre padronização.** Soluções calibradas à voz e ao contexto de cada organização atendida.

## Estrutura do repositório

- [`context/brand.md`](context/brand.md) — identidade visual e linguajar da marca (paleta, tipografia, tom de voz, vocabulário-âncora).
- [`context/principles.md`](context/principles.md) — guideline de decisão: princípios inegociáveis e operacionais a checar antes de qualquer entrega.
- [`context/custos-ia.md`](context/custos-ia.md) — referência de custos: diferença entre assinatura Claude Pro e uso da API, estimativas por volume de uso.
- [`examples-ong/`](examples-ong/) — documentos **fictícios** de uma ONG de exemplo (Instituto Raízes do Amanhã), usados como base de conhecimento do tenant ONG na demo.
- [`server/`](server/) — **servidor v1 (produção)**: FastAPI + PostgreSQL/SQLite, login por senha e Google, papéis admin/member, rate limits e cotas de uso de IA, painel administrativo em `/admin`. Ver [`server/README.md`](server/README.md).
- [`chat-research/`](chat-research/) — demo original multi-tenant (referência histórica; ver abaixo).
- [`docs/arquitetura-c4.md`](docs/arquitetura-c4.md) — arquitetura do chat em modelo C4 (Mermaid), incluindo o desenho de separação de cobrança por cliente e a tabela demo → produção.
- [`docs/prompt-servidor-v1.md`](docs/prompt-servidor-v1.md) — o prompt/especificação que guiou a construção do servidor v1.
- [`docs/superpowers/specs/`](docs/superpowers/specs/) e [`docs/superpowers/plans/`](docs/superpowers/plans/) — design aprovado e plano de execução da **base de conhecimento indexada** (tags hierárquicas + busca híbrida full-text/vetorial), em desenvolvimento.
- [`docker-compose.yml`](docker-compose.yml) — PostgreSQL 16 local para o servidor v1 (requer Docker Desktop).

## Servidor v1 (produção)

A versão final do chat vive em [`server/`](server/): autenticação por e-mail/senha (argon2) **e Google** (OIDC + PKCE, apenas e-mails convidados), banco de dados com usuários/papéis/organizações, rate limiting e cotas de uso de IA (por usuário/dia e por tenant/mês, em mensagens e custo), e um **painel administrativo dinâmico** em `/admin` com uso, custo, eventos de segurança e gestão de usuários. Instruções completas em [`server/README.md`](server/README.md).

Em desenvolvimento no mesmo servidor: **base de conhecimento indexada** — upload de documentos (.md/.txt/.pdf) por admins, classificação automática em taxonomia hierárquica por tenant (com aprovação humana das tags novas) e busca híbrida (tags + full-text + embeddings) para enviar ao modelo só os trechos relevantes, em vez da base inteira. Design em [`docs/superpowers/specs/`](docs/superpowers/specs/).

## Chat TeIA (demo multi-tenant original)

Protótipo de chat com Claude (Haiku 4.5) por trás, com autenticação: cada usuário logado conversa **apenas com a base de conhecimento do seu tenant**, e cada tenant pode ter sua própria chave de API — direcionando a cobrança para a conta/workspace daquela organização.

| Login | Senha | Base de conhecimento |
|---|---|---|
| `teia` | `teia123` | `context/` (marca, princípios e custos da TeIA) |
| `ong` | `ong123` | `examples-ong/` (docs fictícios da ONG) |

- [`chat-research/server.py`](chat-research/server.py) — servidor Python (só biblioteca padrão, sem dependências): `POST /api/login` emite token de sessão; `POST /api/chat` resolve o tenant, monta o system prompt com os `.md` da pasta dele e chama a API da Anthropic com a chave dele.
- [`chat-research/index.html`](chat-research/index.html) — página única com tela de login + chat, estilizada conforme `context/brand.md`.

> ⚠️ Autenticação simplificada para demonstração (usuários em código, sessões em memória). O caminho para produção está documentado em [`docs/arquitetura-c4.md`](docs/arquitetura-c4.md).

### Como rodar

1. Crie um arquivo `.env` na raiz do projeto com sua chave da Anthropic:
   ```
   ANTHROPIC_API_KEY=sk-ant-sua-chave-aqui
   ```
   Chave obtida em [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys) — requer billing configurado, é uma conta separada da assinatura Claude Pro. Opcionalmente, defina `ANTHROPIC_API_KEY_TEIA` e `ANTHROPIC_API_KEY_ONG` para separar a cobrança por tenant.
2. Rode o servidor:
   ```powershell
   cd chat-research
   py server.py
   ```
3. Abra `http://localhost:8000` e entre com um dos logins da tabela acima.
4. Editou o `.env`? Reinicie o servidor — ele lê o arquivo só na inicialização.
