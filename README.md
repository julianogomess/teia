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
- [`chat-research/`](chat-research/) — chat web com a identidade da TeIA, que responde apenas com base no conteúdo de `context/` (ver abaixo).

## Chat TeIA

Protótipo de chat com Sonnet 5 por trás, restrito à base de conhecimento em `context/` — a IA não responde nada fora do que está documentado ali.

- [`chat-research/server.py`](chat-research/server.py) — servidor Python (só biblioteca padrão, sem dependências) que injeta `context/*.md` no system prompt e chama a API da Anthropic.
- [`chat-research/index.html`](chat-research/index.html) — página única do chat, estilizada conforme `context/brand.md`.

### Como rodar

1. Crie um arquivo `.env` na raiz do projeto com sua chave da Anthropic:
   ```
   ANTHROPIC_API_KEY=sk-ant-sua-chave-aqui
   ```
   (chave obtida em [console.anthropic.com](https://console.anthropic.com) → API Keys — requer billing configurado, é uma conta separada da assinatura Claude Pro)
2. Rode o servidor:
   ```powershell
   cd chat-research
   py server.py
   ```
3. Abra `http://localhost:8000`.
