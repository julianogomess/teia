---
name: revisao-principios
description: Checa uma entrega (feature, texto, decisão de arquitetura) contra os princípios inegociáveis da TeIA antes de finalizar. Use antes de commitar mudanças significativas, ao propor arquitetura nova, ou quando o usuário pedir "revisa contra os princípios" / "isso fere algum princípio?".
---

# Revisão contra os princípios da TeIA

Leia [context/principles.md](../../../context/principles.md) — é a fonte da verdade. Depois avalie a entrega contra cada princípio abaixo e produza um veredito por item: **OK**, **ATENÇÃO** (com o quê ajustar) ou **VIOLA** (com o porquê e alternativa).

## Checklist inegociável

1. **A tecnologia serve à missão.** Essa feature/mudança existe porque ajuda a organização a cumprir a missão, ou só porque é tecnicamente possível? Se não souber articular o benefício de missão em uma frase, é ATENÇÃO.
2. **Human-in-the-loop por padrão.** Alguma parte da entrega toma decisão ou executa ação (publicar, enviar, apagar, responder em nome de alguém) sem aprovação humana? Se sim, VIOLA — redesenhe para sugerir em vez de agir.
3. **Impacto como métrica.** O sucesso está descrito em termos de efeito real (tempo liberado, atendimentos, doações) ou em volume de output de IA? Volume não é impacto.
4. **Soberania de dados.** Dados, contas e chaves de API do cliente ficam sob controle do cliente? Atenção especial a: chave de API de um tenant usada para outro, dados de um tenant acessíveis a outro, segredos em código ou em log, dependência que envia dados a terceiros sem necessidade.
5. **Personalização sobre padronização.** A solução respeita a voz e o contexto da organização atendida, ou empurra um padrão genérico?

## Formato do relatório

Tabela curta (princípio → veredito → observação), seguida de no máximo 3 recomendações priorizadas. Se tudo for OK, diga isso em uma linha — sem relatório inflado.
