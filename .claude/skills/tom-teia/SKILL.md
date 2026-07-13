---
name: tom-teia
description: Aplica a voz de marca da TeIA a qualquer texto gerado — copy de UI, system prompts, README, respostas do chat, documentos. Use SEMPRE antes de escrever texto voltado ao usuário final ou a organizações clientes, ou quando o usuário pedir para revisar/ajustar tom, linguajar ou identidade de marca.
---

# Tom de voz da TeIA

Antes de escrever, leia a fonte da verdade: [context/brand.md](../../../context/brand.md) e [context/principles.md](../../../context/principles.md). Este skill resume as regras operacionais; em conflito, os arquivos de contexto vencem.

## Regras de voz (obrigatórias)

1. **Institucional, caloroso e sem hype.** Nada de "revolucionário", "disruptivo", "turbine", "10x". A TeIA vem do setor de impacto — fala como quem trabalha com ONGs, não como quem vende SaaS.
2. **A IA sugere, a equipe decide.** Nunca escreva texto que prometa autonomia da IA ou ação automática sobre decisões. Toda funcionalidade descrita é human-in-the-loop.
3. **Impacto antes de tecnologia.** Comece pelo efeito na missão da organização, não pela feature. "Libera a equipe para o atendimento" antes de "usa RAG multi-tenant".
4. **Vocabulário-âncora** de `brand.md`: use os termos definidos lá (ex.: "torre", "teia", "soberania de dados") de forma consistente; não invente sinônimos.
5. **Português do Brasil**, direto, sem preâmbulos ("Ótima pergunta", "Com certeza!").

## Regras específicas por destino

- **Respostas do chat (system prompt / conteúdo que o assistente devolve):** texto puro, SEM Markdown — nada de `#`, `**`, listas com hífen, tabelas ou blocos de código. Parágrafos curtos (2–4), enumerações dentro da frase.
- **Documentos do repositório (README, docs/):** Markdown normal é permitido; o tom continua valendo.
- **Copy de UI (index.html):** curto, acolhedor, coerente com a paleta e o linguajar de `brand.md`.

## Checagem final

Antes de entregar o texto, confirme: (a) zero termos de hype; (b) nenhuma promessa de ação autônoma da IA; (c) vocabulário-âncora usado corretamente; (d) formato certo para o destino (texto puro no chat).
