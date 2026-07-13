---
description: Cria um novo tenant no chat TeIA (pasta de contexto, TENANTS, env var, README e C4)
argument-hint: <slug-do-tenant> [Nome da Organização]
---

Crie um novo tenant no chat multi-tenant da TeIA. Argumentos recebidos: `$ARGUMENTS` — o primeiro token é o slug (minúsculas, sem espaço); o restante, se houver, é o nome de exibição da organização. Se faltar o slug ou o nome, pergunte antes de prosseguir.

Passos (todos obrigatórios — o onboarding hoje é manual em 4 lugares e esquecer um deles quebra a demo):

1. **Pasta de contexto**: crie `examples-<slug>/` na raiz com um `sobre.md` inicial (marcado como fictício/placeholder, seguindo o padrão de `examples-ong/`). O conteúdo deve seguir o tom de `context/brand.md`.
2. **Registro em `chat-research/server.py`**: adicione a entrada no dict `TENANTS` seguindo exatamente o formato das existentes:
   - `password`: gere uma senha simples de demo no padrão `<slug>123`;
   - `label`: nome de exibição da organização;
   - `description`: uma linha descrevendo a base de conhecimento;
   - `context_dir`: `PROJECT_ROOT / "examples-<slug>"`;
   - `api_key_env`: `ANTHROPIC_API_KEY_<SLUG_MAIUSCULO>`.
3. **README.md**: adicione a linha do novo login na tabela da seção "Chat TeIA (demo multi-tenant)" e mencione a nova env var opcional na seção "Como rodar".
4. **docs/arquitetura-c4.md**: adicione a nova base de conhecimento no diagrama de contêineres (novo `ContainerDb`) e a relação `Rel(server, kb<Slug>, "Lê se tenant = <slug>")`.
5. **NÃO** escreva nenhuma chave de API real em lugar nenhum. Apenas referencie o nome da env var; lembre o usuário de defini-la no `.env` se quiser cobrança separada.
6. Ao final, valide com `py -m py_compile chat-research/server.py` e mostre um resumo: login/senha de demo, pasta criada, env var esperada.
