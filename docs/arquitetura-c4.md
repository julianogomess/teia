# Arquitetura do Chat TeIA — Modelo C4

> Diagramas em Mermaid (renderizam direto no GitHub). Descrevem a arquitetura multi-tenant do portal de chat: cada organização autenticada conversa apenas com a sua própria base de conhecimento, e o custo de IA é roteado para a conta/chave daquela organização.

---

## Nível 1 — Contexto

Quem usa o sistema e com o que ele conversa.

```mermaid
C4Context
    title Chat TeIA — Diagrama de Contexto

    Person(userTeia, "Usuário TeIA", "Membro da equipe TeIA. Pergunta sobre marca, princípios e custos.")
    Person(userOng, "Usuário ONG", "Membro de organização cliente (ex: Instituto Raízes do Amanhã). Pergunta sobre os documentos da própria ONG.")

    System(portal, "Portal de Chat TeIA", "Chat web com autenticação. Restringe as respostas da IA à base de conhecimento do tenant logado.")

    System_Ext(anthropic, "API da Anthropic", "Claude Sonnet 5. Cobrança por token, separada por chave de API / workspace.")

    Rel(userTeia, portal, "Faz login e pergunta", "HTTPS")
    Rel(userOng, portal, "Faz login e pergunta", "HTTPS")
    Rel(portal, anthropic, "Envia prompt + base de conhecimento do tenant", "HTTPS, chave do tenant")
```

**Ponto-chave do desenho**: o portal decide, *depois* da autenticação, (a) qual base de conhecimento injetar no prompt e (b) qual chave de API usar — e é a chave que determina em qual conta/workspace da Anthropic a cobrança cai.

---

## Nível 2 — Contêineres

As peças que compõem o portal.

```mermaid
C4Container
    title Chat TeIA — Diagrama de Contêineres

    Person(userTeia, "Usuário TeIA")
    Person(userOng, "Usuário ONG")

    Container_Boundary(portal, "Portal de Chat TeIA") {
        Container(spa, "Página do chat", "HTML + JS (arquivo único)", "Tela de login + interface de chat com a identidade visual da TeIA. Guarda o token de sessão e o envia em cada pergunta.")
        Container(server, "Servidor de chat", "Python (stdlib)", "Autentica usuários, resolve o tenant, monta o system prompt com a base do tenant e faz proxy para a Anthropic.")
        ContainerDb(kbTeia, "Base TeIA", "context/*.md", "brand.md, principles.md, custos-ia.md")
        ContainerDb(kbOng, "Base ONG", "examples-ong/*.md", "sobre.md, projetos-2026.md, faq-doadores.md (fictícios)")
    }

    System_Ext(anthropic, "API da Anthropic", "Claude Sonnet 5")

    Rel(userTeia, spa, "Usa", "navegador")
    Rel(userOng, spa, "Usa", "navegador")
    Rel(spa, server, "POST /api/login e POST /api/chat", "JSON + Bearer token")
    Rel(server, kbTeia, "Lê se tenant = teia")
    Rel(server, kbOng, "Lê se tenant = ong")
    Rel(server, anthropic, "POST /v1/messages", "x-api-key do tenant")
```

---

## Nível 3 — Componentes do servidor

O que acontece dentro do servidor a cada requisição.

```mermaid
C4Component
    title Servidor de chat — Diagrama de Componentes

    Container_Boundary(server, "Servidor de chat (server.py)") {
        Component(auth, "Autenticação", "/api/login", "Valida usuário/senha, emite token de sessão. Demo: usuários em memória; produção: banco + hash de senha.")
        Component(sessions, "Registro de sessões", "dict token → tenant", "Resolve o Bearer token de cada requisição para um tenant.")
        Component(registry, "Registro de tenants", "TENANTS", "Mapeia tenant → pasta da base de conhecimento + variável de ambiente da chave de API.")
        Component(prompt, "Montador de prompt", "build_system_prompt()", "Concatena os .md da pasta do tenant dentro das regras de escopo (responder só com base neles).")
        Component(proxy, "Proxy Anthropic", "/api/chat", "Chama a API com a chave do tenant. A cobrança cai na conta/workspace dono da chave.")
    }

    System_Ext(anthropic, "API da Anthropic")

    Rel(auth, sessions, "Grava token")
    Rel(proxy, sessions, "Valida token")
    Rel(proxy, registry, "Resolve base + chave")
    Rel(proxy, prompt, "Monta system prompt")
    Rel(proxy, anthropic, "POST /v1/messages")
```

---

## Fluxo de uma pergunta (resumo)

1. Usuário faz login (`POST /api/login`) → servidor valida e devolve um **token de sessão**.
2. Cada pergunta (`POST /api/chat`) leva o token no header `Authorization: Bearer`.
3. O servidor resolve o token → tenant → **pasta de conhecimento** (`context/` ou `examples-ong/`) e **chave de API** (`ANTHROPIC_API_KEY_TEIA` ou `ANTHROPIC_API_KEY_ONG`).
4. Monta o system prompt só com os documentos daquele tenant e chama a Anthropic com a chave daquele tenant.
5. A cobrança aparece no dashboard da conta/workspace dono da chave — cada "torre" paga o seu consumo.

## Do demo para produção

| Aspecto | Demo (este repositório) | Produção |
|---|---|---|
| Usuários e senhas | Hardcoded em `TENANTS`, texto puro | Banco de dados com hash (bcrypt/argon2) ou SSO/OAuth |
| Sessões | Dict em memória (some no restart) | JWT com expiração, ou store externo (Redis) |
| Chaves de API | Variáveis de ambiente no `.env` | Secrets manager, uma chave por cliente |
| Separação de cobrança | 1 env var por tenant | 1 workspace (ou conta) Anthropic por cliente — ver [context/custos-ia.md](../context/custos-ia.md) |
| Base de conhecimento | Pastas de `.md` no repositório | Storage por cliente, com upload/gestão pelo próprio cliente |
| Transporte | HTTP local | HTTPS atrás de proxy reverso |

Alinhado ao princípio de **soberania de dados** ([principles.md](../context/principles.md)): no desenho de produção recomendado, cada organização cliente é dona da própria conta Anthropic e dos próprios documentos — a TeIA orquestra, não centraliza.
