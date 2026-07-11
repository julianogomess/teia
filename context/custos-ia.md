# Custos de IA — Plano Pro vs. API

> Documento de referência técnica: explica a diferença entre a assinatura Claude Pro e o uso da API da Anthropic, e estima custos de operação do chat TeIA em diferentes escalas de uso.
> Gerado em 11/07/2026. Preços mudam ao longo do tempo — sempre validar contra [platform.claude.com/docs/en/pricing](https://platform.claude.com/docs/en/pricing) antes de decisões de orçamento.

---

## 1. Dois produtos diferentes, duas contas diferentes

| | **Claude Pro** (claude.ai) | **API da Anthropic** (console.anthropic.com) |
|---|---|---|
| O que é | Assinatura mensal para uso pessoal do site/app Claude | Acesso programático ao modelo, usado por aplicações (como o chat da TeIA) |
| Cobrança | Valor fixo por mês | Pay-as-you-go — cobrado por token consumido (entrada + saída) |
| Limite de uso | Cota de mensagens por período (reseta) | Sem limite fixo — cresce com o uso; pode ser controlado por spend limit |
| Dá acesso à API? | **Não.** São contas e billings separados | — |
| Uso típico | Uma pessoa conversando no site | Um produto/serviço com múltiplos usuários finais |

**Ponto central**: pagar pelo Claude Pro não gera crédito nenhum para a API. O chat da TeIA (ou qualquer produto construído com `ANTHROPIC_API_KEY`) só funciona com billing configurado na conta da API, com cartão cadastrado em [console.anthropic.com/settings/billing](https://console.anthropic.com/settings/billing).

---

## 2. Como funciona o preço da API

O modelo usado no chat da TeIA é o **Claude Sonnet 5** (`claude-sonnet-5`). Preço por milhão de tokens:

| | Preço promocional (até 31/08/2026) | Preço padrão (a partir de 01/09/2026) |
|---|---|---|
| Entrada (input) | US$ 2,00 / MTok | US$ 3,00 / MTok |
| Saída (output) | US$ 10,00 / MTok | US$ 15,00 / MTok |

- **Entrada** = tudo que é enviado ao modelo: prompt de sistema (identidade da marca, princípios) + histórico da conversa + pergunta do usuário.
- **Saída** = a resposta gerada pelo modelo.
- Saída custa ~5x mais que entrada — respostas mais longas pesam mais que perguntas longas.

### Prompt caching — a alavanca de custo mais importante

Quando o mesmo bloco de contexto (ex: `brand.md` + `principles.md`, ou o texto de um PDF) é reenviado em várias perguntas seguidas, a API pode **cachear** esse bloco: a primeira chamada paga preço cheio, as seguintes pagam ~10% do preço de entrada pelo trecho em cache. Em cenários com contexto fixo reutilizado (nosso caso), isso normalmente reduz o custo total em 2–3x.

---

## 3. Estimativas por volume de uso

Premissas usadas: prompt de sistema fixo (~1.000–3.000 tokens, dependendo se inclui só a marca ou também documentos como PDFs), resposta média de ~300 tokens, preço promocional vigente até 31/08/2026.

| Cenário | Usuários | Perguntas/usuário/dia | Perguntas/mês | Custo estimado/mês (sem cache) | Custo estimado/mês (com cache) |
|---|---:|---:|---:|---:|---:|
| **Piloto interno** | 10 | 5 | 1.500 | ≈ US$ 15 | ≈ US$ 6–8 |
| **Equipe pequena** | 50 | 5 | 7.500 | ≈ US$ 76 | ≈ US$ 30–40 |
| **Uso departamental** | 200 | 5 | 30.000 | ≈ US$ 303 | ≈ US$ 120–160 |
| **500 usuários** (cenário discutido) | 500 | 5 | 75.000 | ≈ US$ 758 | ≈ US$ 300–400 |
| **Uso institucional amplo** | 2.000 | 5 | 300.000 | ≈ US$ 3.030 | ≈ US$ 1.200–1.600 |

**Como ler esta tabela**: os valores escalam quase linearmente com o número de perguntas — dobrar usuários ou perguntas/dia dobra o custo aproximado. O que **não** escala linearmente é o efeito do cache: quanto mais perguntas repetidas sobre o mesmo contexto (mesmo PDF, mesma base de conhecimento), maior a economia proporcional.

### O que muda a estimativa para cima ou para baixo

- **Documentos maiores** (PDFs extensos, múltiplos arquivos por pergunta) → mais tokens de entrada → custo sobe.
- **Respostas mais longas ou com raciocínio estendido** (`thinking`) → custo de saída sobe.
- **Perguntas por usuário acima de 5/dia** → escala proporcionalmente.
- **Cache mal configurado ou contexto que muda a cada chamada** (ex: incluir timestamp no prompt) → cache nunca é lido, custo fica no cenário "sem cache".
- **Preço padrão após 31/08/2026** → aumento de ~50% sobre os valores desta tabela.

---

## 4. Recomendações práticas

1. **Configurar prompt caching** no `system` da API assim que o volume de uso justificar (ver [server.py](../chat-research/server.py)) — é a maior alavanca de custo disponível sem trocar de modelo.
2. **Definir um spend limit mensal** no console da Anthropic para evitar surpresas de fatura.
3. **Monitorar `usage.cache_read_input_tokens`** nas respostas da API para confirmar que o cache está sendo aproveitado (se ficar em zero, algo no prompt está mudando a cada chamada e invalidando o cache).
4. **Reavaliar o modelo conforme o caso de uso**: para perguntas realmente simples, `claude-haiku-4-5` (US$ 1,00 / US$ 5,00 por MTok) pode reduzir custo em ~3x mantendo qualidade suficiente — vale testar antes de escalar para centenas de usuários.
