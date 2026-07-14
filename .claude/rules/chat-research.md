---
paths:
  - "chat-research/**"
---

# Regras — chat-research/ (demo histórica)

- Referência histórica congelada: **não** adicionar features aqui — evolução vai em `server/`. Só correções de segurança/bug.
- `server.py` usa apenas biblioteca padrão do Python — não introduzir dependências.
- Depois de **qualquer** mudança em `server.py` (auth, sessões, tenants, rotas): rodar o agente `auditor-de-isolamento`.
