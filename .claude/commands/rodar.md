---
description: Sobe o servidor do chat TeIA e faz smoke-test dos logins dos tenants
---

Suba o chat TeIA e verifique que os dois tenants funcionam:

1. **Pré-checagem**: confirme que `.env` existe na raiz com `ANTHROPIC_API_KEY` definida (liste só os NOMES das variáveis com `cut -d= -f1 .env` — nunca os valores). Se não existir, pare e explique como criar (ver README).
2. **Servidor**: inicie com o preview do navegador (preview_start) usando `py server.py` a partir de `chat-research/`, porta 8000. Se a porta estiver ocupada, avise e pergunte se deve usar outra via env var `PORT`.
3. **Smoke-test de login** (via curl ou requisição HTTP):
   - `POST /api/login` com `teia`/`teia123` → deve devolver token;
   - `POST /api/login` com `ong`/`ong123` → deve devolver token;
   - `POST /api/login` com credencial inválida → deve devolver 401.
4. **Smoke-test de isolamento** (barato, 1 pergunta por tenant): com o token do tenant `ong`, envie `POST /api/chat` perguntando algo que só existe na base da TeIA (ex.: "qual a paleta de cores da marca TeIA?") — a resposta deve dizer que a informação não está na base de conhecimento. Se a resposta trouxer conteúdo de `context/`, isso é vazamento entre tenants: reporte como CRÍTICO.
5. Abra `http://localhost:8000` no navegador embutido e confirme que a tela de login renderiza.
6. Resuma: status do servidor, resultado dos logins, resultado do teste de isolamento.
